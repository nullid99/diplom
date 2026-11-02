"""Перевірка підготовлених списків і контрольних сум без навчання."""
import json
from pathlib import Path

import yaml

from scripts.audit_dfire import DATASET, REPORTS, sha256


def main():
    report = json.loads((REPORTS / 'audit.json').read_text(encoding='utf-8'))
    prepared = DATASET / 'prepared'
    config = yaml.safe_load((prepared / 'data.yaml').read_text(encoding='utf-8'))
    assert config['names'] == {0: 'smoke', 1: 'fire'}
    assigned_groups = {}
    hashes = {}
    count = 0
    for split in ('train', 'val', 'test'):
        rows = [json.loads(line) for line in (prepared / f'{split}.jsonl').read_text(encoding='utf-8').splitlines()]
        paths = (prepared / f'{split}.txt').read_text(encoding='utf-8').splitlines()
        assert paths == [str(DATASET / row['image']) for row in rows]
        assert len(rows) == report['prepared_counts'][split]['images']
        for row in rows:
            image, label = DATASET / row['image'], DATASET / row['label']
            assert sha256(image) == row['image_sha256']
            assert sha256(label) == row['label_sha256']
            assert assigned_groups.setdefault(row['candidate_group_id'], split) == split
            assert hashes.setdefault(row['image_sha256'], split) == split
            assert split == 'train' or not image.name.startswith('AoF')
            count += 1
    for filename, checksum in report['manifest_sha256'].items():
        assert sha256(prepared / filename) == checksum
    print(f'Перевірено {count} записів списків: шляхи, SHA-256 зображень/міток, групи кандидатів і карантин AoF. Незалежність невідомих сцен цим не доведена.')


if __name__ == '__main__':
    main()
