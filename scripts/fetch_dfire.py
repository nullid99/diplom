"""Отримання Kaggle-версії, прямо зазначеної авторами D-Fire."""
import hashlib
import json
import shutil
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from backend.app.config import PROJECT_ROOT

SOURCE = 'https://www.kaggle.com/api/v1/datasets/download/sayedgamal99/smoke-fire-detection-yolo?datasetVersionNumber=1'
ROOT = PROJECT_ROOT / 'datasets/dfire'


def fetch_provenance():
    sources = {
        'README.md': 'https://raw.githubusercontent.com/gaia-solutions-on-demand/DFireDataset/master/README.md',
        'LICENSE': 'https://raw.githubusercontent.com/gaia-solutions-on-demand/DFireDataset/master/LICENSE',
        'utils_utils.py': 'https://raw.githubusercontent.com/gaia-solutions-on-demand/DFireDataset/master/utils/utils.py',
        'author-dfire.yaml': 'https://raw.githubusercontent.com/pedbrgs/Fire-Detection/master/data/dfire.yaml',
        'kaggle-metadata.json': 'https://www.kaggle.com/api/v1/datasets/view/sayedgamal99/smoke-fire-detection-yolo',
    }
    evidence = []
    for filename, url in sources.items():
        destination = ROOT / 'provenance' / filename
        if not destination.exists():
            with urllib.request.urlopen(url, timeout=30) as response, destination.open('xb') as output:
                shutil.copyfileobj(response, output)
        with destination.open('rb') as source:
            checksum = hashlib.file_digest(source, 'sha256').hexdigest()
        evidence.append({'file': filename, 'source': url, 'sha256': checksum})
    manifest = ROOT / 'provenance/sources.json'
    if not manifest.exists():
        manifest.write_text(json.dumps({'recorded_at': datetime.now(timezone.utc).isoformat(), 'sources': evidence}, indent=2), encoding='utf-8')


def main():
    for folder in ('archives', 'raw', 'provenance'):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    fetch_provenance()
    free = shutil.disk_usage(PROJECT_ROOT).free
    if free < 12 * 1024**3:
        raise RuntimeError('На D: потрібно щонайменше 12 ГіБ вільного місця для архіву, даних і звітів.')
    archive = ROOT / 'archives/dfire-kaggle-v1.zip'
    if not archive.exists():
        partial = archive.with_suffix('.part')
        print('Вільно на D:, байтів:', free, flush=True)
        try:
            with urllib.request.urlopen(SOURCE, timeout=60) as response:
                if 'zip' not in response.headers.get('Content-Type', '').lower() and 'octet-stream' not in response.headers.get('Content-Type', '').lower():
                    raise RuntimeError('Kaggle не повернув архів; можливий вхід або блокування. Не обходити обмеження.')
                total = 0
                with partial.open('wb') as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                        total += len(chunk)
                        if total % (128 * 1024 * 1024) == 0:
                            print('Завантажено MiB:', total // 1024**2, flush=True)
            if not zipfile.is_zipfile(partial):
                raise RuntimeError('Отриманий файл не є ZIP-архівом.')
            partial.rename(archive)
        except Exception:
            print('Автоматичне отримання не завершено. Ручне джерело: https://www.kaggle.com/datasets/sayedgamal99/smoke-fire-detection-yolo; папка: datasets/dfire/archives.', flush=True)
            raise
    with archive.open('rb') as source:
        checksum = hashlib.file_digest(source, 'sha256').hexdigest()
    raw = ROOT / 'raw'
    marker = ROOT / 'provenance/extraction.json'
    if marker.exists() and json.loads(marker.read_text(encoding='utf-8'))['archive_sha256'] != checksum:
        raise RuntimeError('Архів не відповідає маркеру початкових даних; автоматична заміна заборонена.')
    if not marker.exists():
        if any(raw.iterdir()):
            raise RuntimeError('raw не порожній без маркера завершення; перевірте перерване розпакування вручну.')
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                if not (raw / entry.filename).resolve().is_relative_to(raw.resolve()):
                    raise RuntimeError('Архів має некоректний шлях.')
            bundle.extractall(raw)
        marker.write_text(json.dumps({'archive_sha256': checksum}, indent=2), encoding='utf-8')
    manifest = {
        'source': SOURCE, 'author_repository': 'https://github.com/gaia-solutions-on-demand/DFireDataset',
        'retrieved_at': datetime.now(timezone.utc).isoformat(), 'archive': str(archive.relative_to(PROJECT_ROOT)),
        'archive_bytes': archive.stat().st_size, 'sha256': checksum,
        'free_bytes_before_download': free,
    }
    destination = ROOT / 'provenance/download.json'
    if not destination.exists():
        destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == '__main__':
    main()
