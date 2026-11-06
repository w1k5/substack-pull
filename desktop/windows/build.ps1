$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot/../..").Path
$build = Join-Path $PSScriptRoot '.build'
$venv = Join-Path $build 'venv'
New-Item -ItemType Directory -Force $build | Out-Null
py -3 -m venv $venv
$python = Join-Path $venv 'Scripts/python.exe'
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
    --self-contained true -o (Join-Path $build 'publish')
Copy-Item (Join-Path $build 'engine-dist/clearview-engine') `
    (Join-Path $build 'publish/engine') -Recurse -Force
$archive = Join-Path $build 'Clearview-Windows-beta.zip'
if (Test-Path $archive) { Remove-Item $archive }
Compress-Archive -Path (Join-Path $build 'publish/*') -DestinationPath $archive
Write-Host "Windows beta ready at $archive"
