. "$PSScriptRoot\project-env.ps1"
Use-ProjectEnvironment {
    Invoke-ProjectCommand '.\.venv\Scripts\python.exe' @('-X', 'utf8', '-m', 'scripts.fetch_dfire')
}
