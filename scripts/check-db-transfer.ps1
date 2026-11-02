param([Parameter(Mandatory=$true)][string]$PgBin)
. "$PSScriptRoot\project-env.ps1"
Use-ProjectEnvironment {
    Invoke-ProjectCommand '.\.venv\Scripts\python.exe' @('-X', 'utf8', '-m', 'scripts.check_db_transfer', '--pg-bin', $PgBin)
}
