#!/usr/bin/env bash
# Torna obrigatória a atualização para quem está abaixo do build N (mesma ideia do /forcar-versao da ThomSoft).
# Só use depois que o build N estiver publicado nas DUAS plataformas — senão você tranca quem não tem para onde ir.
#   scripts/set-required.sh 7     → quem está no build < 7 vê a tela de atualização obrigatória
#   scripts/set-required.sh 0     → tira a obrigatoriedade
# O latest.json vai assinado (o app recusa o que não confere): a chave vem do Keychain (codeck-update-signing).
set -euo pipefail
export PATH="/opt/homebrew/bin:$PATH"
N="${1:?uso: set-required.sh <build>}"
CONFIG="$HOME/.config/thomsoft/downloads.env"
# shellcheck source=/dev/null
source "$CONFIG"
LFTP_PASSWORD="$(security find-generic-password -s thomsoft-downloads-ftp -a "$DOWNLOADS_FTP_USER" -w)"; export LFTP_PASSWORD
run() { lftp -u "$DOWNLOADS_FTP_USER" --env-password "ftp://$DOWNLOADS_FTP_SERVER" -e "set ftp:ssl-force true; set ftp:ssl-protect-data true; set ssl:verify-certificate true; set ssl:check-hostname false; set net:max-retries 3; set cmd:fail-exit true; $1 bye"; }
tmp="$(mktemp -d)"
run "cd /codeck; lcd $tmp; get latest.json;"
for p in windows macos; do
  b="$(jq -r ".$p.build // 0" "$tmp/latest.json")"
  [ "$N" -le "$b" ] || { echo "✗ $p só tem o build $b publicado — publique o $N antes de obrigar." >&2; exit 1; }
done
jq --argjson n "$N" '.required = $n' "$tmp/latest.json" > "$tmp/new.json"
diff <(jq . "$tmp/latest.json") <(jq . "$tmp/new.json") || true
read -r -p "Publicar? [s/N] " ok; [ "$ok" = s ] || exit 0
mv "$tmp/new.json" "$tmp/latest.json"
key="$(mktemp)"; chmod 600 "$key"
security find-generic-password -s codeck-update-signing -a codeck -w | base64 -D > "$key"
openssl dgst -sha256 -sign "$key" "$tmp/latest.json" | base64 | tr -d '\n' > "$tmp/latest.json.sig"
rm -f "$key"
run "cd /codeck; lcd $tmp; put latest.json; put latest.json.sig;"
echo "✓ required = $N"
