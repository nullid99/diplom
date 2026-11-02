. "$PSScriptRoot\analysis-env.ps1"
Use-AnalysisEnvironment {
    Invoke-ProjectCommand '.\.venv\Scripts\python.exe' @('-X','utf8','-m','unittest','tests.test_analysis','-v')
    Push-Location frontend
    try { Invoke-ProjectCommand 'npm.cmd' @('run','build') } finally { Pop-Location }
    Invoke-ProjectCommand '.\.venv-api\Scripts\python.exe' @('-m','pip','check')
}
