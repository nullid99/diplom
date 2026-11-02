"""CPU FFmpeg I/O; VFR PTS зберігаються через потоковий MJPEG/Matroska міст.

Matroska TimestampScale=1000 ns, BlockDuration у мікросекундах.
Жодних припущень CFR, PNG/JPEG-секвенцій на диску або повного відео в RAM.
"""
import concurrent.futures
import contextlib
import json
import math
from fractions import Fraction
import queue
import subprocess
import threading
import time
from pathlib import Path


class MediaError(RuntimeError):
    pass


def wait_item(items,process,control,timeout):
    start=time.monotonic()
    while True:
        control()
        try: return items.get(timeout=.2)
        except queue.Empty:
            if time.monotonic()-start>timeout:
                raise MediaError('Інструмент обробки відео не відповідає.')


@contextlib.contextmanager
def child(arguments,error_path):
    with Path(error_path).open('wb') as errors:
        process=subprocess.Popen([str(arg) for arg in arguments],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=errors)
        try: yield process
        finally:
            if process.poll() is None: process.kill()
            process.wait(timeout=10)
            process.stdout.close()


def probe_rows(path,settings,control,error_path):
    args=[settings.ffprobe_path,'-v','error','-threads','1','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time,duration_time,width,height','-of','compact=p=0:nk=0',path]
    with child(args,error_path) as process:
        items=queue.Queue(maxsize=4)
        stopped=threading.Event()
        def read():
            try:
                for line in iter(process.stdout.readline,b''):
                    while not stopped.is_set():
                        try: items.put(line,timeout=.2); break
                        except queue.Full: pass
                    if stopped.is_set(): return
            finally:
                while not stopped.is_set():
                    try: items.put(None,timeout=.2); break
                    except queue.Full: pass
        reader=threading.Thread(target=read,daemon=True)
        reader.start()
        try:
            while True:
                line=wait_item(items,process,control,settings.analysis_io_timeout_seconds)
                if line is None: break
                values=dict(part.split('=',1) for part in line.decode('utf-8',errors='replace').strip().split('|') if '=' in part)
                if 'width' not in values: continue
                try:
                    pts=float(values['best_effort_timestamp_time'])
                    duration=float(values.get('duration_time','nan'))
                    width,height=int(values['width']),int(values['height'])
                    if not math.isfinite(pts): raise ValueError
                    yield dict(source_pts_seconds=pts,duration_seconds=duration,width=width,height=height)
                except (KeyError,ValueError):
                    raise MediaError('Відео не має придатних часових міток кадрів.') from None
            if process.wait(timeout=10)!=0 or Path(error_path).stat().st_size:
                raise MediaError('Не вдалося прочитати часові мітки відео без помилок декодування.')
        finally:
            stopped.set()
            if process.poll() is None: process.kill()
            reader.join(timeout=2)


def scan_timeline(path,target,settings,control):
    control()
    try:
        header=subprocess.run([str(settings.ffprobe_path),'-v','error','-select_streams','v:0','-show_entries','stream=sample_aspect_ratio,start_time:stream_side_data=rotation:stream_disposition=attached_pic:format=start_time','-of','json',str(path)],capture_output=True,check=True,timeout=settings.ffprobe_timeout_seconds)
        info=json.loads(header.stdout)
        stream=info['streams'][0]
        if stream.get('disposition',{}).get('attached_pic'):
            raise MediaError('Перший відеопотік є обкладинкою, а не записом.')
        if any(abs(float(item.get('rotation',0)))%360>.001 for item in stream.get('side_data_list',[])):
            raise MediaError('Поворот через метадані поки не підтримується. Потрібен окремо нормалізований відеозапис.')
        start=stream.get('start_time')
        container_start=info.get('format',{}).get('start_time')
        if start not in (None,'N/A') and container_start not in (None,'N/A') and abs(float(start)-float(container_start))>.01:
            raise MediaError('Зміщений початок відео відносно контейнера поки не підтримується.')
        sar=stream.get('sample_aspect_ratio')
        ratio=Fraction(sar.replace(':','/')) if sar not in (None,'N/A','0:1') else None
        if ratio is not None and ratio<=0: raise ValueError
    except (OSError,subprocess.SubprocessError,ValueError,KeyError,IndexError):
        raise MediaError('Не вдалося перевірити параметри відеопотоку.') from None
    control()
    previous=None
    origin=None
    count=0
    dimensions=None
    last_duration=None
    with Path(target).open('w',encoding='utf-8') as out:
        for row in probe_rows(path,settings,control,Path(target).with_suffix('.probe.log')):
            if min(row['width'],row['height'])<=0 or row['width']*row['height']>settings.analysis_max_pixels:
                raise MediaError('Роздільна здатність перевищує ліміт аналізу або некоректна.')
            current=(row['width'],row['height'])
            if dimensions is not None and current!=dimensions:
                raise MediaError('Зміна роздільної здатності всередині запису поки не підтримується.')
            dimensions=current
            if origin is None: origin=row['source_pts_seconds']
            row['time_seconds']=row['source_pts_seconds']-origin
            row['frame_index']=count
            count+=1
            if previous is not None:
                delta=row['time_seconds']-previous['time_seconds']
                if delta<.000001: raise MediaError('Часові мітки кадрів не є строго зростаючими.')
                previous['duration_seconds']=delta
                out.write(json.dumps(previous,allow_nan=False)+'\n')
            previous=row
        if previous is None: raise MediaError('У відео немає декодованих кадрів.')
        last_duration=previous['duration_seconds']
        if not math.isfinite(last_duration) or last_duration<=0:
            raise MediaError('Невідома тривалість останнього кадру; часову шкалу не підмінено припущенням CFR.')
        out.write(json.dumps(previous,allow_nan=False)+'\n')
    return dict(frames=count,width=dimensions[0],height=dimensions[1],duration_seconds=previous['time_seconds']+last_duration,last_duration_seconds=last_duration,source_first_pts_seconds=origin,sample_aspect_ratio=str(ratio) if ratio is not None else None)


def decoded_frames(path,width,height,settings,control,error_path):
    # -noautorotate узгоджує матрицю пікселів із ffprobe width/height.
    args=[settings.ffmpeg_path,'-v','error','-nostdin','-threads','1','-noautorotate','-i',path,'-map','0:v:0','-an','-sn','-dn','-vf','format=bgr24','-threads','1','-fps_mode','passthrough','-f','rawvideo','pipe:1']
    import numpy as np
    size=width*height*3
    with child(args,error_path) as process:
        items=queue.Queue(maxsize=2)
        stopped=threading.Event()
        def read():
            try:
                while not stopped.is_set():
                    frame=bytearray()
                    while len(frame)<size:
                        part=process.stdout.read(size-len(frame))
                        if not part: break
                        frame.extend(part)
                    payload=bytes(frame) if frame else None
                    while not stopped.is_set():
                        try: items.put(payload,timeout=.2); break
                        except queue.Full: pass
                    if payload is None: return
            except (OSError,ValueError): pass
        reader=threading.Thread(target=read,daemon=True)
        reader.start()
        try:
            while True:
                data=wait_item(items,process,control,settings.analysis_io_timeout_seconds)
                if data is None: break
                if len(data)!=size: raise MediaError('Декодування повернуло неповний кадр.')
                yield np.frombuffer(data,dtype=np.uint8).reshape(height,width,3).copy()
            if process.wait(timeout=10)!=0 or Path(error_path).stat().st_size: raise MediaError('Помилка декодування відео.')
        finally:
            stopped.set()
            if process.poll() is None: process.kill()
            reader.join(timeout=2)


def element(identifier,payload):
    # EBML ID уже містить marker; size — VINT із найкоротшою довжиною.
    encoded_id=identifier.to_bytes((identifier.bit_length()+7)//8,'big')
    length=len(payload)
    for size in range(1,9):
        if length<(1<<(7*size))-1:
            return encoded_id+((1<<(7*size))|length).to_bytes(size,'big')+payload
    raise MediaError('Кадр перевищує підтриманий розмір контейнера.')


def number(identifier,value):
    return element(identifier,value.to_bytes(max(1,(value.bit_length()+7)//8),'big'))


class VideoSink:
    def __init__(self,path,metadata,settings,control):
        self.control=control
        self.timeout=settings.analysis_io_timeout_seconds
        self.errors=Path(path).with_suffix('.encoder.log').open('wb')
        video_filter='pad=ceil(iw/2)*2:ceil(ih/2)*2'
        if metadata.get('sample_aspect_ratio'): video_filter+=',setsar='+metadata['sample_aspect_ratio']
        arguments=[settings.ffmpeg_path,'-v','error','-nostdin','-threads','1','-f','matroska','-i','pipe:0','-an','-vf',video_filter,'-c:v','libx264','-threads','1','-preset','ultrafast','-crf','23','-bf','0','-fps_mode','passthrough','-enc_time_base','1:1000000','-video_track_timescale','1000000','-movflags','+faststart',path]
        try:
            self.process=subprocess.Popen([str(arg) for arg in arguments],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=self.errors)
        except BaseException:
            self.errors.close()
            raise
        self.executor=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        ebml=number(0x4286,1)+number(0x42F7,1)+number(0x42F2,4)+number(0x42F3,8)+element(0x4282,b'matroska')+number(0x4287,4)+number(0x4285,2)
        info=number(0x2AD7B1,1000)+element(0x4D80,b'FireVision')+element(0x5741,b'FireVision')
        track=number(0xD7,1)+number(0x73C5,1)+number(0x83,1)+element(0x86,b'V_MJPEG')+element(0xE0,number(0xB0,metadata['width'])+number(0xBA,metadata['height']))
        try:
            self.write(element(0x1A45DFA3,ebml)+bytes.fromhex('1853806701ffffffffffffff')+element(0x1549A966,info)+element(0x1654AE6B,element(0xAE,track)))
        except BaseException:
            self.close()
            raise

    def write(self,payload):
        future=self.executor.submit(self.process.stdin.write,payload)
        start=time.monotonic()
        while True:
            self.control()
            try: future.result(timeout=.2); return
            except concurrent.futures.TimeoutError:
                if time.monotonic()-start>self.timeout: raise MediaError('Кодування відео не відповідає.')

    def frame(self,image,timestamp,duration):
        import cv2
        ok,encoded=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,92])
        if not ok: raise MediaError('Не вдалося закодувати кадр результату.')
        block=element(0xA1,b'\x81\x00\x00\x00'+encoded.tobytes())+number(0x9B,max(1,round(duration*1_000_000)))
        cluster=number(0xE7,max(0,round(timestamp*1_000_000)))+element(0xA0,block)
        self.write(element(0x1F43B675,cluster))

    def close(self,success=False):
        try:
            if success:
                self.process.stdin.close()
                start=time.monotonic()
                while self.process.poll() is None:
                    self.control()
                    if time.monotonic()-start>self.timeout: raise MediaError('Не вдалося завершити відеофайл.')
                    time.sleep(.1)
                if self.process.returncode!=0: raise MediaError('FFmpeg не зберіг відео результату.')
        finally:
            if self.process.poll() is None: self.process.kill()
            self.process.wait(timeout=10)
            self.executor.shutdown(wait=True,cancel_futures=True)
            try:
                if not self.process.stdin.closed: self.process.stdin.close()
            except OSError:
                pass  # Windows pipe flush після kill може повернути EINVAL.
            finally:
                self.errors.close()


def validate_video(path,timeline,metadata,settings,control):
    count=0
    end=None
    with Path(timeline).open(encoding='utf-8') as expected:
        for row in probe_rows(path,settings,control,Path(path).with_suffix('.verify.log')):
            line=expected.readline()
            if not line: raise MediaError('Кількість кадрів результату перевищує оригінал.')
            wanted=json.loads(line)
            if abs(row['source_pts_seconds']-wanted['time_seconds'])>.000002:
                raise MediaError('Часові мітки результату не відповідають оригіналу.')
            count+=1
            end=row['source_pts_seconds']+row['duration_seconds']
        if expected.readline() or count!=metadata['frames']:
            raise MediaError('Результат містить не всі кадри відео.')
    if end is None or not math.isfinite(end) or abs(end-metadata['duration_seconds'])>.000003:
        raise MediaError('Тривалість результату не відповідає вихідному відео.')
