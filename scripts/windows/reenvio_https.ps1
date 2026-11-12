<#
.SYNOPSIS
  Mantiene vivo el reenvio del puerto 443 de Windows para el acceso externo del Cerebro 101.cat (Docker Desktop + WSL2).

.DESCRIPTION
  El acceso desde fuera entra por el 443 de Windows y una regla de "netsh interface portproxy" lo lleva al reenviador de Docker (puerto 18443).
  Esas reglas las ejecuta el servicio de Windows "Ayudante de IP" (iphlpsvc). Si ese servicio arranca antes de que la red este lista (tras reiniciar el PC),
  la regla queda escrita pero NO escucha y desde fuera no se llega. Este script lo detecta y lo arregla solo:

    -Instalar   registra la tarea "Cerebro - reenvio HTTPS" (como SYSTEM): al arrancar Windows (esperando a que la red este lista) y despues cada 5 minutos.
                Con -Dominios "brain.101.cat,auth.101.cat" ademas prueba de punta a punta que el acceso externo responde y se repara por escalones (ver abajo)
    -Vigilar    lo que hace la tarea. Escalones, de menos a mas:
                  1. Windows no escucha en el 443: reinicia el servicio iphlpsvc.
                  2. Faltan los dominios en el archivo hosts: los anade.
                  3. Pide la pagina de verdad (por el 443 de Windows). Si responde, termina. Si no:
                  4. Si Docker responde en el 18443 pero Windows no: recrea la regla netsh del 443.
                  5. Si Docker tampoco responde: reinicia los contenedores del reenviador y del proxy (con tope: uno cada 10 minutos y 6 al dia).
                  6. Si tras eso sigue sin responder, lo deja escrito en el registro como REQUIERE ATENCION (lo normal: Docker Desktop esta cerrado).
    -Estado     ensena la tarea, las reglas, si escuchan, una prueba en vivo y las ultimas lineas del registro
    -Quitar     borra la tarea

  Uso (PowerShell COMO ADMINISTRADOR):
    powershell -ExecutionPolicy Bypass -File reenvio_https.ps1 -Instalar -Dominios "brain.101.cat,auth.101.cat"
    powershell -ExecutionPolicy Bypass -File reenvio_https.ps1 -Estado
  Registro: C:\ProgramData\Cerebro\reenvio-https.log (se rota a 1 MB)
  No hace nada si no hay ninguna regla de reenvio del 443 (el acceso externo no esta activado con Docker Desktop).
#>
param([switch]$Instalar, [switch]$Quitar, [switch]$Vigilar, [switch]$Estado, [string]$Dominios = "")
$ErrorActionPreference = "Continue"
$Tarea = "Cerebro - reenvio HTTPS"
$Base = Join-Path $env:ProgramData "Cerebro"
$Log = Join-Path $Base "reenvio-https.log"
$Config = Join-Path $Base "reenvio-config.json"    # los dominios a vigilar (los escribe -Instalar)
$EstadoRuta = Join-Path $Base "reenvio-estado.json"  # fallos seguidos y reinicios hechos (para no reiniciar en bucle)
$EsperaReinicios = 10   # minutos minimos entre dos reinicios de contenedores
$MaxReinicios = 6       # reinicios de contenedores como mucho en 24 horas
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


function Leer-Json([string]$Ruta) {
  try { if (Test-Path $Ruta) { return (Get-Content $Ruta -Raw | ConvertFrom-Json) } } catch { }
  return $null
}

function Guardar-Json([string]$Ruta, $Objeto) {
  try { $Objeto | ConvertTo-Json -Depth 4 | Set-Content -Path $Ruta -Encoding ASCII } catch { Escribir-Log ("No se pudo guardar " + $Ruta + ": " + $_.Exception.Message) }
}

# Las reglas del 443 con su destino: @{Escucha=...; Destino=...; Puerto=...}
function Reglas-443-Detalle {
  $salida = & netsh interface portproxy show v4tov4 2>$null
  $reglas = @()
  foreach ($linea in $salida) {
    if ($linea -match '^\s*(\d{1,3}(\.\d{1,3}){3})\s+443\s+(\d{1,3}(\.\d{1,3}){3})\s+(\d+)') { $reglas += @{ Escucha = $Matches[1]; Destino = $Matches[3]; Puerto = $Matches[5] } }
  }
  return $reglas
}

# Pide la pagina de verdad, con el nombre del dominio (sin el no hay certificado). Devuelve el codigo HTTP ("000" si no hay respuesta) o $null si no hay curl
function Probar-Https([string]$Dominio, [int]$Puerto, [string]$Ip) {
  $curl = Join-Path $env:SystemRoot "System32\curl.exe"
  if (-not (Test-Path $curl)) { return $null }
  $codigo = & $curl -k -s -o NUL -w "%{http_code}" --max-time 15 --resolve ("{0}:{1}:{2}" -f $Dominio, $Puerto, $Ip) ("https://{0}:{1}/" -f $Dominio, $Puerto) 2>$null
  return [string]$codigo
}

function Responde([string]$Codigo) { return ($Codigo -match '^[1-5]\d\d$') }

# Que los dominios del acceso externo apunten a la IP del PC (sin esto el navegador del propio PC no llega)
function Asegurar-Hosts([string[]]$Sitios, [string]$Ip) {
  $ruta = Join-Path $env:SystemRoot "System32\drivers\etc\hosts"
  try { $lineas = @(Get-Content $ruta -ErrorAction Stop) } catch { return }
  foreach ($d in $Sitios) {
    $con = @($lineas | Where-Object { $_ -notmatch '^\s*#' -and $_ -match ('\s' + [regex]::Escape($d) + '(\s|$)') })
    if ($con.Count -eq 0) {
      try { Add-Content -Path $ruta -Value ("{0} {1}" -f $Ip, $d) -ErrorAction Stop; Escribir-Log ("Faltaba en hosts: anado {0} {1}" -f $Ip, $d) } catch { Escribir-Log ("No se pudo escribir en hosts: " + $_.Exception.Message) }
    }
    elseif (-not ($con | Where-Object { $_ -match ('^\s*' + [regex]::Escape($Ip) + '\s') })) { Escribir-Log ("Aviso: en hosts {0} no apunta a {1}" -f $d, $Ip) }
  }
}

function Docker-Exe {
  $propio = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
  if (Test-Path $propio) { return $propio }
  $g = Get-Command docker.exe -ErrorAction SilentlyContinue
  if ($g) { return $g.Source }
  return $null
}

# Ejecuta docker con tiempo maximo (si el motor esta colgado, no se queda esperando para siempre). Devuelve el texto o $null
function Docker-Ejecutar([string[]]$Argumentos, [int]$Segundos = 60) {
  $exe = Docker-Exe
  if (-not $exe) { return $null }
  $trabajo = Start-Job -ScriptBlock { param($e, $a) & $e @a 2>&1 | Out-String } -ArgumentList $exe, $Argumentos
  if (Wait-Job $trabajo -Timeout $Segundos) { $r = Receive-Job $trabajo; Remove-Job $trabajo -Force; return [string]$r }
  Stop-Job $trabajo; Remove-Job $trabajo -Force
  return $null
}

# Reinicia los contenedores del reenviador y del proxy. Respeta el tope: uno cada $EsperaReinicios minutos y $MaxReinicios al dia
function Reiniciar-Contenedores($Est) {
  $ahora = Get-Date
  $recientes = @($Est.reinicios | Where-Object { $_ -and (($ahora - [datetime]$_).TotalHours -lt 24) })
  if ($recientes.Count -gt 0 -and (($ahora - [datetime]($recientes | Select-Object -Last 1)).TotalMinutes -lt $EsperaReinicios)) { Escribir-Log "Docker sigue sin responder; espero antes de reiniciar otra vez."; $Est.reinicios = $recientes; return }
  if ($recientes.Count -ge $MaxReinicios) { Escribir-Log "REQUIERE ATENCION: ya se han reiniciado los contenedores $MaxReinicios veces en 24 h y sigue sin responder."; $Est.reinicios = $recientes; return }
  $nombres = @()
  foreach ($filtro in @("reenvio", "proxy")) {
    $r = Docker-Ejecutar @("ps", "-a", "--filter", ("name=" + $filtro), "--format", "{{.Names}}") 30
    if ($r) { $nombres += @($r -split "\s+" | Where-Object { $_ -match '^[A-Za-z0-9_.-]+$' -and $_ -match 'cerebro' }) }
  }
  if ($nombres.Count -eq 0) { Escribir-Log "REQUIERE ATENCION: Docker no responde (probablemente Docker Desktop esta cerrado): abrelo y espera a Engine running."; $Est.reinicios = $recientes; return }
  Escribir-Log ("Reinicio los contenedores: " + ($nombres -join ", "))
  $r = Docker-Ejecutar (@("restart") + $nombres) 120
  if ($null -eq $r) { Escribir-Log "REQUIERE ATENCION: el reinicio de los contenedores no termino (Docker colgado): reinicia Docker Desktop." } else { Escribir-Log ("Resultado: " + ($r -replace "\s+", " ").Trim()) }
  $Est.reinicios = @($recientes) + @($ahora.ToString("s"))
}

# Escalones 3 a 6 (ver la ayuda): la prueba de punta a punta y, si falla, la reparacion
function Comprobar-Camino($Reglas) {
  $cfg = Leer-Json $Config
  if (-not $cfg -or -not $cfg.dominios) { return }
  $sitios = @($cfg.dominios)
  $regla = $Reglas[0]
  Asegurar-Hosts $sitios $regla.Escucha
  $dom = $sitios[0]
  $ipPc = $regla.Escucha
  $codigo = Probar-Https $dom 443 $ipPc
  if ($null -eq $codigo) { return }
  $est = Leer-Json $EstadoRuta
  if (-not $est) { $est = [pscustomobject]@{ fallos = 0; reinicios = @() } }
  if (Responde $codigo) {
    if ([int]$est.fallos -gt 0) { Escribir-Log ("Recuperado: el acceso externo responde (" + $codigo + ") tras " + $est.fallos + " comprobaciones fallidas."); $est.fallos = 0; Guardar-Json $EstadoRuta $est }
    return
  }
  $est.fallos = [int]$est.fallos + 1
  Escribir-Log ("El acceso externo NO responde (codigo " + $codigo + "), comprobacion fallida n." + $est.fallos)
  $puertoDocker = [int]$regla.Puerto
  $destino = $regla.Destino
  $interno = Probar-Https $dom $puertoDocker $destino
  if (Responde $interno) {
    Escribir-Log "Docker SI responde en el puerto interno: falla la regla de Windows. Recreo la regla netsh y reinicio iphlpsvc."
    & netsh interface portproxy delete v4tov4 listenaddress=$($regla.Escucha) listenport=443 2>&1 | Out-Null
    & netsh interface portproxy add v4tov4 listenaddress=$($regla.Escucha) listenport=443 connectaddress=$($regla.Destino) connectport=$($regla.Puerto) 2>&1 | Out-Null
    try { Restart-Service -Name iphlpsvc -Force -ErrorAction Stop } catch { Escribir-Log ("No se pudo reiniciar iphlpsvc: " + $_.Exception.Message) }
  }
  else { Reiniciar-Contenedores $est }
  Guardar-Json $EstadoRuta $est
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
  if ($caidas.Count -eq 0) { Comprobar-Camino @(Reglas-443-Detalle); return }
  Escribir-Log ("Windows NO escucha en el 443 de: " + ($caidas -join ", ") + ". Reinicio el servicio iphlpsvc.")
  try { Restart-Service -Name iphlpsvc -Force -ErrorAction Stop } catch { Escribir-Log ("No se pudo reiniciar iphlpsvc: " + $_.Exception.Message); return }
  Start-Sleep -Seconds 5
  $siguen = @($ips | Where-Object { -not (Escucha $_) })
  if ($siguen.Count -eq 0) { Escribir-Log "Arreglado: Windows vuelve a escuchar en el 443."; Comprobar-Camino @(Reglas-443-Detalle) }
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
    -Description "Vigila el acceso externo (443): si Windows no escucha reinicia iphlpsvc; si la pagina no responde, repara la regla, el archivo hosts o los contenedores del reenviador. Cerebro 101.cat." -Force | Out-Null
  if ($Dominios) {
    $lista = @($Dominios -split "[,; ]+" | Where-Object { $_ -match '^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$' })
    if ($lista.Count -gt 0) { Guardar-Json $Config ([pscustomobject]@{ dominios = $lista }); Escribir-Log ("Dominios a vigilar: " + ($lista -join ", ")) }
    else { Write-Host "Los dominios no son validos; la tarea solo vigilara que Windows escuche en el 443." }
  }
  Escribir-Log "Tarea instalada."
  Write-Host "Tarea instalada: $Tarea (al arrancar Windows y cada 5 minutos). Registro: $Log"
  if (-not (Leer-Json $Config)) { Write-Host 'Aviso: sin -Dominios solo vigila el 443 de Windows. Para que tambien repare Docker: -Instalar -Dominios "brain.101.cat,auth.101.cat"' }
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
  $cfg = Leer-Json $Config
  $reglas = @(Reglas-443-Detalle)
  if ($cfg -and $cfg.dominios -and $reglas.Count -gt 0) {
    $dom = @($cfg.dominios)[0]
    $ipPc = $reglas[0].Escucha
    $c = Probar-Https $dom 443 $ipPc
    Write-Host ("Prueba en vivo de https://{0}: {1}" -f $dom, $(if (Responde $c) { "RESPONDE ($c) - bien" } else { "NO responde ($c) - la tarea lo intenta arreglar cada 5 minutos" }))
  } elseif (-not $cfg) { Write-Host "Dominios a vigilar: ninguno (reinstala con -Dominios para la prueba de punta a punta)" }
  if (Test-Path $Log) { Write-Host "--- ultimas lineas del registro ---"; Get-Content $Log -Tail 10 }
}

if ($Instalar) { Instalar-Tarea }
elseif ($Quitar) { Unregister-ScheduledTask -TaskName $Tarea -Confirm:$false -ErrorAction SilentlyContinue; Write-Host "Tarea quitada." }
elseif ($Vigilar) { Vigilar-Reenvio }
elseif ($Estado) { Mostrar-Estado }
else { Get-Help $PSCommandPath -Detailed }
