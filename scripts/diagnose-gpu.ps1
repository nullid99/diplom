. "$PSScriptRoot\project-env.ps1"
Use-ProjectEnvironment {
    Invoke-ProjectCommand '.\.venv\Scripts\python.exe' @('-X', 'utf8', '-m', 'scripts.diagnose_gpu')
}
