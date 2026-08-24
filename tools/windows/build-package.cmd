@echo off
setlocal

rem Use a process-only policy override so ordinary Windows installations can
rem run the checked-in packaging script without changing the user's settings.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-package.ps1"
set "CHANNEL_OS_BUILD_EXIT=%ERRORLEVEL%"

if not "%CHANNEL_OS_BUILD_EXIT%"=="0" (
    echo.
    echo ChannelOS packaging stopped with an error.
)

exit /b %CHANNEL_OS_BUILD_EXIT%
