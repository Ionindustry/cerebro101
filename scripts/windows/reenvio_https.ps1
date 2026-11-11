<#
.SYNOPSIS
  Mantiene vivo el reenvio del puerto 443 de Windows para el acceso externo del Cerebro 101.cat (Docker Desktop + WSL2).

.DESCRIPTION
  El acceso desde fuera entra por el 443 de Windows y una regla de "netsh interface portproxy" lo lleva al reenviador de Docker (puerto 18443).
  Esas reglas las ejecuta el servicio de Windows "Ayudante de IP" (iphlpsvc). Si ese servicio arranca antes de que la red este lista (tras reiniciar el PC),
  la regla queda escrita pero NO escucha y desde fuera no se llega. Este script lo detecta y lo arregla solo:

    -Instalar   registra la tarea "Cerebro - reenvio HTTPS" (como SYSTEM): al arrancar Windows (esperando a que la red este lista) y despues cada 5 minutos
    -Vigilar    lo que hace la tarea: para cada regla de reenvio del 443 comprueba que Windows escucha en esa direccion; si no, reinicia el servicio y lo anota
    -Estado     ensena la tarea, las reglas, si escuchan y las ultimas lineas del registro
    -Quitar     borra la tarea

  Uso (PowerShell COMO ADMINISTRADOR):
    powershell -ExecutionPolicy Bypass -File reenvio_https.ps1 -Instalar
    powershell -ExecutionPolicy Bypass -File reenvio_https.ps1 -Estado
  Registro: C:\ProgramData\Cerebro\reenvio-https.log (se rota a 1 MB)
  No hace nada si no hay ninguna regla de reenvio del 443 (el acceso externo no esta activado con Docker Desktop).
#>
param([switch]$Instalar, [switch]$Quitar, [switch]$Vigilar, [switch]$Estado)
$ErrorActionPreference = "Continue"
$Tarea = "Cerebro - reenvio HTTPS"
$Base = Join-Path $env:ProgramData "Cerebro"
$Log = Join-Path $Base "reenvio-https.log"
$ArranqueEspera = 90   # segundos desde que arranco Windows antes de comprobar (la red tarda en estar lista)

function Escribir-Log([string]$Mensaje) {
  if (-not (Test-Path $Base)) { New-Item -ItemType Directory -Path $Base -Force | Out-Null }
  if ((Test-Path $Log) -and ((Get-Item $Log).Length -gt 1MB)) { Move-Item -Force $Log "$Log.antiguo" }
  Add-Content -Path $Log -Value ("{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $Mensaje)
}

# Direcciones donde hay una regla de reenvio (portproxy IPv4) del puerto 443
function Reglas-443 {
  $salida = & netsh interface portproxy show v4tov4 2>$null
  $ips = @()
  foreach ($linea in $salida) {
    if ($linea -match '^\s*(\d{1,3}(\.\d{1,3}){3})\s+443\s+') { $ips += $Matches[1] }
  }
  return $ips
}

function Escucha([string]$Ip) {
  $patron = "\s" + [regex]::Escape($Ip) + ":443\s.*LISTENING"
  return [bool](& netstat -ano -p tcp | Select-String -Pattern $patron)
}

function Vigilar-Reenvio {
  # Tras arrancar Windows, esperar a que la red este lista antes de comprobar nada
  try {
    $arranque = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
    $falta = $ArranqueEspera - [int]((Get-Date) - $arranque).TotalSeconds
    if ($falta -gt 0 -and $falta -le $ArranqueEspera) { Start-Sleep -Seconds $falta }
  } catch { }
  $ips = @(Reglas-443)
  if ($ips.Count -eq 0) { return }
  $caidas = @($ips | Where-Object { -not (Escucha $_) })
  if ($caidas.Count -eq 0) { return }
  Escribir-Log ("Windows NO escucha en el 443 de: " + ($caidas -join ", ") + ". Reinicio el servicio iphlpsvc.")
  try { Restart-Service -Name iphlpsvc -Force -ErrorAction Stop } catch { Escribir-Log ("No se pudo reiniciar iphlpsvc: " + $_.Exception.Message); return }
  Start-Sleep -Seconds 5
  $siguen = @($ips | Where-Object { -not (Escucha $_) })
  if ($siguen.Count -eq 0) { Escribir-Log "Arreglado: Windows vuelve a escuchar en el 443." }
  else { Escribir-Log ("SIGUE sin escuchar en: " + ($siguen -join ", ") + ". Mira que la direccion del PC no haya cambiado (ipconfig) y repite la regla netsh.") }
}

function Instalar-Tarea {
  $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  if (-not $admin) { Write-Host "Ejecuta este script en PowerShell COMO ADMINISTRADOR."; exit 1 }
  $ruta = $PSCommandPath
  if (-not $ruta) { $ruta = $MyInvocation.MyCommand.Path }
  # El script se copia a una carpeta fija para que la tarea no dependa de donde estaba (p. ej. un recurso de WSL que puede no estar listo al arrancar)
  if (-not (Test-Path $Base)) { New-Item -ItemType Directory -Path $Base -Force | Out-Null }
  $destino = Join-Path $Base "reenvio_https.ps1"
  Copy-Item -Path $ruta -Destination $destino -Force
  $accion = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $destino + '" -Vigilar')
  $alArrancar = New-ScheduledTaskTrigger -AtStartup
  $cadaCinco = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
  $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
  $ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
  Register-ScheduledTask -TaskName $Tarea -Action $accion -Trigger @($alArrancar, $cadaCinco) -Principal $principal -Settings $ajustes `
    -Description "Si Windows no escucha en el 443 del reenvio (netsh portproxy), reinicia el servicio iphlpsvc. Cerebro 101.cat, acceso externo." -Force | Out-Null
  Escribir-Log "Tarea instalada."
  Write-Host "Tarea instalada: $Tarea (al arrancar Windows y cada 5 minutos). Registro: $Log"
  Mostrar-Estado
}

function Mostrar-Estado {
  $t = Get-ScheduledTask -TaskName $Tarea -ErrorAction SilentlyContinue
  if ($t) { Write-Host ("Tarea: {0}  ({1})" -f $Tarea, $t.State) } else { Write-Host "Tarea: NO instalada (usa -Instalar)" }
  $servicio = Get-Service -Name iphlpsvc -ErrorAction SilentlyContinue
  if ($servicio) { Write-Host ("Servicio iphlpsvc: {0}" -f $servicio.Status) }
  $ips = @(Reglas-443)
  if ($ips.Count -eq 0) { Write-Host "Reglas de reenvio del 443: ninguna" }
  foreach ($ip in $ips) { Write-Host ("Regla del 443 en {0}: {1}" -f $ip, $(if (Escucha $ip) { "ESCUCHANDO (bien)" } else { "NO escucha (la tarea lo arregla en menos de 5 minutos)" })) }
  if (Test-Path $Log) { Write-Host "--- ultimas lineas del registro ---"; Get-Content $Log -Tail 8 }
}

if ($Instalar) { Instalar-Tarea }
elseif ($Quitar) { Unregister-ScheduledTask -TaskName $Tarea -Confirm:$false -ErrorAction SilentlyContinue; Write-Host "Tarea quitada." }
elseif ($Vigilar) { Vigilar-Reenvio }
elseif ($Estado) { Mostrar-Estado }
else { Get-Help $PSCommandPath -Detailed }
