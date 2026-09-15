# Quita lo que instalar.ps1 puso en Windows.
#
# NO borra la base de datos, los PDFs descargados ni la configuracion: eso
# vive en data\ y se borra a mano si de verdad lo quieres.
#
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\desinstalar.ps1

$ErrorActionPreference = "Continue"

Write-Host "PHDjournal, desinstalacion" -ForegroundColor Cyan

$enlaces = @(
    (Join-Path ([Environment]::GetFolderPath("Programs")) "PHDjournal.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Startup"))  "PHDjournal.lnk")
)
foreach ($e in $enlaces) {
    if (Test-Path $e) {
        Remove-Item $e -Force
        Write-Host "  quitado: $e"
    }
}

foreach ($t in @("PHDjournal-manana", "PHDjournal-tarde")) {
    if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $t -Confirm:$false
        Write-Host "  tarea quitada: $t"
    }
}

Write-Host "`nListo. Tus datos siguen en data\ (base, PDFs, audio, configuracion)." -ForegroundColor Green
