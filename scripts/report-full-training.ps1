param([string]$RunDir='', [string]$OutputDir='')
. "$PSScriptRoot\project-env.ps1"
$reportArguments=@('-X','utf8','-m','scripts.report_full_training')
if ($RunDir) { $reportArguments+=@('--run-dir',$RunDir) }
if ($OutputDir) { $reportArguments+=@('--output-dir',$OutputDir) }
Use-ProjectEnvironment {
    Invoke-ProjectCommand (Join-Path $ProjectRoot '.venv\Scripts\python.exe') $reportArguments
}
