@echo off
echo ========================================
echo      DIAGNOSTIC SHIZU BOT PREMIUM
echo ========================================
echo.

echo Verification des serveurs...

netstat -ano | findstr ":5001" | findstr "LISTENING" >nul
if %errorlevel% == 0 (
    echo [OK] Backend API (5001) : ACTIF
) else (
    echo [ERREUR] Backend API (5001) : INACTIF
)

netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if %errorlevel% == 0 (
    echo [OK] Site Web (8000) : ACTIF
) else (
    echo [ERREUR] Site Web (8000) : INACTIF
)

netstat -ano | findstr ":8080" | findstr "LISTENING" >nul
if %errorlevel% == 0 (
    echo [OK] Bot Discord (8080) : ACTIF
) else (
    echo [ERREUR] Bot Discord (8080) : INACTIF
)

echo.
echo Test d'activation premium...

curl -X POST http://localhost:5001/dev/activate-premium -H "Content-Type: application/json" -d "{\"discord_id\":\"912076290075525140\"}" --connect-timeout 10

echo.
echo ========================================
echo Appuyez sur une touche pour continuer...
pause >nul