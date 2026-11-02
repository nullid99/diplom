"""Time-based, per-class one-to-one association. No dependency on ML or wall time."""
import math
import uuid
from collections import deque
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Zone(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    id: str=Field(min_length=1,max_length=64)
    name: str=Field(min_length=1,max_length=80)
    mode: str=Field(pattern='^(include|exclude)$')
    x1: float=Field(ge=0,le=1)
    y1: float=Field(ge=0,le=1)
    x2: float=Field(ge=0,le=1)
    y2: float=Field(ge=0,le=1)

    @model_validator(mode='after')
    def rectangle(self):
        if self.x2-self.x1<.001 or self.y2-self.y1<.001:
            raise ValueError('Зона повинна мати додатну площу (мінімум 0,001 сторони кадру).')
        return self


class TemporalConfig(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True,allow_inf_nan=False)
    window_seconds: float=Field(3,ge=.1,le=60)
    min_hits: int=Field(3,ge=2,le=120,strict=True)
    min_span_seconds: float=Field(1,ge=.05,le=60)
    absence_seconds: float=Field(2,ge=.1,le=120)
    match_iou: float=Field(.1,ge=.01,le=1)
    center_distance: float=Field(.12,ge=.001,le=.5)
    clip_before_seconds: float=Field(2,ge=0,le=15)
    clip_after_seconds: float=Field(3,ge=.1,le=15)

    @model_validator(mode='after')
    def coherent(self):
        if self.min_span_seconds>self.window_seconds:
            raise ValueError('Мінімальна тривалість перевищує вікно підтвердження.')
        return self

    def validate_frequency(self,fps):
        if (self.min_hits-1)/fps>self.window_seconds+1e-9 or self.absence_seconds+1e-9<1/fps:
            raise ValueError('Часові параметри несумісні з частотою аналізу: збільшіть вікно/інтервал відсутності або частоту.')


class EventDefaults(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    analysis_fps: float=Field(2,ge=.1,le=60)
    temporal: TemporalConfig=Field(default_factory=TemporalConfig)

    @model_validator(mode='after')
    def coherent(self):
        self.temporal.validate_frequency(self.analysis_fps)
        return self


def allowed(box,zones):
    x,y=(box[0]+box[2])/2,(box[1]+box[3])/2
    def contains(zone): return zone.x1<=x<=zone.x2 and zone.y1<=y<=zone.y2
    if any(z.mode=='exclude' and contains(z) for z in zones): return False
    includes=[z for z in zones if z.mode=='include']
    return not includes or any(contains(z) for z in includes)


def overlap(a,b):
    area=lambda box: max(0,box[2]-box[0])*max(0,box[3]-box[1])
    intersection=area([max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])])
    return intersection/max(1e-12,area(a)+area(b)-intersection)


@dataclass
class Track:
    key: str
    feature_type: str
    box: list
    first: float
    last: float
    confidence: float
    history: deque=field(default_factory=deque)
    confirmed: float|None=None
    confirmation_box: list|None=None

    def view(self,closed=None,reason=None):
        return dict(track_key=self.key,feature_type=self.feature_type,start_seconds=self.first,
                    confirmed_seconds=self.confirmed,last_seen_seconds=self.last,closed_seconds=closed,
                    closure_reason=reason,automatic_status=('completed' if reason in ('absence','eof') else 'interrupted') if reason else 'confirmed',
                    confidence=self.confidence,region={'coordinate_system':'normalized','xyxy':self.confirmation_box,
                                                     'last_xyxy':self.box})


class TemporalEvents:
    def __init__(self,config):
        self.config=config
        self.tracks={}
        self.previous=None

    def update(self,when,detections):
        if not math.isfinite(when) or when<0 or self.previous is not None and when<=self.previous:
            raise ValueError('Потрібні строго зростаючі часові мітки відео.')
        self.previous=when
        changes=[]
        # Expire before association: a detection beyond the timeout is a new episode.
        for key,track in list(self.tracks.items()):
            if when-track.last>self.config.absence_seconds+1e-9:
                if track.confirmed is not None: changes.append(track.view(track.last+self.config.absence_seconds,'absence'))
                del self.tracks[key]
        unique=[]
        for detection in sorted(detections,key=lambda d:-d['confidence']):
            if not any(d['class_name']==detection['class_name'] and overlap(d['xyxy'],detection['xyxy'])>=.85 for d in unique):
                unique.append(detection)
        candidates=[]
        for key,track in self.tracks.items():
            for index,detection in enumerate(unique):
                if detection['class_name']!=track.feature_type: continue
                box=detection['xyxy']; old=track.box
                iou=overlap(box,old)
                distance=math.hypot((box[0]+box[2]-old[0]-old[2])/2,(box[1]+box[3]-old[1]-old[3])/2)
                areas=[(b[2]-b[0])*(b[3]-b[1]) for b in (box,old)]
                if iou>=self.config.match_iou or distance<=self.config.center_distance and min(areas)/max(areas)>=.2:
                    candidates.append((-iou,distance,key,index))
        used_tracks=set(); used_detections=set(); assignments=[]
        for _,_,key,index in sorted(candidates):
            if key not in used_tracks and index not in used_detections:
                assignments.append((key,index));used_tracks.add(key);used_detections.add(index)
        for index,detection in enumerate(unique):
            if index not in used_detections:
                key=uuid.uuid4().hex
                self.tracks[key]=Track(key,detection['class_name'],detection['xyxy'],when,when,detection['confidence'])
                assignments.append((key,index))
        for key,index in assignments:
            track=self.tracks[key]; detection=unique[index]
            track.last=when;track.box=detection['xyxy'];track.confidence=max(track.confidence,detection['confidence'])
            track.history.append(when)
            while track.history and track.history[0]<when-self.config.window_seconds-1e-9: track.history.popleft()
            if track.confirmed is None and len(track.history)>=self.config.min_hits and when-track.history[0]+1e-9>=self.config.min_span_seconds:
                track.confirmed=when;track.confirmation_box=list(track.box)
                changes.append(track.view())
        for key,track in list(self.tracks.items()):
            if when-track.last>=self.config.absence_seconds-1e-9:
                if track.confirmed is not None: changes.append(track.view(track.last+self.config.absence_seconds,'absence'))
                del self.tracks[key]
        return changes

    def finish(self,when,reason):
        changes=[track.view(when,reason) for track in self.tracks.values() if track.confirmed is not None]
        self.tracks.clear()
        return changes
