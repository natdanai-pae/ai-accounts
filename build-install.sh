#!/bin/bash
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
app_id="th.co.bda.ai-accounts"
destination="$HOME/Applications/AI Accounts.app"
desktop="$HOME/Desktop/AI Accounts.app"
package_only=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --package-only) package_only=true; shift ;;
    --destination) destination="$2"; shift 2 ;;
    *) echo 'Unknown argument' >&2; exit 2 ;;
  esac
done
if [[ -e "$destination" || -L "$destination" ]]; then
  if [[ -L "$destination" || ! -f "$destination/Contents/Info.plist" ]] || [[ "$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$destination/Contents/Info.plist" 2>/dev/null || true)" != "$app_id" ]]; then
    echo "Refusing to replace unrelated application: $destination" >&2
    exit 1
  fi
fi
if [[ "$package_only" == false ]] && [[ -e "$desktop" || -L "$desktop" ]]; then
  if [[ ! -L "$desktop" ]] || [[ "$(readlink "$desktop")" != "$destination" ]]; then
    echo "Refusing to replace unrelated Desktop item: $desktop" >&2
    exit 1
  fi
fi
build_dir="$(mktemp -d "${TMPDIR:-/tmp}/ai-accounts-build.XXXXXX")"
trap 'rm -rf -- "$build_dir"' EXIT
bundle="$build_dir/AI Accounts.app"
mkdir -p "$bundle/Contents/MacOS"
mkdir -p "$bundle/Contents/Resources"
cp "$source_dir/assets/AppIcon.png" "$bundle/Contents/Resources/AppIcon.png"
cp "$source_dir/assets/AppIcon.icns" "$bundle/Contents/Resources/AppIcon.icns"
# Keep assertions enabled in the installed self-test executable.
xcrun swiftc -Onone -target arm64-apple-macos14.0 -debug-prefix-map "$source_dir=/src" -framework AppKit "$source_dir/Main.swift" -o "$bundle/Contents/MacOS/AI Accounts"
"$bundle/Contents/MacOS/AI Accounts" --self-test
/usr/bin/plutil -create xml1 "$bundle/Contents/Info.plist"
/usr/bin/plutil -insert CFBundleIdentifier -string "$app_id" "$bundle/Contents/Info.plist"
/usr/bin/plutil -insert CFBundleName -string 'AI Accounts' "$bundle/Contents/Info.plist"
/usr/bin/plutil -insert CFBundleExecutable -string 'AI Accounts' "$bundle/Contents/Info.plist"
/usr/bin/plutil -insert CFBundlePackageType -string APPL "$bundle/Contents/Info.plist"
/usr/bin/plutil -insert CFBundleShortVersionString -string 0.3.0 "$bundle/Contents/Info.plist"
/usr/bin/plutil -insert CFBundleVersion -string 3 "$bundle/Contents/Info.plist"
/usr/bin/plutil -insert CFBundleIconFile -string AppIcon "$bundle/Contents/Info.plist"
/usr/bin/plutil -insert NSHighResolutionCapable -bool YES "$bundle/Contents/Info.plist"
/usr/bin/plutil -lint "$bundle/Contents/Info.plist"
/usr/bin/codesign --force --sign - "$bundle"
mkdir -p "$(dirname "$destination")"
if [[ "$package_only" == false ]]; then mkdir -p "$HOME/Desktop"; fi
backup=""
if [[ -d "$destination" ]]; then
  backup="${destination}.backup-$(date +%Y%m%d-%H%M%S)-$$"
  mv -- "$destination" "$backup"
fi
if ! mv -- "$bundle" "$destination"; then
  if [[ -n "$backup" ]]; then mv -- "$backup" "$destination"; fi
  exit 1
fi
if [[ "$package_only" == false && ! -L "$desktop" ]]; then ln -s "$destination" "$desktop"; fi
test -x "$destination/Contents/MacOS/AI Accounts"
if [[ "$package_only" == false ]]; then test "$(readlink "$desktop")" = "$destination"; fi
printf 'Installed: %s\nBundle ID: %s\n' "$destination" "$app_id"
if [[ -n "$backup" ]]; then printf 'Previous bundle retained: %s\n' "$backup"; fi
