# Аналіз відео

Зони спостереження, часові події, журнал і збережені defaults додані наступним етапом: [docs/EVENTS.md](EVENTS.md), [фактичні перевірки](../reports/events/REPORT.md).

Фінальні ваги YOLO11n після 50 епох перевірено та зареєстровано 02.11.2026. Реальний UI/API/DB/worker/CUDA/результати сценарій пройдено на технічному відеоряді з val-зображень. Це не перевірка природного руху або часових подій; незалежність сцен не підтверджена. [Фактичні метрики, ідентифікатори, команди та screenshot](../reports/ml/final-verification-20261102/REPORT.md). Технічні/pretrained COCO ваги як готовий детектор не реєстрували. За відсутності доступної моделі порожній стан і заборона запуску зберігаються.

## Середовища й запуск у PowerShell

API працює в окремому `.venv-api`: наявному ML `.venv` не встановлювали й не оновлювали пакети. Для WebSocket додано лише в API `wsproto==1.3.2` з h11==0.16.0. Підготовка не змінює глобальних PATH/TEMP/TMP. Усі файли середовищ, кеші й тимчасові дані — у проєкті на D:.

```powershell
Set-Location D:\FireVision
.\scripts\setup-api.ps1
.\scripts\db.ps1 -Action upgrade
.\scripts\start-backend.ps1
```

В іншому вікні:

```powershell
Set-Location D:\FireVision
.\scripts\start-frontend.ps1
```

Адреси: <http://127.0.0.1:5173> → «Аналіз відео», <http://127.0.0.1:8000/docs>. Попередня сторінка «Відеоджерела» збережена. Worker запускається в окремому процесі, незалежно від HTTP-сервера й вкладки браузера:

```powershell
Set-Location D:\FireVision
.\scripts\start-analysis-worker.ps1
```

Одноразовий реальний worker фінальної перевірки вже завершився. Для наступних завдань запустіть команду вище; для GPU після підтвердження завершення навчання задайте `$env:ANALYSIS_ALLOW_GPU='true'` у вікні API та у вікні worker (лише процеси/нащадки, без глобальних змін). Журнал кожного процесу: `storage/logs/analysis-worker-<pid>-<timestamp>.log`. Після активного скасування процес worker закриває ресурси й завершується з кодом 20; PowerShell supervisor запускає наступний worker для черги. Під час обробки одночасно існує лише один власник глобального блокування БД.

Кеші worker/реєстрації ізольовано в `.cache/analysis/`: Ultralytics, torch, Matplotlib, CUDA та torchinductor. `scripts/analysis-env.ps1` встановлює змінні лише для свого процесу/нащадків, після виконання відновлює їх. Кеші та конфігурація навчання не використовуються для аналізу. `YOLO_AUTOINSTALL=false`; worker не встановлює пакети автоматично.

## Реєстрація ваг — тільки після завершення навчання

Спочатку перевірити фактичне завершення через train-full Status, сформувати й переглянути фінальний звіт. Звіт запускає GPU-валідацію: його не виконувати паралельно з навчанням. Поточна фінальна версія вже зареєстрована; повторення register створить дублікат. Для майбутнього окремого звіту використовуйте нову папку поза завершеним експериментом:

```powershell
$run = 'D:\FireVision\runs\full\yolo11n_baseline_20261101T203432Z_b1931c45'
.\scripts\train-full.ps1 -Action Status -RunDir $run
# Тільки коли Status реально completed і процес уже не працює:
$reportDir = 'D:\FireVision\reports\ml\another-final-report' # нова, ще не наявна папка
.\scripts\report-full-training.ps1 -RunDir $run -OutputDir $reportDir
# Тільки для нової, ще не зареєстрованої версії:
.\scripts\register-model.ps1 -Report (Join-Path $reportDir 'report.json') -Name 'YOLO11n — базова версія'
```

Команда вимагає завершений full-run, підсумковий звіт з обома класами val, перевірку цілісності, належність до погоджених pretrained YOLO11n і SHA-256 саме best.pt. Лише після цих умов завантажує фіналізований checkpoint на CPU, перевіряє класи 0=smoke / 1=fire та скінченність ваг. Копіює його в `STORAGE_ROOT/models/<uuid>/weights.pt`, перевіряє SHA, синхронізує файл і записує `model_versions`. Початкові ваги не змінює. У БД — відносний шлях, архітектура, класи, SHA та походження/валідаційні показники; незалежність сцен не стверджується. Реєстрації через HTTP і автоматичної підстановки моделі немає.

## API

| Метод і шлях | Поведінка |
| --- | --- |
| `GET /api/model-versions?page=1&page_size=20` | Версії, архітектура, class_mapping, відносний шлях, SHA, available/unavailable_reason; доступність включає SHA-перевірку |
| `POST /api/analysis-runs` | Існуючі video_source_id, model_version_id, settings; HTTP 201 після COMMIT pending |
| `GET /api/analysis-runs?page=1&page_size=20` | Історія, імена джерел/моделей, стан, реальний прогрес і часи |
| `GET /api/analysis-runs/{id}` | Деталі та незмінний знімок налаштувань |
| `POST /api/analysis-runs/{id}/cancel` | Запит скасування; active залишається running до підтвердження worker |
| `WS /api/analysis-runs/ws?page=1&selected_id=<uuid>` | Знімок історії та вибраного запуску з БД щосекунди й одразу при з’єднанні/refresh |
| `GET /api/analysis-runs/{id}/files/video` | Готовий MP4; FileResponse підтримує Range |
| `GET /api/analysis-runs/{id}/files/detections` | Готовий JSONL |
| `GET /api/analysis-runs/{id}/files/summary` | Готовий JSON-підсумок |

`?download=true` задає attachment; без нього inline. Довільного файлового шляху клієнт не передає. Для незавершеного запуску файли дають HTTP 409; для невідомого id/типу файла — 404. WebSocket перевіряє Origin за CORS_ORIGINS. Після відкриття сторінки/reconnect UI читає API й отримує новий DB snapshot, вибраний запуск відновлюється за збереженим id; прогрес не симулюється таймером.

Тіло POST:

```json
{
  "video_source_id": "<UUID існуючого відео>",
  "model_version_id": "<UUID зареєстрованої моделі>",
  "settings": {
    "smoke_threshold": 0.25,
    "fire_threshold": 0.25,
    "imgsz": 640,
    "analysis_fps": 2,
    "device": "cpu"
  }
}
```

Пороги: 0.01–1, частота: 0.1–60 кадрів/с (верхня межа відбору, без дублікації рідших вихідних кадрів), imgsz: 320–1280, кратне 32, device: cpu або cuda:0. NaN/Inf, сторонні поля, некоректні UUID відхиляються. Без доступної моделі/файла/SHA/інструмента — 409 без створення завдання. Невідоме відеоджерело — 404, заповнена черга — 429. Налаштування включають source/model SHA та class_mapping, захищені DB trigger разом із source/model id і режимом.

## Черга й стани

Використано наявні чотири предметні таблиці; нових таблиць виявлень/користувачів/ролей немає. Міграція `0003_analysis_worker` додає analysis_runs.worker_id, heartbeat_at, cancel_requested_at та посилює незмінність входів. Стани схеми:

- pending — очікування;
- running — оброблення, включно з очікуванням підтвердження скасування;
- completed — усі обов’язкові файли збережені й перевірені;
- failed — помилка, зокрема втрата worker;
- stopped — фактично скасовано; у сторінці «Скасовано».

Admission атомарний через advisory transaction lock, `ANALYSIS_QUEUE_LIMIT=10` обмежує pending + running. Claim: `FOR UPDATE SKIP LOCKED`, унікальний worker_id. Session advisory lock забезпечує один worker на БД; heartbeat і оновлення перевіряють власника. При втраті lock/БД поточна обробка припиняється. API/WS розпізнає аварійні running лише якщо може отримати той самий DB lock — старий PID або давній heartbeat окремо не є доказом. Перерваний запуск стає failed (або stopped, якщо скасування вже запитано), не відновлюється з довільного кадру; користувач створює новий запуск. Наступний worker прибирає відомі приватні залишки.

Pending можна скасувати одразу, running — між кадрами/під час очікування I/O; довгий forward завершується до перевірки прапорця. Зміна вікна або закриття вкладки не надсилає cancel. Завершений запуск не скасовується заднім числом. Partial-файли недоступні через API; при помилці або скасуванні створені файли прибираються. Якщо COMMIT має невідомий результат через втрату зв’язку, файли лишаються в карантині до звірки з БД, щоб не видалити успішно опублікований результат.

## Медіа та результати

Worker перевіряє SHA source/model та читає ffprobe часові мітки кадрів потоково в приватний timeline.jsonl. Далі FFmpeg послідовно декодує кадри; YOLO отримує лише відібрані кадри з явним пристроєм, окремими smoke/fire порогами. Немає автоматичної заміни GPU на CPU або зміни параметрів.

Кожний оригінальний кадр потрапляє у результат. Кадри між викликами детектора не отримують вигадані рамки: у JSONL `analyzed=false`, detections=[]; порожній результат перевіреного кадру має `analyzed=true`. Рамки xyxy — пікселі вихідного кадру, confidence, class_id/name. JSONL також містить frame_index, time_seconds та source_pts_seconds. Час нормалізовано від першого відеокадру, початковий PTS збережено; зсув відеопотоку відносно контейнера понад 10 мс відхиляється, щоб не скорочувати початкову паузу непомітно.

Відео кодується поступово у H.264 MP4 через невеликий MJPEG/Matroska pipe-міст з індивідуальними PTS і BlockDuration, без збереження повної секвенції JPEG та без повного відео/списку виявлень у RAM. FFmpeg працює на CPU, threads=1, fps_mode=passthrough, time base 1 мкс; неправильні часові мітки або невідома тривалість останнього кадру дають помилку замість вигаданого CFR. Зберігається pixel aspect ratio, непарні розміри доповнюються до парних для H.264. Поточна версія не переносить звук/субтитри, не підтримує rotation metadata, зміну роздільної здатності в записі та перший потік-обкладинку; повідомлення про ці обмеження явні. Ліміт кадру — 8 294 400 пікселів, I/O timeout — 60 с. Оригінал залишається незмінним і доступним окремо.

Приватні файли: `STORAGE_ROOT/tmp/analysis/<run>-<worker>/`. Після перевірки кількості всіх кадрів, кожного PTS (допуск 2 мкс) і кінцевої тривалості (3 мкс), закриття/синхронізації обов’язкових файлів каталог атомарно перейменовується в `results/analysis/<run>/<worker>/`, потім публікується COMMIT completed. Обов’язкові результати: annotated.mp4, detections.jsonl, summary.json. У БД лише відносні шляхи та агрегати (frames_read, frames_analyzed, detections_by_class, video_duration_seconds, wall_seconds, device); кількість рамок не є кількістю подій.

GPU аналізу типово вимкнений. Після завершення навчання, якщо потрібна GPU-перевірка, явно встановити `ANALYSIS_ALLOW_GPU=true` локально й перезапустити API/worker. Навіть за дозволу worker мусить отримати `.cache/full-training-gpu0.lock`, який використовує training worker. Заблокований GPU дає failed з поясненням, а не паралельне виконання чи CPU fallback. Сторонні програми цим проєктним lock не керуються.

## Перевірки та відкладена частина

```powershell
Set-Location D:\FireVision
.\scripts\check-analysis.ps1
```

Потрібні наявні PostgreSQL із CREATEDB, FFmpeg, Edge і готовий ML `.venv` (для OpenCV/NumPy та тестового клієнта). Тести створюють власну `firevision_analysis_test_*`, зберігають лише тестові матеріали в `.tmp/analysis-test-*`, видаляють свою БД. Fake detector живе тільки в tests; продакшн CLI не має перемикача або fallback на нього. Перевіряються API, порожні моделі, валідація/SHA, concurrent claim/capacity, snapshot trigger, cancellation, аварійний child-process, DB commit failure, очистка, VFR/нерівна остання тривалість кадру, Range/seek, різні пороги та живий прогрес WebSocket. Browser-тести вимикають GPU й hardware video decode. TypeScript/build та pip check також входять у команду. Попередні БД/API/відеоперевірки запущені окремо через зміну схеми й навігації.

**Після реєстрації виконано 02.11.2026:** реальний Ultralytics CUDA forward, наскрізний upload → зареєстрована модель → queue → окремий worker → MP4/JSONL → браузер; реальний WS-прогрес, повна відповідність PTS, Range/play/seek/download/reload та візуальна перевірка успішних і помилкових рамок. Матеріал — технічний відеоряд із val-зображень. **Ще потрібно:** природне відео полум'я/диму з негативними фрагментами, природна часова динаміка/VFR, перевірка навантаження/OOM за окремим завданням. Фінальні ваги в цьому інтеграційному запуску на CPU не перевіряли — пристрій був явно CUDA без fallback. Незалежну якість та часові події цей сценарій не доводить. Зони й часові події тепер реалізовані та перевірені ізольовано (див. EVENTS.md), природна відеоперевірка ще потрібна. Багатоджерельний моніторинг не реалізований.

Технічні джерела: [Uvicorn WebSocket settings](https://www.uvicorn.org/settings/#implementation), [wsproto 1.3.2](https://pypi.org/project/wsproto/1.3.2/), [FFmpeg timing options](https://ffmpeg.org/ffmpeg.html), [Matroska codec mappings](https://www.matroska.org/technical/codec_specs.html), [Matroska timestamp/duration specification](https://www.matroska.org/technical/elements.html).
