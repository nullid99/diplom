"""Portable FFmpeg зі збірки, на яку посилається офіційний сайт FFmpeg."""
import hashlib
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from backend.app.config import PROJECT_ROOT

URL = 'https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip'
SHA256 = '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'
ARCHIVE_SIZE = 114768076


def main():
    target = PROJECT_ROOT / 'tools' / 'ffmpeg'
    if not target.exists():
        cache = PROJECT_ROOT / '.cache' / 'downloads'
        cache.mkdir(parents=True, exist_ok=True)
        archive = cache / 'ffmpeg-9.0.2-essentials_build.zip'
        valid = False
        if archive.exists():
            with archive.open('rb') as cached:
                valid = hashlib.file_digest(cached, 'sha256').hexdigest() == SHA256
        if not valid:
            partial = archive.with_suffix('.part')
            offset = partial.stat().st_size if partial.exists() else 0
            print('Завантаження portable FFmpeg; уже отримано байтів:', offset, flush=True)
            if offset >= ARCHIVE_SIZE:
                partial.unlink()
                offset = 0
            try:
                while offset < ARCHIVE_SIZE:
                    last = min(offset + 8 * 1024 * 1024, ARCHIVE_SIZE) - 1
                    request = urllib.request.Request(URL, headers={'Range': f'bytes={offset}-{last}'})
                    with urllib.request.urlopen(request, timeout=30) as response:
                        if response.status != 206 or not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                            raise RuntimeError('Сервер не підтвердив запитаний фрагмент архіву.')
                        with partial.open('ab') as output:
                            shutil.copyfileobj(response, output, length=65536)
                    offset = partial.stat().st_size
                    print('Отримано байтів:', offset, flush=True)
                with partial.open('rb') as source:
                    checksum = hashlib.file_digest(source, 'sha256').hexdigest()
                if checksum != SHA256:
                    partial.unlink(missing_ok=True)
                    raise RuntimeError('Контрольна сума архіву не збігається.')
                partial.replace(archive)
            except Exception:
                print('Завантаження не завершено; частковий файл залишено для повторного запуску.', flush=True)
                raise
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='ffmpeg-', dir=target.parent) as staging:
            staging = Path(staging)
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.infolist():
                    if not (staging / member.filename).resolve().is_relative_to(staging.resolve()):
                        raise RuntimeError('Некоректний шлях в архіві.')
                bundle.extractall(staging)
            roots = [path for path in staging.iterdir() if (path / 'bin' / 'ffmpeg.exe').is_file()]
            if len(roots) != 1 or not (roots[0] / 'bin' / 'ffprobe.exe').is_file():
                raise RuntimeError('Архів не містить очікуваних інструментів.')
            roots[0].rename(target)
    for executable in ('ffmpeg', 'ffprobe'):
        result = subprocess.run([str(target / 'bin' / (executable + '.exe')), '-version'], capture_output=True, text=True, check=True, timeout=15)
        print(result.stdout.splitlines()[0])


if __name__ == '__main__':
    main()
