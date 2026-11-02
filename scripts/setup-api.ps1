. "$PSScriptRoot\project-env.ps1"
Use-ProjectEnvironment {
    $apiPython=Join-Path $ProjectRoot '.venv-api\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $apiPython)) {
        if (Test-Path -LiteralPath '.venv-api') { throw 'Перевірте неповне .venv-api вручну.' }
        Invoke-ProjectCommand '.\.venv\Scripts\python.exe' @('-m','venv','.venv-api')
    }
    Invoke-ProjectCommand $apiPython @('-m','pip','install','-r','backend/requirements.txt')
    Invoke-ProjectCommand $apiPython @('-m','pip','check')
}
