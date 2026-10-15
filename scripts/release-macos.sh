#!/usr/bin/env bash
# O .dmg do Codeck para macOS, feito no Mac e publicado — o runner de macOS do GitHub conta dez vezes na cota
# gratuita, então o Mac sai daqui e só o Windows sai do Actions (.github/workflows/release-windows.yml).
#
#   scripts/release-macos.sh            gera e publica
#   scripts/release-macos.sh --dry-run  gera o .dmg; não publica
#   scripts/release-macos.sh --verify   não gera nada: confere a parte do Mac nos dois latest.json e corrige se
#                                       outra publicação (o Windows, no CI) a sobrescreveu
#
# Publica o que está na main (árvore limpa, commit já no origin/main), na versão do arquivo VERSION (x.y.z+N),
# a mesma do Windows. Destinos:
#   · site da ThomSoft: downloads/codeck/<dmg> + latest.json (o canal público que o app consulta)
#   · GitHub Releases (privado): tag v<x.y.z>-<N>, como histórico
# Credenciais do FTP do site — as mesmas do Chefinho/LuriSystem:
#   · servidor e usuário em ~/.config/thomsoft/downloads.env (DOWNLOADS_FTP_SERVER, DOWNLOADS_FTP_USER)
#   · a senha no Keychain (serviço thomsoft-downloads-ftp); nunca em arquivo nem na linha de comando.
set -euo pipefail

DRY_RUN=false
VERIFY=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --verify) VERIFY=true ;;
    *) echo "argumento desconhecido: $arg" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE_URL="${DOWNLOADS_BASE_URL:-https://thomsoft.com.br/downloads}"
CHANNEL=codeck
KEYCHAIN_SERVICE=thomsoft-downloads-ftp
CONFIG="$HOME/.config/thomsoft/downloads.env"

say() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(uname)" = Darwin ] || fail "Só no macOS."
# o openssl do sistema (LibreSSL) não tem "x509 -ext" e sai com erro no STARTTLS do FTP: usa o do Homebrew
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
openssl version | grep -q '^OpenSSL 3' || fail "Precisa do OpenSSL 3 (brew install openssl@3)."
for tool in jq lftp create-dmg openssl gh; do command -v "$tool" >/dev/null || fail "Falta o $tool (brew install $tool)."; done

cd "$ROOT"
line="$(sed -nE 's/^([0-9]+\.[0-9]+\.[0-9]+)\+([0-9]+)$/\1 \2/p' VERSION)"
[ -n "$line" ] || fail "VERSION precisa ser x.y.z+N"
read -r VERSION BUILD <<< "$line"
TAG="v$VERSION-$BUILD"
if [ "$DRY_RUN" = false ]; then
  [ -z "$(git status --porcelain)" ] || fail "Há mudanças não commitadas. Publique só o que está na main."
  git fetch -q origin main
  git merge-base --is-ancestor HEAD origin/main || fail "O commit atual não está no origin/main. Faça o push antes."
fi
say "Codeck $VERSION (build $BUILD) — $(git rev-parse --short HEAD)"

if [ "$DRY_RUN" = false ]; then
  [ -f "$CONFIG" ] || fail "Crie $CONFIG com DOWNLOADS_FTP_SERVER e DOWNLOADS_FTP_USER (ver o topo deste script)."
  # shellcheck source=/dev/null
  source "$CONFIG"
  : "${DOWNLOADS_FTP_SERVER:?falta em $CONFIG}" "${DOWNLOADS_FTP_USER:?falta em $CONFIG}"
  if ! LFTP_PASSWORD="$(security find-generic-password -s "$KEYCHAIN_SERVICE" -a "$DOWNLOADS_FTP_USER" -w 2>/dev/null)"; then
    say "Senha do FTP ($DOWNLOADS_FTP_USER) — fica guardada no Keychain"
    security add-generic-password -U -s "$KEYCHAIN_SERVICE" -a "$DOWNLOADS_FTP_USER" -l "ThomSoft — FTP dos downloads" -w
    LFTP_PASSWORD="$(security find-generic-password -s "$KEYCHAIN_SERVICE" -a "$DOWNLOADS_FTP_USER" -w)"
  fi
  export LFTP_PASSWORD
  # O servidor é um IP com certificado *.hstgr.io: a cadeia é conferida aqui e o lftp dispensa só o hostname.
  cert="$(mktemp)"
  openssl s_client -starttls ftp -connect "$DOWNLOADS_FTP_SERVER:21" -verify_return_error -verify 5 \
    </dev/null 2>/dev/null | openssl x509 > "$cert" || fail "Certificado do FTP não validou."
  openssl x509 -in "$cert" -noout -checkend 0 >/dev/null || fail "Certificado do FTP vencido."
  openssl x509 -in "$cert" -noout -ext subjectAltName | grep -q 'DNS:\*\.hstgr\.io' || fail "Certificado do FTP não é da Hostinger."
fi

lftp_run() {
  lftp -u "$DOWNLOADS_FTP_USER" --env-password "ftp://$DOWNLOADS_FTP_SERVER" -e "
    set ftp:ssl-force true;
    set ftp:ssl-protect-data true;
    set ssl:verify-certificate true;
    set ssl:check-hostname false;
    set ftp:passive-mode true;
    set net:max-retries 3;
    set net:timeout 30;
    set net:reconnect-interval-base 5;
    set cmd:fail-exit true;
    $1
    bye"
}

out="$ROOT/dist/release-macos"
dmg="$out/Codeck-$VERSION-$BUILD.dmg"

# Grava a parte do Mac no latest.json de um canal. O instalador JÁ deve estar no servidor: ler, ajustar e gravar
# acontecem em sequência, em segundos — a mesma ordem do CI do Windows, para um não apagar a parte do outro.
#   publish_json <canal> <arquivo no servidor> <productId> <notas>
publish_json() {
  local ch="$1" file="$2" pid="$3" notes="$4" cur="$out/$1-current.json" next="$out/$1-latest.json"
  rm -f "$cur"
  if lftp_run "cd /$ch; cls -1" 2>/dev/null | grep -qx 'latest.json'; then
    lftp_run "cd /$ch; lcd $out; get latest.json -o $(basename "$cur")" || fail "Não li o latest.json de $ch — nada foi enviado."
    jq -e 'type == "object"' "$cur" >/dev/null || fail "O latest.json de $ch não é JSON — nada foi enviado."
  else
    echo '{}' > "$cur"   # primeira publicação
  fi
  jq --arg url "$BASE_URL/$ch/$file" \
     --arg sha "$(shasum -a 256 "$dmg" | cut -d' ' -f1)" \
     --argjson size "$(stat -f %z "$dmg")" \
     --arg version "$VERSION" --argjson build "$BUILD" \
     --arg pid "$pid" --arg notes "$notes" \
     --arg date "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
     '.productId = $pid
      | .macos = {url: $url, sha256: $sha, size: $size, version: $version, build: $build}
      | .notes = $notes | .publishedAt = $date
      | ([.windows, .macos] | map(select(. != null)) | max_by(.build)) as $n
      | .version = $n.version | .build = $n.build' "$cur" > "$next"
  lftp_run "cd /$ch; lcd $out; put $(basename "$next") -o latest.json;"
}

# Pontes para quem ainda tem o app com um nome antigo: cada um lê o latest.json do próprio canal e só aceita
# instalador com o próprio prefixo. O mesmo .dmg vai para lá com esse nome; instalado, o app se renomeia para
# Codeck.app e adota a pasta de dados antiga. Podem sair quando ninguém mais estiver nos nomes antigos.
#   canal:prefixo do arquivo
LEGACY_CHANNELS="commitdeck:Commitdeck pr-pilot:PR-Pilot"
channel_file() {   # channel_file <canal> → nome do .dmg deste build naquele canal
  local ch="$1" pair
  [ "$ch" = "$CHANNEL" ] && { echo "Codeck-$VERSION-$BUILD.dmg"; return; }
  for pair in $LEGACY_CHANNELS; do
    if [ "${pair%%:*}" = "$ch" ]; then echo "${pair#*:}-$VERSION-$BUILD.dmg"; return 0; fi
  done
  return 1   # canal desconhecido: com set -e, para aqui
}
all_channels() { echo "$CHANNEL"; for pair in $LEGACY_CHANNELS; do echo "${pair%%:*}"; done; }
channel_notes() { [ "$1" = "$CHANNEL" ] || printf 'Agora se chama Codeck. '; git log -1 --format=%s; }

# Confere os canais e regrava a parte do Mac onde ela não for a deste build.
verify_channels() {
  local ok=true ch file got
  for ch in $(all_channels); do
    got="$(curl -fsS "$BASE_URL/$ch/latest.json?t=$(date +%s)" | jq -r '.macos.build // empty')"
    [ "$got" = "$BUILD" ] && continue
    ok=false
    file="$(channel_file "$ch")"
    curl -fsSI "$BASE_URL/$ch/$file" >/dev/null || fail "$ch: o $file não está no servidor — publique de novo."
    say "$ch servia o Mac no build ${got:-nenhum} — corrigindo para $BUILD"
    publish_json "$ch" "$file" "$ch" "$(channel_notes "$ch")"
  done
  $ok && echo "✓ $(all_channels | xargs | sed 's/ /, /g') servem o Mac no build $BUILD"
  return 0
}

if [ "$VERIFY" = true ]; then
  [ -f "$dmg" ] || fail "Não achei $dmg (o --verify usa o .dmg da última publicação deste build)."
  verify_channels
  exit 0
fi

say "Build"
bash scripts/build-macos.sh --no-install
rm -rf "$out"; mkdir -p "$out/stage"
cp -R "$ROOT/dist/Codeck.app" "$out/stage/"
ln -s /Applications "$out/stage/Aplicativos"
create-dmg --volname "Codeck" --volicon macos/AppIcon.icns \
  --window-pos 200 120 --window-size 600 380 --icon-size 104 --text-size 13 \
  --icon "Codeck.app" 160 180 --hide-extension "Codeck.app" --icon "Aplicativos" 440 180 \
  --no-internet-enable "$dmg" "$out/stage/" >/dev/null
echo "✓ $dmg ($(du -h "$dmg" | cut -f1))"

if [ "$DRY_RUN" = true ]; then say "Ensaio: o .dmg está em $out — nada foi publicado."; exit 0; fi

# O .dmg primeiro, o latest.json por último — só a parte do Mac; a do Windows fica como o CI a deixou.
say "Publicando no site"
name="$(basename "$dmg")"
lftp_run "mkdir -p -f /$CHANNEL; cd /$CHANNEL; put $dmg;"
publish_json "$CHANNEL" "$name" codeck "$(git log -1 --format=%s)"
old="$(lftp_run "cd /$CHANNEL; cls -1" | sed -nE 's/^Codeck-[0-9.]+-([0-9]+)\.dmg$/\1/p' | sort -un | awk '{a[NR]=$0} END {for (i = 1; i <= NR - 2; i++) print a[i]}')"
for b in $old; do lftp_run "cd /$CHANNEL; glob -a rm -f Codeck-*-$b.dmg;" || true; done
got="$(curl -fsS "$BASE_URL/$CHANNEL/latest.json?t=$(date +%s)" | jq -r .macos.build)"
[ "$got" = "$BUILD" ] || fail "O site ainda serve o build $got."
curl -fsSI "$BASE_URL/$CHANNEL/$name" >/dev/null || fail "O .dmg não responde no site."

for pair in $LEGACY_CHANNELS; do
  ch="${pair%%:*}" prefix="${pair#*:}"
  legacy="$out/$(channel_file "$ch")"
  cp "$dmg" "$legacy"
  say "Ponte no canal antigo ($ch)"
  lftp_run "mkdir -p -f /$ch; cd /$ch; put $legacy;"
  publish_json "$ch" "$(basename "$legacy")" "$ch" "$(channel_notes "$ch")"
  old="$(lftp_run "cd /$ch; cls -1" | sed -nE "s/^$prefix-[0-9.]+-([0-9]+)\.dmg$/\1/p" | sort -un | awk '{a[NR]=$0} END {for (i = 1; i <= NR - 2; i++) print a[i]}')"
  for b in $old; do lftp_run "cd /$ch; glob -a rm -f $prefix-*-$b.dmg;" || true; done
done

say "GitHub Releases ($TAG)"
gh release view "$TAG" >/dev/null 2>&1 || gh release create "$TAG" --title "Codeck $VERSION (build $BUILD)" \
  --notes "$(git log -1 --format=%B)" --target "$(git rev-parse HEAD)"
gh release upload "$TAG" "$dmg" --clobber
cp "$out/$CHANNEL-latest.json" "$out/latest.json" && gh release upload "$TAG" "$out/latest.json" --clobber

say "Conferindo os canais"
sleep 20
verify_channels
say "Publicado: $BASE_URL/$CHANNEL/latest.json"
