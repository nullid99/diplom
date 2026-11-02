param(
    [ValidateSet('create','upgrade','current','check','sql','backup','restore')]
    [string]$Action = 'current',
    [string]$File = '',
    [string]$PgBin = ''
)
. "$PSScriptRoot\project-env.ps1"
$dbOperation = $Action
Use-ProjectEnvironment {
    $dbArguments = @('-X', 'utf8', '-m', 'scripts.db', $dbOperation)
    if ($File) { $dbArguments += @('--file', $File) }
    if ($PgBin) { $dbArguments += @('--pg-bin', $PgBin) }
    Invoke-ProjectCommand '.\.venv-api\Scripts\python.exe' $dbArguments
}
