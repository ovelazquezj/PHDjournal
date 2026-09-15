# Instala PHDjournal en el escritorio de Windows.
#
# Crea:
#   1. Acceso directo en el menu Inicio, con AppUserModelID propio. El AUMID es
#      lo que hace que las notificaciones nativas se atribuyan a la app y no a
#      "Python", y que el clic la traiga al frente.
#   2. Acceso directo en Inicio automatico, que arranca minimizado en bandeja.
#   3. Dos tareas programadas de respaldo, unos minutos antes de cada busqueda,
#      que levantan la app si no esta corriendo. La app tiene su propio
#      temporizador; esto solo cubre el caso de haberla cerrado.
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1 -Python "C:\ruta\pythonw.exe"
#   powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1 -CrearEntorno

param(
    [string]$Python = "",
    [switch]$CrearEntorno,
    [string]$HoraManana = "05:25",
    [string]$HoraTarde  = "18:25"
)

$ErrorActionPreference = "Stop"
$Raiz  = Split-Path -Parent $PSScriptRoot
$AppId = "PHDjournal"
$Icono = Join-Path $Raiz "data\phdjournal.ico"

Write-Host "PHDjournal, instalacion" -ForegroundColor Cyan
Write-Host "  raiz: $Raiz"

# --- 0. Encontrar Python ------------------------------------------------
# Se busca en orden, de lo mas especifico a lo mas general. Nada esta fijo
# en el codigo: este script tiene que servir en cualquier maquina.
function Get-PythonW {
    param([string]$Preferido)

    if ($Preferido) {
        if (Test-Path $Preferido) { return (Resolve-Path $Preferido).Path }
        throw "No existe el Python indicado: $Preferido"
    }

    # 1. Entorno virtual dentro del proyecto
    foreach ($n in @(".venv", "venv", "env")) {
        $p = Join-Path $Raiz "$n\Scripts\pythonw.exe"
        if (Test-Path $p) { return (Resolve-Path $p).Path }
    }

    # 2. Entorno conda o virtualenv activo en esta sesion
    foreach ($v in @($env:CONDA_PREFIX, $env:VIRTUAL_ENV)) {
        if ($v) {
            foreach ($rel in @("pythonw.exe", "Scripts\pythonw.exe")) {
                $p = Join-Path $v $rel
                if (Test-Path $p) { return (Resolve-Path $p).Path }
            }
        }
    }

    # 3. Entorno conda llamado como el proyecto
    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($conda) {
        try {
            $envs = & conda env list 2>$null | Where-Object { $_ -match "^\s*phdjournal\s" }
            if ($envs) {
                $ruta = ($envs -split "\s+" | Select-Object -Last 1)
                $p = Join-Path $ruta "pythonw.exe"
                if (Test-Path $p) { return (Resolve-Path $p).Path }
            }
        } catch { }
    }

    # 4. Lanzador py y python del PATH
    foreach ($cmd in @("pythonw", "python")) {
        $c = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($c) {
            $p = $c.Source -replace "python\.exe$", "pythonw.exe"
            if (Test-Path $p) { return $p }
            return $c.Source
        }
    }
    return $null
}

if ($CrearEntorno) {
    $venv = Join-Path $Raiz ".venv"
    if (-not (Test-Path $venv)) {
        Write-Host "`nCreando entorno virtual en .venv ..."
        $base = (Get-Command python -ErrorAction SilentlyContinue)
        if (-not $base) { throw "No hay 'python' en el PATH para crear el entorno." }
        & $base.Source -m venv $venv
    }
    Write-Host "Instalando dependencias ..."
    & (Join-Path $venv "Scripts\python.exe") -m pip install --quiet --upgrade pip
    & (Join-Path $venv "Scripts\python.exe") -m pip install --quiet -r (Join-Path $Raiz "requirements.txt")
}

$PythonW = Get-PythonW -Preferido $Python
if (-not $PythonW) {
    Write-Host "`nNo se encontro una instalacion de Python." -ForegroundColor Red
    Write-Host "Opciones:"
    Write-Host "  - instalar Python 3.11 o superior y repetir"
    Write-Host "  - crear el entorno aqui mismo:"
    Write-Host "      powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1 -CrearEntorno"
    Write-Host "  - indicar la ruta a mano:"
    Write-Host "      ... -Python `"C:\ruta\a\pythonw.exe`""
    exit 1
}
Write-Host "  python: $PythonW"

# Comprobar que las dependencias esten puestas
$falta = & ($PythonW -replace "pythonw\.exe$", "python.exe") -c @"
import importlib, sys
faltan = [m for m in ('PySide6', 'anthropic', 'httpx2', 'fitz')
          if not importlib.util.find_spec(m)]
print(','.join(faltan))
"@ 2>$null
if ($falta) {
    Write-Host "`nFaltan dependencias: $falta" -ForegroundColor Yellow
    Write-Host "Instalalas con:"
    Write-Host "  & `"$($PythonW -replace 'pythonw\.exe$','python.exe')`" -m pip install -r requirements.txt"
    Write-Host ""
}

# --- 1. Icono -----------------------------------------------------------
Write-Host "`n[1/4] Generando el icono..."
$PythonExe = $PythonW -replace "pythonw\.exe$", "python.exe"
& $PythonExe -c @"
import os, sys
sys.path.insert(0, r'$Raiz')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
from phdjournal.ui.iconos import guardar_ico
destino = Path(r'$Icono')
destino.parent.mkdir(parents=True, exist_ok=True)
guardar_ico(destino)
print('  icono en', destino)
"@

# --- 2. Acceso directo en el menu Inicio --------------------------------
Write-Host "`n[2/4] Acceso directo en el menu Inicio..."
$Enlace = Join-Path ([Environment]::GetFolderPath("Programs")) "PHDjournal.lnk"
$Shell = New-Object -ComObject WScript.Shell
$sc = $Shell.CreateShortcut($Enlace)
$sc.TargetPath       = $PythonW
$sc.Arguments        = "-m phdjournal"
$sc.WorkingDirectory = $Raiz
$sc.Description      = "Lector diario de novedades cientificas"
if (Test-Path $Icono) { $sc.IconLocation = $Icono }
$sc.Save()
Write-Host "  $Enlace"

# El AUMID va en una propiedad del shell link que WScript.Shell no expone.
try {
    $codigo = @'
using System;
using System.Runtime.InteropServices;
public static class Aumid {
    [DllImport("shell32.dll", CharSet=CharSet.Unicode, PreserveSig=false)]
    public static extern void SHGetPropertyStoreFromParsingName(
        string path, IntPtr bind, int flags, ref Guid iid,
        [MarshalAs(UnmanagedType.Interface)] out IPropertyStore store);

    [ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IPropertyStore {
        int GetCount(out uint c);
        int GetAt(uint i, out PropertyKey k);
        int GetValue(ref PropertyKey k, out PropVariant v);
        int SetValue(ref PropertyKey k, ref PropVariant v);
        int Commit();
    }
    [StructLayout(LayoutKind.Sequential, Pack=4)]
    public struct PropertyKey { public Guid fmtid; public uint pid; }
    [StructLayout(LayoutKind.Explicit)]
    public struct PropVariant {
        [FieldOffset(0)] public ushort vt;
        [FieldOffset(8)] public IntPtr p;
    }

    public static void Set(string lnk, string appId) {
        Guid iid = new Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99");
        IPropertyStore store;
        SHGetPropertyStoreFromParsingName(lnk, IntPtr.Zero, 2, ref iid, out store);
        PropertyKey key = new PropertyKey {
            fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
        PropVariant pv = new PropVariant { vt = 31, p = Marshal.StringToCoTaskMemUni(appId) };
        store.SetValue(ref key, ref pv);
        store.Commit();
        Marshal.FreeCoTaskMem(pv.p);
        Marshal.ReleaseComObject(store);
    }
}
'@
    Add-Type -TypeDefinition $codigo -Language CSharp -ErrorAction Stop
    [Aumid]::Set($Enlace, $AppId)
    Write-Host "  AppUserModelID fijado: $AppId"
} catch {
    Write-Host "  aviso: no se pudo fijar el AUMID ($($_.Exception.Message))" -ForegroundColor Yellow
    Write-Host "         las notificaciones caeran al globo de la bandeja, que igual funciona"
}

# --- 3. Arranque con Windows --------------------------------------------
Write-Host "`n[3/4] Arranque automatico..."
$EnlaceInicio = Join-Path ([Environment]::GetFolderPath("Startup")) "PHDjournal.lnk"
$si = $Shell.CreateShortcut($EnlaceInicio)
$si.TargetPath       = $PythonW
$si.Arguments        = "-m phdjournal --minimizado"
$si.WorkingDirectory = $Raiz
$si.Description      = "PHDjournal en la bandeja del sistema"
if (Test-Path $Icono) { $si.IconLocation = $Icono }
$si.Save()
Write-Host "  $EnlaceInicio"

# --- 4. Tareas programadas de respaldo -----------------------------------
Write-Host "`n[4/4] Tareas de respaldo en el Programador..."
$Accion = New-ScheduledTaskAction -Execute $PythonW `
    -Argument "-m phdjournal --minimizado" -WorkingDirectory $Raiz
$Ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

foreach ($t in @(@{n="PHDjournal-manana"; h=$HoraManana}, @{n="PHDjournal-tarde"; h=$HoraTarde})) {
    $Disparador = New-ScheduledTaskTrigger -Daily -At $t.h
    Unregister-ScheduledTask -TaskName $t.n -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $t.n -Action $Accion -Trigger $Disparador `
        -Settings $Ajustes -Description "Levanta PHDjournal por si esta cerrado" | Out-Null
    Write-Host "  $($t.n) a las $($t.h)"
}

Write-Host "`nListo." -ForegroundColor Green
Write-Host "Abre PHDjournal desde el menu Inicio. La primera vez te preguntara"
Write-Host "de que campo quieres que te traiga papers."
Write-Host ""
Write-Host "Para exportar a Zotero hace falta crear una vez, a mano, la coleccion"
Write-Host "destino que configures en la app (Configuracion, pestana Zotero):"
Write-Host "  clic derecho sobre tu biblioteca > Nueva coleccion"
