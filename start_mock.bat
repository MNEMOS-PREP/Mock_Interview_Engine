@echo off
REM ============================================================
REM  M06 only.
REM
REM  The services in scripts\services.txt whose id starts with
REM  m06-. Upstream modules are NOT started - each one is
REM  optional and /v1/deps says which are missing. Use
REM  start_all.bat to bring up the siblings as well.
REM
REM  Usage:  start_mock.bat          launch M06
REM          start_mock.bat -Check   verify prerequisites only
REM ============================================================

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Only m06 -Title "M06 - Mock Interview Engine" %*
