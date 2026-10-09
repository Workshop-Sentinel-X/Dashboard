# Démo locale : rend le broker MQTT (port 8883) joignable par l'ESP8266 depuis le Wi-Fi.
# À lancer UNE fois, dans PowerShell EN ADMINISTRATEUR, après start.bat (ou docker compose up -d) :
#   powershell -ExecutionPolicy Bypass -File .\demo-reseau.ps1

$port = 8883

# 1. Pare-feu Windows : autorise l'ESP à joindre le broker
if (-not (Get-NetFirewallRule -DisplayName "Sentinel-X MQTT" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "Sentinel-X MQTT" -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow | Out-Null
}
Write-Host "[OK] Pare-feu : port $port ouvert"

# 2. Docker installé directement dans WSL (pas Docker Desktop) : il faut relayer le port vers WSL
$os = ""
try { $os = (docker info --format '{{.OperatingSystem}}' 2>$null) } catch {}
if (-not $os) { try { $os = (wsl docker info --format '{{.OperatingSystem}}' 2>$null) } catch {} }

if ($os -match "Docker Desktop") {
    Write-Host "[OK] Docker Desktop : pas de relais nécessaire"
} else {
    $wslIp = ((wsl hostname -I) -split " ")[0].Trim()
    netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 2>$null | Out-Null
    netsh interface portproxy add v4tov4 listenport=$port listenaddress=0.0.0.0 connectport=$port connectaddress=$wslIp | Out-Null
    Write-Host "[OK] Docker dans WSL : port $port relayé vers WSL ($wslIp)"
}

# 3. IP à saisir dans le dashboard du NodeMCU (section "Envoi vers l'API")
Write-Host ""
Write-Host "IP du PC à mettre dans le NodeMCU (champ 'IP du broker') :"
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.InterfaceAlias -match "Wi-?Fi|Wireless|WLAN" -and $_.IPAddress -notmatch "^169\." } |
    ForEach-Object { Write-Host "   $($_.IPAddress)   ($($_.InterfaceAlias))" -ForegroundColor Green }
Write-Host ""
Write-Host "Réglages NodeMCU : port $port | TLS : Non | utilisateur esp01 | mot de passe esp01-sx"
