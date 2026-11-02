. "$PSScriptRoot\analysis-env.ps1"
Use-AnalysisEnvironment {
    do {
        & '.\.venv\Scripts\python.exe' -X utf8 -u -m backend.app.analysis_worker
        $workerExit=$LASTEXITCODE
        # 20: active cancellation released resources and ended the worker process.
        if ($workerExit -eq 20) { Write-Output 'Cancelled job closed; restarting queue worker.' }
    } while ($workerExit -eq 20)
    if ($workerExit -ne 0) { throw "Analysis worker stopped: exit $workerExit" }
}
