param([Parameter(Mandatory=$true)][string]$Report,[Parameter(Mandatory=$true)][string]$Name)
. "$PSScriptRoot\analysis-env.ps1"
$registrationDisplayName=$Name
Use-AnalysisEnvironment {
    Invoke-ProjectCommand '.\.venv\Scripts\python.exe' @('-X','utf8','-m','scripts.register_model','--report',$Report,'--name',$registrationDisplayName)
}
