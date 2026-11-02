# Перевірка скорочення D-Fire

Ідентифікатор: `yolo11n_tech_20261101T195952Z_f9f60144`.

21 527 − 10 858 = 10 669 = 7 238 train + 1 436 val + 1 995 test.

## Унікальні зображення за причинами (множини перетинаються)

| Причина | Кількість |
| --- | ---: |
| aof_source_family_reserved_for_train | 2848 |
| cross_split_duplicate_candidate_component | 10464 |
| invalid_or_unknown_annotation | 340 |

Точних байтових/піксельних дублікатів: 0. Множина близьких кандидатів — не підтверджені дублікати чи scene_id.

## Неперетинні комбінації причин

| Точна комбінація | Кількість |
| --- | ---: |
| aof_source_family_reserved_for_train | 146 |
| aof_source_family_reserved_for_train & cross_split_duplicate_candidate_component | 2679 |
| aof_source_family_reserved_for_train & cross_split_duplicate_candidate_component & invalid_or_unknown_annotation | 22 |
| aof_source_family_reserved_for_train & invalid_or_unknown_annotation | 1 |
| cross_split_duplicate_candidate_component | 7693 |
| cross_split_duplicate_candidate_component & invalid_or_unknown_annotation | 70 |
| invalid_or_unknown_annotation | 247 |

Сума неперетинних комбінацій = 10 858. Попарні включні перетини й потрійний перетин збережено в review.json.

## Склад підготовлених частин

| Частина | fire-only | smoke-only | mixed | Фон | smoke рамки | fire рамки |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| train | 386 | 2023 | 2203 | 2626 | 4874 | 7079 |
| val | 85 | 426 | 465 | 460 | 1025 | 1455 |
| test | 89 | 560 | 619 | 727 | 1325 | 1984 |

Найбільші компоненти мають 1386, 1231, 806, 710, 651 зображень. Причина масштабу: транзитивне замикання pHash-сусідств, повторювані фони стаціонарних камер і карантин цілої AoF-родини. pHash не класифікує сцени; навіть не схожі попарно кінці ланцюжка потрапляють в одну компоненту.

576 компонентів між частинами зачіпають 10 464 зображення; це консервативний карантин кандидатів. Правило AoF утримує родину лише у вихідному train через підтверджений епізод між train/val, але не встановлює межі всіх сцен.

Основні маніфести не змінено, дані не повернуто для збільшення обсягу. Незалежність невідомих WEB/PublicDataset сцен і test не доведена.

Окрема підмножина `D:\FireVision\datasets\dfire\technical\yolo11n_tech_20261101T195952Z_f9f60144`: {"train": {"images": 512, "categories": {"mixed": 128, "fire-only": 128, "background": 128, "smoke-only": 128}, "boxes": {"fire": 651, "smoke": 300}}, "val": {"images": 128, "categories": {"mixed": 32, "smoke-only": 32, "background": 32, "fire-only": 32}, "boxes": {"fire": 153, "smoke": 69}}}. Seed=42; test відсутній у її YAML та не бере участі у відборі.

Монтажі group-01…06 показують тільки train/val; результати ручного огляду зафіксовано окремо у VISUAL_REVIEW.md.
