[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$SdkRoot = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
$BuildTools = Join-Path $SdkRoot 'build-tools\35.0.0'
$AndroidJar = Join-Path $SdkRoot 'platforms\android-35\android.jar'
$BuildRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot 'build'))
$DistRoot = Join-Path $ProjectRoot 'dist'

foreach ($Required in @(
    (Join-Path $BuildTools 'aapt2.exe'),
    (Join-Path $BuildTools 'd8.bat'),
    (Join-Path $BuildTools 'zipalign.exe'),
    (Join-Path $BuildTools 'apksigner.bat'),
    $AndroidJar,
    (Join-Path $env:JAVA_HOME 'bin\javac.exe'),
    (Join-Path $env:JAVA_HOME 'bin\jar.exe'),
    (Join-Path $env:JAVA_HOME 'bin\keytool.exe')
)) {
    if (-not (Test-Path -LiteralPath $Required)) {
        throw "Required build tool not found: $Required"
    }
}

if (-not $BuildRoot.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe build path: $BuildRoot"
}
if (Test-Path -LiteralPath $BuildRoot) {
    Remove-Item -LiteralPath $BuildRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $BuildRoot, $DistRoot -Force | Out-Null
$Classes = New-Item -ItemType Directory -Path (Join-Path $BuildRoot 'classes')
$Dex = New-Item -ItemType Directory -Path (Join-Path $BuildRoot 'dex')
$CompiledResources = New-Item -ItemType Directory -Path (Join-Path $BuildRoot 'compiled-resources')

$Aapt2 = Join-Path $BuildTools 'aapt2.exe'
$BaseApk = Join-Path $BuildRoot 'base.apk'
& $Aapt2 compile --dir (Join-Path $ProjectRoot 'res') -o $CompiledResources.FullName
if ($LASTEXITCODE -ne 0) { throw 'aapt2 resource compile failed' }
$ResourceFiles = @(Get-ChildItem -LiteralPath $CompiledResources.FullName -Filter '*.flat' |
    ForEach-Object { $_.FullName })
$AssetArgs = @()
if (Test-Path -LiteralPath (Join-Path $ProjectRoot 'assets')) {
    $AssetArgs = @('-A', (Join-Path $ProjectRoot 'assets'))
}
& $Aapt2 link `
    -o $BaseApk `
    -I $AndroidJar `
    --manifest (Join-Path $ProjectRoot 'AndroidManifest.xml') `
    --min-sdk-version 26 `
    --target-sdk-version 35 `
    --version-code 120 `
    --version-name '1.2.0' `
    $AssetArgs `
    $ResourceFiles
if ($LASTEXITCODE -ne 0) { throw 'aapt2 link failed' }

$Sources = @(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'src\com\labcapsule\remote') `
    -Filter '*.java' | ForEach-Object { $_.FullName })
& (Join-Path $env:JAVA_HOME 'bin\javac.exe') `
    -encoding UTF-8 `
    --release 8 `
    -classpath $AndroidJar `
    -d $Classes.FullName `
    $Sources
if ($LASTEXITCODE -ne 0) { throw 'javac failed' }

$ClassesJar = Join-Path $BuildRoot 'classes.jar'
& (Join-Path $env:JAVA_HOME 'bin\jar.exe') cf $ClassesJar -C $Classes.FullName .
if ($LASTEXITCODE -ne 0) { throw 'jar failed' }

& (Join-Path $BuildTools 'd8.bat') `
    --min-api 26 `
    --lib $AndroidJar `
    --output $Dex.FullName `
    $ClassesJar
if ($LASTEXITCODE -ne 0) { throw 'd8 failed' }

& (Join-Path $env:JAVA_HOME 'bin\jar.exe') uf $BaseApk -C $Dex.FullName 'classes.dex'
if ($LASTEXITCODE -ne 0) { throw 'Adding classes.dex to APK failed' }

$AlignedApk = Join-Path $BuildRoot 'aligned.apk'
& (Join-Path $BuildTools 'zipalign.exe') -f -p 4 $BaseApk $AlignedApk
if ($LASTEXITCODE -ne 0) { throw 'zipalign failed' }

$KeyStore = Join-Path $ProjectRoot 'labcapsule-dev.jks'
if (-not (Test-Path -LiteralPath $KeyStore)) {
    & (Join-Path $env:JAVA_HOME 'bin\keytool.exe') `
        -genkeypair `
        -keystore $KeyStore `
        -storepass labcapsule `
        -keypass labcapsule `
        -alias labcapsule `
        -keyalg RSA `
        -keysize 2048 `
        -validity 10000 `
        -dname 'CN=LabCapsule Development,O=LabCapsule,C=CN' `
        -noprompt | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'keytool failed' }
}

$OutputApk = Join-Path $DistRoot 'LabCapsule-1.2.0.apk'
& (Join-Path $BuildTools 'apksigner.bat') sign `
    --ks $KeyStore `
    --ks-pass 'pass:labcapsule' `
    --key-pass 'pass:labcapsule' `
    --out $OutputApk `
    $AlignedApk
if ($LASTEXITCODE -ne 0) { throw 'apksigner failed' }

& (Join-Path $BuildTools 'apksigner.bat') verify --verbose $OutputApk
if ($LASTEXITCODE -ne 0) { throw 'APK verification failed' }

Write-Output "APK=$OutputApk"
