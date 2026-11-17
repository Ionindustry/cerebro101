<#
.SYNOPSIS
  Arranque automatico y vigilancia del Cerebro 101.cat en Windows (Docker Desktop + WSL2).

.DESCRIPTION
  Registra cuatro tareas programadas del usuario actual:
    "Cerebro - arranque"   al iniciar sesion (con 1 minuto de espera): abre Docker Desktop, espera a que responda y levanta el Cerebro y el ERP
    "Cerebro - copia"      cada dia a las 14:00 (si el PC estaba apagado, en cuanto se enciende): copia de seguridad automatica (scripts/copia_automatica.sh:
                           comprueba la copia, conserva las ultimas 7 y avisa a soporte@ si falla)
    "Cerebro - vigilante"  cada 5 minutos: si Docker no responde durante dos comprobaciones seguidas lo reinicia (maximo 3 veces por hora);
                           si Docker responde pero la API o el panel no, vuelve a levantar los servicios (recreando api y panel si sus puertos se perdieron);
                           si aun asi los puertos publicados siguen sin responder (Docker Desktop deja de reenviarlos, p. ej. tras reiniciar WSL: su
                           com.docker.backend queda mas viejo que wslrelay), reinicia Docker Desktop, pero SOLO si no hay una oferta ni un analisis de pliegos
                           en curso (se cortaria el trabajo) y con tope de 2 reinicios por hora
    "Cerebro - disco"      cada 30 minutos: mira el espacio libre de las unidades donde viven los discos de WSL y Docker (las lee del registro de Windows) y AVISA
                           antes de que se llenen: por debajo de 50 GB libres (aviso) y de 20 GB (critico), con una notificacion de Windows y una linea en el registro;
                           si Docker responde, ademas un correo a soporte@. No depende de Docker: un disco lleno lo deja parado, y esta tarea sigue avisando.
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
  [switch]$Instalar, [switch]$Quitar, [switch]$Arrancar, [switch]$Vigilar, [switch]$Copiar, [switch]$Disco, [switch]$Estado,
  [string]$Distro = "Ubuntu", [string]$Carpeta = "~/cerebro101",
  [int]$AvisoGB = 50, [int]$CriticoGB = 20, [string[]]$Unidades = @()
)
$ErrorActionPreference = "Continue"
$Base   = Join-Path $env:USERPROFILE "cerebro-autoarranque"
$Log    = Join-Path $Base "autoarranque.log"
$Fichero = Join-Path $Base "estado.json"
$Tareas = @("Cerebro - arranque", "Cerebro - vigilante", "Cerebro - copia", "Cerebro - disco")
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

# docker info con limite de tiempo: un Docker medio caido puede quedarse colgado.
# No se usa el codigo de salida: tras Start-Process -PassThru a veces llega vacio y daba siempre "no responde".
# Docker responde si "docker info" llega a imprimir "Server Version" (solo lo muestra si el motor esta vivo).
function Docker-Responde {
  $salida = Join-Path $env:TEMP "cerebro-docker-info.txt"; $err = Join-Path $env:TEMP "cerebro-docker-info-err.txt"
  Remove-Item $salida, $err -ErrorAction SilentlyContinue
  try {
    $p = Start-Process -FilePath "docker" -ArgumentList "info" -NoNewWindow -PassThru -RedirectStandardOutput $salida -RedirectStandardError $err
    if (-not $p.WaitForExit(20000)) { try { $p.Kill() } catch {}; return $false }
    Start-Sleep -Milliseconds 200
    if (-not (Test-Path $salida)) { return $false }
    $texto = Get-Content $salida -Raw -ErrorAction SilentlyContinue
    return [bool]($texto -match "Server Version")
  } catch { return $false }
}

function Api-Responde {
  try { $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/salud" -UseBasicParsing -TimeoutSec 5; return ($r.StatusCode -eq 200) }
  catch { return $false }
}

function Panel-Responde {       # cualquier respuesta HTTP vale (incluso una redireccion): lo que se comprueba es que el puerto este publicado
  try { $null = Invoke-WebRequest -Uri "http://127.0.0.1:3000/" -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0; return $true }
  catch { return ($null -ne $_.Exception.Response) }
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
  return [pscustomobject]@{ fallos = 0; puertos = 0; recuperaciones = @() }
}
function Guardar-Estado($e) { $e | ConvertTo-Json -Depth 5 | Set-Content -Path $Fichero -Encoding UTF8 }

# Docker con tiempo maximo y devolviendo lo que imprime (o $null si no responde a tiempo)
function Docker-Salida([string[]]$Argumentos, [int]$Segundos = 30) {
  $salida = Join-Path $env:TEMP "cerebro-docker-salida.txt"; $err = Join-Path $env:TEMP "cerebro-docker-salida-err.txt"
  Remove-Item $salida, $err -ErrorAction SilentlyContinue
  try {
    $p = Start-Process -FilePath "docker" -ArgumentList $Argumentos -NoNewWindow -PassThru -RedirectStandardOutput $salida -RedirectStandardError $err
    if (-not $p.WaitForExit($Segundos * 1000)) { try { $p.Kill() } catch {}; return $null }
    Start-Sleep -Milliseconds 200
    if (-not (Test-Path $salida)) { return $null }
    return [string](Get-Content $salida -Raw -ErrorAction SilentlyContinue)
  } catch { return $null }
}

# Cuantas ofertas redactandose y analisis de pliegos hay en curso (reiniciar Docker los cortaria). $null si no se puede saber.
function Trabajos-En-Curso {
  $consulta = "SELECT (SELECT count(*) FROM ofertas_ejecuciones WHERE estado = 'en_curso') + (SELECT count(*) FROM licitaciones_analisis_pliego WHERE estado = 'en_curso')"
  $texto = Docker-Salida @("exec", "cerebro-101-postgres-1", "psql", "-U", "cerebro", "-d", "cerebro", "-tAc", ('"' + $consulta + '"')) 30
  if ($null -eq $texto) { return $null }
  $m = [regex]::Match($texto, '^\s*(\d+)\s*$')
  if ($m.Success) { return [int]$m.Groups[1].Value }
  return $null
}

# El reenvio de puertos de Docker Desktop (com.docker.backend) esta mas viejo que el de WSL (wslrelay): WSL se reinicio por debajo y el backend se quedo
# con una conexion muerta. Pasa tras "wsl --shutdown" si Docker Desktop no se cierra del todo.
function Backend-Viejo {
  $b = Get-Process -Name "com.docker.backend" -ErrorAction SilentlyContinue | Sort-Object StartTime | Select-Object -First 1
  $r = Get-Process -Name "wslrelay" -ErrorAction SilentlyContinue | Sort-Object StartTime -Descending | Select-Object -First 1
  if (-not $b -or -not $r) { return $false }
  return (($r.StartTime - $b.StartTime).TotalMinutes -gt 2)
}

function Recuperar-Docker {
  Escribir-Log "RECUPERANDO Docker: se cierra Docker Desktop, se reinicia WSL y se vuelve a abrir"
  Get-Process | Where-Object { $_.ProcessName -like "com.docker*" -or $_.ProcessName -eq "Docker Desktop" } | Stop-Process -Force -ErrorAction SilentlyContinue
  & wsl.exe --shutdown
  Start-Sleep -Seconds 10
  Abrir-DockerDesktop
  if (Esperar-Docker 300) { Escribir-Log "Docker responde otra vez"; Levantar-Cerebro } else { Escribir-Log "Docker NO ha vuelto a responder en 5 minutos" }
}


# ---- Espacio en disco -------------------------------------------------------------------------------------------------------------------------------------
# Los discos de Docker Desktop y de WSL son ficheros .vhdx que crecen y NO se encogen solos: si la unidad donde viven se llena, Docker no arranca. Se vigilan las
# unidades donde estan (se leen del registro: cada distribucion de WSL guarda ahi su carpeta, tambien si se movio a otra unidad) mas las que se pidan con -Unidades.
function Unidades-Vigiladas {
  $letras = @()
  $lxss = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss"
  foreach ($k in (Get-ChildItem $lxss -ErrorAction SilentlyContinue)) {
    $ruta = [string](Get-ItemProperty -Path $k.PSPath -ErrorAction SilentlyContinue).BasePath
    if ($ruta -match '^(\\\\\?\\)?([A-Za-z]):') { $letras += $Matches[2].ToUpper() }
  }
  foreach ($u in $Unidades) { if ($u -match '^([A-Za-z]):?$') { $letras += $Matches[1].ToUpper() } }
  if ($letras.Count -eq 0) { $letras = @("C") }
  return @($letras | Select-Object -Unique)
}

function Nivel-Disco([double]$LibreGB) {
  if ($LibreGB -lt $CriticoGB) { return "critico" }
  if ($LibreGB -lt $AvisoGB) { return "aviso" }
  return "ok"
}

# Notificacion de Windows (no necesita Docker ni correo). Si algo falla no pasa nada: queda el registro.
function Avisar-Windows([string]$Titulo, [string]$Texto) {
  try {
    [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
    [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
    $t = [System.Security.SecurityElement]::Escape($Titulo); $m = [System.Security.SecurityElement]::Escape($Texto)
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml("<toast><visual><binding template='ToastText02'><text id='1'>$t</text><text id='2'>$m</text></binding></visual></toast>")
    $aviso = [Windows.UI.Notifications.ToastNotification]::new($xml)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Cerebro 101").Show($aviso)
  } catch { Escribir-Log "No se pudo mostrar la notificacion de Windows: $($_.Exception.Message)" }
}

# Correo a soporte@ (los mismos destinatarios que los fallos del motor) SOLO si Docker responde: con el disco lleno suele estar parado y no puede enviarlo.
function Avisar-Correo([string]$Asunto, [string]$Cuerpo) {
  if (-not (Docker-Responde)) { Escribir-Log "Docker no responde: el aviso de disco no se envia por correo (queda la notificacion de Windows y este registro)"; return }
  $orden = "cd $Carpeta && docker compose exec -T api python -m cerebro.avisar_soporte '$Asunto' '$Cuerpo'"
  $lineas = & wsl.exe -d $Distro -- bash -lc $orden 2>&1
  foreach ($l in $lineas) { Escribir-Log ("    " + ($l -replace "`0", "")) }
}

# Cuando se vuelve a avisar de una unidad que sigue en el mismo nivel: critico cada 3 horas, aviso cada 24
function Toca-Avisar([string]$Nivel, $Previo) {
  if ($null -eq $Previo -or $Previo.nivel -ne $Nivel -or -not $Previo.aviso) { return $true }
  $horas = if ($Nivel -eq "critico") { 3 } else { 24 }
  return (((Get-Date) - [datetime]$Previo.aviso).TotalHours -ge $horas)
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

  # Copia de seguridad diaria a las 14:00 (horario de oficina: el PC suele estar encendido); con StartWhenAvailable, si estaba apagado se hace en cuanto se enciende
  $t3 = New-ScheduledTaskTrigger -Daily -At "14:00"
  Register-ScheduledTask -TaskName $Tareas[2] -Action (New-ScheduledTaskAction -Execute $powershell -Argument "$comun -Copiar") `
    -Trigger $t3 -Settings $ajustes -Principal $principal -Force | Out-Null

  # Espacio en disco cada 30 minutos (no depende de Docker)
  $t4 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
  Register-ScheduledTask -TaskName $Tareas[3] -Action (New-ScheduledTaskAction -Execute $powershell -Argument "$comun -Disco -AvisoGB $AvisoGB -CriticoGB $CriticoGB") `
    -Trigger $t4 -Settings $ajustes -Principal $principal -Force | Out-Null

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
  foreach ($u in (Unidades-Vigiladas)) {
    $d = Get-PSDrive -Name $u -PSProvider FileSystem -ErrorAction SilentlyContinue
    if ($d) { $g = [math]::Round($d.Free / 1GB, 1); Write-Host ("Disco {0}: {1} GB libres ({2})" -f $u, $g, (Nivel-Disco $g)) }
  }
  Write-Host ("Docker: " + $(if (Docker-Responde) { "responde" } else { "NO responde" }))
  Write-Host ("API del Cerebro: " + $(if (Api-Responde) { "responde" } else { "NO responde" }))
  if (Test-Path $Log) { Write-Host "--- ultimas lineas del registro ($Log):"; Get-Content $Log -Tail 15 }
  return
}

if ($Disco) {
  if (-not (Tomar-Turno)) { return }
  $e = Leer-Estado
  $guardado = @{}
  foreach ($u in (Unidades-Vigiladas)) {
    $d = Get-PSDrive -Name $u -PSProvider FileSystem -ErrorAction SilentlyContinue
    if (-not $d) { continue }
    $libre = [math]::Round($d.Free / 1GB, 1)
    $nivel = Nivel-Disco $libre
    $previo = $null
    if ($e.PSObject.Properties["discos"] -and $e.discos.PSObject.Properties[$u]) { $previo = $e.discos.$u }
    $ultimo = if ($previo) { [string]$previo.aviso } else { "" }
    Write-Host ("Disco {0}: {1} GB libres ({2})" -f $u, $libre, $nivel)
    if ($nivel -eq "ok") {
      if ($previo -and $previo.nivel -ne "ok") { Escribir-Log "Disco ${u}: ya tiene $libre GB libres (vuelve a estar bien)" }
    }
    elseif (Toca-Avisar $nivel $previo) {
      $titulo = if ($nivel -eq "critico") { "DISCO ${u}: CASI LLENO" } else { "Disco ${u}: queda poco espacio" }
      $texto = "Quedan $libre GB libres en ${u}: (aviso por debajo de $AvisoGB GB, critico por debajo de $CriticoGB GB). Si se llena, Docker y el Cerebro dejan de funcionar. Libera espacio."
      Escribir-Log "$titulo - $texto"
      Avisar-Windows $titulo $texto
      Avisar-Correo $titulo ($texto -replace "'", "")
      $ultimo = (Get-Date).ToString("o")
    }
    $guardado[$u] = @{ nivel = $nivel; libreGB = $libre; aviso = $ultimo }
  }
  $e | Add-Member -NotePropertyName discos -NotePropertyValue ([pscustomobject]$guardado) -Force
  Guardar-Estado $e
  return
}

if ($Copiar) {
  if (-not (Tomar-Turno)) { return }
  Escribir-Log "== Copia de seguridad automatica =="
  if (-not (Esperar-Docker 120)) { Escribir-Log "Docker no responde: no se puede hacer la copia ahora (la tarea lo reintentara en cuanto sea posible)"; return }
  $lineas = & wsl.exe -d $Distro -- bash -lc "cd $Carpeta && ./scripts/copia_automatica.sh" 2>&1
  foreach ($l in $lineas) { Escribir-Log ("    " + ($l -replace "`0", "")) }
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
  # Si la API del Cerebro responde, el motor de Docker esta vivo aunque la comprobacion de "docker info" falle
  if ((Docker-Responde) -or (Api-Responde)) {
    if ($e.fallos -ne 0) { Escribir-Log "Docker vuelve a responder"; $e.fallos = 0; Guardar-Estado $e }
    if ((-not (Api-Responde)) -or (-not (Panel-Responde))) {
      Escribir-Log "Docker responde pero la API o el panel no: se vuelven a levantar los servicios (y, si hace falta, se recrean api y panel)"
      Levantar-Cerebro
      if ((Api-Responde) -and (Panel-Responde)) { Escribir-Log "La API y el panel responden otra vez"; $e | Add-Member -NotePropertyName puertos -NotePropertyValue 0 -Force; Guardar-Estado $e }
      else {
        # Los servicios estan levantados pero sus puertos no responden: Docker Desktop no los esta reenviando. Reiniciar Docker Desktop lo arregla
        $e | Add-Member -NotePropertyName puertos -NotePropertyValue (([int]$e.puertos) + 1) -Force
        $viejo = Backend-Viejo
        Escribir-Log ("La API o el panel siguen sin responder con Docker vivo (comprobacion n.o $($e.puertos)" + $(if ($viejo) { "; el reenvio de puertos de Docker Desktop esta MAS VIEJO que el de WSL" } else { "" }) + ")")
        if (($e.puertos -ge 3) -or ($viejo -and $e.puertos -ge 2)) {
          $trabajos = Trabajos-En-Curso
          $hace1h = (Get-Date).AddHours(-1)
          $recientes = @($e.recuperaciones | Where-Object { $_ -and ([datetime]$_ -gt $hace1h) })
          if ($null -ne $trabajos -and $trabajos -gt 0) { Escribir-Log "Hay $trabajos trabajo(s) en curso (oferta o analisis de pliego): no reinicio Docker Desktop hasta que terminen." }
          elseif ($recientes.Count -ge 2) { Escribir-Log "REQUIERE ATENCION: ya se reinicio Docker Desktop 2 veces en la ultima hora y los puertos siguen sin responder. Revisalo a mano." }
          else {
            Escribir-Log "Los puertos publicados no responden y no hay trabajos en curso: reinicio Docker Desktop."
            $e.recuperaciones = @($recientes + (Get-Date).ToString("o")); $e.puertos = 0; Guardar-Estado $e
            Recuperar-Docker
            return
          }
        }
        Guardar-Estado $e
      }
    }
    elseif ([int]$e.puertos -ne 0) { $e | Add-Member -NotePropertyName puertos -NotePropertyValue 0 -Force; Guardar-Estado $e }
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

Write-Host "Indica una accion: -Instalar, -Estado, -Quitar, -Disco (mira ahora el espacio libre) (y, solo para uso interno, -Arrancar, -Vigilar o -Copiar). Mira la ayuda: Get-Help .\autoarranque.ps1 -Full"
