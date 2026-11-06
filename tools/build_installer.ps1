# بناء حزمة التوزيع وملف التثبيت (Inno Setup 6)
# المتطلبات: dist\AMDH-HR\AMDH-HR.exe موجود (ناتج PyInstaller)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = "$env:LOCALAPPDATA\Python\bin\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
Set-Location $root

$version = "0.10.0"
$match = Select-String -Path "amdh_hr\config.py" -Pattern 'APP_VERSION\s*=\s*"([^"]+)"'
if ($match) { $version = $match.Matches[0].Groups[1].Value }

$dist = Join-Path $root "dist\AMDH-HR"
$exe = Join-Path $dist "AMDH-HR.exe"
if (-not (Test-Path $exe)) {
    throw "ابنِ النسخة التنفيذية أولاً: powershell -File tools\build_exe.ps1"
}
if (Test-Path (Join-Path $dist "data")) {
    throw "مجلد dist يحتوي data — أزل بيانات الاختبار قبل التوزيع."
}
$versionFile = Join-Path $dist "VERSION.txt"
if (Test-Path $versionFile) {
    $built = (Select-String -Path $versionFile -Pattern '^VERSION=(.+)$').Matches[0].Groups[1].Value
    if ($built -ne $version) {
        throw "نسخة dist ($built) لا تطابق المصدر ($version). أعد بناء EXE أولاً."
    }
}

Write-Host "حساب بصمات SHA-256..."
$lines = Get-ChildItem $dist -Recurse -File | Sort-Object FullName | ForEach-Object {
    $relative = $_.FullName.Substring($dist.Length + 1).Replace('\', '/')
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    "$hash  $relative"
}
$lines | Set-Content (Join-Path $dist "SHA256SUMS.txt") -Encoding utf8

$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = "C:\Program Files\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { throw "Inno Setup 6 غير مثبت." }

Write-Host "بناء المثبّت $version..."
& $iscc "/DMyAppVersion=$version" (Join-Path $root "installer\AMDH-HR.iss")
if ($LASTEXITCODE -ne 0) { throw "فشل بناء المثبّت." }

$setup = Join-Path $root "dist\installer\AMDH-HR_Setup_$version.exe"
if (-not (Test-Path $setup)) { throw "لم يُنتج ملف التثبيت." }
$setupHash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
Write-Host ""
Write-Host "المثبّت: $setup"
Write-Host "SHA-256: $setupHash"
Write-Host "البصمات: $dist\SHA256SUMS.txt"
