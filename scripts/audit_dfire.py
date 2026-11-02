"""Відтворюваний аудит D-Fire; початкові файли не змінюються."""
import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from backend.app.config import PROJECT_ROOT

DATASET = PROJECT_ROOT / 'datasets/dfire'
REPORTS = PROJECT_ROOT / 'reports/dfire'
NEAR_DISTANCE = 6


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect_image(item):
    from PIL import Image
    import imagehash
    split, image = item
    label = image.parent.parent / 'labels' / (image.stem + '.txt')
    record = {
        'split': split, 'image': image.relative_to(DATASET).as_posix(),
        'label': label.relative_to(DATASET).as_posix(), 'image_sha256': sha256(image),
        'label_sha256': sha256(label) if label.exists() else None,
        'image_bytes': image.stat().st_size, 'issues': [], 'boxes': [],
        'background_verified': False,
        'annotation_lines': 0, 'raw_objects_by_class': {},
        'source_family': 'AoF' if image.name.startswith('AoF') else 'PublicDataset' if image.name.startswith('PublicDataset') else 'WEB' if image.name.startswith('WEB') else 'unknown',
    }
    try:
        with Image.open(image) as picture:
            picture.load()
            rgb = picture.convert('RGB')
            record.update(width=rgb.width, height=rgb.height,
                          pixel_sha256=hashlib.sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest(),
                          phash=str(imagehash.phash(rgb, hash_size=8)))
    except Exception as error:
        record['issues'].append('unreadable_image:' + type(error).__name__)
    if not label.exists():
        record['issues'].append('missing_label_unknown_background')
        return record
    try:
        lines = label.read_text(encoding='utf-8-sig').splitlines()
    except (OSError, UnicodeError):
        record['issues'].append('unreadable_label')
        return record
    if not any(line.strip() for line in lines):
        record['background_verified'] = True
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        record['annotation_lines'] += 1
        try:
            parts = line.split()
            if parts and parts[0] in ('0', '1'):
                record['raw_objects_by_class'][parts[0]] = record['raw_objects_by_class'].get(parts[0], 0) + 1
            if len(parts) != 5 or parts[0] not in ('0', '1'):
                raise ValueError('class_or_field_count')
            class_id = int(parts[0])
            x, y, width, height = map(float, parts[1:])
            if not all(math.isfinite(value) for value in (x, y, width, height)):
                raise ValueError('nonfinite_box')
            if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1):
                raise ValueError('box_range')
            if x - width/2 < -1e-6 or x + width/2 > 1+1e-6 or y - height/2 < -1e-6 or y + height/2 > 1+1e-6:
                raise ValueError('box_outside_image')
            record['boxes'].append([class_id, x, y, width, height])
        except ValueError as error:
            record['issues'].append(f'label_line_{line_number}:{error}')
    return record


class BKTree:
    def __init__(self):
        self.root = None

    def search(self, value, threshold):
        if self.root is None:
            return []
        stack = [self.root]
        results = []
        while stack:
            node = stack.pop()
            distance = (value ^ node[0]).bit_count()
            if distance <= threshold:
                results.append((node[1], distance))
            stack.extend(child for edge, child in node[2].items() if distance-threshold <= edge <= distance+threshold)
        return results

    def add(self, value, index):
        if self.root is None:
            self.root = (value, index, {})
            return
        node = self.root
        while True:
            distance = (value ^ node[0]).bit_count()
            if distance == 0:
                return
            if distance not in node[2]:
                node[2][distance] = (value, index, {})
                return
            node = node[2][distance]


def grouped(records, key):
    groups = defaultdict(list)
    for index, record in enumerate(records):
        if record.get(key):
            groups[record[key]].append(index)
    return [members for members in groups.values() if len(members) > 1]


def main():
    import yaml
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    REPORTS.mkdir(parents=True, exist_ok=True)
    author = yaml.safe_load((DATASET / 'provenance/author-dfire.yaml').read_text(encoding='utf-8-sig'))
    raw_config = DATASET / 'raw/data.yaml'
    if not raw_config.is_file():
        raise RuntimeError('Потрібен data.yaml завантаженої Kaggle-версії.')
    config = yaml.safe_load(raw_config.read_text(encoding='utf-8-sig'))
    names = config['names']
    if names != author['names'] or names != ['smoke', 'fire']:
        raise RuntimeError('Відповідність класів не збігається з перевіреним авторським файлом.')
    items = []
    orphan_labels = []
    roots = {}
    for split in ('train', 'val', 'test'):
        folder = DATASET / 'raw' / config[split]
        if not folder.is_dir():
            raise RuntimeError('Відсутня частина набору: ' + split)
        roots[split] = folder
        images = sorted(path for path in folder.rglob('*') if path.suffix.lower() in ('.jpg', '.jpeg', '.png', '.bmp', '.webp'))
        items.extend((split, image) for image in images)
        image_stems = {path.stem for path in images}
        orphan_labels.extend(str(path.relative_to(DATASET)) for path in (folder.parent / 'labels').rglob('*.txt') if path.stem not in image_stems)
    print('Зображень для аудиту:', len(items), flush=True)
    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for record in executor.map(inspect_image, items):
            records.append(record)
            if len(records) % 2000 == 0:
                print('Перевірено:', len(records), flush=True)
    exact_groups = grouped(records, 'image_sha256')
    pixel_groups = grouped(records, 'pixel_sha256')
    parents = list(range(len(records)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left, right):
        parents[find(right)] = find(left)

    for members in exact_groups + pixel_groups:
        for member in members[1:]:
            union(members[0], member)
    tree = BKTree()
    near_edges = []
    for index, record in enumerate(records):
        if 'phash' not in record:
            continue
        value = int(record['phash'], 16)
        for other, distance in tree.search(value, NEAR_DISTANCE):
            first = records[other]
            ratio = record['width'] / record['height']
            other_ratio = first['width'] / first['height']
            if abs(ratio / other_ratio - 1) <= .05:
                union(index, other)
                near_edges.append({'a': other, 'b': index, 'distance': distance})
        tree.add(value, index)
    components = defaultdict(list)
    for index in range(len(records)):
        components[find(index)].append(index)
        records[index]['candidate_group_id'] = f'phash-component-{find(index):06d}'
    cross_components = [members for members in components.values() if len({records[index]['split'] for index in members}) > 1]
    excluded = {index: ['invalid_or_unknown_annotation'] for index, record in enumerate(records) if record['issues']}
    for members in cross_components:
        for index in members:
            excluded.setdefault(index, []).append('cross_split_duplicate_candidate_component')
    # Візуально підтверджено спільний епізод AoF04042 (train) / AoF04045 (val).
    # Меж сцен для всієї AoF-послідовності немає: утримуємо цю родину лише в train,
    # не переносимо кадри з holdout до навчання й не вигадуємо межі за номерами.
    for index, record in enumerate(records):
        if record['source_family'] == 'AoF' and record['split'] != 'train':
            excluded.setdefault(index, []).append('aof_source_family_reserved_for_train')
    # Суперечливу розмітку точних дублікатів не виправляємо автоматично.
    conflicting_groups = []
    for members in {tuple(members) for members in exact_groups + pixel_groups}:
        signatures = {json.dumps(sorted(records[index]['boxes'])) for index in members}
        if len(signatures) > 1:
            conflicting_groups.append(members)
            for index in members:
                excluded.setdefault(index, []).append('conflicting_duplicate_annotations')
    prepared = {}
    manifests = DATASET / 'prepared'
    manifests.mkdir(exist_ok=True)
    for split in ('train', 'val', 'test'):
        prepared[split] = [index for index, record in enumerate(records) if record['split'] == split and index not in excluded]
        # Ultralytics читає абсолютні рядки списку; зображення не копіюються.
        (manifests / f'{split}.txt').write_text(''.join(str(DATASET / records[index]['image']) + '\n' for index in prepared[split]), encoding='utf-8')
        with (manifests / f'{split}.jsonl').open('w', encoding='utf-8') as output:
            for index in prepared[split]:
                output.write(json.dumps({key: records[index][key] for key in ('image', 'label', 'image_sha256', 'label_sha256', 'split', 'candidate_group_id')}, ensure_ascii=False) + '\n')
    data_yaml = {'path': str(manifests.resolve()), 'train': 'train.txt', 'val': 'val.txt', 'test': 'test.txt', 'nc': 2, 'names': {index: name for index, name in enumerate(names)}}
    (manifests / 'data.yaml').write_text(yaml.safe_dump(data_yaml, allow_unicode=True, sort_keys=False), encoding='utf-8')
    with (manifests / 'excluded.jsonl').open('w', encoding='utf-8') as output:
        for index, reasons in sorted(excluded.items()):
            output.write(json.dumps({'image': records[index]['image'], 'image_sha256': records[index]['image_sha256'], 'reasons': sorted(set(reasons))}, ensure_ascii=False) + '\n')
    def statistics(indices):
        objects = Counter()
        annotated_objects = Counter()
        annotated_images = Counter()
        categories = Counter()
        images = Counter()
        backgrounds = 0
        for index in indices:
            record = records[index]
            objects.update(names[box[0]] for box in record['boxes'])
            annotated_objects.update({names[int(key)]: value for key, value in record['raw_objects_by_class'].items()})
            present = {names[int(key)] for key in record['raw_objects_by_class']}
            annotated_images.update(present)
            categories['+'.join(sorted(present)) if present else 'background' if record['background_verified'] else 'unknown'] += 1
            images.update(set(names[box[0]] for box in record['boxes']))
            backgrounds += record['background_verified']
        return {'images': len(indices), 'objects': dict(objects), 'annotated_objects_including_invalid_geometry': dict(annotated_objects), 'annotated_images_with_class': dict(annotated_images), 'annotated_image_categories': dict(categories), 'images_with_class': dict(images), 'verified_backgrounds': backgrounds}
    report = {
        'audited_at': datetime.now(timezone.utc).isoformat(), 'class_mapping': dict(enumerate(names)),
        'class_evidence': ['https://raw.githubusercontent.com/pedbrgs/Fire-Detection/master/data/dfire.yaml', 'raw/data.yaml'],
        'archive': json.loads((DATASET / 'provenance/download.json').read_text(encoding='utf-8')),
        'raw_bytes': sum(path.stat().st_size for path in (DATASET / 'raw').rglob('*') if path.is_file()),
        'raw_counts': {split: statistics([index for index, record in enumerate(records) if record['split'] == split]) for split in roots},
        'prepared_counts': {split: statistics(indices) for split, indices in prepared.items()},
        'issues_images': sum(bool(record['issues']) for record in records),
        'issue_counts': dict(Counter(issue.split(':', 1)[-1] for record in records for issue in record['issues'])),
        'missing_labels': sum('missing_label_unknown_background' in record['issues'] for record in records),
        'unreadable_images': sum(any(issue.startswith('unreadable_image') for issue in record['issues']) for record in records),
        'orphan_labels': orphan_labels,
        'exact_byte_groups': exact_groups, 'exact_pixel_groups': pixel_groups,
        'exact_byte_cross_split_groups': [members for members in exact_groups if len({records[index]['split'] for index in members}) > 1],
        'exact_pixel_cross_split_groups': [members for members in pixel_groups if len({records[index]['split'] for index in members}) > 1],
        'conflicting_duplicate_groups': conflicting_groups,
        'near_duplicate_method': {'hash': 'pHash64', 'hamming_max': NEAR_DISTANCE, 'aspect_ratio_relative_tolerance': .05, 'candidate_only': True},
        'near_edges': near_edges, 'cross_split_components': cross_components,
        'excluded': {str(index): reasons for index, reasons in excluded.items()},
        'split_policy': 'Збережено вихідні частини Kaggle без випадкового перерозподілу; кандидати компонентів дублікатів між частинами й помилки виключені зі всіх списків. AoF дозволено лише у вихідному train, решта AoF у val/test виключена без перенесення до train. Незалежність решти сцен НЕ підтверджено.',
        'source_family_counts': {split: dict(Counter(record['source_family'] for record in records if record['split'] == split)) for split in roots},
        'visual_scene_overlap': {'train_image': 'AoF04042.jpg', 'val_image': 'AoF04045.jpg', 'evidence': 'Camera0001, 17.Oct.2019 18:59:54 та 19:00:09: той самий епізод; pHash distance=20, поріг 6 його не знаходить.', 'mitigation': 'Уся AoF-родина утримується лише у вихідному train; AoF з val/test виключено. Родина джерела не є встановленим scene_id.'},
        'split_seed': None,
        'scene_provenance': 'Ідентифікатори вихідних відео/сцен не надано; порядок AoF/PublicDataset не доводить межі сцен. pHash не доводить незалежність.',
        'ready_for_technical_trial': all(prepared[split] for split in ('train', 'val')),
        'ready_for_final_independent_experiment': False,
        'records': records,
        'manifest_sha256': {path.name: sha256(path) for path in sorted(manifests.glob('*')) if path.is_file()},
    }
    (REPORTS / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    with (REPORTS / 'files.jsonl').open('w', encoding='utf-8') as output:
        for index, record in enumerate(records):
            output.write(json.dumps({'index': index, **record}, ensure_ascii=False) + '\n')
    make_visuals(records, prepared, names)
    markdown_report(report)
    print(json.dumps({key: report[key] for key in ('raw_counts', 'prepared_counts', 'issues_images', 'missing_labels', 'unreadable_images', 'ready_for_technical_trial')}, ensure_ascii=False, indent=2), flush=True)


def make_visuals(records, prepared, names):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 16)
    for split in ('train', 'val'):
        # Фіксований порядок, по 2 приклади кожного класу й 2 фони; test не візуалізується.
        chosen = []
        for category in ('smoke', 'fire', 'background'):
            candidates = [index for index in prepared[split] if (records[index]['background_verified'] if category == 'background' else any(names[box[0]] == category for box in records[index]['boxes']))]
            chosen.extend(candidates[:2])
        chosen = list(dict.fromkeys(chosen))
        board = Image.new('RGB', (960, 340 * math.ceil(max(1, len(chosen))/2)), 'white')
        for position, index in enumerate(chosen):
            record = records[index]
            with Image.open(DATASET / record['image']) as original:
                tile = original.convert('RGB')
            tile.thumbnail((470, 290))
            draw = ImageDraw.Draw(tile)
            for class_id, x, y, width, height in record['boxes']:
                box = ((x-width/2)*tile.width, (y-height/2)*tile.height, (x+width/2)*tile.width, (y+height/2)*tile.height)
                color = '#ff5b21' if names[class_id] == 'fire' else '#008bff'
                draw.rectangle(box, outline=color, width=max(2, tile.width//300))
                draw.text((max(0, box[0]), max(0, box[1]-20)), f'{class_id}: {names[class_id]}', fill=color, font=font, stroke_width=1, stroke_fill='white')
            left, top = (position % 2)*480, (position//2)*340
            board.paste(tile, (left, top+35))
            ImageDraw.Draw(board).text((left+5, top+5), f'{split}: {Path(record["image"]).name}', fill='black', font=font)
        board.save(REPORTS / f'{split}-samples.jpg', quality=92)


def markdown_report(report):
    lines = ['# Аудит D-Fire', '', f'Дата: {report["audited_at"]}', '',
             'Джерело: Kaggle-версія v1, прямо зазначена в авторському README D-Fire. Числа нижче отримано з файлів, а не переписано з опису.', '',
             '**Класи: 0 = smoke, 1 = fire.** Перевірено за авторським `Fire-Detection/data/dfire.yaml` і конфігурацією отриманого архіву.', '',
             f'Архів: {report["archive"]["archive_bytes"]} байтів; SHA-256 `{report["archive"]["sha256"]}`.',
             f'Розпаковані початкові файли: {report["raw_bytes"]} байтів. Зображення не копіювалися для поділу.', '',
             '| Частина | Зображення | smoke валідні рамки | fire валідні рамки | Фони (порожній наявний label) | Підготовлено зображень |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for split, counts in report['raw_counts'].items():
        lines.append(f'| {split} | {counts["images"]} | {counts["objects"].get("smoke",0)} | {counts["objects"].get("fire",0)} | {counts["verified_backgrounds"]} | {report["prepared_counts"][split]["images"]} |')
    annotation_totals = Counter()
    category_totals = Counter()
    for counts in report['raw_counts'].values():
        annotation_totals.update(counts['annotated_objects_including_invalid_geometry'])
        category_totals.update(counts['annotated_image_categories'])
    lines += ['', f'Усі записи розмітки до геометричної перевірки: {sum(annotation_totals.values())}; за класами: {dict(annotation_totals)}. У таблиці вище наведено лише рамки з коректною геометрією, включно з валідними рамками зображень, що можуть мати інші помилки. Підготовлені списки виключають усе зображення з помилкою.',
              f'Проблеми рамок: {report["issue_counts"]}.']
    lines += [f'Категорії зображень за вихідною розміткою (до перевірки геометрії): {dict(category_totals)}.']
    lines += ['', f'Нечитабельних зображень: {report["unreadable_images"]}; відсутніх label: {report["missing_labels"]}; зображень із проблемами: {report["issues_images"]}; orphan label: {len(report["orphan_labels"])}.',
              f'Груп точних байтових дублікатів: {len(report["exact_byte_groups"])}; однакових декодованих пікселів: {len(report["exact_pixel_groups"])}; груп із суперечливою розміткою: {len(report["conflicting_duplicate_groups"])}.',
              f'Між частинами: {len(report["exact_byte_cross_split_groups"])} груп байтових і {len(report["exact_pixel_cross_split_groups"])} груп піксельних точних дублікатів.',
              f'Компонентів кандидатів дублікатів між частинами: {len(report["cross_split_components"])}; виключено зі списків: {len(report["excluded"])} зображень.', '',
              'Метод близьких дублікатів: pHash64, Hamming ≤6, відношення сторін у межах 5%. Це кандидати; можливі хибні збіги й пропуски. Компоненти транзитивні, тому не всі їхні пари мають відстань ≤6.', '',
              report['split_policy'], '', report['scene_provenance'], '',
              'Візуально підтверджено той самий епізод Camera0001: train/AoF04042.jpg (17.10.2019 18:59:54) і val/AoF04045.jpg (19:00:09). Їхня pHash-відстань 20: це прямий приклад того, чому перевірка дублікатів не доводить незалежність сцен. Усі AoF із val/test виключено зі списків, без перенесення в train. Інші WEB/PublicDataset можуть містити невідомі пов’язані сцени.', '',
              'Відсутній label не вважається фоном. Геометрія рамок перевіряється з допуском 1e-6 для похибки округлення; початкові файли не виправляються.', '',
              'Частини архіву є поділом Kaggle-пакувальника. Їхню тотожність окремим авторським OneDrive train/val/test архівам не підтверджено. Готові списки — консервативна технічна підмножина цього поділу, без випадкового перерозподілу.', '',
              f'Короткий технічний запуск можливий: {"так" if report["ready_for_technical_trial"] else "ні"}. Для підсумкових незалежних метрик готовність НЕ підтверджено через невідомі сцени.',
              'Test не використовувався для вибору гіперпараметрів; аудит перевіряє лише цілісність і перетини. Часові відеопослідовності для оцінки подій потрібно підготувати окремо.', '',
              'Списки й SHA-256: datasets/dfire/prepared; повний машинний звіт: audit.json, files.jsonl; візуальні приклади лише train/val: train-samples.jpg, val-samples.jpg.', '',
              'Умови: репозиторій D-Fire декларує CC0 для колекції; зображення сторонніх постачальників залишаються під їхніми умовами. Збережено авторські README/LICENSE; врахувати атрибуцію HPWREN, FESB та FireNet і рекомендоване цитування статей.']
    (REPORTS / 'AUDIT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
