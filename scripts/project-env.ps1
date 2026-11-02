$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Invoke-ProjectCommand {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Команда завершилася з кодом ${LASTEXITCODE}: $Executable" }
}

function Use-ProjectEnvironment {
    param([scriptblock]$Action)
    $values = @{
        PIP_CACHE_DIR = Join-Path $ProjectRoot '.cache\pip'
        npm_config_cache = Join-Path $ProjectRoot '.cache\npm'
        TEMP = Join-Path $ProjectRoot '.tmp'
        TMP = Join-Path $ProjectRoot '.tmp'
        TORCH_HOME = Join-Path $ProjectRoot '.cache\torch'
        YOLO_CONFIG_DIR = Join-Path $ProjectRoot '.cache\ultralytics'
        MPLCONFIGDIR = Join-Path $ProjectRoot '.cache\matplotlib'
        XDG_CACHE_HOME = Join-Path $ProjectRoot '.cache'
        HF_HOME = Join-Path $ProjectRoot '.cache\huggingface'
        CUDA_CACHE_PATH = Join-Path $ProjectRoot '.cache\cuda'
        TORCHINDUCTOR_CACHE_DIR = Join-Path $ProjectRoot '.cache\torchinductor'
        TRITON_CACHE_DIR = Join-Path $ProjectRoot '.cache\triton'
    }
    $previous = @{}
    foreach ($name in $values.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        New-Item -ItemType Directory -Path $values[$name] -Force | Out-Null
        [Environment]::SetEnvironmentVariable($name, $values[$name], 'Process')
    }
    # Автоінсталяція Ultralytics не повинна змінювати зафіксоване середовище.
    $values['YOLO_AUTOINSTALL'] = 'false'
    $previous['YOLO_AUTOINSTALL'] = [Environment]::GetEnvironmentVariable('YOLO_AUTOINSTALL', 'Process')
    [Environment]::SetEnvironmentVariable('YOLO_AUTOINSTALL', 'false', 'Process')
    Push-Location $ProjectRoot
    try { & $Action } finally {
        Pop-Location
        foreach ($name in $values.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
        }
    }
}
