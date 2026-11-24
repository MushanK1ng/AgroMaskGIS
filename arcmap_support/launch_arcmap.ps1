[CmdletBinding()]
param([Parameter(Mandatory)][string]$CaseFolder, [switch]$PrepareOnly)

$ErrorActionPreference = 'Stop'
$case = Get-Item -LiteralPath $CaseFolder
$inputs = Get-ChildItem -LiteralPath $case.FullName -Directory -Filter '01_*' | Select-Object -First 1
$products = Get-ChildItem -LiteralPath $case.FullName -Directory -Filter '02_*' | Select-Object -First 1
if (-not ($inputs -and $products)) { throw 'The input and results folders must stay with the ArcMap launcher.' }

$registryPath = 'HKLM:\SOFTWARE\WOW6432Node\ESRI\Desktop10.8'
$installation = (Get-ItemProperty -Path $registryPath -Name InstallDir -ErrorAction SilentlyContinue).InstallDir
if (-not $installation) { $installation = Join-Path ${env:ProgramFiles(x86)} 'ArcGIS\Desktop10.8' }
$arcmap = Join-Path $installation 'bin\ArcMap.exe'
if (-not (Test-Path -LiteralPath $arcmap -PathType Leaf)) { throw 'ArcMap 10.8 was not found on this computer.' }

$mapFolder = Join-Path $case.FullName 'ArcMapView'
$document = Join-Path $mapFolder 'Iowa_Crops_2023_ArcMap.mxd'
if (-not (Test-Path -LiteralPath $document -PathType Leaf)) {
    $pythonRoot = Join-Path $env:SystemDrive 'Python27\ArcGIS10.8'
    $python = Join-Path $pythonRoot 'python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'ArcMap Python 2.7 was not found.' }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $numpy = Join-Path $PSScriptRoot 'py27'
    if (-not (Test-Path -LiteralPath (Join-Path $numpy 'numpy\__init__.py') -PathType Leaf)) {
        $wheel = Join-Path $PSScriptRoot 'numpy-1.16.6-cp27-cp27m-win32.whl'
        [IO.Compression.ZipFile]::ExtractToDirectory($wheel, $numpy)
    }

    New-Item -ItemType Directory -Path $mapFolder -Force | Out-Null
    $zip = [IO.Compression.ZipFile]::OpenRead((Join-Path $PSScriptRoot 'arcmap-layers.zip'))
    try {
        $names = @('aerial_display.tif', 'crop_display.tif')
        foreach ($crop in @('corn', 'soybeans')) {
            foreach ($extension in @('shp', 'shx', 'dbf', 'prj', 'cpg')) { $names += "$crop.$extension" }
        }
        foreach ($name in $names) {
            $entry = $zip.GetEntry($name)
            if (-not $entry) { throw "Missing $name in arcmap-layers.zip." }
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $mapFolder $name), $true)
        }
    } finally { $zip.Dispose() }

    $env:PYTHONPATH = $numpy
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:Path = (Join-Path $pythonRoot 'DLLs') + ';' + (Join-Path $installation 'bin') + ';' + $env:Path
    $env:AGROMASK_MAP_FOLDER = $mapFolder
    $env:AGROMASK_ARCMAP_INSTALL = $installation
    Write-Host 'Preparing the ArcMap document on first launch...'
    & $python -u (Join-Path $PSScriptRoot 'build_map.py')
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $document -PathType Leaf)) {
        throw 'ArcPy could not prepare the map. Check the ArcMap desktop license and the message above.'
    }
}

Write-Host $document
if (-not $PrepareOnly) {
    Start-Process -FilePath $arcmap -ArgumentList ('"{0}"' -f $document) -WorkingDirectory (Split-Path -Parent $arcmap) -WindowStyle Normal
}
