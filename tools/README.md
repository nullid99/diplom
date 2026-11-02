# Portable FFmpeg

Підготовка: `scripts/setup-ffmpeg.ps1`. Бінарні файли, ліцензії та документація збірки розміщуються в `tools/ffmpeg/`; глобальний PATH не змінюється.

Джерело: [офіційна сторінка FFmpeg для Windows](https://ffmpeg.org/download.html#build-windows) → [Gyan Windows builds](https://www.gyan.dev/ffmpeg/builds/).

Зафіксовано release essentials 9.0.2: [архів](https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip), [SHA-256 постачальника](https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip.sha256).

SHA-256: `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`. Інсталятор перевіряє суму й не перезаписує наявний каталог інструментів. Архів кешується на D: у `.cache/downloads`; розпакування виконується в тимчасовий каталог у `tools`.
