. "$PSScriptRoot\analysis-env.ps1"
Use-AnalysisEnvironment {
    $eventReport=Join-Path $ProjectRoot 'reports\events'
    New-Item -ItemType Directory -Path $eventReport -Force | Out-Null
    $eventChecks=Start-Process -FilePath (Join-Path $ProjectRoot '.venv\Scripts\python.exe') -ArgumentList @('-X','utf8','-m','unittest','tests.test_temporal','tests.test_events','-v') -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $eventReport 'tests-stdout.log') -RedirectStandardError (Join-Path $eventReport 'tests.log') -Wait -PassThru
    Get-Content (Join-Path $eventReport 'tests.log') -Encoding UTF8 -Tail 12
    if ($eventChecks.ExitCode -ne 0) { throw 'Events checks failed. See reports/events/tests.log.' }
    Push-Location frontend
    try { Invoke-ProjectCommand 'npm.cmd' @('run','build') } finally { Pop-Location }
}
