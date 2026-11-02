"""Справжня коротка перевірка CUDA без завантаження ваг і навчання детектора."""
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone

from backend.app.config import PROJECT_ROOT


def main():
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'python': platform.python_version(), 'executable': sys.executable, 'success': False}
    output = PROJECT_ROOT / 'reports/ml/gpu-diagnostic.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        import torch
        import torchvision
        import ultralytics
        import importlib.metadata as metadata
        report['analysis_packages'] = {name: metadata.version(name) for name in ('opencv-python', 'numpy', 'pandas', 'scikit-learn', 'matplotlib', 'Pillow', 'ImageHash')}
        variants = [package.metadata['Name'] for package in metadata.distributions() if package.metadata['Name'].lower().startswith('opencv-')]
        report['opencv_distributions'] = variants
        assert variants == ['opencv-python'], 'Очікується лише opencv-python без конфліктних варіантів.'
        report.update(torch=torch.__version__, torchvision=torchvision.__version__, ultralytics=ultralytics.__version__, cuda_build=torch.version.cuda, cuda_available=torch.cuda.is_available(), compiled_architectures=torch.cuda.get_arch_list())
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA недоступна в установленому PyTorch; перевірку на CPU не виконано.')
        report['gpu_name'] = torch.cuda.get_device_name(0)
        report['compute_capability'] = list(torch.cuda.get_device_capability(0))
        free, total = torch.cuda.mem_get_info(0)
        report.update(free_vram_bytes=free, total_vram_bytes=total)
        driver = subprocess.run(['nvidia-smi', '--query-gpu=driver_version', '--format=csv,noheader'], capture_output=True, text=True, timeout=10)
        report['driver'] = driver.stdout.strip()
        torch.manual_seed(42)
        x = torch.randn(128, 128, device='cuda')
        product = x @ x.T
        torch.cuda.synchronize()
        assert product.is_cuda and torch.isfinite(product).all()
        report['gpu_matmul'] = True
        network = torch.nn.Sequential(torch.nn.Conv2d(3, 8, 3, padding=1), torch.nn.ReLU(), torch.nn.AdaptiveAvgPool2d(1), torch.nn.Flatten(), torch.nn.Linear(8, 2)).cuda()
        optimizer = torch.optim.SGD(network.parameters(), lr=0.01)
        optimizer.zero_grad()
        result = network(torch.randn(2, 3, 64, 64, device='cuda'))
        loss = result.square().mean()
        loss.backward()
        assert all(parameter.grad is not None and parameter.grad.is_cuda and torch.isfinite(parameter.grad).all() for parameter in network.parameters())
        optimizer.step()
        torch.cuda.synchronize()
        report['gpu_forward_backward'] = True
        from torchvision.ops import nms
        kept = nms(torch.tensor([[0., 0., 10., 10.], [1., 1., 9., 9.], [20., 20., 30., 30.]], device='cuda'), torch.tensor([.9, .8, .7], device='cuda'), .5)
        torch.cuda.synchronize()
        assert kept.is_cuda and kept.tolist() == [0, 2]
        report['gpu_torchvision_nms'] = True
        # Перевіряємо наявність архітектури YOLO11, не створюючи COCO-детектор.
        from pathlib import Path
        report['yolo11_config_available'] = (Path(ultralytics.__file__).parent / 'cfg/models/11/yolo11.yaml').is_file()
        assert report['yolo11_config_available']
        report['success'] = True
    except Exception as error:
        report['error_type'] = type(error).__name__
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
