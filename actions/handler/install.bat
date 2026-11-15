@echo off
rem Pembungkus 1-klik untuk installer handler (HKCU, tidak perlu admin).
rem Pemakaian: double-click, atau: install.bat https://rani.corp.local:8091
if "%~1"=="" (
  echo Pemakaian: install.bat https://rani.corp.local:8091
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-action-handler.ps1" -ServerUrl %1
pause
