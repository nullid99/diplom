. "$PSScriptRoot\project-env.ps1"
Use-ProjectEnvironment {
    Push-Location frontend
    try { Invoke-ProjectCommand 'npm.cmd' @('run', 'dev') } finally { Pop-Location }
}
