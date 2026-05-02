@echo off
echo ========================================
echo      SHIZU BOT PREMIUM - TEST COMPLET
echo ========================================
echo.

REM Vérifier si les serveurs sont actifs
echo 🔍 Vérification des serveurs...

netstat -ano | findstr ":5001" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo ❌ Backend API (5001) : INACTIF
) else (
    echo ✅ Backend API (5001) : ACTIF
)

netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo ❌ Site Web (8000) : INACTIF
) else (
    echo ✅ Site Web (8000) : ACTIF
)

netstat -ano | findstr ":8080" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo ❌ Bot Discord (8080) : INACTIF
) else (
    echo ✅ Bot Discord (8080) : ACTIF
)

echo.
echo 🧪 Test de l'activation premium...

REM Test de l'API
powershell -Command "try { $response = Invoke-WebRequest -Uri 'http://localhost:5001/dev/activate-premium' -Method POST -Body '{\"discord_id\":\"912076290075525140\"}' -ContentType 'application/json' -UseBasicParsing; $data = $response.Content | ConvertFrom-Json; if ($data.success) { Write-Host '✅ Activation Premium : RÉUSSIE' -ForegroundColor Green } else { Write-Host '❌ Activation Premium : ÉCHEC' -ForegroundColor Red } } catch { Write-Host '❌ Activation Premium : ERREUR - Serveurs non démarrés' -ForegroundColor Red }"

echo.
echo ========================================
echo              RÉSULTATS DU TEST
echo ========================================
echo.
echo 🌐 Site Web : http://localhost:8000
echo 🚀 Backend API : http://localhost:5001
echo 🤖 Bot Discord : Webhook actif
echo.
echo 🎯 Votre ID Discord : 912076290075525140
echo.
echo Appuyez sur une touche pour continuer...
pause >nul