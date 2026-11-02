param([string]$Data='')
. "$PSScriptRoot\project-env.ps1"
Use-ProjectEnvironment {
    $trainingArguments = @('-X', 'utf8', '-m', 'scripts.train_technical')
    if ($Data) { $trainingArguments += @('--data', $Data) }
    Invoke-ProjectCommand '.\.venv\Scripts\python.exe' $trainingArguments
}
