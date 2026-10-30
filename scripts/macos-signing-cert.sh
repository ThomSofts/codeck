#!/usr/bin/env bash
# Cria (uma vez, no Mac que faz as releases) o certificado que assina o Codeck.app — sempre o mesmo.
#
# Por quê: o macOS guarda as permissões (acesso a Documentos/Mesa/Downloads, modificar apps…) presas à identidade
# do app. Com assinatura ad-hoc, a identidade é o hash do binário — muda a cada versão, e depois de cada atualização
# o macOS pergunta tudo de novo. Assinado sempre com o mesmo certificado, a identidade passa a ser "este bundle id
# + este certificado", e as permissões atravessam as atualizações.
#
# O certificado é próprio (não é Developer ID da Apple): o app continua não notarizado, como antes. Fica no Keychain
# de início de sessão como o .p12 em base64 (serviço codeck-codesign), como a chave do latest.json: o build monta um
# keychain temporário com ele, já liberado para o codesign — sem a pergunta "codesign quer usar a chave" no meio.
# FAÇA BACKUP (scripts/macos-signing-cert.sh --export arquivo.p12): se ele se perder, a próxima versão vem com outra
# identidade e cada pessoa autoriza tudo uma última vez.
#
#   scripts/macos-signing-cert.sh                      cria (se ainda não existe) e mostra a impressão digital
#   scripts/macos-signing-cert.sh --export x.p12       backup, cifrado (AES-256) com uma senha forte gerada na hora —
#                                                      mostrada uma vez: guarde no gerenciador de senhas
#   scripts/macos-signing-cert.sh --import x.p12       restaura de um backup (pede a senha)
set -euo pipefail
SERVICE=codeck-codesign
P12_PASS=codeck   # o .p12 fica protegido pelo Keychain; a senha dele é só formalidade do formato
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
fail() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
[ "$(uname)" = Darwin ] || fail "Só no macOS."
case "$(openssl version)" in LibreSSL*) fail "Precisa do OpenSSL do Homebrew (brew install openssl)." ;; esac
stored() { security find-generic-password -s "$SERVICE" -a codeck -w 2>/dev/null; }
store() { security add-generic-password -U -s "$SERVICE" -a codeck -l "Codeck — certificado que assina o app" -w "$(base64 < "$1" | tr -d '\n')"; }
show() {
  stored | base64 -D | openssl pkcs12 -nokeys -passin "pass:$P12_PASS" -legacy 2>/dev/null | openssl x509 -noout -subject -fingerprint -sha1 -enddate
  echo "Os builds (scripts/build-macos.sh) assinam com ele."
}

case "${1:-}" in
  --export)
    [ -n "${2:-}" ] || fail "Uso: $0 --export arquivo.p12"
    B="$(stored)" || fail "Ainda não há certificado."
    T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
    printf '%s' "$B" | base64 -D | openssl pkcs12 -passin "pass:$P12_PASS" -legacy -nodes -out "$T/all.pem" 2>/dev/null
    PW="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-28)"
    umask 077
    openssl pkcs12 -export -in "$T/all.pem" -name "Codeck Code Signing" -keypbe AES-256-CBC -certpbe AES-256-CBC -macalg sha256 \
      -iter 600000 -out "$2" -passout "pass:$PW"
    echo "Backup em $2"
    echo "Senha (aparece só agora — guarde no gerenciador de senhas): $PW"; exit 0 ;;
  --import)
    [ -f "${2:-}" ] || fail "Uso: $0 --import arquivo.p12"
    read -rsp "Senha do backup: " PW; echo
    T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
    openssl pkcs12 -in "$2" -passin "pass:$PW" -nodes -out "$T/all.pem" 2>/dev/null || fail "Senha errada ou arquivo inválido."
    openssl pkcs12 -export -legacy -in "$T/all.pem" -name "Codeck Code Signing" -out "$T/c.p12" -passout "pass:$P12_PASS"
    store "$T/c.p12"; show; exit 0 ;;
  "") ;;
  *) fail "opção desconhecida: $1" ;;
esac
if stored >/dev/null; then show; exit 0; fi

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
cat > "$T/c.cnf" <<EOF
[req]
distinguished_name=dn
x509_extensions=ext
prompt=no
[dn]
CN=Codeck Code Signing
O=ThomSoft
[ext]
basicConstraints=critical,CA:false
keyUsage=critical,digitalSignature
extendedKeyUsage=critical,codeSigning
subjectKeyIdentifier=hash
EOF
# 30 anos: o codesign não assina com um certificado vencido (o macOS não confere a validade para manter as permissões)
openssl req -x509 -newkey rsa:3072 -nodes -keyout "$T/k.pem" -out "$T/c.pem" -days 10950 -config "$T/c.cnf" 2>/dev/null
openssl pkcs12 -export -legacy -inkey "$T/k.pem" -in "$T/c.pem" -name "Codeck Code Signing" -out "$T/c.p12" -passout "pass:$P12_PASS" 2>/dev/null
store "$T/c.p12"
echo "Criado e guardado no Keychain (serviço $SERVICE)."
show
echo "Faça o backup: $0 --export ~/algum-lugar-seguro/codeck-codesign.p12"
