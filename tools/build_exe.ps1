# بناء نسخة تنفيذية (onedir) وحزمة توزيع بلا قاعدة بيانات
$ErrorActionPreference = "Stop"
$py = "$env:LOCALAPPDATA\Python\bin\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$version = "0.4.0"
if (Test-Path "amdh_hr\config.py") {
    $match = Select-String -Path "amdh_hr\config.py" -Pattern 'APP_VERSION\s*=\s*"([^"]+)"'
    if ($match) { $version = $match.Matches[0].Groups[1].Value }
}

Write-Host "تشغيل الاختبارات..."
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "الاختبارات فشلت — أُوقف البناء." }

Write-Host "بناء AMDH-HR $version..."
& $py -m PyInstaller AMDH-HR.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "فشل البناء." }

$dist = Join-Path $root "dist\AMDH-HR"
New-Item -ItemType Directory -Force (Join-Path $dist "docs") | Out-Null
Copy-Item "README.md" $dist -Force
Copy-Item "docs\دليل_التشغيل.md" (Join-Path $dist "docs") -Force
Copy-Item "docs\محضر_الاستلام.md" (Join-Path $dist "docs") -Force
Copy-Item "docs\ADR-001-architecture.md" (Join-Path $dist "docs") -Force
@(
    "APP=نظام السجل الوظيفي والعلاوات والترفيعات"
    "VERSION=$version"
    "RELEASE=2026-10"
    "SCHEMA=3"
) | Set-Content (Join-Path $dist "VERSION.txt") -Encoding utf8

$zip = Join-Path $root "dist\AMDH-HR_$version.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $dist "*") -DestinationPath $zip -CompressionLevel Optimal

Write-Host ""
Write-Host "الناتج: dist\AMDH-HR\AMDH-HR.exe"
Write-Host "الحزمة: dist\AMDH-HR_$version.zip"
Write-Host "لا تنسخ مجلد data إلى التوزيع؛ يُنشأ عند أول تشغيل."
