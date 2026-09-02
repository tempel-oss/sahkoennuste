
@echo off
cd /d "%~dp0"
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo [VIRHE] Tama kansio ei ole Git-repository.
  echo Aja ensin 27_VALMISTELE_GITHUB_PAGES.bat ja 28_YHDISTA_GITHUB_REPOON.bat.
  pause
  exit /b 1
)
if not exist output\index.html (
  echo [VIRHE] output\index.html puuttuu.
  pause
  exit /b 1
)
git add output
if errorlevel 1 goto :fail
git diff --cached --quiet
if not errorlevel 1 (
  echo Ei uusia muutoksia julkaistavaksi.
  exit /b 0
)
git commit -m "Update forecast"
if errorlevel 1 goto :fail
git push
if errorlevel 1 goto :fail
echo [OK] Ennuste lahetetty GitHubiin.
exit /b 0

:fail
echo [VIRHE] GitHub-julkaisu epaonnistui.
exit /b 1
