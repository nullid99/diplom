"""Final integrity/volume facts and extra descriptive error evidence, without inference."""
import json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import httpx
from backend.app.config import PROJECT_ROOT,storage_path
from scripts.fetch_firesense import ROOT,digest
from scripts.firesense_prepare import REPORT,frame,sheet


def main():
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    observations=json.loads((REPORT/'observations.json').read_text(encoding='utf-8'))
    runs=json.loads((REPORT/'runs.json').read_text(encoding='utf-8'))
    frozen=json.loads((ROOT/'freeze.json').read_text())
    assert digest(ROOT/'manifest.json')==frozen['manifest_sha256']
    lookup={r['id']:r for r in manifest['clips']}
    for row in runs['runs']:
        assert row['created']['settings_snapshot']['source_sha256']==lookup[row['clip_id']]['sha256']
        assert digest(ROOT/lookup[row['clip_id']]['file'])==lookup[row['clip_id']]['sha256']
    reference=next(row for row in runs['runs'] if row['clip_id']=='F02')
    output=storage_path(reference['result']['result_paths']['video'])
    sheet([(frame(ROOT/'clips/F02.mp4',6),'F02 SOURCE | smoke still visible at6s'),(frame(output,6),'F02 REAL RESULT | smoke event closed at5.5s')],REPORT/'examples/F02-smoke-after-closure.jpg',columns=2,size=(640,480))
    lines=[json.loads(line) for line in storage_path(reference['result']['result_paths']['detections']).read_text().splitlines()]
    at_six=min((line for line in lines if line['analyzed']),key=lambda line:abs(line['time_seconds']-6))
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=30) as api:
        models=api.get('/api/model-versions').raise_for_status().json()
        model=next(m for m in models['items'] if m['id']==runs['model_id'])
        weights_sha=digest(storage_path(model['weights_path']))
        assert weights_sha=='d0fb93c60b88dcf27eb3933a66e49d88f475aafd8c13faf11971e3b590b0e4d7'
        assert digest(PROJECT_ROOT/'runs/full/yolo11n_baseline_20261101T203432Z_b1931c45/training/weights/best.pt')==weights_sha
        old=api.get('/api/analysis-runs/b4cf3470-3216-42b3-8aff-216e7f8765e0').raise_for_status().json()
        prior=json.loads((PROJECT_ROOT/'reports/ml/final-verification-20261102/application/artifact-check.json').read_text(encoding='utf-8'))
        assert digest(storage_path(old['result_paths']['video']))==prior['result_sha256']
        assert digest(storage_path(old['result_paths']['detections']))==prior['detections_sha256']
        sources=api.get('/api/video-sources?page_size=100').raise_for_status().json()
        history=api.get('/api/analysis-runs?page_size=100').raise_for_status().json()
        events=api.get('/api/events?page_size=100').raise_for_status().json()
    acquisition=json.loads((ROOT/'provenance/acquisition.json').read_text())
    data=dict(checked_at=datetime.now(timezone.utc).isoformat(),archive_bytes=sum(row['bytes'] for row in acquisition['archives']),
              raw_bytes=sum(row['bytes'] for path in (ROOT/'provenance').glob('*.extraction.json') for row in json.loads(path.read_text())['files']),
              clip_bytes=sum(row['bytes'] for row in manifest['clips']),base_clips=10,degraded_variants=3,
              analysis_wall_seconds=sum(row['wall_seconds'] for row in observations['observations']),
              run_loop_elapsed_seconds=(datetime.fromisoformat(runs['finished_at'])-datetime.fromisoformat(runs['started_at'])).total_seconds(),
              total_frames=sum(row['frames'] for row in manifest['clips']),analyzed_frames=sum(row['analyzed_frames'] for row in observations['observations']),
              events_by_class=dict(Counter(row['feature_type'] for row in observations['events'])),
              model_sha256=weights_sha,registered_and_original_weights_unchanged=True,prior_video_and_jsonl_unchanged=True,
              uploaded_source_hashes_equal_manifest=True,prepared_clip_hashes_unchanged=True,
              working_counts=dict(sources=sources['total'],models=models['total'],runs=history['total'],events=events['total']),
              natural_video_demonstration_completed=True,independence_proven=False,
              f02_at_six_seconds=at_six,settings_changed_per_clip=False,new_training_started=False)
    (REPORT/'summary.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(data,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
