. "$PSScriptRoot\project-env.ps1"
function Use-AnalysisEnvironment {
    param([scriptblock]$AnalysisWork)
    Use-ProjectEnvironment {
        $analysisCaches=@{
            YOLO_CONFIG_DIR='.cache\analysis\ultralytics'
            TORCH_HOME='.cache\analysis\torch'
            MPLCONFIGDIR='.cache\analysis\matplotlib'
            CUDA_CACHE_PATH='.cache\analysis\cuda'
            TORCHINDUCTOR_CACHE_DIR='.cache\analysis\torchinductor'
        }
        foreach ($cacheKey in $analysisCaches.Keys) {
            $cachePath=Join-Path $ProjectRoot $analysisCaches[$cacheKey]
            New-Item -ItemType Directory -Path $cachePath -Force | Out-Null
            [Environment]::SetEnvironmentVariable($cacheKey,$cachePath,'Process')
        }
        & $AnalysisWork
    }
}
