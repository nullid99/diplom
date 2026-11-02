"""Val-only prediction evidence and an explicitly image-derived technical video.

Reads final-report predictions and original labels without changing either.
The montage is integration material, not independent video/event evaluation.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from backend.app.config import PROJECT_ROOT, get_settings


def iou(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union else 0


def compare(predictions, truth):
    matched = set()
    tp, fp = [], []
    for prediction in sorted(predictions, key=lambda item: -item['confidence']):
        candidates = [(iou(prediction['xyxy'], box['xyxy']), index) for index, box in enumerate(truth)
                      if index not in matched and box['class_id'] == prediction['class_id']]
        overlap, index = max(candidates, default=(0, -1))
        if overlap >= .5:
            matched.add(index)
            tp.append(dict(prediction, gt_index=index, iou=overlap))
        else:
            fp.append(dict(prediction, best_unmatched_same_class_iou=overlap))
    return dict(true_positives=tp, false_positives=fp,
                false_negatives=[box for index, box in enumerate(truth) if index not in matched])


def prepare(report_path, output):
    import cv2
    import numpy as np
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['test_used'] is False
    output.mkdir(parents=True, exist_ok=False)
    settings = get_settings()
    video = output/'val-derived-technical-NOT-independent-video.mp4'
    command = [str(settings.ffmpeg_path), '-v', 'error', '-n', '-threads', '1', '-f', 'rawvideo',
               '-pix_fmt', 'bgr24', '-s', '640x480', '-r', '4', '-i', 'pipe:0', '-an',
               '-c:v', 'libx264', '-threads', '1', '-preset', 'fast', '-crf', '16', '-pix_fmt', 'yuv420p',
               '-movflags', '+faststart', str(video)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    samples, frames = [], []
    try:
        for segment, prediction in enumerate(report['predictions']):
            image_path = PROJECT_ROOT/'datasets/dfire'/prediction['image']
            assert '/val/images/' in image_path.as_posix()
            image = cv2.imread(str(image_path))
            assert image is not None
            height, width = image.shape[:2]
            label = image_path.parent.parent/'labels'/(image_path.stem+'.txt')
            truth = []
            for line in label.read_text().splitlines():
                class_id, x, y, w, h = map(float, line.split())
                truth.append(dict(class_id=int(class_id), xyxy=[(x-w/2)*width, (y-h/2)*height,
                                                               (x+w/2)*width, (y+h/2)*height]))
            sample = dict(image=prediction['image'], sha256=prediction['image_sha256'],
                          ground_truth=truth, predictions=prediction['detections'],
                          comparison=compare(prediction['detections'], truth), preview=prediction['preview'])
            samples.append(sample)
            # Upper row: original D-Fire labels; lower row: actual model predictions.
            panels = []
            for title, boxes, color in [('AUTHOR LABELS', truth, (60, 210, 70)),
                                         ('YOLO11n conf >= 0.25', prediction['detections'], (0, 120, 255))]:
                panel = image.copy()
                for box in boxes:
                    x1, y1, x2, y2 = map(round, box['xyxy'])
                    cv2.rectangle(panel, (x1,y1), (x2,y2), color, 2)
                    name = ['smoke','fire'][box['class_id']]
                    cv2.putText(panel, name, (x1,max(y1-4,15)), cv2.FONT_HERSHEY_SIMPLEX, .5, color, 1)
                panel = cv2.resize(panel, (640,480))
                cv2.rectangle(panel,(0,0),(640,27),(25,25,25),-1)
                cv2.putText(panel,title,(10,19),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
                panels.append(panel)
            cv2.imwrite(str(output/(image_path.stem+'-labels-vs-predictions.jpg')),np.vstack(panels))
            scale = min(640/width, 448/height)
            size = (round(width*scale), round(height*scale))
            left, top = (640-size[0])//2, 32+(448-size[1])//2
            canvas = np.zeros((480,640,3), dtype=np.uint8)
            canvas[top:top+size[1],left:left+size[0]] = cv2.resize(image,size)
            cv2.putText(canvas,'VAL stills / TECHNICAL CLIP / NOT event evaluation',(8,21),cv2.FONT_HERSHEY_SIMPLEX,.43,(255,255,255),1)
            mapped_truth = [dict(class_id=box['class_id'],xyxy=[box['xyxy'][0]*size[0]/width+left,
                            box['xyxy'][1]*size[1]/height+top,box['xyxy'][2]*size[0]/width+left,
                            box['xyxy'][3]*size[1]/height+top]) for box in truth]
            for repeat in range(8):
                index = segment*8+repeat
                process.stdin.write(canvas.tobytes())
                frames.append(dict(frame_index=index,time_seconds=index/4,image=prediction['image'],ground_truth=mapped_truth))
        process.stdin.close()
        errors=process.stderr.read().decode('utf-8',errors='replace')
        if process.wait(timeout=60) != 0:
            raise RuntimeError(errors)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    payload = dict(report=str(report_path), test_used=False, video=str(video),
                   video_sha256=hashlib.file_digest(video.open('rb'),'sha256').hexdigest(),
                   fps=4, duration_seconds=len(frames)/4, frames=frames, samples=samples,
                   matching_rule='Greedy confidence order; same class and IoU >= 0.5; comparisons are examples, not aggregate validation metrics.',
                   limitation='Image-derived val montage. Repeated stills are not natural temporal video, independent scenes or event evaluation.')
    (output/'evidence.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(video=str(video),frames=len(frames),samples=len(samples),
                         tp=sum(len(s['comparison']['true_positives']) for s in samples),
                         fp=sum(len(s['comparison']['false_positives']) for s in samples),
                         fn=sum(len(s['comparison']['false_negatives']) for s in samples))))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    prepare(args.report,args.output)
