$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot/../..").Path
$build = Join-Path $PSScriptRoot '.build'
$venv = Join-Path $build 'venv'
New-Item -ItemType Directory -Force $build | Out-Null
py -3 -m venv $venv
$python = Join-Path $venv 'Scripts/python.exe'
& $python (Join-Path $root 'desktop/release_metadata.py')
if ($LASTEXITCODE -ne 0) { throw 'Invalid Clearview release metadata.' }
$release = Get-Content (Join-Path $root 'desktop/release.json') -Raw | ConvertFrom-Json
$fileVersion = "$(($release.version -split '-', 2)[0]).$($release.build)"
& $python -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11 or newer is required'"
& $python -m pip install --disable-pip-version-check pyinstaller tzdata tzlocal
& $python -m pip install --disable-pip-version-check -r (Join-Path $root 'requirements-analytics-mcp.txt')
Push-Location $root
try {
    & $python -m PyInstaller --noconfirm --clean --onedir --name clearview-engine `
        --distpath (Join-Path $build 'engine-dist') --workpath (Join-Path $build 'py-work') `
        --specpath $build --paths $root --collect-data tzdata --hidden-import tzlocal `
        --hidden-import substack_local.mcp.server --collect-submodules mcp `
        --add-data 'substack_local/dashboard/static;substack_local/dashboard/static' `
        'substack_local/desktop/entry.py'
} finally { Pop-Location }
dotnet publish (Join-Path $PSScriptRoot 'Clearview.Windows.csproj') -c Release -r win-x64 `
    --self-contained true -o (Join-Path $build 'publish') `
    "-p:Version=$($release.version)" "-p:FileVersion=$fileVersion" `
    "-p:IncludeSourceRevisionInInformationalVersion=false"
if ($LASTEXITCODE -ne 0) { throw 'Clearview Windows publish failed.' }
$assembly = Join-Path $build 'publish/Clearview.Windows.dll'
$builtVersion = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($assembly)
if ($builtVersion.ProductVersion -cne $release.version -or $builtVersion.FileVersion -cne $fileVersion) {
    throw 'Published Clearview version does not match desktop/release.json.'
}
Copy-Item (Join-Path $build 'engine-dist/clearview-engine') `
    (Join-Path $build 'publish/engine') -Recurse -Force
$archive = Join-Path $build "Clearview-$($release.version)-windows-x64.zip"
if (Test-Path $archive) { Remove-Item $archive }
Compress-Archive -Path (Join-Path $build 'publish/*') -DestinationPath $archive
Write-Host "Windows beta ready at $archive"
