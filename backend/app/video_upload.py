"""Потокове читання multipart без проміжного файлу на системному диску."""
import hashlib
import os
import uuid
from pathlib import Path

from fastapi import HTTPException, Request
from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header
from starlette.concurrency import run_in_threadpool

from backend.app.config import Settings, storage_path


class VideoUpload:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = storage_path(f'tmp/uploads/{uuid.uuid4().hex}.part', settings.storage_root)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = None
        self.owns_file = False
        self.size = 0
        self.digest = hashlib.sha256()
        self.name = ''
        self.original_filename = ''
        self.seen = set()
        self.completed = False
        self.header_bytes = 0
        self.part = ''

    def on_part_begin(self):
        self.headers = {}
        self.header_name = bytearray()
        self.header_value = bytearray()
        self.field_data = bytearray()

    def header_data(self, target, data, start, end):
        self.header_bytes += end - start
        if self.header_bytes > 16384:
            raise HTTPException(400, 'Заголовки форми завеликі.')
        target.extend(data[start:end])

    def on_header_field(self, data, start, end):
        self.header_data(self.header_name, data, start, end)

    def on_header_value(self, data, start, end):
        self.header_data(self.header_value, data, start, end)

    def on_header_end(self):
        self.headers[bytes(self.header_name).lower()] = bytes(self.header_value)
        self.header_name.clear()
        self.header_value.clear()

    def on_headers_finished(self):
        _, options = parse_options_header(self.headers.get(b'content-disposition', b''))
        field = options.get(b'name', b'')
        if field not in (b'name', b'file') or field in self.seen:
            raise HTTPException(400, 'Потрібні рівно одне поле name та один файл file.')
        self.seen.add(field)
        self.part = field.decode('ascii')
        if field == b'file':
            try:
                filename = options.get(b'filename', b'').decode('utf-8')
            except UnicodeDecodeError:
                raise HTTPException(400, 'Ім’я файлу має бути в UTF-8.') from None
            self.original_filename = filename.replace('\\', '/').split('/')[-1]
            if not self.original_filename or len(self.original_filename) > 255 or '\x00' in filename:
                raise HTTPException(422, 'Некоректне оригінальне ім’я файлу.')
            self.stream = self.path.open('xb')
            self.owns_file = True

    def on_part_data(self, data, start, end):
        chunk = data[start:end]
        if self.part == 'file':
            self.size += len(chunk)
            if self.size > self.settings.upload_max_bytes:
                raise HTTPException(413, 'Файл перевищує налаштований ліміт розміру.')
            self.stream.write(chunk)
            self.digest.update(chunk)
        else:
            if len(self.field_data) + len(chunk) > 2048:
                raise HTTPException(422, 'Назва джерела завелика.')
            self.field_data.extend(chunk)

    def on_part_end(self):
        if self.part == 'file':
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()
        else:
            try:
                self.name = self.field_data.decode('utf-8').strip()
            except UnicodeDecodeError:
                raise HTTPException(422, 'Назва джерела має бути в UTF-8.') from None

    def on_end(self):
        self.completed = True

    async def receive(self, request: Request):
        kind, options = parse_options_header(request.headers.get('content-type', ''))
        boundary = options.get(b'boundary')
        if kind != b'multipart/form-data' or not boundary or len(boundary) > 200:
            raise HTTPException(400, 'Очікується multipart/form-data з полями name і file.')
        callbacks = {name: getattr(self, name) for name in (
            'on_part_begin', 'on_header_field', 'on_header_value', 'on_header_end',
            'on_headers_finished', 'on_part_data', 'on_part_end', 'on_end',
        )}
        parser = MultipartParser(boundary, callbacks)
        received = 0
        try:
            async for chunk in request.stream():
                received += len(chunk)
                if received > self.settings.upload_max_bytes + 65536:
                    raise HTTPException(413, 'Завантаження перевищує налаштований ліміт розміру.')
                await run_in_threadpool(parser.write, chunk)
            parser.finalize()
        except MultipartParseError:
            raise HTTPException(400, 'Некоректна або незавершена форма завантаження.') from None
        if not self.completed or self.seen != {b'name', b'file'}:
            raise HTTPException(400, 'Завантаження не завершено або поля форми відсутні.')
        if not self.name or len(self.name) > 255 or '\x00' in self.name:
            raise HTTPException(422, 'Назва джерела має містити від 1 до 255 символів.')
        if self.size == 0:
            raise HTTPException(422, 'Завантажений файл порожній.')

    def cleanup(self):
        if self.stream and not self.stream.closed:
            self.stream.close()
        if self.owns_file:
            self.path.unlink(missing_ok=True)
