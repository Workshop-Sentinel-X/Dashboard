# Simule tout le pipeline (FastAPI + IA capteurs + IA vision) pour développer le dashboard sans les autres briques.
# Usage : .\simulate.ps1   (Ctrl+C pour arrêter)
function Pub($u, $p, $t, $j) {
  $j | docker exec -i sentinelx-mosquitto mosquitto_pub -p 8883 -u $u -P $p -t $t -s
}
$inv = [Globalization.CultureInfo]::InvariantCulture
$i = 0
while ($true) {
  $i++
  $anom  = ($i % 40) -ge 33
  $temp  = if ($anom) { Get-Random -Min 40 -Max 55 } else { Get-Random -Min 20 -Max 26 }
  $hum   = Get-Random -Min 40 -Max 60
  $dist  = if ($anom) { Get-Random -Min 5 -Max 30 } else { Get-Random -Min 100 -Max 200 }
  $pres  = if ($anom) { 1 } else { Get-Random -Max 2 }
  $score = if ($anom) { (Get-Random -Min 70 -Max 99) / 100 } else { (Get-Random -Min 5 -Max 30) / 100 }
  $score = $score.ToString($inv)

  Pub api api-sx sentinel/validated ('{"device_id":"esp01","temp":' + $temp + ',"humidity":' + $hum + ',"distance":' + $dist + ',"presence":' + $pres + '}')
  Pub ia ia-sx sentinel/scores ('{"device_id":"esp01","score":' + $score + '}')

  if ($i % 40 -eq 35) { Pub vision vision-sx sentinel/alerts '{"code":"INTRUSION","source":"ia_vision","severity":"high","confidence":0.91,"message":"Intrus detecte par la camera"}' }
  if ($i % 40 -eq 34) { Pub ia ia-sx sentinel/alerts '{"code":"ANOMALY","source":"ia_capteurs","severity":"medium","message":"Score anormal sur esp01"}' }
  if ($i % 60 -eq 0)  { Pub api api-sx sentinel/alerts '{"code":"CYBER_SPOOFING","source":"fastapi","severity":"critical","message":"Signature HMAC invalide, trame rejetee"}' }
  Start-Sleep 1
}
