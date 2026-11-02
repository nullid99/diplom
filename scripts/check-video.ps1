. "$PSScriptRoot\project-env.ps1"
Use-ProjectEnvironment {
    Invoke-ProjectCommand '.\.venv\Scripts\python.exe' @('-X', 'utf8', '-m', 'unittest', 'tests.test_video_sources', '-v')
}
