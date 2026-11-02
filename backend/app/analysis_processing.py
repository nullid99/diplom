import json
import math
import os
import time

from backend.app.analysis_media import MediaError, VideoSink, decoded_frames, scan_timeline, validate_video


def process_video(source,weights,options,folder,settings,control,progress,detector_factory,event_callback=None):
    import cv2
    started=time.monotonic()
    timeline=folder/'timeline.jsonl'
    metadata=scan_timeline(source,timeline,settings,control)
    detector=None
    sink=None
    frames=None
    processed=analyzed=0
    counts={'smoke':0,'fire':0}
    next_analysis=0.
    thresholds={'smoke':options.smoke_threshold,'fire':options.fire_threshold}
    from backend.app.temporal import TemporalEvents, allowed
    tracker=TemporalEvents(options.temporal) if options.temporal else None
    last_time=0.
    event_count=0
    try:
        control()
        detector=detector_factory(weights,options.device,options.imgsz)
        sink=VideoSink(folder/'annotated.mp4',metadata,settings,control)
        frames=decoded_frames(source,metadata['width'],metadata['height'],settings,control,folder/'decode.log')
        with timeline.open(encoding='utf-8') as times,(folder/'detections.jsonl').open('w',encoding='utf-8') as out:
            for frame in frames:
                control()
                line=times.readline()
                if not line: raise MediaError('Декодер повернув зайві кадри.')
                timing=json.loads(line)
                when=timing['time_seconds']
                last_time=when
                selected=when+1e-9>=next_analysis
                detections=[]
                if selected:
                    detections=detector.detect(frame,thresholds)
                    analyzed+=1
                    next_analysis=(math.floor((when+1e-9)*options.analysis_fps)+1)/options.analysis_fps
                    accepted=[]
                    for detection in detections:
                        name=detection['class_name']
                        if name not in thresholds or detection['class_id']!={'smoke':0,'fire':1}.get(name) or not math.isfinite(detection['confidence']) or not thresholds[name]<=detection['confidence']<=1:
                            raise MediaError('Детектор повернув недопустимий клас або confidence.')
                        box=detection['xyxy']
                        if len(box)!=4 or not all(math.isfinite(v) for v in box) or not (0<=box[0]<box[2]<=metadata['width'] and 0<=box[1]<box[3]<=metadata['height']):
                            raise MediaError('Детектор повернув некоректну рамку.')
                        normalized=[v/(metadata['width'] if i%2==0 else metadata['height']) for i,v in enumerate(box)]
                        if not allowed(normalized,options.zones): continue
                        accepted.append(detection)
                        counts[name]+=1
                        x1,y1,x2,y2=map(round,box)
                        color=(0,100,255) if name=='fire' else (220,180,0)
                        cv2.rectangle(frame,(x1,y1),(x2,y2),color,2)
                        cv2.putText(frame,f"{name} {detection['confidence']:.2f}",(x1,max(15,y1-5)),cv2.FONT_HERSHEY_SIMPLEX,.5,color,1)
                    detections=accepted
                    if tracker:
                        normalized=[{**d,'xyxy':[v/(metadata['width'] if i%2==0 else metadata['height']) for i,v in enumerate(d['xyxy'])]} for d in detections]
                        changes=tracker.update(when,normalized)
                        for event in changes:
                            if event_callback: event_callback(event,frame,metadata,options.temporal)
                            if event['closure_reason'] is None: event_count+=1
                        newly_confirmed={event['track_key'] for event in changes if event['closure_reason'] is None}
                        # Update the existing aggregate, never insert per-frame detection rows.
                        for track in tracker.tracks.values():
                            if event_callback and track.confirmed is not None and track.last==when and track.key not in newly_confirmed:
                                event_callback(track.view(),None,metadata,options.temporal)
                # Порожні результати й неаналізовані кадри розрізняються.
                out.write(json.dumps({'frame_index':timing['frame_index'],'time_seconds':when,'source_pts_seconds':timing['source_pts_seconds'],'analyzed':selected,'detections':detections},allow_nan=False)+'\n')
                sink.frame(frame,when,timing['duration_seconds'])
                processed+=1
                out.flush()
                progress(min(.99,processed/metadata['frames']),{'stage':'processing','frames_read':processed,'frames_analyzed':analyzed,'total_frames':metadata['frames']})
            if times.readline() or processed!=metadata['frames']: raise MediaError('Відео декодовано не повністю.')
        sink.close(success=True)
        sink=None
        control()
        progress(.99,{'stage':'verifying','frames_read':processed,'frames_analyzed':analyzed,'total_frames':metadata['frames']})
        validate_video(folder/'annotated.mp4',timeline,metadata,settings,control)
        if tracker:
            for event in tracker.finish(metadata['duration_seconds'],'eof'):
                if event_callback: event_callback(event,None,metadata,options.temporal)
        summary=dict(frames_read=processed,frames_analyzed=analyzed,detections_by_class=counts,
                     video_duration_seconds=metadata['duration_seconds'],source_first_pts_seconds=metadata['source_first_pts_seconds'],
                     wall_seconds=time.monotonic()-started,device=options.device,output_audio=False,
                     timestamp_precision_seconds=.000001,all_original_frames_retained=True,confirmed_events=event_count)
        with (folder/'summary.json').open('w',encoding='utf-8') as out: json.dump(summary,out,ensure_ascii=False,allow_nan=False)
        for filename in ('annotated.mp4','detections.jsonl','summary.json'):
            if (folder/filename).stat().st_size==0: raise MediaError('Обов’язковий результат порожній.')
            with (folder/filename).open('rb+') as saved:
                os.fsync(saved.fileno())
        return summary
    except BaseException as error:
        if tracker:
            reason='cancelled' if type(error).__name__=='Cancelled' else 'failed'
            for event in tracker.finish(last_time,reason):
                if event_callback:
                    try: event_callback(event,None,metadata,options.temporal)
                    except Exception: pass
        raise
    finally:
        if frames is not None: frames.close()
        if sink is not None: sink.close()
        if detector is not None: detector.close()
