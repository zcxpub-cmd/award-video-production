@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python skills\science-achievement-film\workbench\launch.py %*
) else (
  py -3 skills\science-achievement-film\workbench\launch.py %*
)
if errorlevel 1 pause
