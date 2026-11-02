param(
    [ValidateSet('Start','Status','Resume','Inspect')][string]$Action='Status',
    [string]$RunDir='',
    [string]$Checkpoint='',
    [ValidateSet(4,2)][int]$Batch=4
)
. "$PSScriptRoot\project-env.ps1"
$fullAction = $Action
Use-ProjectEnvironment {
    $fullPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if ($fullAction -eq 'Start') {
        $preparedOutput = & $fullPython -X utf8 -m scripts.train_full prepare --batch $Batch
        if ($LASTEXITCODE -ne 0) { throw 'Перевірку готовності не пройдено.' }
        $script:fullRunPath = ($preparedOutput | Select-Object -Last 1).ToString().Trim()
    } elseif ($RunDir) { $script:fullRunPath = (Resolve-Path -LiteralPath $RunDir).Path }
    else { $script:fullRunPath = (Get-Content -LiteralPath 'reports\ml\full-training-latest.json' -Raw | ConvertFrom-Json).run_dir }
    if ($fullAction -eq 'Status') {
        Invoke-ProjectCommand $fullPython @('-X','utf8','-m','scripts.train_full','status','--run-dir',$script:fullRunPath)
    } elseif ($fullAction -eq 'Inspect') {
        if (-not $Checkpoint) { throw 'Потрібен -Checkpoint.' }
        Invoke-ProjectCommand $fullPython @('-X','utf8','-m','scripts.train_full','inspect','--checkpoint',$Checkpoint)
    } else {
        $launchArguments = @('-X','utf8','-u','-m','scripts.train_full','worker','--run-dir',$script:fullRunPath)
        if ($fullAction -eq 'Resume') {
            if ($Checkpoint) { throw 'Resume автоматично обирає справний checkpoint цієї папки; використайте Inspect для окремого файлу.' }
            $resumeOutput = & $fullPython -X utf8 -m scripts.train_full select-resume --run-dir $script:fullRunPath
            if ($LASTEXITCODE -ne 0) { throw 'Справного checkpoint для resume немає або процес працює.' }
            $launchArguments += @('--checkpoint',($resumeOutput | Select-Object -Last 1).ToString().Trim())
        }
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-ffff'
        $outFile = Join-Path $script:fullRunPath "console-$stamp.log"
        $errFile = Join-Path $script:fullRunPath "stderr-$stamp.log"
        $launched = Start-Process -FilePath $fullPython -ArgumentList $launchArguments -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $outFile -RedirectStandardError $errFile -PassThru
        [pscustomobject]@{ PID=$launched.Id; RunDir=$script:fullRunPath; Log=$outFile; ErrorLog=$errFile } | ConvertTo-Json
    }
}
