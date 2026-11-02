"""Collect completed real runs, validate retained timelines, and export descriptive observations."""
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import httpx
from PIL import Image,ImageDraw
from backend.app.config import PROJECT_ROOT,storage_path
from scripts.fetch_firesense import ROOT,FILES,digest
from scripts.firesense_prepare import REPORT,frame,sheet,probe,FONT
import subprocess
from backend.app.config import get_settings


def main():
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    freeze=json.loads((ROOT/'freeze.json').read_text())
    assert digest(ROOT/'manifest.json')==freeze['manifest_sha256']
    runs=json.loads((REPORT/'runs.json').read_text(encoding='utf-8'))
    assert runs.get('finished_at')
    examples=REPORT/'examples';examples.mkdir(exist_ok=True)
    observations=[];all_events=[];previews=[];timeline_checks=[]
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=60) as api:
        events=[];page=1
        while True:
            result=api.get('/api/events',params={'page':page,'page_size':100}).raise_for_status().json()
            events.extend(result['items'])
            if page*100>=result['total']:break
            page+=1
        for row in manifest['clips']:
            recorded=next(item for item in runs['runs'] if item['clip_id']==row['id'])
            run=api.get('/api/analysis-runs/'+recorded['run_id']).raise_for_status().json()
            assert run['status']=='completed'
            for key,value in runs['configuration'].items():assert run['settings_snapshot'][key]==value
            video=storage_path(run['result_paths']['video'])
            detections=storage_path(run['result_paths']['detections'])
            lines=[json.loads(line) for line in detections.read_text().splitlines()]
            timeline=json.loads((ROOT/'clips'/(row['id']+'.timeline.json')).read_text())
            output=json.loads(subprocess.run([str(get_settings().ffprobe_path),'-v','error','-select_streams','v:0','-show_entries','frame=best_effort_timestamp_time','-of','json',str(video)],capture_output=True,check=True,timeout=30).stdout)['frames']
            assert len(lines)==len(timeline)==len(output)==row['frames']
            origin=float(timeline[0]['best_effort_timestamp_time'])
            error=max(abs(float(source['best_effort_timestamp_time'])-origin-float(target['best_effort_timestamp_time'])) for source,target in zip(timeline,output))
            assert error<=.000002
            for index,(line,timing) in enumerate(zip(lines,timeline)):
                assert line['frame_index']==index
                assert abs(line['time_seconds']-(float(timing['best_effort_timestamp_time'])-origin))<=.000002
            timeline_checks.append(dict(id=row['id'],frames=len(lines),max_pts_error_seconds=error))
            associated=[event for event in events if event['analysis_run_id']==run['id']]
            for event in associated:
                detail=api.get('/api/events/'+event['id']).raise_for_status().json()
                assert detail['automatic_status']=='completed'
                start,confirmation,last,closed=map(float,[detail['start_seconds'],detail['confirmed_seconds'],detail['last_seen_seconds'],detail['closed_seconds']])
                assert 0<=start<=confirmation<=last<=closed+.000002
                region=detail['region']
                assert 0<=region['clip_start_seconds']<=confirmation<=region['clip_end_seconds']<=run['summary_metrics']['video_duration_seconds']+.000002
                for kind in ('frame','clip'):
                    reply=api.get(f"/api/events/{event['id']}/files/{kind}").raise_for_status()
                    assert len(reply.content)>0
                all_events.append({**detail,'clip_id':row['id']})
            frames_by_class={kind:sum(any(d['class_name']==kind for d in line['detections']) for line in lines if line['analyzed']) for kind in ('fire','smoke')}
            counts=Counter(event['feature_type'] for event in associated)
            record=dict(id=row['id'],fire_visible=row['fire'],smoke_visible=row['smoke'],transform=row['transform'],
                        duration_seconds=run['summary_metrics']['video_duration_seconds'],width=row['metadata']['streams'][0]['width'],height=row['metadata']['streams'][0]['height'],
                        analyzed_frames=run['summary_metrics']['frames_analyzed'],fire_detection_frames=frames_by_class['fire'],smoke_detection_frames=frames_by_class['smoke'],
                        fire_events=counts['fire'],smoke_events=counts['smoke'],run_id=run['id'],source_id=recorded['source_id'],wall_seconds=run['summary_metrics']['wall_seconds'])
            observations.append(record)
            notes=[]
            for kind in ('fire','smoke'):
                if row[kind] and counts[kind]==0:notes.append('No confirmed '+kind+' event despite visually present class')
                if not row[kind] and frames_by_class[kind]:notes.append('False '+kind+' frame detections'+(' with confirmed event' if counts[kind] else ' without confirmed event'))
            chosen=next((line for line in lines if line['analyzed'] and any(not row[d['class_name']] for d in line['detections'])),None)
            if chosen is None:chosen=min((line for line in lines if line['analyzed']),key=lambda line:abs(line['time_seconds']-2))
            when=chosen['time_seconds']
            source_image=frame(ROOT/row['file'],when)
            predicted=frame(video,when)
            label=f"{row['id']} @ {when:.3f}s | visible fire={row['fire']} smoke={row['smoke']}"
            sheet([(source_image,'SOURCE | '+label),(predicted,'REAL YOLO OUTPUT | '+label)],examples/(row['id']+'-source-vs-result.jpg'),columns=2,size=(640,480))
            previews.append((predicted,f"{row['id']} @ {when:.2f}s\nevents F={counts['fire']} S={counts['smoke']}"))
            record['notes']=notes
            record['example_seconds']=when
            record['example_detections']=chosen['detections']
    sheet(previews,REPORT/'results-overview.jpg',columns=4,size=(320,240))
    (REPORT/'observations.json').write_text(json.dumps(dict(created_at=datetime.now(timezone.utc).isoformat(),demonstration_only=True,independent_test=False,configuration=runs['configuration'],observations=observations,events=all_events,timeline_checks=timeline_checks,notes='Descriptive clip-level presence/counts; no spatial or temporal ground-truth matching, no precision/recall claims.'),ensure_ascii=False,indent=2),encoding='utf-8')
    columns=['id','fire_visible','smoke_visible','transform','duration_seconds','width','height','analyzed_frames','fire_detection_frames','smoke_detection_frames','fire_events','smoke_events','run_id','source_id']
    with (REPORT/'observations.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(observations)
    # Verify all acquired originals against extraction SHA; never alter source data.
    checked=0
    for name,checksum in FILES.items():
        assert digest(ROOT/name,'md5')==checksum
        original=json.loads((ROOT/'provenance'/(name+'.extraction.json')).read_text())
        for entry in original['files']:
            assert digest(ROOT/entry['path'])==entry['sha256'];checked+=1
    (REPORT/'verification.json').write_text(json.dumps(dict(original_files_sha256_unchanged=checked,published_archive_md5_match=True,
        frozen_manifest_unchanged=digest(ROOT/'manifest.json')==freeze['manifest_sha256'],completed_runs=len(observations),events=len(all_events),
        timeline_checks=timeline_checks,all_event_files_accessible=True,same_settings_all_runs=True,training_started=False),indent=2),encoding='utf-8')
    print(json.dumps(dict(completed_runs=len(observations),events=len(all_events),original_files_checked=checked)))


if __name__=='__main__':main()
