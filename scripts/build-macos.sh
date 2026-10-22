#!/usr/bin/env bash
# Gera o "Codeck.app" (universal: Apple Silicon + Intel, macOS 13+).
#   scripts/build-macos.sh               gera em dist/ e instala em /Applications (ou ~/Applications)
#   scripts/build-macos.sh --no-install  só gera em dist/
# Precisa das Command Line Tools (xcode-select --install): trazem o swiftc e o python3 que o app usa.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/dist/Codeck.app"
line="$(sed -nE 's/^([0-9]+\.[0-9]+\.[0-9]+)\+([0-9]+)$/\1 \2/p' "$ROOT/VERSION")"
[ -n "$line" ] || { echo "VERSION precisa ser x.y.z+N" >&2; exit 1; }
read -r VERSION BUILD <<< "$line"

# interface (Svelte) → backend/static
if [ "${SKIP_UI:-}" != 1 ]; then
  echo "Compilando a interface…"
  (cd "$ROOT/ui" && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npm run build --silent)
fi
[ -f "$ROOT/backend/static/index.html" ] || { echo "backend/static vazio — rode sem SKIP_UI=1" >&2; exit 1; }

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/backend"
echo "Compilando $VERSION ($BUILD)…"
tmp="$(mktemp -d)"
for arch in arm64 x86_64; do
  swiftc -O -swift-version 5 -target "$arch-apple-macos13.0" \
    -framework Cocoa -framework WebKit -framework ServiceManagement -framework UserNotifications \
    "$ROOT/macos/Codeck.swift" -o "$tmp/Codeck-$arch"
done
lipo -create "$tmp/Codeck-arm64" "$tmp/Codeck-x86_64" -output "$APP/Contents/MacOS/Codeck"
rm -rf "$tmp"
sed -e "s/__VERSION__/$VERSION/" -e "s/__BUILD__/$BUILD/" "$ROOT/macos/Info.plist" > "$APP/Contents/Info.plist"
cp "$ROOT/backend/server.py" "$APP/Contents/Resources/backend/"
rsync -a --exclude __pycache__ "$ROOT/backend/pilot" "$ROOT/backend/static" "$APP/Contents/Resources/backend/"
cp "$ROOT/macos/AppIcon.icns" "$APP/Contents/Resources/"
cp "$ROOT/macos/MenuIcon.png" "$ROOT/macos/MenuIcon@2x.png" "$ROOT/brand/splash.html" "$APP/Contents/Resources/"
codesign --force --deep --sign - "$APP" >/dev/null 2>&1   # assinatura ad-hoc (o app não é notarizado)
codesign --verify --deep --strict "$APP"
echo "Gerado: $APP"

[ "${1:-}" = "--no-install" ] && exit 0

# versões antigas rodavam como serviço do launchd; o app assume
for label in dev.prpilot com.thomaz.prpilot; do
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
done
DEST="/Applications"; [ -w "$DEST" ] || DEST="$HOME/Applications"
mkdir -p "$DEST"
osascript -e 'tell application "Codeck" to quit' >/dev/null 2>&1 || true
for n in Commitdeck "PR Pilot"; do   # nomes antigos
  osascript -e "tell application \"$n\" to quit" >/dev/null 2>&1 || true
done
sleep 1
rm -rf "$DEST/Commitdeck.app" "$DEST/PR Pilot.app"
sleep 2
rm -rf "$DEST/Codeck.app"
ditto "$APP" "$DEST/Codeck.app"
echo "Instalado em $DEST/Codeck.app"
open "$DEST/Codeck.app"
