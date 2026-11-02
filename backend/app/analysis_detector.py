"""Імпорт ML виконується лише в окремому worker після перевірок і GPU-lock."""
import math


class YoloDetector:
    def __init__(self,weights,device,imgsz):
        from ultralytics import YOLO
        self.model=YOLO(str(weights))
        if self.model.names!={0:'smoke',1:'fire'} or self.model.task!='detect':
            raise ValueError('Класи ваг не відповідають зареєстрованій моделі.')
        self.device='0' if device=='cuda:0' else 'cpu'
        self.imgsz=imgsz

    def detect(self,frame,thresholds):
        result=self.model.predict(frame,device=self.device,imgsz=self.imgsz,conf=min(thresholds.values()),iou=.7,half=False,verbose=False,save=False)[0]
        expected='cpu' if self.device=='cpu' else 'cuda'
        if self.model.predictor.model.device.type!=expected:
            raise RuntimeError('Пристрій детектора не відповідає налаштуванням запуску.')
        found=[]
        for class_id,confidence,box in zip(result.boxes.cls.tolist(),result.boxes.conf.tolist(),result.boxes.xyxy.tolist()):
            name=self.model.names[int(class_id)]
            if name in thresholds and math.isfinite(confidence) and confidence>=thresholds[name]:
                found.append(dict(class_id=int(class_id),class_name=name,confidence=float(confidence),xyxy=[float(v) for v in box]))
        return found

    def close(self):
        self.model=None
        import gc
        gc.collect()
        if self.device!='cpu':
            import torch
            torch.cuda.empty_cache()
