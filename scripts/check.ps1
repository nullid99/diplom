. "$PSScriptRoot\project-env.ps1"
Use-ProjectEnvironment {
    Invoke-ProjectCommand '.\.venv\Scripts\python.exe' @('-m', 'pip', 'check')
    Push-Location frontend
    try { Invoke-ProjectCommand 'npm.cmd' @('run', 'build') } finally { Pop-Location }
    Invoke-ProjectCommand 'node' @('scripts/smoke.mjs')
}
