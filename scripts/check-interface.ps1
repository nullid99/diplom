. "$PSScriptRoot\project-env.ps1"
Use-ProjectEnvironment {
    Push-Location frontend
    try { Invoke-ProjectCommand 'npm.cmd' @('run','build') } finally { Pop-Location }
    Invoke-ProjectCommand 'node.exe' @('scripts/frontend-design-check.mjs')
    Invoke-ProjectCommand 'node.exe' @('scripts/frontend-accessibility-check.mjs')
}
