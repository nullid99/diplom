"""Дві технічні епохи YOLO11n у власному процесі, без інтеграції з API."""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.app.config import PROJECT_ROOT

WEIGHTS_URL = 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def initial_weights():
    path = PROJECT_ROOT / 'weights/pretrained/yolo11n-v8.3.0.pt'
    provenance = path.with_suffix('.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        partial = path.with_suffix('.part')
        with urllib.request.urlopen(WEIGHTS_URL, timeout=60) as source, partial.open('xb') as destination:
            while chunk := source.read(1024*1024):
                destination.write(chunk)
        partial.rename(path)
    checksum = digest(path)
    if provenance.exists():
        assert json.loads(provenance.read_text(encoding='utf-8'))['sha256'] == checksum
    else:
        write_json(provenance, {'source': WEIGHTS_URL, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'sha256': checksum, 'bytes': path.stat().st_size, 'purpose': 'Офіційні COCO pretrained лише як початкова точка донавчання; не готовий детектор вогню/диму.'})
    return path


def monitor_gpu(stop, samples):
    while not stop.is_set():
        try:
            result = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,memory.free', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5)
            used, free = [int(value.strip()) for value in result.stdout.splitlines()[0].split(',')]
            samples.append({'time': time.time(), 'device_used_mib': used, 'device_free_mib': free})
        except Exception:
            pass
        stop.wait(1)


def readonly_check_image(im_file):
    """Перевірка декодування без автоматичного JPEG-ремонту початкових даних."""
    from PIL import Image
    from ultralytics.data.utils import exif_size, IMG_FORMATS
    formats = ('JPEG', 'PNG', 'BMP', 'WEBP', 'TIFF', 'JPEG2000', 'MPO')
    with Image.open(im_file, formats=formats) as picture:
        image_format = picture.format.lower()
        picture.verify()
    with Image.open(im_file, formats=formats) as picture:
        width, height = exif_size(picture)
        picture.load()
    assert min(width, height) > 9
    assert image_format in IMG_FORMATS | {'jpeg2000'}
    # Додаткові байти після JPEG EOI не є підставою перезаписувати джерело,
    # якщо verify й повне декодування успішні.
    return '', (height, width)


def worker(data, directory, batch, weights):
    import torch
    import yaml
    import ultralytics
    from ultralytics import YOLO
    from ultralytics.cfg import get_cfg
    from ultralytics.models.yolo.detect.train import DetectionTrainer
    import ultralytics.data.dataset as dataset_module
    import ultralytics.data.utils as data_utils_module
    from unittest.mock import patch

    directory = Path(directory)
    summary = {'status': 'running', 'batch': batch, 'technical_only': True, 'started_at': datetime.now(timezone.utc).isoformat()}
    write_json(directory / 'summary.json', summary)
    samples, stop = [], threading.Event()
    monitor = threading.Thread(target=monitor_gpu, args=(stop, samples), daemon=True)
    monitor.start()
    start = time.perf_counter()
    training_start = None
    model = None
    try:
        assert torch.cuda.is_available(), 'CUDA недоступна; CPU fallback заборонено.'
        torch.cuda.set_device(0)
        torch.cuda.reset_peak_memory_stats(0)
        configuration = yaml.safe_load(Path(data).read_text(encoding='utf-8'))
        assert configuration['names'] == {0: 'smoke', 1: 'fire'} and 'test' not in configuration
        manifest = json.loads((Path(data).parent / 'manifest.json').read_text(encoding='utf-8'))
        for filename, checksum in manifest['files_sha256'].items():
            assert digest(Path(data).parent / filename) == checksum
        summary.update(versions={name: importlib.metadata.version(name) for name in ('torch','torchvision','ultralytics','numpy','opencv-python')}, python=sys.version, cuda=torch.version.cuda, gpu=torch.cuda.get_device_name(0), initial_weights_sha256=digest(weights), subset_manifest_sha256=digest(Path(data).parent/'manifest.json'))
        options = dict(data=str(data), epochs=2, imgsz=640, batch=batch, device=0, workers=0, cache=False, seed=42, save=True, save_period=1, project=str(directory), name='training', exist_ok=False, pretrained=True, resume=False, deterministic=True, amp=True, plots=True, verbose=True)
        get_cfg(overrides=options)  # Перевіряє параметри саме встановленої версії.
        write_json(directory / 'requested-config.json', options)
        model = YOLO(str(weights))

        class TechnicalTrainer(DetectionTrainer):
            def _handle_nan_recovery(self, epoch):
                if self.loss is not None and not bool(torch.isfinite(self.loss).all()):
                    raise FloatingPointError('NaN/Inf training loss; автоматичне повторення епохи вимкнено.')
                if self.fitness is not None and not math.isfinite(float(self.fitness)):
                    raise FloatingPointError('NaN/Inf validation fitness.')
                return False

        progress = {'batches_seen': 0}

        def epoch_start(trainer):
            assert trainer.device.type == 'cuda' and trainer.device.index in (None, 0)
            trainer._oom_retries = 3  # Вимикає приховані 3 повтори бібліотеки; повтором керує supervisor.
            progress['epoch'] = trainer.epoch + 1
            write_json(directory/'progress.json', progress)

        def batch_end(trainer):
            if trainer.loss is not None and not bool(torch.isfinite(trainer.loss).all()):
                raise FloatingPointError('NaN/Inf training loss.')
            progress['batches_seen'] += 1
            if progress['batches_seen'] % 16 == 0:
                progress.update(loss=float(trainer.loss.detach().cpu()), peak_allocated_bytes=torch.cuda.max_memory_allocated(0))
                write_json(directory/'progress.json', progress)

        model.add_callback('on_train_epoch_start', epoch_start)
        model.add_callback('on_train_batch_end', batch_end)
        original_load = dataset_module.load_dataset_cache_file
        original_save = dataset_module.save_dataset_cache_file

        def cache_location(path):
            target = PROJECT_ROOT / '.cache/ultralytics-labels' / (hashlib.sha256(('readonly-v1:'+str(path)).encode()).hexdigest()+'.cache')
            target.parent.mkdir(parents=True, exist_ok=True)
            return target

        def load_cache(path):
            return original_load(cache_location(path))

        def save_cache(prefix, path, payload, version):
            return original_save(prefix, cache_location(path), payload, version)

        training_start = time.perf_counter()
        with patch.object(dataset_module, 'load_dataset_cache_file', load_cache), patch.object(dataset_module, 'save_dataset_cache_file', save_cache), patch.object(data_utils_module, 'check_image', readonly_check_image):
            model.train(trainer=TechnicalTrainer, **options)
        for split in ('train','val'):
            for row in map(json.loads,(Path(data).parent/f'{split}.jsonl').read_text(encoding='utf-8').splitlines()):
                assert digest(PROJECT_ROOT/'datasets/dfire'/row['image']) == row['image_sha256'], 'Порушено незмінність зображення.'
                assert digest(PROJECT_ROOT/'datasets/dfire'/row['label']) == row['label_sha256'], 'Порушено незмінність розмітки.'
        summary['input_hashes_unchanged'] = True
        summary['image_verification_policy'] = 'readonly-v1: PIL verify + full decode, no JPEG rewrite'
        summary['train_call_seconds'] = time.perf_counter()-training_start
        csv_path = Path(model.trainer.save_dir) / 'results.csv'
        with csv_path.open(encoding='utf-8') as stream:
            rows = [{key.strip(): value.strip() for key,value in row.items()} for row in csv.DictReader(stream)]
        assert len(rows) == 2, 'Технічний запуск має виконати рівно 2 епохи.'
        assert model.trainer.batch_size == batch, 'Бібліотека змінила batch без supervisor.'
        losses = {f'epoch_{i+1}': {key: float(value) for key,value in row.items() if 'loss' in key} for i,row in enumerate(rows)}
        assert all(math.isfinite(value) for row in losses.values() for value in row.values())
        summary.update(status='success', epochs_completed=len(rows), losses_finite=True, losses=losses, results=rows, training_dir=str(model.trainer.save_dir), checkpoint_best=str(model.trainer.best), checkpoint_last=str(model.trainer.last), peak_allocated_bytes=torch.cuda.max_memory_allocated(0), peak_reserved_bytes=torch.cuda.max_memory_reserved(0), final_device=str(model.trainer.device))
    except BaseException as error:
        details = traceback.format_exc()
        (directory/'error.txt').write_text(details, encoding='utf-8')
        summary.update(status='failed', error_type=type(error).__name__, error=str(error), cuda_oom=isinstance(error, torch.cuda.OutOfMemoryError) or ('out of memory' in str(error).lower() and 'cuda' in str(error).lower()))
        print(details, flush=True)
    finally:
        stop.set()
        monitor.join(timeout=6)
        summary.update(wall_seconds=time.perf_counter()-start, finished_at=datetime.now(timezone.utc).isoformat())
        if torch.cuda.is_initialized():
            summary['peak_allocated_bytes'] = torch.cuda.max_memory_allocated(0)
            summary['peak_reserved_bytes'] = torch.cuda.max_memory_reserved(0)
        if samples:
            summary['nvidia_smi_peak_whole_device_used_mib'] = max(sample['device_used_mib'] for sample in samples)
        write_json(directory/'gpu-samples.json', samples)
        write_json(directory/'summary.json', summary)
    return 0 if summary['status']=='success' else 1


def supervise(data):
    weights = initial_weights()
    identifier = 'yolo11n_trial_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    root = PROJECT_ROOT / 'runs/technical' / identifier
    root.mkdir(parents=True, exist_ok=False)
    info = {'id': identifier, 'data': str(Path(data).resolve()), 'initial_weights': str(weights), 'attempts': [], 'technical_only': True}
    for batch in (4, 2):
        directory = root / f'batch-{batch}'
        directory.mkdir(exist_ok=False)
        command = [sys.executable, '-X', 'utf8', '-u', '-m', 'scripts.train_technical', '--worker', '--data', str(data), '--attempt-dir', str(directory), '--batch', str(batch), '--weights', str(weights)]
        info['attempts'].append({'batch': batch, 'directory': str(directory), 'command': command})
        write_json(root/'run.json', info)
        print(f'Запуск GPU batch={batch}; журнал: {directory / "console.log"}', flush=True)
        with (directory/'console.log').open('w', encoding='utf-8') as output:
            completed = subprocess.run(command, cwd=PROJECT_ROOT, stdout=output, stderr=subprocess.STDOUT, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        summary_path = directory/'summary.json'
        summary = json.loads(summary_path.read_text(encoding='utf-8')) if summary_path.exists() else {'status':'failed','error':'Worker завершився без звіту.'}
        info['attempts'][-1]['result'] = summary
        write_json(root/'run.json', info)
        if completed.returncode==0 and summary['status']=='success':
            info.update(status='success', successful_attempt=str(directory))
            write_json(root/'run.json', info)
            write_json(PROJECT_ROOT/'reports/ml/technical-training.json', {'run':str(root), **info})
            print('Технічне навчання завершено:', root, flush=True)
            return 0
        if batch != 4 or not summary.get('cuda_oom'):
            info['status']='failed'
            write_json(root/'run.json',info)
            print('Запуск не завершено; деталі збережено:', directory, flush=True)
            return 1
        print('Зафіксовано CUDA OOM. Один окремий повтор із batch=2.', flush=True)
    return 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--attempt-dir', type=Path)
    parser.add_argument('--batch', type=int, choices=(4,2), default=4)
    parser.add_argument('--weights', type=Path)
    args=parser.parse_args()
    if args.data is None:
        args.data=Path(json.loads((PROJECT_ROOT/'reports/ml/technical-input.json').read_text())['data'])
    if args.worker:
        return worker(args.data,args.attempt_dir,args.batch,args.weights)
    return supervise(args.data)


if __name__ == '__main__':
    sys.exit(main())
