@echo off
rem Launcher for the APC40 <-> Cakewalk integration.
rem Runs inside the uv-managed environment so the system Python is never used.
rem
rem Examples:
rem   run-apc40-sonar.cmd --list-ports
rem
rem Note: uv is often installed to %USERPROFILE%\.local\bin and is not always on
rem the cmd.exe PATH, so fall back to that location when it is not found.

setlocal

set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not exist "%UV%" set "UV=uv"

"%UV%" run apc40sonar %*
exit /b %ERRORLEVEL%
