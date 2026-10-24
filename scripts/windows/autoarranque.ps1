<#
.SYNOPSIS
  Arranque automatico y vigilancia del Cerebro 101.cat en Windows (Docker Desktop + WSL2).

.DESCRIPTION
  Registra dos tareas programadas del usuario actual:
    "Cerebro - arranque"   al iniciar sesion (con 1 minuto de espera): abre Docker Desktop, espera a que responda y levanta el Cerebro y el ERP
    "Cerebro - vigilante"  cada 5 minutos: si Docker no responde durante dos comprobaciones seguidas lo reinicia (maximo 3 veces por hora);
                           si Docker responde pero la API no, vuelve a levantar los servicios
  Todo queda en %USERPROFILE%\cerebro-autoarranque\autoarranque.log

  Uso (PowerShell; -Instalar hay que lanzarlo como ADMINISTRADOR, las tareas luego se ejecutan con tu usuario, sin privilegios):
    powershell -ExecutionPolicy Bypass -File autoarranque.ps1 -Instalar
    powershell -ExecutionPolicy Bypass -File autoarranque.ps1 -Estado
    powershell -ExecutionPolicy Bypass -File autoarranque.ps1 -Quitar
  Opciones: -Distro Ubuntu (nombre de la distribucion de WSL)  -Carpeta "~/cerebro101" (donde esta el proyecto dentro de WSL)

  Limitaciones: Docker Desktop necesita una sesion de usuario abierta, asi que tras reiniciar el PC hay que iniciar sesion
  (o activar el inicio de sesion automatico). Si el equipo se suspende, todo se para: desactiva la suspension.
#>
param(
  [switch]$Instalar, [switch]$Quitar, [switch]$Arrancar, [switch]$Vigilar, [switch]$Estado,
  [string]$Distro = "Ubuntu", [string]$Carpeta = "~/cerebro101"
)
$ErrorActionPreference = "Continue"
$Base   = Join-Path $env:USERPROFILE "cerebro-autoarranque"
$Log    = Join-Path $Base "autoarranque.log"
$Fichero = Join-Path $Base "estado.json"
$Tareas = @("Cerebro - arranque", "Cerebro - vigilante")
$DockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
if (-not (Test-Path $Base)) { New-Item -ItemType Directory -Path $Base | Out-Null }

function Escribir-Log([string]$Mensaje) {
  if ((Test-Path $Log) -and ((Get-Item $Log).Length -gt 1MB)) { Move-Item -Force $Log "$Log.antiguo" }
  Add-Content -Path $Log -Value ("{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $Mensaje)
}

# Un solo proceso a la vez (el arranque y el vigilante podrian coincidir)
function Tomar-Turno {
  $script:Mutex = New-Object System.Threading.Mutex($false, "Local\CerebroAutoarranque")
  try { return $script:Mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { return $true }
}

# docker info con limite de tiempo: un Docker medio caido puede quedarse colgado
function Docker-Responde {
  $salida = Join-Path $env:TEMP "cerebro-docker-info.txt"; $err = Join-Path $env:TEMP "cerebro-docker-info-err.txt"
  try {
    $p = Start-Process -FilePath "docker" -ArgumentList "info" -NoNewWindow -PassThru -RedirectStandardOutput $salida -RedirectStandardError $err
    if (-not $p.WaitForExit(20000)) { try { $p.Kill() } catch {}; return $false }
    return ($p.ExitCode -eq 0)
  } catch { return $false }
}

function Api-Responde {
  try { $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/salud" -UseBasicParsing -TimeoutSec 5; return ($r.StatusCode -eq 200) }
  catch { return $false }
}

function Abrir-DockerDesktop {
  if (Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue) { return }
  if (-not (Test-Path $DockerDesktop)) { Escribir-Log "No encuentro Docker Desktop en $DockerDesktop"; return }
  Escribir-Log "Abriendo Docker Desktop"
  Start-Process -FilePath $DockerDesktop
}

function Esperar-Docker([int]$Segundos = 300) {
  $limite = (Get-Date).AddSeconds($Segundos)
  while ((Get-Date) -lt $limite) {
    if (Docker-Responde) { return $true }
    Start-Sleep -Seconds 5
  }
  return $false
}

function Levantar-Cerebro {
  Escribir-Log "Levantando el Cerebro y el ERP (scripts/arrancar.sh)"
  $orden = "cd $Carpeta && ./scripts/arrancar.sh"
  $lineas = & wsl.exe -d $Distro -- bash -lc $orden 2>&1
  foreach ($l in $lineas) { Escribir-Log ("    " + ($l -replace "`0", "")) }
}

function Leer-Estado {
  if (Test-Path $Fichero) { try { return Get-Content $Fichero -Raw | ConvertFrom-Json } catch {} }
  return [pscustomobject]@{ fallos = 0; recuperaciones = @() }
}
function Guardar-Estado($e) { $e | ConvertTo-Json -Depth 3 | Set-Content -Path $Fichero -Encoding UTF8 }

function Recuperar-Docker {
  Escribir-Log "RECUPERANDO Docker: se cierra Docker Desktop, se reinicia WSL y se vuelve a abrir"
  Get-Process | Where-Object { $_.ProcessName -like "com.docker*" -or $_.ProcessName -eq "Docker Desktop" } | Stop-Process -Force -ErrorAction SilentlyContinue
  & wsl.exe --shutdown
  Start-Sleep -Seconds 10
  Abrir-DockerDesktop
  if (Esperar-Docker 300) { Escribir-Log "Docker responde otra vez"; Levantar-Cerebro } else { Escribir-Log "Docker NO ha vuelto a responder en 5 minutos" }
}

if ($Instalar) {
  $destino = Join-Path $Base "autoarranque.ps1"
  if ($PSCommandPath -ne $destino) { Copy-Item -Force $PSCommandPath $destino }
  $powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
  $comun = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$destino`" -Distro `"$Distro`" -Carpeta `"$Carpeta`""
  $usuario = "$env:USERDOMAIN\$env:USERNAME"
  $ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
  $principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited

  $t1 = New-ScheduledTaskTrigger -AtLogOn -User $usuario
  $t1.Delay = "PT1M"
  Register-ScheduledTask -TaskName $Tareas[0] -Action (New-ScheduledTaskAction -Execute $powershell -Argument "$comun -Arrancar") `
    -Trigger $t1 -Settings $ajustes -Principal $principal -Force | Out-Null

  $t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(3) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
  Register-ScheduledTask -TaskName $Tareas[1] -Action (New-ScheduledTaskAction -Execute $powershell -Argument "$comun -Vigilar") `
    -Trigger $t2 -Settings $ajustes -Principal $principal -Force | Out-Null

  Escribir-Log "Tareas instaladas para $usuario (distribucion $Distro, carpeta $Carpeta)"
  Write-Host "Instalado. Tareas: $($Tareas -join ' y ')."
  Write-Host "Registro: $Log"
  Write-Host "Para probarlo ahora: Start-ScheduledTask -TaskName '$($Tareas[0])'   y luego mira el registro."
  Write-Host "Recomendado: que el PC no se suspenda ->  powercfg /change standby-timeout-ac 0"
  return
}

if ($Quitar) {
  foreach ($t in $Tareas) { Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue }
  Escribir-Log "Tareas quitadas"
  Write-Host "Tareas quitadas. (Se conservan el registro y el script en $Base)"
  return
}

if ($Estado) {
  foreach ($t in $Tareas) {
    $x = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    if ($x) { $i = Get-ScheduledTaskInfo -TaskName $t; Write-Host ("{0}: {1}; ultima ejecucion {2}; resultado {3}" -f $t, $x.State, $i.LastRunTime, $i.LastTaskResult) }
    else { Write-Host "${t}: NO instalada" }
  }
  Write-Host ("Docker: " + $(if (Docker-Responde) { "responde" } else { "NO responde" }))
  Write-Host ("API del Cerebro: " + $(if (Api-Responde) { "responde" } else { "NO responde" }))
  if (Test-Path $Log) { Write-Host "--- ultimas lineas del registro ($Log):"; Get-Content $Log -Tail 15 }
  return
}

if ($Arrancar) {
  if (-not (Tomar-Turno)) { return }
  Escribir-Log "== Arranque al iniciar sesion =="
  Abrir-DockerDesktop
  if (-not (Esperar-Docker 300)) { Escribir-Log "Docker no respondio en 5 minutos: el vigilante lo intentara de nuevo"; return }
  Levantar-Cerebro
  return
}

if ($Vigilar) {
  if (-not (Tomar-Turno)) { return }
  $e = Leer-Estado
  if (Docker-Responde) {
    if ($e.fallos -ne 0) { Escribir-Log "Docker vuelve a responder"; $e.fallos = 0; Guardar-Estado $e }
    if (-not (Api-Responde)) {
      Escribir-Log "Docker responde pero la API no: se vuelven a levantar los servicios"
      Levantar-Cerebro
      if (Api-Responde) { Escribir-Log "La API responde otra vez" } else { Escribir-Log "La API sigue sin responder (puede estar cargando; se reintentara en 5 minutos)" }
    }
    return
  }
  $e.fallos = [int]$e.fallos + 1
  Escribir-Log "Docker NO responde (comprobacion fallida n.o $($e.fallos))"
  if ($e.fallos -ge 2) {
    $hace1h = (Get-Date).AddHours(-1)
    $recientes = @($e.recuperaciones | Where-Object { $_ -and ([datetime]$_ -gt $hace1h) })
    if ($recientes.Count -ge 3) { Escribir-Log "Ya se reinicio Docker 3 veces en la ultima hora: no se insiste. Revisalo a mano."; }
    else { $e.recuperaciones = @($recientes + (Get-Date).ToString("o")); Guardar-Estado $e; Recuperar-Docker; $e.fallos = 0 }
  }
  Guardar-Estado $e
  return
}

Write-Host "Indica una accion: -Instalar, -Estado, -Quitar (y, solo para uso interno, -Arrancar o -Vigilar). Mira la ayuda: Get-Help .\autoarranque.ps1 -Full"
