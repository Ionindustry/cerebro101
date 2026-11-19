<#
  Recolector de inventario de REA (Reverse Engineering Anything) - SOLO LECTURA.
  Uso (PowerShell):  .\recolectar_rea.ps1 -Nombre "REA"
  Genera la carpeta .\rea_inventario con ficheros de texto para subir al repositorio.
  No modifica nada ni envia datos a ningun sitio. Revisa la salida antes de subirla:
  puede contener rutas, nombres de usuario o tokens en argumentos de procesos.
#>
param([string]$Nombre = "REA")

$out = Join-Path (Get-Location) "rea_inventario"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$ErrorActionPreference = "SilentlyContinue"

# 1. Programa instalado (registro)
$claves = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
          "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
          "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
Get-ItemProperty $claves | Where-Object { $_.DisplayName -like "*$Nombre*" } |
  Select DisplayName, DisplayVersion, Publisher, InstallLocation, UninstallString |
  Format-List | Out-File "$out\01_instalacion_registro.txt"

# 2. Carpetas candidatas
$raices = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA, $env:APPDATA, $env:ProgramData)
$carpetas = foreach ($r in $raices) { Get-ChildItem $r -Directory | Where-Object { $_.Name -like "*$Nombre*" } }
$carpetas | Select FullName | Out-File "$out\02_carpetas.txt"

# 3. Arbol de ficheros (tamano y fecha) y tipos
foreach ($c in $carpetas) {
  Get-ChildItem $c.FullName -Recurse -File |
    Select FullName, Length, LastWriteTime | Out-File "$out\03_ficheros.txt" -Append
  Get-ChildItem $c.FullName -Recurse -File | Group-Object Extension | Sort Count -Descending |
    Select Count, Name | Out-File "$out\04_extensiones.txt" -Append
}

# 4. Ejecutables y DLL: version, firma y pistas de tecnologia
$bins = foreach ($c in $carpetas) { Get-ChildItem $c.FullName -Recurse -Include *.exe,*.dll,*.node,*.jar,*.pyd }
$bins | ForEach-Object {
  $v = $_.VersionInfo
  $firma = (Get-AuthenticodeSignature $_.FullName).Status
  [pscustomobject]@{
    Ruta = $_.FullName; Tam = $_.Length; Producto = $v.ProductName
    Version = $v.FileVersion; Empresa = $v.CompanyName; Firma = $firma
  }
} | Format-Table -AutoSize -Wrap | Out-String -Width 300 | Out-File "$out\05_binarios.txt"

$pistas = @()
foreach ($c in $carpetas) {
  if (Test-Path "$($c.FullName)\resources\app.asar") { $pistas += "Electron (app.asar) en $($c.FullName)" }
  if (Get-ChildItem $c.FullName -Recurse -Filter "python*.dll") { $pistas += "Python embebido" }
  if (Get-ChildItem $c.FullName -Recurse -Filter "*.jar") { $pistas += "Java (.jar)" }
  if (Get-ChildItem $c.FullName -Recurse -Filter "*.deps.json") { $pistas += ".NET (deps.json)" }
  if (Get-ChildItem $c.FullName -Recurse -Filter "hostfxr.dll") { $pistas += ".NET Core/5+" }
  if (Get-ChildItem $c.FullName -Recurse -Filter "*.sqlite*","*.db") { $pistas += "Base de datos local (sqlite/db)" }
}
$pistas | Sort-Object -Unique | Out-File "$out\06_pistas_tecnologia.txt"

# 5. Procesos y servicios de REA en ejecucion (ejecuta REA antes de lanzar el script)
Get-CimInstance Win32_Process | Where-Object { $_.Name -like "*$Nombre*" -or $_.ExecutablePath -like "*$Nombre*" } |
  Select ProcessId, Name, ExecutablePath, ParentProcessId | Format-Table -AutoSize |
  Out-File "$out\07_procesos.txt"
Get-CimInstance Win32_Service | Where-Object { $_.Name -like "*$Nombre*" -or $_.PathName -like "*$Nombre*" } |
  Select Name, State, StartMode, PathName | Format-List | Out-File "$out\08_servicios.txt"

# 6. Red: puertos en escucha y conexiones de esos procesos
$pids = (Get-CimInstance Win32_Process | Where-Object { $_.Name -like "*$Nombre*" -or $_.ExecutablePath -like "*$Nombre*" }).ProcessId
Get-NetTCPConnection | Where-Object { $pids -contains $_.OwningProcess } |
  Select State, LocalAddress, LocalPort, RemoteAddress, RemotePort, OwningProcess |
  Format-Table -AutoSize | Out-File "$out\09_red.txt"

# 7. Ficheros de configuracion de texto (primeras lineas; REVISA secretos antes de subir)
foreach ($c in $carpetas) {
  Get-ChildItem $c.FullName -Recurse -Include *.json,*.ini,*.config,*.xml,*.yaml,*.yml,*.toml |
    Where-Object { $_.Length -lt 200KB } | ForEach-Object {
      "=== $($_.FullName)"; Get-Content $_.FullName -TotalCount 60
    } | Out-File "$out\10_configuracion.txt" -Append
}

Write-Host "Listo. Revisa y sube la carpeta: $out"
