@echo off
echo ========================================
echo      TEST RAPIDE - SHIZU BOT PREMIUM
echo ========================================
echo.

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
echo 🧪 Test d'activation premium...

powershell -Command "try { $response = Invoke-WebRequest -Uri 'http://localhost:5001/dev/activate-premium' -Method POST -Body '{\"discord_id\":\"912076290075525140\"}' -ContentType 'application/json' -UseBasicParsing -TimeoutSec 10; $data = $response.Content | ConvertFrom-Json; if ($data.success) { Write-Host '✅ ACTIVATION RÉUSSIE !' -ForegroundColor Green; Write-Host '🎉 Votre système fonctionne parfaitement !' -ForegroundColor Green } else { Write-Host '❌ ÉCHEC' -ForegroundColor Red } } catch { Write-Host '❌ ERREUR - Serveurs non démarrés' -ForegroundColor Red; Write-Host '💡 Lancez d''abord LANCER_TOUT.bat' -ForegroundColor Yellow }"

echo.
echo ========================================
echo Appuyez sur une touche pour continuer...
pause >nul