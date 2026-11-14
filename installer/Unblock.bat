@echo off
rem Removes Windows' "downloaded from the internet" block from every file in this folder, so MiniDisc Manager can start.
echo Unblocking MiniDisc Manager files, please wait...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0' -Recurse -Force | Unblock-File"
echo.
echo Done. You can now start "MiniDisc Manager.exe".
pause
