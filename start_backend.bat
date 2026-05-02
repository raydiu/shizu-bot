@echo off
echo ========================================
echo    SHIZU BOT PREMIUM - DÉMARRAGE COMPLET
echo ========================================
echo.

REM Vérifier si Python est installé
python --version >nul 2>&1
if errorlevel 1 (
    echo ERREUR: Python n'est pas installé ou n'est pas dans le PATH
    echo Veuillez installer Python depuis https://python.org
    pause
    exit /b 1
)

echo ✅ Python détecté
echo.

REM Tuer les processus existants sur les ports utilisés
echo 🔄 Nettoyage des processus existants...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5001" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
timeout /t 2 >nul

echo ✅ Processus nettoyés
echo.

REM Démarrer le backend
echo 🚀 Démarrage du Backend API (port 5001)...
start "Backend Shizu Bot" cmd /c "cd /d %~dp0 && python backend.py"

REM Attendre que le backend démarre
timeout /t 3 >nul

REM Démarrer le site web
echo 🌐 Démarrage du Site Web (port 8000)...
start "Site Web Shizu" cmd /c "cd /d %~dp0 && python -m http.server 8000"

REM Attendre que le site démarre
timeout /t 2 >nul

REM Démarrer le bot Discord
echo 🤖 Démarrage du Bot Discord (port 8080)...
set BOT_DIR="c:\Users\baadh\Downloads\NEKO_bot v 2(1)-20260430T225107Z-3-001-20260501T055331Z-3-001\uzumaki_fun_complete_bot v 2(1)-20260430T225107Z-3-001\uzumaki_fun_complete_bot v 2(1)\uzumaki_fun_complete_bot (1)"
start "Bot Discord Shizu" cmd /c "cd /d %BOT_DIR% && python bot.py"

echo.
echo ========================================
echo         ✅ TOUS LES SERVEURS DÉMARRÉS !
echo ========================================
echo.
echo 🌐 Site Web : http://localhost:8000
echo 🚀 Backend API : http://localhost:5001
echo 🤖 Bot Discord : Connecté avec webhook
echo.
echo 🎯 Testez avec votre ID : 912076290075525140
echo.
echo Appuyez sur une touche pour fermer cette fenêtre...
pause >nul
    exit /b 1
)

REM Installer les dépendances si requirements.txt existe
if exist requirements.txt (
    echo Installation des dépendances...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERREUR: Impossible d'installer les dépendances
        pause
        exit /b 1
    )
)

REM Vérifier si .env existe
if not exist .env (
    echo ATTENTION: Fichier .env non trouvé
    echo Copiez .env.example vers .env et configurez vos variables
    echo.
    echo Appuyez sur une touche pour continuer quand même...
    pause
)

REM Démarrer le serveur
echo Démarrage du serveur Flask...
python backend.py