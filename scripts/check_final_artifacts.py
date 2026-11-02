"""Read-only verification of published real YOLO video artifacts and experiment hashes."""
import hashlib
import json
import subprocess
from pathlib import Path

from backend.app.config import PROJECT_ROOT, get_settings, storage_path
from scripts.final_model_evidence import compare


def main():
    import cv2
    import numpy as np
    root=PROJECT_ROOT/'reports/ml/final-verification-20261102'
    browser=json.loads((root/'application/browser-check.json').read_text(encoding='utf-8'))
    material=json.loads((root/'examples/evidence.json').read_text(encoding='utf-8'))
    assert browser['result']=='passed'
    run=browser['latest']
    settings=get_settings()
    source=Path(material['video']).resolve()
    result=storage_path(run['result_paths']['video'],settings.storage_root)
    detections=storage_path(run['result_paths']['detections'],settings.storage_root)
    rows=[json.loads(line) for line in detections.read_text().splitlines()]
    def timeline(video):
        command=[str(settings.ffprobe_path),'-v','error','-select_streams','v:0','-show_frames',
                 '-show_entries','frame=best_effort_timestamp_time,duration_time','-of','json',str(video)]
        return json.loads(subprocess.run(command,capture_output=True,check=True,timeout=60).stdout)['frames']
    original_times, result_times=timeline(source),timeline(result)
    assert len(original_times)==len(result_times)==len(rows)==64
    maximum_pts_error=max(abs(float(a['best_effort_timestamp_time'])-float(b['best_effort_timestamp_time']))
                          for a,b in zip(original_times,result_times))
    assert maximum_pts_error<=.000002
    for index,(a,b,row) in enumerate(zip(original_times,result_times,rows)):
        assert abs(float(b['best_effort_timestamp_time'])-row['time_seconds'])<=.000002
        assert row['frame_index']==index
    captures=[cv2.VideoCapture(str(file)) for file in (source,result)]
    samples=[]
    try:
        for index,row in enumerate(rows):
            frames=[]
            for capture in captures:
                ok,frame=capture.read()
                assert ok
                frames.append(frame)
            if index%8==0:
                sample=dict(frame_index=index,time_seconds=row['time_seconds'],
                            image=material['frames'][index]['image'],detections=row['detections'],
                            comparison=compare(row['detections'],material['frames'][index]['ground_truth']))
                samples.append(sample)
                image=np.hstack(frames)
                cv2.imwrite(str(root/'application'/f"source-vs-result-frame-{index:03d}-{row['time_seconds']:04.1f}s.png"),image)
    finally:
        for capture in captures: capture.release()
    experiment=Path(json.loads((root/'final-report/report.json').read_text(encoding='utf-8'))['run_dir'])
    before=json.loads((root/'experiment-before.json').read_text(encoding='utf-8-sig'))
    after=[dict(path=str(file.relative_to(experiment)),bytes=file.stat().st_size,
                sha256=hashlib.file_digest(file.open('rb'),'sha256').hexdigest().upper())
           for file in experiment.rglob('*') if file.is_file()]
    (root/'experiment-after.json').write_text(json.dumps(after,indent=2),encoding='utf-8')
    assert {row['path']:(row['bytes'],row['sha256']) for row in before}=={row['path']:(row['bytes'],row['sha256']) for row in after}
    evidence=dict(run_id=run['id'],experiment_unchanged=True,experiment_files=len(after),
                  source_file=str(source),result_file=str(result),
                  source_sha256=hashlib.file_digest(source.open('rb'),'sha256').hexdigest(),
                  result_sha256=hashlib.file_digest(result.open('rb'),'sha256').hexdigest(),
                  detections_sha256=hashlib.file_digest(detections.open('rb'),'sha256').hexdigest(),
                  source_and_output_frames=64,max_pts_difference_seconds=maximum_pts_error,
                  jsonl_frame_and_time_alignment=True,samples=samples,
                  limitation=material['limitation'])
    (root/'application/artifact-check.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:evidence[key] for key in ('run_id','experiment_unchanged','experiment_files','max_pts_difference_seconds','jsonl_frame_and_time_alignment')}))


if __name__=='__main__':
    main()
