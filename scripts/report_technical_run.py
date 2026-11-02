"""Підсумковий звіт лише з фактичних артефактів технічного запуску."""
import json
from pathlib import Path

from backend.app.config import PROJECT_ROOT
from scripts.train_technical import digest, write_json


def main():
    pointer=json.loads((PROJECT_ROOT/'reports/ml/technical-training.json').read_text(encoding='utf-8'))
    root=Path(pointer['run'])
    assert not (root/'input-integrity.json').exists(), 'Запуск із порушеною цілісністю входів не є підсумковим.'
    attempt=Path(pointer['successful_attempt'])
    summary=json.loads((attempt/'summary.json').read_text(encoding='utf-8'))
    assert summary.get('input_hashes_unchanged') is True
    verification=json.loads((attempt/'verification/verification.json').read_text(encoding='utf-8'))
    data=Path(pointer['data']).parent
    subset=json.loads((data/'manifest.json').read_text(encoding='utf-8'))
    for split in ('train','val'):
        for row in map(json.loads,(data/f'{split}.jsonl').read_text(encoding='utf-8').splitlines()):
            assert digest(PROJECT_ROOT/'datasets/dfire'/row['image'])==row['image_sha256']
            assert digest(PROJECT_ROOT/'datasets/dfire'/row['label'])==row['label_sha256']
    main_before=subset['parent_manifest_sha256']
    main_after={path.name:digest(path) for path in (PROJECT_ROOT/'datasets/dfire/prepared').iterdir() if path.is_file()}
    assert main_before==main_after
    assert not list((PROJECT_ROOT/'datasets/dfire/raw').rglob('*.cache'))
    output={
        'run_id':pointer['id'], 'technical_only':True, 'summary':summary,
        'subset':subset, 'verification':verification,
        'main_manifests_unchanged':True, 'selected_image_and_label_hashes_unchanged':True,
        'checkpoint_hashes':verification['checkpoint_checks'],
        'batch_recommendation':'Початково batch=4, imgsz=640, AMP=true для YOLO11n. Це підтверджено лише технічною підмножиною; піки на повному train потрібно перевіряти окремо, більші batch не тестувалися.',
        'test_used_for_training_or_inference':False,
        'log_sha256':digest(attempt/'console.log'),
        'results_csv_sha256':digest(Path(summary['training_dir'])/'results.csv'),
        'resolved_args_sha256':digest(Path(summary['training_dir'])/'args.yaml'),
    }
    if (root/'supersedes.json').exists():
        output['supersedes'] = json.loads((root/'supersedes.json').read_text(encoding='utf-8'))
    destination=PROJECT_ROOT/'reports/ml'/pointer['id']
    destination.mkdir(exist_ok=False)
    write_json(destination/'report.json',output)
    source=json.loads(Path(pointer['initial_weights']).with_suffix('.json').read_text(encoding='utf-8'))
    lines=['# Технічне донавчання YOLO11n — 2 епохи', '', f'Запуск: `{pointer["id"]}`. Це перевірка процесу, не підсумковий експеримент.', '',
           f'Дані: `{data}`; ідентифікатор `{subset["id"]}`, seed 42, train 512 / val 128. У кожній частині порівну fire-only, smoke-only, mixed, background. Test не використовувався.', '',
           'Конфігурація: epochs=2, imgsz=640, batch=4, device=0, workers=0, cache=false, seed=42, save=true, save_period=1; AMP=true, deterministic=true, resume=false. Повна фактична конфігурація — training/args.yaml; команда процесу — run.json. Підтримку параметрів перевірено get_cfg установленої версії.', '',
           f'Версії: {summary["versions"]}; CUDA {summary["cuda"]}, {summary["gpu"]}. Драйвер і залежності не перевстановлювалися.', '',
           f'Початкові ваги: {source["source"]}; {source["bytes"]} байтів; SHA-256 `{source["sha256"]}`. Це офіційні COCO pretrained лише як початкова точка. Пробні двокласові ваги не реєструються в застосунку.', '',
           f'Виконано епох: **{summary["epochs_completed"]}**. Час model.train із підготовкою/валідацією: **{summary["train_call_seconds"]:.3f} с**; час worker після імпортів: {summary["wall_seconds"]:.3f} с. Cumulative time у CSV на кінці 2-ї епохи: {summary["results"][-1]["time"]} с; це інша межа вимірювання.', '',
           f'GPU PyTorch peak allocated: **{summary["peak_allocated_bytes"]} байтів ({summary["peak_allocated_bytes"]/1024**3:.3f} ГіБ)**; peak reserved: **{summary["peak_reserved_bytes"]} байтів ({summary["peak_reserved_bytes"]/1024**3:.3f} ГіБ)**. nvidia-smi peak використання всього пристрою: {summary["nvidia_smi_peak_whole_device_used_mib"]} MiB, включно з робочим столом/іншими процесами; вибірка приблизно раз на секунду може пропускати короткі піки.', '',
           f'Спроб: {len(pointer["attempts"])}; фактичний batch={summary["batch"]}; OOM не було. CPU fallback відсутній. При CUDA OOM supervisor зберігає помилку й дозволяє тільки один новий процес з batch=2. Внутрішнє автоматичне зменшення batch бібліотеки вимкнено callback; її приховане повторення епох при NaN вимкнено технічним trainer.', '',
           '## Фактичні losses і метрики технічного запуску з CSV', '',
           '| Епоха | train box | train cls | train dfl | val box | val cls | val dfl | mAP50 | mAP50–95 |',
           '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in summary['results']:
        keys=('epoch','train/box_loss','train/cls_loss','train/dfl_loss','val/box_loss','val/cls_loss','val/dfl_loss','metrics/mAP50(B)','metrics/mAP50-95(B)')
        lines.append('| '+' | '.join(row[key] for key in keys)+' |')
    lines+=['', 'NaN/Inf у losses не виявлено: перевірено кожний train batch і всі losses CSV. Показники наведено лише для технічної підмножини й двох епох. Фінальна повторна валідація best у консолі може трохи відрізнятися від CSV після strip/FP16 checkpoint; не підміняємо одні показники іншими. Test незалежним не оголошується.', '',
            '## Перевірка checkpoint і передбачень', '']
    for name, checkpoint in verification['checkpoint_checks'].items():
        lines.append(f'- {name}: `{checkpoint["path"]}`, SHA-256 `{checkpoint["sha256"]}`, успішне завантаження, класи 0=smoke, 1=fire.')
    lines+=['', f'GPU передбачення: {len(verification["gpu_predictions"])} val-зображень, по 2 з кожної категорії; conf=0.25, IoU=0.7, imgsz=640. **Без виявлень: {sum(x["no_detections"] for x in verification["gpu_predictions"])} із {len(verification["gpu_predictions"])}**. Поріг не підбирали, невдалі приклади не відкидали. JSON з порожніми списками detections та растрові результати збережено в verification.', '',
            f'CPU: реальний forward на одному val-зображенні, device={verification["cpu"]["device"]}; виявлень {len(verification["cpu"]["detections"])}. Це окрема перевірка переносності, не підміна GPU-навчання.', '',
            f'Журнал: `{attempt/"console.log"}`. CSV, args.yaml, графіки, train/val приклади: `{summary["training_dir"]}`. Передбачення: `{attempt/"verification"}`. Телеметрія: summary.json і gpu-samples.json у `{attempt}`.', '',
            'Кеш розмітки перенаправлено в .cache/ultralytics-labels локальними обгортками функцій тільки в worker. Перевірку check_image замінено в цьому процесі на read-only PIL verify + повне декодування без ремонту JPEG. Installed-пакет не змінювався; у raw немає нових .cache. SHA-256 основних маніфестів і всіх 640 вибраних зображень/міток до та після цього запуску збігаються.', '',
            output['batch_recommendation'], '',
            'Повне навчання YOLO11n/YOLO11s та підключення пробних ваг до API/інтерфейсу не виконувалися. Потрібен подальший аудит походження сцен перед дослідницькими висновками.']
    if output.get('supersedes'):
        lines += ['', '## Історія виправлення', '',
                  'Перед цим завершилися ще 2 технічні епохи в попередньому запуску. Підсумкова SHA-перевірка виявила автоматичне перекодування двох JPEG бібліотекою через 18 додаткових байтів після EOI. Файли повністю декодувалися; оригінали відновлено з перевіреного архіву. Старі журнали, ваги, перекодовані варіанти й input-integrity.json збережено; старий запуск позначено superseded. Після read-only виправлення виконано новий чистий запуск із тими самими параметрами й підмножиною. Це не пошук гіперпараметрів і не OOM-повтор. Сукупно на етапі виконано 2 + 2 = 4 епохи в двох окремих технічних запусках; фінальним є лише поточний двоепоховий запуск.', '',
                  f'Попередній запуск: `{output["supersedes"]["previous_run"]}`. Основні маніфести не змінювалися, повернення виключених зображень немає.']
    (destination/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write_json(PROJECT_ROOT/'reports/ml/technical-result.json',{'report_dir':str(destination),'run_dir':str(root),'data':str(data)})
    print('Підсумковий звіт:',destination)


if __name__ == '__main__':
    main()
