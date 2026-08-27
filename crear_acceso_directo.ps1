# Crea el acceso directo de Filadelfia Broadcaster con el icono de la emisora.
#
# Por que hace falta: un archivo .bat NO puede llevar icono propio. Windows le
# pone siempre el de la consola, sin importar lo que uno configure. Lo que si
# admite icono es un acceso directo (.lnk), y ademas se puede anclar a la barra
# de tareas — que es donde el icono se ve todo el dia.
#
# Uso:  clic derecho sobre este archivo -> "Ejecutar con PowerShell"
#       (o desde una consola:  powershell -ExecutionPolicy Bypass -File .\crear_acceso_directo.ps1)
#
# Si se mueve la carpeta del proyecto, hay que volver a ejecutarlo.

$ErrorActionPreference = "Stop"

$carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path
$icono   = Join-Path $carpeta "icono.ico"
$guion   = Join-Path $carpeta "app.py"

if (-not (Test-Path $guion))  { throw "No se encuentra app.py en $carpeta" }
if (-not (Test-Path $icono))  { throw "No se encuentra icono.ico. Abre la aplicacion una vez para que lo genere." }

# pythonw.exe = sin ventana negra de consola detras de la aplicacion
$python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $python) {
    $py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if (-not $py) { throw "No se encuentra Python en el PATH." }
    $python = Join-Path (Split-Path -Parent $py) "pythonw.exe"
    if (-not (Test-Path $python)) { $python = $py }
}

$nombre  = "Filadelfia Broadcaster.lnk"
$destinos = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) $nombre),
    (Join-Path ([Environment]::GetFolderPath("StartMenu")) (Join-Path "Programs" $nombre))
)

$shell = New-Object -ComObject WScript.Shell
foreach ($destino in $destinos) {
    $padre = Split-Path -Parent $destino
    if (-not (Test-Path $padre)) { New-Item -ItemType Directory -Force -Path $padre | Out-Null }
    $lnk = $shell.CreateShortcut($destino)
    $lnk.TargetPath       = $python
    $lnk.Arguments        = '"' + $guion + '"'
    $lnk.WorkingDirectory = $carpeta
    $lnk.IconLocation     = $icono + ",0"
    $lnk.Description      = "Estudio en vivo de la Voz de Filadelfia"
    $lnk.WindowStyle      = 1
    $lnk.Save()
    Write-Host "Creado: $destino"
}

# El icono viejo puede quedarse pegado en la cache de Windows. Esto la refresca
# sin tener que reiniciar ni cerrar sesion.
try {
    Start-Process -FilePath "$env:SystemRoot\system32\ie4uinit.exe" -ArgumentList "-show" -NoNewWindow -Wait
    Write-Host "Cache de iconos refrescada."
} catch {
    Write-Host "No se pudo refrescar la cache de iconos (no es grave)."
}

Write-Host ""
Write-Host "Listo. Abrelo desde el escritorio y, con la ventana abierta,"
Write-Host "clic derecho en la barra de tareas -> 'Anclar a la barra de tareas'."
