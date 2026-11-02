param([string]$PythonExecutable = '')
. "$PSScriptRoot\project-env.ps1"

Use-ProjectEnvironment {
    $venvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.venv')) {
            throw 'Каталог .venv вже існує, але інтерпретатор відсутній. Перевірте його вручну.'
        }
        if ($PythonExecutable) {
            Invoke-ProjectCommand $PythonExecutable @('-c', 'import sys; assert sys.version_info[:2] == (3, 12)')
            Invoke-ProjectCommand $PythonExecutable @('-m', 'venv', '.venv')
        } else {
            Invoke-ProjectCommand 'py' @('-3.12', '-m', 'venv', '.venv')
        }
    }
    Invoke-ProjectCommand $venvPython @('-c', 'import sys; assert sys.version_info[:2] == (3, 12) and sys.prefix != sys.base_prefix')
    & "$PSScriptRoot\setup-api.ps1"
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    Push-Location frontend
    try { Invoke-ProjectCommand 'npm.cmd' @('ci') } finally { Pop-Location }
}
