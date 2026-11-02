"""Проєктні каталоги Ultralytics без підключення ваг чи навчання."""
from backend.app.config import PROJECT_ROOT


if __name__ == '__main__':
    from ultralytics import settings
    settings.update({
        'datasets_dir': str(PROJECT_ROOT / 'datasets'),
        'weights_dir': str(PROJECT_ROOT / 'weights'),
        'runs_dir': str(PROJECT_ROOT / 'runs'),
        'sync': False,
    })
    print('Каталоги Ultralytics налаштовано в межах проєкту на D:.')
