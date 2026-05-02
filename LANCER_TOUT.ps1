# Script PowerShell pour lancer tout le système Shizu Bot Premium
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   SHIZU BOT PREMIUM - LANCEMENT TOTAL" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Vérifier Python
try {
    $pythonVersion = python --version 2>$null
    Write-Host "✅ Python détecté" -ForegroundColor Green
} catch {
    Write-Host "❌ ERREUR: Python n'est pas installé !" -ForegroundColor Red
    Write-Host "Téléchargez-le sur https://python.org" -ForegroundColor Yellow
    Read-Host "Appuyez sur Entrée pour quitter"
    exit 1
}

Write-Host ""

# Nettoyer les processus existants
Write-Host "🔄 Nettoyage des anciens processus..." -ForegroundColor Yellow

# Tuer les processus sur les ports utilisés
$ports = @(5001, 8000, 8080)
foreach ($port in $ports) {
    $processes = netstat -ano | findstr ":$port" | findstr "LISTENING"
    if ($processes) {
        foreach ($line in $processes) {
            $pid = ($line -split '\s+')[-1]
            if ($pid -and $pid -match '^\d+$') {
                taskkill /PID $pid /F >$null 2>&1
            }
        }
    }
}

Start-Sleep -Seconds 2
Write-Host "✅ Nettoyage terminé" -ForegroundColor Green
Write-Host ""

# Chemins
$siteDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$botDir = "c:\Users\baadh\Downloads\NEKO_bot v 2(1)-20260430T225107Z-3-001-20260501T055331Z-3-001\uzumaki_fun_complete_bot v 2(1)-20260430T225107Z-3-001\uzumaki_fun_complete_bot v 2(1)\uzumaki_fun_complete_bot (1)"

# Démarrer tous les serveurs
Write-Host "🚀 Lancement de TOUS les serveurs..." -ForegroundColor Green

# Backend
Start-Process -FilePath "cmd" -ArgumentList "/c cd /d `"$siteDir`" && python backend.py" -WindowStyle Normal

# Site web
Start-Process -FilePath "cmd" -ArgumentList "/c cd /d `"$siteDir`" && python -m http.server 8000" -WindowStyle Normal

# Bot Discord
Start-Process -FilePath "cmd" -ArgumentList "/c cd /d `"$botDir`" && python bot.py" -WindowStyle Normal

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "        🎉 TOUT EST LANCÉ !" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "🌐 Site Web : http://localhost:8000" -ForegroundColor Blue
Write-Host "🚀 Backend API : http://localhost:5001" -ForegroundColor Blue
Write-Host "🤖 Bot Discord : Webhook actif" -ForegroundColor Blue
Write-Host ""
Write-Host "🎯 Testez avec votre ID : 912076290075525140" -ForegroundColor Magenta
Write-Host ""
Read-Host "Appuyez sur Entrée pour fermer"