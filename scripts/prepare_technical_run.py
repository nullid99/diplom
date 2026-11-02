"""Пояснення виключень і окрема стратифікована підмножина без зміни основних списків."""
import itertools
import json
import random
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

from scripts.audit_dfire import DATASET, REPORTS, sha256


def category(record):
    present = {int(box[0]) for box in record['boxes']}
    return 'mixed' if present == {0, 1} else 'smoke-only' if present == {0} else 'fire-only' if present == {1} else 'background'


def group_board(records, group, destination):
    selected = []
    for split in ('train', 'val'):
        members = [i for i in group if records[i]['split'] == split]
        if members:
            selected += [members[0], members[len(members)//2], members[-1]]
    for family in ('WEB', 'PublicDataset'):
        selected += [i for i in group if records[i]['source_family'] == family and records[i]['split'] in ('train', 'val')][:2]
    selected = list(dict.fromkeys(selected))[:8]
    board = Image.new('RGB', (1000, 330*((len(selected)+1)//2)), 'white')
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 15)
    for position, index in enumerate(selected):
        record = records[index]
        with Image.open(DATASET / record['image']) as original:
            tile = original.convert('RGB')
        tile.thumbnail((490, 280))
        x, y = position%2*500, position//2*330
        board.paste(tile, (x, y+45))
        draw = ImageDraw.Draw(board)
        draw.text((x+4, y+4), f'{index}: {record["split"]}/{Path(record["image"]).name}', font=font, fill='black')
        draw.text((x+4, y+23), record['candidate_group_id'], font=font, fill='black')
    board.save(destination, quality=92)
    return selected


def main():
    run_id = 'yolo11n_tech_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8]
    review = REPORTS / 'reviews' / run_id
    subset = DATASET / 'technical' / run_id
    review.mkdir(parents=True, exist_ok=False)
    subset.mkdir(parents=True, exist_ok=False)
    report = json.loads((REPORTS / 'audit.json').read_text(encoding='utf-8'))
    records = report['records']
    before = {path.name: sha256(path) for path in (DATASET / 'prepared').iterdir() if path.is_file()}
    assert before == report['manifest_sha256']
    excluded = {int(index): set(reasons) for index, reasons in report['excluded'].items()}
    reasons = sorted(set().union(*excluded.values()))
    counts = {reason: sum(reason in values for values in excluded.values()) for reason in reasons}
    intersections = {' & '.join(pair): sum(set(pair) <= values for values in excluded.values()) for pair in itertools.combinations(reasons, 2)}
    signatures = Counter(' & '.join(sorted(values)) for values in excluded.values())
    union_size = len(excluded)
    assert len(records) - union_size == 7238+1436+1995 == 10669
    assert sum(signatures.values()) == union_size == 10858
    review_data = {
        'id': run_id, 'total': len(records), 'kept': len(records)-union_size, 'excluded_union': union_size,
        'unique_per_reason': counts, 'inclusive_pair_intersections': intersections,
        'inclusive_triple_intersection': sum(len(values)==3 for values in excluded.values()),
        'disjoint_reason_signatures': dict(signatures), 'prepared_counts': report['prepared_counts'],
        'exact_duplicate_groups': len(report['exact_byte_groups']),
        'main_manifest_sha256': before, 'main_manifests_changed': False,
        'groups_total': len(report['cross_split_components']),
    }
    groups = sorted(report['cross_split_components'], key=lambda group: (-len(group), group[0]))
    selected_groups = groups[:3]
    selected_groups += [group for group in groups if 2 <= len(group) <= 8 and {records[i]['split'] for i in group} >= {'train', 'val'}][:3]
    review_data['visual_groups'] = []
    for number, group in enumerate(selected_groups):
        filename = f'group-{number+1:02d}.jpg'
        selected = group_board(records, group, review / filename)
        review_data['visual_groups'].append({'size': len(group), 'group_id': records[group[0]]['candidate_group_id'], 'selected_indices': selected, 'image': filename})

    by_path = {record['image']: record for record in records}
    rng = random.Random(42)
    subset_stats = {}
    for split, target in (('train', 512), ('val', 128)):
        source_rows = [json.loads(line) for line in (DATASET / f'prepared/{split}.jsonl').read_text(encoding='utf-8').splitlines()]
        buckets = {name: [] for name in ('fire-only', 'smoke-only', 'mixed', 'background')}
        for row in source_rows:
            buckets[category(by_path[row['image']])].append(row)
        selected = []
        for name, bucket in buckets.items():
            assert len(bucket) >= target//4, f'Недостатньо {name} у {split}'
            selected.extend(rng.sample(sorted(bucket, key=lambda row: row['image']), target//4))
        rng.shuffle(selected)
        assert len(selected) == target
        for row in selected:
            assert row['split'] == split
            assert sha256(DATASET / row['image']) == row['image_sha256']
            assert sha256(DATASET / row['label']) == row['label_sha256']
        (subset / f'{split}.txt').write_text(''.join(str(DATASET / row['image'])+'\n' for row in selected), encoding='utf-8')
        (subset / f'{split}.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in selected), encoding='utf-8')
        objects = Counter('smoke' if box[0]==0 else 'fire' for row in selected for box in by_path[row['image']]['boxes'])
        subset_stats[split] = {'images': len(selected), 'categories': dict(Counter(category(by_path[row['image']]) for row in selected)), 'boxes': dict(objects)}
    training_config = {'path': str(subset.resolve()), 'train': 'train.txt', 'val': 'val.txt', 'nc': 2, 'names': {0: 'smoke', 1: 'fire'}}
    (subset / 'data.yaml').write_text(yaml.safe_dump(training_config, sort_keys=False), encoding='utf-8')
    provenance = {'id': run_id, 'seed': 42, 'stratification': 'equal fire-only/smoke-only/mixed/background; fixed sorted input, random.Random(42)', 'counts': subset_stats, 'parent_manifest_sha256': before, 'files_sha256': {p.name: sha256(p) for p in sorted(subset.iterdir()) if p.is_file()}, 'test_used_for_training_or_selection': False}
    (subset / 'manifest.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    assert before == {path.name: sha256(path) for path in (DATASET / 'prepared').iterdir() if path.is_file()}
    review_data['technical_subset'] = str(subset.relative_to(DATASET.parent.parent))
    (review / 'review.json').write_text(json.dumps(review_data, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# Перевірка скорочення D-Fire', '', f'Ідентифікатор: `{run_id}`.', '',
             '21 527 − 10 858 = 10 669 = 7 238 train + 1 436 val + 1 995 test.', '',
             '## Унікальні зображення за причинами (множини перетинаються)', '', '| Причина | Кількість |', '| --- | ---: |']
    lines += [f'| {reason} | {count} |' for reason,count in counts.items()]
    lines += ['', 'Точних байтових/піксельних дублікатів: 0. Множина близьких кандидатів — не підтверджені дублікати чи scene_id.', '',
              '## Неперетинні комбінації причин', '', '| Точна комбінація | Кількість |', '| --- | ---: |']
    lines += [f'| {reason} | {count} |' for reason,count in sorted(signatures.items())]
    lines += ['', 'Сума неперетинних комбінацій = 10 858. Попарні включні перетини й потрійний перетин збережено в review.json.', '',
              '## Склад підготовлених частин', '', '| Частина | fire-only | smoke-only | mixed | Фон | smoke рамки | fire рамки |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for split, data in report['prepared_counts'].items():
        c=data['annotated_image_categories'];b=data['objects']
        lines.append(f'| {split} | {c.get("fire",0)} | {c.get("smoke",0)} | {c.get("fire+smoke",0)} | {c.get("background",0)} | {b.get("smoke",0)} | {b.get("fire",0)} |')
    lines += ['', 'Найбільші компоненти мають ' + ', '.join(str(len(group)) for group in groups[:5]) + ' зображень. Причина масштабу: транзитивне замикання pHash-сусідств, повторювані фони стаціонарних камер і карантин цілої AoF-родини. pHash не класифікує сцени; навіть не схожі попарно кінці ланцюжка потрапляють в одну компоненту.', '',
              '576 компонентів між частинами зачіпають 10 464 зображення; це консервативний карантин кандидатів. Правило AoF утримує родину лише у вихідному train через підтверджений епізод між train/val, але не встановлює межі всіх сцен.', '',
              'Основні маніфести не змінено, дані не повернуто для збільшення обсягу. Незалежність невідомих WEB/PublicDataset сцен і test не доведена.', '',
              f'Окрема підмножина `{subset}`: {json.dumps(subset_stats,ensure_ascii=False)}. Seed=42; test відсутній у її YAML та не бере участі у відборі.', '',
              'Монтажі group-01…06 показують тільки train/val; результати ручного огляду зафіксовано окремо у VISUAL_REVIEW.md.']
    (review / 'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    pointer = {'id': run_id, 'data': str(subset / 'data.yaml'), 'subset': str(subset), 'review': str(review)}
    (PROJECT_ROOT_PATH() / 'reports/ml/technical-input.json').write_text(json.dumps(pointer, indent=2), encoding='utf-8')
    print(json.dumps(pointer, indent=2))


def PROJECT_ROOT_PATH():
    return DATASET.parent.parent


if __name__ == '__main__':
    main()
