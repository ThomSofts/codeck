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
cp "$ROOT/backend/server.py" "$ROOT/backend/mcp_db.py" "$APP/Contents/Resources/backend/"
rsync -a --exclude __pycache__ "$ROOT/backend/pilot" "$ROOT/backend/static" "$APP/Contents/Resources/backend/"
cp "$ROOT/macos/AppIcon.icns" "$APP/Contents/Resources/"
# build local (instala neste Mac): os plugins de banco vão junto do app. A release não embute — cada um instala pela
# tela o plugin que usar (baixado e conferido pelo SHA-256 assinado no latest.json).
if [ "${1:-}" != "--no-install" ]; then
  if command -v go >/dev/null || [ -x /opt/homebrew/bin/go ]; then
    bash "$ROOT/scripts/build-db-plugins.sh" macos "$APP/Contents/Resources/db-plugins" >/dev/null && echo "Plugins de banco embutidos"
  else
    echo "Sem o Go: o app sai sem os plugins de banco (instale pela tela ou: brew install go)"
  fi
fi
cp "$ROOT/macos/MenuIcon.png" "$ROOT/macos/MenuIcon@2x.png" "$ROOT/brand/splash.html" "$APP/Contents/Resources/"
# Sempre o mesmo certificado (scripts/macos-signing-cert.sh): o macOS prende as permissões (acesso a Documentos,
# modificar apps…) à identidade do app; com ad-hoc ela é o hash do binário e cada atualização perguntaria tudo de novo.
# O .p12 vem do Keychain para um keychain temporário já liberado para o codesign (sem a pergunta "quer usar a chave").
# Sem o certificado (build de outra pessoa), sai ad-hoc. O app não é notarizado de nenhum jeito.
P12="$(security find-generic-password -s codeck-codesign -a codeck -w 2>/dev/null || true)"
if [ -n "$P12" ]; then
  SKC="$(mktemp -d)/codeck-sign.keychain-db"; SKP="$(openssl rand -hex 16)"
  trap 'security delete-keychain "$SKC" 2>/dev/null; rm -rf "$(dirname "$SKC")"' EXIT
  security create-keychain -p "$SKP" "$SKC"
  security set-keychain-settings "$SKC"   # sem trancar sozinho no meio
  security unlock-keychain -p "$SKP" "$SKC"
  printf '%s' "$P12" | base64 -D > "$(dirname "$SKC")/c.p12"
  security import "$(dirname "$SKC")/c.p12" -k "$SKC" -P codeck -T /usr/bin/codesign >/dev/null
  rm -f "$(dirname "$SKC")/c.p12"
  security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$SKP" "$SKC" >/dev/null
  SIGN_SHA="$(security find-certificate -c "Codeck Code Signing" -Z "$SKC" | awk '/SHA-1/ {print $3; exit}')"
  codesign --force --deep --timestamp=none --keychain "$SKC" --sign "$SIGN_SHA" "$APP"
  echo "Assinado com o certificado Codeck Code Signing ($SIGN_SHA)"
else
  [ "${CODECK_REQUIRE_SIGNING:-}" = 1 ] && { echo "Sem o certificado que assina o app — rode scripts/macos-signing-cert.sh" >&2; exit 1; }
  codesign --force --deep --sign - "$APP" >/dev/null 2>&1
  echo "Assinatura ad-hoc (sem o certificado de scripts/macos-signing-cert.sh): o macOS pede as permissões de novo a cada build"
fi
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
