#!/usr/bin/env bash
set -euo pipefail

OWNER="${OWNER:-<OWNER>}"
REPO="${REPO:-<REPO>}"

arch="$(uname -m)"
case "$arch" in
  arm64)  suffix="darwin-arm64" ;;
  x86_64) suffix="darwin-x64" ;;
  *) echo "Unsupported arch: $arch" >&2; exit 1 ;;
esac

asset="KucoinStatusBar-${suffix}.dmg"
url="https://github.com/${OWNER}/${REPO}/releases/latest/download/${asset}"

echo "Detected arch: ${arch} -> ${suffix}"
echo "Downloading: ${url}"

tmpd="$(mktemp -d)"
cd "$tmpd"
curl -fL --retry 3 -o "$asset" "$url"

echo "Mounting DMG..."
hdiutil attach "$asset" -nobrowse -quiet
vol="/Volumes/KucoinStatusBar"

echo "Copying app to /Applications..."
cp -R "${vol}/KucoinStatusBar.app" /Applications/

echo "Detaching..."
hdiutil detach "${vol}" -quiet || true

echo "Installed: /Applications/KucoinStatusBar.app"