. "$PSScriptRoot\project-env.ps1"
Use-ProjectEnvironment {
    $mlPython = '.\.venv\Scripts\python.exe'
    Invoke-ProjectCommand $mlPython @('-m', 'pip', 'install', 'torch==2.9.1', 'torchvision==0.24.1', '--index-url', 'https://download.pytorch.org/whl/cu126')
    Invoke-ProjectCommand $mlPython @('-m', 'pip', 'install', '-c', 'ml/constraints.txt', '-r', 'ml/requirements.txt')
    Invoke-ProjectCommand $mlPython @('-X', 'utf8', '-m', 'scripts.configure_ml')
    Invoke-ProjectCommand $mlPython @('-m', 'pip', 'check')
}
