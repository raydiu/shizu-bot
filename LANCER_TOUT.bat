@echo off
echo ========================================
echo    SHIZU BOT PREMIUM - LANCEMENT TOTAL
echo ========================================
echo.

REM Vérifier si Python est installé
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ ERREUR: Python n'est pas installé !
    echo Téléchargez-le sur https://python.org
    pause
    exit /b 1
)

echo ✅ Python détecté
echo.

REM Nettoyer les processus existants
echo 🔄 Nettoyage des anciens processus...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5001" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
timeout /t 2 >nul

echo ✅ Nettoyage terminé
echo.

REM Démarrer tous les serveurs en parallèle
echo 🚀 Lancement de TOUS les serveurs...

start "Backend Shizu Bot" cmd /c "cd /d %~dp0 && python backend.py"
start "Site Web Shizu" cmd /c "cd /d %~dp0 && python -m http.server 8000"
start "Bot Discord Shizu" cmd /c "cd /d \"c:\Users\baadh\Downloads\NEKO_bot v 2(1)-20260430T225107Z-3-001-20260501T055331Z-3-001\uzumaki_fun_complete_bot v 2(1)-20260430T225107Z-3-001\uzumaki_fun_complete_bot v 2(1)\uzumaki_fun_complete_bot (1)\" && python bot.py"

echo.
echo ========================================
echo         🎉 TOUT EST LANCÉ !
echo ========================================
echo.
echo 🌐 Site Web : http://localhost:8000
echo 🚀 Backend API : http://localhost:5001
echo 🤖 Bot Discord : Webhook actif
echo.
echo 🎯 Testez avec votre ID : 912076290075525140
echo.
echo Appuyez sur une touche pour fermer...
pause >nul