$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot
$build = Join-Path ([System.IO.Path]::GetTempPath()) ('ai-accounts-build-' + [guid]::NewGuid())
$dist = Join-Path $source 'dist'
New-Item -ItemType Directory -Force $build, $dist | Out-Null
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "Build command failed: $LASTEXITCODE" } }
python -m unittest discover -s $source -p 'tests_*.py'
Check-Exit
python -m PyInstaller --noconfirm --onedir --name aiaccounts-helper --paths "$source/vendor/claude-switcher" --hidden-import windows_backend --hidden-import windows_usage --hidden-import claude_switch --hidden-import cs_config --hidden-import cs_sync --hidden-import cs_share --collect-all cryptography --distpath "$build/frozen" --workpath "$build/helper-work" --specpath $build "$source/backend.py"
Check-Exit
python -m PyInstaller --noconfirm --onedir --windowed --name 'AI Accounts' --hidden-import backend --distpath "$build/frozen" --workpath "$build/gui-work" --specpath $build "$source/windows_gui.py"
Check-Exit
$payload = Join-Path $build 'frozen/AI Accounts'
Copy-Item -Recurse "$build/frozen/aiaccounts-helper" "$payload/backend"
New-Item -ItemType Directory -Force "$payload/bin", "$payload/licenses", "$payload/assets" | Out-Null
Copy-Item "$source/assets/AppIcon.png" "$payload/assets/"
Invoke-WebRequest 'https://codeload.github.com/ScWen7/CodexSwitch/tar.gz/65469fc42160ae89a16c8829dd9babe2950d569e' -OutFile "$build/switch.tar.gz"
New-Item -ItemType Directory "$build/switch" | Out-Null
tar -xzf "$build/switch.tar.gz" --strip-components=1 -C "$build/switch"
Check-Exit
Push-Location "$build/switch"
try { go build -trimpath -ldflags='-s -w' -o "$payload/bin/codex-switch.exe" ./cmd/codex-switch; Check-Exit } finally { Pop-Location }
$release = Invoke-RestMethod 'https://api.github.com/repos/openai/codex/releases/tags/rust-v0.167.0'
$asset = $release.assets | Where-Object { $_.name -eq 'codex-x86_64-pc-windows-msvc.exe' }
if (-not $asset -or $asset.browser_download_url -ne 'https://github.com/openai/codex/releases/download/rust-v0.167.0/codex-x86_64-pc-windows-msvc.exe') { throw 'Expected official Codex asset missing' }
Invoke-WebRequest $asset.browser_download_url -OutFile "$payload/bin/codex.exe"
if (-not $asset.digest -or ('sha256:' + (Get-FileHash "$payload/bin/codex.exe" -Algorithm SHA256).Hash.ToLower()) -ne $asset.digest) { throw 'Codex release checksum mismatch' }
Copy-Item "$build/switch/LICENSE" "$payload/licenses/codex-switch-MIT.txt"
Copy-Item "$source/vendor/claude-switcher/LICENSE" "$payload/licenses/claude-switcher-MIT.txt"
Copy-Item "$source/vendor/licenses/*" "$payload/licenses/"
Copy-Item "$source/THIRD-PARTY-NOTICES.md", "$source/README-TH.md" $payload
& "$payload/backend/aiaccounts-helper.exe" --self-test
Check-Exit
$smoke = Start-Process -FilePath "$payload/AI Accounts.exe" -ArgumentList '--self-test' -Wait -PassThru
if ($smoke.ExitCode -ne 0) { throw 'Windows GUI smoke failed' }
Get-ChildItem -Recurse -File $payload | ForEach-Object { (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower() + '  ' + $_.FullName.Substring($payload.Length + 1) } | Set-Content "$payload/DEPENDENCY-SHA256SUMS" -Encoding utf8
$zip = Join-Path $dist 'AI-Accounts-0.3.0-windows-x64.zip'
Compress-Archive -Path $payload -DestinationPath $zip -Force
((Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() + '  ' + (Split-Path $zip -Leaf)) | Set-Content "$dist/SHA256SUMS-windows" -Encoding ascii
Write-Output "Built $zip; unsigned beta. Build workspace retained: $build"
