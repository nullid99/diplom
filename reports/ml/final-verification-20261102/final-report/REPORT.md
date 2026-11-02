# Перший базовий експеримент YOLO11n

Стан: completed; причина: max_epochs; епох: 50; найкраща: 50.

Ваги: `D:\FireVision\runs\full\yolo11n_baseline_20261101T203432Z_b1931c45\training\weights\best.pt`; SHA-256 `d0fb93c60b88dcf27eb3933a66e49d88f475aafd8c13faf11971e3b590b0e4d7`; 0=smoke, 1=fire.

Train 7238 / val 1436, test не використано. Пік allocated: 761832448; reserved: 1264582656 байтів. Час worker: 13726.315914299996 с.

## Фактичні метрики val

{
  "metrics/precision(B)": 0.7324267001851046,
  "metrics/recall(B)": 0.6085525102673707,
  "metrics/mAP50(B)": 0.6911874762247406,
  "metrics/mAP50-95(B)": 0.3914435282237917,
  "fitness": 0.3914435282237917
}

По класах:

{
  "smoke": {
    "precision": 0.7954456614851293,
    "recall": 0.704390243902439,
    "mAP50": 0.787494995912513,
    "mAP50-95": 0.499330024496517
  },
  "fire": {
    "precision": 0.6694077388850799,
    "recall": 0.5127147766323024,
    "mAP50": 0.5948799565369682,
    "mAP50-95": 0.2835570319510664
  }
}

Збережено 8 передбачень; без виявлень: 1.

Конфігурація, версії, хеші даних, графіки та перевірки цілісності — у report.json і каталогах training/validation/predictions.

Val is used for model selection; scene independence is not proven. These are development validation metrics, not independent test results or event/video evaluation.
