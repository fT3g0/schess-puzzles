param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root "web"
$docs = Join-Path $root "docs"

if (-not (Test-Path $web)) {
    throw "web directory not found: $web"
}

if (Test-Path $docs) {
    Remove-Item -Recurse -Force $docs
}
Copy-Item -Recurse -Path $web -Destination $docs
Set-Content -Path (Join-Path $docs "CNAME") -Value "www.schesspuzzles.com" -Encoding ASCII
Set-Content -Path (Join-Path $docs ".nojekyll") -Value "" -Encoding ASCII
Write-Host "Copied web/ to docs/ for GitHub Pages."
