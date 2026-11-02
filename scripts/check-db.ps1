param([switch]$WithDatabase)
. "$PSScriptRoot\project-env.ps1"
Use-ProjectEnvironment {
    $previousTestFlag = [Environment]::GetEnvironmentVariable('FIREVISION_TEST_DB', 'Process')
    try {
        if ($WithDatabase) { $env:FIREVISION_TEST_DB = '1' } else { $env:FIREVISION_TEST_DB = '0' }
        Invoke-ProjectCommand '.\.venv\Scripts\python.exe' @('-X', 'utf8', '-m', 'unittest', 'tests.test_database', '-v')
        Invoke-ProjectCommand '.\.venv\Scripts\python.exe' @('-m', 'pip', 'check')
    } finally {
        [Environment]::SetEnvironmentVariable('FIREVISION_TEST_DB', $previousTestFlag, 'Process')
    }
}
