@echo off
rem Ping 4 kali dengan jendela tetap terbuka (pause di akhir)
ping %1 -n 4 || (echo timeout & pause & exit /b 1)
pause
