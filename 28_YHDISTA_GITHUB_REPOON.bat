
@echo off
cd /d "%~dp0"
set /p REPO="Liita GitHub-repositoryn HTTPS-osoite: "
git remote remove origin 2>nul
git remote add origin "%REPO%"
git branch -M main
git push -u origin main
echo GitHubissa: Settings ^> Pages ^> Source = GitHub Actions
pause
