#!/usr/bin/env bash
# Compila os plugins de banco (db/, Go puro — sem C) para um sistema.
#   scripts/build-db-plugins.sh macos <pasta>            universal (Apple Silicon + Intel), nomes codeck-db-<banco>
#   scripts/build-db-plugins.sh windows <pasta>          x64, nomes codeck-db-<banco>.exe
#   scripts/build-db-plugins.sh <sistema> <pasta> <sufixo>   nomes da release: codeck-db-<banco>-<sufixo>[.exe]
# Precisa do Go (brew install go / actions/setup-go). A versão do app vai dentro do plugin (o "hello" a devolve).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OS="${1:?macos ou windows}" OUT="${2:?pasta de saída}" SUFFIX="${3:-}"
VERSION="$(sed -nE 's/^([0-9]+\.[0-9]+\.[0-9]+)\+([0-9]+)$/\1+\2/p' "$ROOT/VERSION")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH" CGO_ENABLED=0
command -v go >/dev/null || { echo "Falta o Go (brew install go)" >&2; exit 1; }
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
FLAGS=(-trimpath -ldflags "-s -w -X codeck/db/internal/engine.PluginVersion=$VERSION")
cd "$ROOT/db"
for bin in $(ls cmd); do
  name="codeck-db-$bin${SUFFIX:+-$SUFFIX}"
  case "$OS" in
    macos)
      tmp="$(mktemp -d)"
      GOOS=darwin GOARCH=arm64 go build "${FLAGS[@]}" -o "$tmp/arm64" "./cmd/$bin"
      GOOS=darwin GOARCH=amd64 go build "${FLAGS[@]}" -o "$tmp/amd64" "./cmd/$bin"
      lipo -create "$tmp/arm64" "$tmp/amd64" -output "$OUT/$name"
      rm -rf "$tmp"
      codesign --force --sign - "$OUT/$name" >/dev/null 2>&1 || true   # ad-hoc: o arm64 exige assinatura
      ;;
    windows)
      GOOS=windows GOARCH=amd64 go build "${FLAGS[@]}" -o "$OUT/$name.exe" "./cmd/$bin"
      ;;
    *) echo "sistema desconhecido: $OS" >&2; exit 2 ;;
  esac
  echo "✓ $name"
done
