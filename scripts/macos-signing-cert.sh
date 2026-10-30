#!/usr/bin/env bash
# Cria (uma vez, no Mac que faz as releases) o certificado que assina o Codeck.app — sempre o mesmo.
#
# Por quê: o macOS guarda as permissões (acesso a Documentos/Mesa/Downloads, modificar apps…) presas à identidade
# do app. Com assinatura ad-hoc, a identidade é o hash do binário — muda a cada versão, e depois de cada atualização
# o macOS pergunta tudo de novo. Assinado sempre com o mesmo certificado, a identidade passa a ser "este bundle id
# + este certificado", e as permissões atravessam as atualizações.
#
# O certificado é próprio (não é Developer ID da Apple): o app continua não notarizado, como antes. A chave fica no
# Keychain de início de sessão. FAÇA BACKUP (Acesso às Chaves → "Codeck Code Signing" → Exportar .p12): se ela se
# perder, a próxima versão vem com outra identidade e cada pessoa autoriza tudo uma última vez.
#
#   scripts/macos-signing-cert.sh            cria (se ainda não existe) e mostra a impressão digital
#   scripts/macos-signing-cert.sh --import x.p12   restaura de um backup
set -euo pipefail
NAME="${CODECK_CODESIGN_IDENTITY:-Codeck Code Signing}"
KC="$HOME/Library/Keychains/login.keychain-db"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
fail() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
[ "$(uname)" = Darwin ] || fail "Só no macOS."

show() {
  local sha
  sha="$(security find-certificate -c "$NAME" -Z "$KC" | awk '/SHA-1/ {print $3; exit}')"
  echo "Certificado \"$NAME\" — SHA-1 $sha"
  echo "Os builds (scripts/build-macos.sh) assinam com ele daqui em diante."
}

if [ "${1:-}" = "--import" ]; then
  [ -f "${2:-}" ] || fail "Uso: $0 --import arquivo.p12"
  security import "$2" -k "$KC" -T /usr/bin/codesign
  show; exit 0
fi
if security find-certificate -c "$NAME" "$KC" >/dev/null 2>&1; then
  show; exit 0
fi
case "$(openssl version)" in LibreSSL*) fail "Precisa do OpenSSL do Homebrew (brew install openssl)." ;; esac

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
cat > "$T/c.cnf" <<EOF
[req]
distinguished_name=dn
x509_extensions=ext
prompt=no
[dn]
CN=$NAME
O=ThomSoft
[ext]
basicConstraints=critical,CA:false
keyUsage=critical,digitalSignature
extendedKeyUsage=critical,codeSigning
subjectKeyIdentifier=hash
EOF
# 30 anos: a identidade do app não pode vencer (o macOS não confere a validade para manter as permissões, mas o codesign recusa assinar com um vencido)
openssl req -x509 -newkey rsa:3072 -nodes -keyout "$T/k.pem" -out "$T/c.pem" -days 10950 -config "$T/c.cnf" 2>/dev/null
P="$(openssl rand -hex 16)"
openssl pkcs12 -export -legacy -inkey "$T/k.pem" -in "$T/c.pem" -name "$NAME" -out "$T/c.p12" -passout "pass:$P" 2>/dev/null
security import "$T/c.p12" -k "$KC" -P "$P" -T /usr/bin/codesign >/dev/null
echo "Criado. Na primeira assinatura, o macOS pergunta se o codesign pode usar a chave: \"Permitir Sempre\"."
show
echo "Faça o backup agora: Acesso às Chaves → \"$NAME\" → Exportar (.p12) — e guarde fora deste Mac."
