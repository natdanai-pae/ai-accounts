#!/bin/bash
set -euo pipefail
[[ "$(uname -m)" == arm64 ]] || { echo 'This package targets macOS Apple Silicon; use an arm64 builder.' >&2; exit 1; }
source_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
release_dir="${1:-$source_dir/dist}"
build_dir="$(mktemp -d /tmp/ai-accounts-release.XXXXXX)"
trap 'rm -rf -- "$build_dir"' EXIT
mkdir -p "$release_dir"
release_dir="$(cd "$release_dir" && pwd)"
python_bin="${AI_ACCOUNTS_BUILD_PYTHON:-/tmp/ai-accounts-build-env/bin/python}"
if [[ ! -x "$python_bin" ]]; then
  uv venv --python 3.12.14 "$build_dir/venv"
  python_bin="$build_dir/venv/bin/python"
  uv pip install --python "$python_bin" pyinstaller==6.22.3 cryptography==50.0.2
fi
"$python_bin" "$source_dir/tests_backend.py"
"$python_bin" "$source_dir/tests_macos_launcher.py"
mkdir -p "$build_dir/src" "$build_dir/payload"
cp "$source_dir/backend.py" "$build_dir/src/backend.py"
cp "$source_dir/ai_advisor.py" "$build_dir/src/ai_advisor.py"
cp "$source_dir/macos_codex.py" "$build_dir/src/macos_codex.py"
cp "$source_dir/mcp_server.py" "$build_dir/src/mcp_server.py"
cp -R "$source_dir/vendor" "$build_dir/src/vendor"
"$python_bin" -m PyInstaller --noconfirm --onedir --name aiaccounts-helper --paths "$build_dir/src/vendor/claude-switcher" --hidden-import claude_switch --hidden-import cs_config --hidden-import cs_sync --hidden-import cs_share --distpath "$build_dir/frozen" --workpath "$build_dir/work" --specpath "$build_dir" "$build_dir/src/backend.py"
bash "$source_dir/build-install.sh" --package-only --destination "$build_dir/payload/AI Accounts.app"
resources="$build_dir/payload/AI Accounts.app/Contents/Resources"
cp -R "$build_dir/frozen/aiaccounts-helper" "$resources/backend"
cp -R "$source_dir/skills" "$resources/skills"
mkdir -p "$resources/bin" "$resources/codexbar" "$resources/licenses"
switch_source="${AI_ACCOUNTS_SWITCH_SOURCE:-$HOME/.local/share/codex-switch-source}"
if [[ ! -f "$switch_source/go.mod" ]]; then
  mkdir "$build_dir/codex-switch-source"
  curl -fsSL https://codeload.github.com/ScWen7/CodexSwitch/tar.gz/65469fc42160ae89a16c8829dd9babe2950d569e -o "$build_dir/switch.tar.gz"
  tar -xzf "$build_dir/switch.tar.gz" --strip-components=1 -C "$build_dir/codex-switch-source"
  switch_source="$build_dir/codex-switch-source"
fi
(cd "$switch_source" && go build -trimpath -ldflags='-s -w' -o "$resources/bin/codex-switch" ./cmd/codex-switch)
if command -v codex >/dev/null && [[ "$(codex --version)" == 'codex-cli 0.157.1' ]]; then
  cp -L "$(command -v codex)" "$resources/bin/codex"
else
  curl -fsSL https://github.com/openai/codex/releases/download/rust-v0.157.1/codex-aarch64-apple-darwin.tar.gz -o "$build_dir/codex.tar.gz"
  mkdir "$build_dir/codex-cli"
  tar -xzf "$build_dir/codex.tar.gz" -C "$build_dir/codex-cli"
  cp "$build_dir/codex-cli/codex-aarch64-apple-darwin" "$resources/bin/codex"
fi
local_codexbar_version="$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' /Applications/CodexBar.app/Contents/Info.plist 2>/dev/null || true)"
if [[ -x /Applications/CodexBar.app/Contents/Helpers/CodexBarCLI && "$local_codexbar_version" == 0.84.0 ]]; then
  cp -R /Applications/CodexBar.app/Contents/Helpers "$resources/codexbar/Helpers"
else
  curl -fsSL https://github.com/steipete/CodexBar/releases/download/v0.84.0/CodexBarCLI-v0.84.0-macos-arm64.tar.gz -o "$build_dir/CodexBarCLI.tar.gz"
  curl -fsSL https://github.com/steipete/CodexBar/releases/download/v0.84.0/CodexBarCLI-v0.84.0-macos-arm64.tar.gz.sha256 -o "$build_dir/CodexBarCLI.sha256"
  expected="$(awk '{print $1}' "$build_dir/CodexBarCLI.sha256")"
  actual="$(shasum -a 256 "$build_dir/CodexBarCLI.tar.gz" | awk '{print $1}')"
  [[ "$expected" == "$actual" ]] || { echo 'CodexBar checksum mismatch' >&2; exit 1; }
  mkdir "$resources/codexbar/Helpers"
  tar -xzf "$build_dir/CodexBarCLI.tar.gz" -C "$resources/codexbar/Helpers"
fi
cp "$source_dir/vendor/claude-switcher/LICENSE" "$resources/licenses/claude-switcher-MIT.txt"
cp "$switch_source/LICENSE" "$resources/licenses/codex-switch-MIT.txt"
cp "$source_dir/vendor/licenses/"* "$resources/licenses/"
cp "$source_dir/THIRD-PARTY-NOTICES.md" "$resources/"
cp "$source_dir/README-TH.md" "$build_dir/payload/README-TH.md"
cp "$source_dir/docs/manual/AI-Accounts-User-Guide-BDA-TH.pdf" "$build_dir/payload/AI-Accounts-User-Guide-BDA-TH.pdf"
"$resources/codexbar/Helpers/CodexBarCLI" --version
"$resources/bin/codex" --version
"$resources/bin/codex-switch" version --json
"$resources/backend/aiaccounts-helper" --self-test
/usr/bin/codesign --force --deep --sign - "$build_dir/payload/AI Accounts.app"
/usr/bin/codesign --verify --deep --strict "$build_dir/payload/AI Accounts.app"
find "$resources" -type f -exec shasum -a 256 {} + | sed "s|$resources/||" > "$build_dir/payload/DEPENDENCY-SHA256SUMS"
ln -s /Applications "$build_dir/payload/Applications"
/usr/bin/ditto -c -k --sequesterRsrc "$build_dir/payload" "$release_dir/AI-Accounts-0.3.0-macos-arm64.zip"
/usr/bin/hdiutil create -volname 'AI Accounts 0.3.0 Beta' -srcfolder "$build_dir/payload" -ov -format UDZO "$release_dir/AI-Accounts-0.3.0-macos-arm64.dmg"
(cd "$release_dir" && shasum -a 256 AI-Accounts-0.3.0-macos-arm64.zip AI-Accounts-0.3.0-macos-arm64.dmg > SHA256SUMS)
cp "$build_dir/payload/DEPENDENCY-SHA256SUMS" "$release_dir/"
cp "$source_dir/README-TH.md" "$release_dir/"
printf 'Local beta artifacts: %s\n' "$release_dir"
