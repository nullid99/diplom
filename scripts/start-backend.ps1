. "$PSScriptRoot\project-env.ps1"
Use-ProjectEnvironment {
    if (-not (Test-Path '.\.venv-api\Scripts\python.exe')) { throw 'Спочатку виконайте scripts/setup-api.ps1.' }
    Invoke-ProjectCommand '.\.venv-api\Scripts\python.exe' @('-m', 'scripts.run_backend')
}
