# Перевод исходного PDF из pdf_files/ в Results/output_zh.pdf
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$pdf = Get-ChildItem -Path (Join-Path $root "pdf_files") -Filter "*.pdf" -File -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $pdf) {
    Write-Error "В pdf_files/ нет PDF. Положите туда исходник (например референс-лист)."
}
$out = Join-Path $root "Results\output_zh.pdf"
New-Item -ItemType Directory -Path (Split-Path $out) -Force | Out-Null

Write-Host "Вход:  $($pdf.FullName)"
Write-Host "Выход: $out"
python -m pdf_translate.cli --in $pdf.FullName --out $out
exit $LASTEXITCODE
