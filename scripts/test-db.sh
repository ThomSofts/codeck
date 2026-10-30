#!/usr/bin/env bash
# Bateria completa dos bancos de dados no macOS: sobe os bancos de verdade (Docker), os emuladores do Firebase e do
# Android, o app Flutter de teste, e roda tests/db/run_tests.py contra todos — depois a tela no Chrome (tests/db/ui_test.mjs).
#
#   scripts/test-db.sh                 tudo
#   scripts/test-db.sh --sem-android   sem o emulador Android (o mais lento)
#   scripts/test-db.sh --sem-ui        sem o teste da tela
#   scripts/test-db.sh --rapido        só os testes gerais (sem Docker, emuladores e tela)
#
# Precisa: Docker, Go, Python 3. Opcional: Java + Node (Firebase), Flutter + Android SDK com um AVD (Android), Google
# Chrome (tela). O que faltar é pulado (e aparece no relatório). Não usa o seu celular nem os seus apps: o app de teste
# roda num emulador. Tudo some no fim — containers, emuladores, dados e as senhas de teste do Keychain.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d "${TMPDIR:-/tmp}/codeck-test-db.XXXXXX")"
CACHE="$HOME/.cache/codeck-tests"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
FLUTTER_DIR="$(dirname "$(command -v flutter 2>/dev/null || echo "$HOME/Documents/devPrograms/flutter/bin/flutter")")"
[ -x "$FLUTTER_DIR/flutter" ] && export PATH="$FLUTTER_DIR:$PATH"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}}"
ADB="$SDK/platform-tools/adb"
ANDROID=true UI=true FULL=true
for a in "$@"; do
  case "$a" in
    --sem-android) ANDROID=false ;;
    --sem-ui) UI=false ;;
    --rapido) FULL=false ANDROID=false UI=false ;;
    *) echo "opção desconhecida: $a" >&2; exit 2 ;;
  esac
done
say() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m  – %s\033[0m\n' "$*"; }
C=(codeck-test-pg codeck-test-pgnotls codeck-test-mysql codeck-test-maria codeck-test-mssql codeck-test-mongo codeck-test-redis codeck-test-libsql codeck-test-sshd)
EMU_PID="" FB_PID="" DESK_APP=""
cleanup() {
  say "Limpando"
  docker rm -f "${C[@]}" >/dev/null 2>&1
  docker network rm codeck-test-net >/dev/null 2>&1
  [ -n "$FB_PID" ] && kill "$FB_PID" 2>/dev/null
  pkill -f "firebase.*emulators:start" 2>/dev/null
  [ -n "$EMU_PID" ] && { "$ADB" -s emulator-5580 emu kill >/dev/null 2>&1; kill "$EMU_PID" 2>/dev/null; }
  [ -n "$DESK_APP" ] && osascript -e 'tell application id "br.com.codeck.codeckDbTeste" to quit' >/dev/null 2>&1
  rm -rf "$T"
}
trap cleanup EXIT
wait_for() {   # wait_for <descrição> <segundos> <comando…>
  local what="$1" secs="$2"; shift 2
  for _ in $(seq 1 "$secs"); do "$@" >/dev/null 2>&1 && return 0; sleep 1; done
  warn "$what não ficou pronto em ${secs}s"; return 1
}

say "Go: vet e testes dos plugins (inclui o servidor TLS 1.0, como um SQL Server 2008 R2)"
(cd "$ROOT/db" && go vet ./... && go test ./...) || exit 1

say "Plugins"
mkdir -p "$T/plugins"
(cd "$ROOT/db" && for b in $(ls cmd); do CGO_ENABLED=0 go build -trimpath -o "$T/plugins/codeck-db-$b" "./cmd/$b" || exit 1; done) || exit 1
ls "$T/plugins"

TARGETS="$T/alvos.json"
echo '{}' > "$TARGETS"
add() { python3 - "$TARGETS" "$1" "$2" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1])); d[sys.argv[2]] = json.loads(sys.argv[3]); json.dump(d, open(sys.argv[1], "w"), indent=1)
EOF
}

if $FULL && command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  say "Bancos (Docker)"
  docker network create codeck-test-net >/dev/null 2>&1
  docker run -d --name codeck-test-pg --network codeck-test-net --network-alias pgnet -e POSTGRES_PASSWORD='Pg!pass1' -p 65432:5432 postgres:17 \
    -c ssl=on -c ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem -c ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key >/dev/null
  docker run -d --name codeck-test-pgnotls -e POSTGRES_PASSWORD='Pg!pass1' -p 65433:5432 postgres:17 >/dev/null   # ssl = off (o padrão)
  docker run -d --name codeck-test-mysql -e MYSQL_ROOT_PASSWORD='My!pass1' -e MYSQL_DATABASE=loja -p 63306:3306 mysql:8.4 >/dev/null
  docker run -d --name codeck-test-maria -e MARIADB_ROOT_PASSWORD='Ma!pass1' -e MARIADB_DATABASE=loja -p 63307:3306 mariadb:11 >/dev/null
  if [ "$(uname -m)" = arm64 ]; then MSSQL_IMG=mcr.microsoft.com/azure-sql-edge:latest; else MSSQL_IMG=mcr.microsoft.com/mssql/server:2022-latest; fi
  docker run -d --name codeck-test-mssql -e ACCEPT_EULA=Y -e 'MSSQL_SA_PASSWORD=Ms!pass12345' -p 61433:1433 "$MSSQL_IMG" >/dev/null
  docker run -d --name codeck-test-mongo -e MONGO_INITDB_ROOT_USERNAME=root -e 'MONGO_INITDB_ROOT_PASSWORD=Mo!pass1' -p 63017:27017 mongo:7 >/dev/null
  docker run -d --name codeck-test-redis -p 63379:6379 redis:7-alpine redis-server --requirepass 'Re!pass1' >/dev/null
  docker run -d --name codeck-test-libsql -p 63080:8080 ghcr.io/tursodatabase/libsql-server:latest >/dev/null
  # bastion SSH (só chave; o banco atrás dele é o Postgres pela rede interna)
  ssh-keygen -q -t ed25519 -N "" -f "$T/id_teste"
  # a chave pública vai por variável: o Docker Desktop não monta arquivos de pastas temporárias
  docker run -d --name codeck-test-sshd --network codeck-test-net -p 62222:22 -e "PUBKEY=$(cat "$T/id_teste.pub")" alpine:3.20 sh -c \
    'apk add --no-cache openssh >/dev/null && ssh-keygen -A && adduser -D dev && sed -i "s/^dev:!/dev:*/" /etc/shadow &&
     mkdir -p /home/dev/.ssh && echo "$PUBKEY" > /home/dev/.ssh/authorized_keys && chown -R dev /home/dev/.ssh && chmod 600 /home/dev/.ssh/authorized_keys &&
     exec /usr/sbin/sshd -D -e -o AllowTcpForwarding=yes -o PasswordAuthentication=no' >/dev/null

  wait_for Postgres 90 docker exec codeck-test-pg pg_isready -U postgres && sleep 2 && \
    add postgres '{"engine":"postgres","env":{"host":"127.0.0.1","port":65432,"database":"postgres","user":"postgres","password":"Pg!pass1","tls":{"mode":"pin"}}}'
  wait_for "Postgres sem TLS" 90 docker exec codeck-test-pgnotls pg_isready -U postgres && sleep 2 && \
    add pg-sem-tls '{"kind":"notls","engine":"postgres","env":{"host":"127.0.0.1","port":65433,"database":"postgres","user":"postgres","password":"Pg!pass1"}}'
  wait_for MySQL 120 docker exec codeck-test-mysql mysql -uroot -pMy!pass1 -e "select 1" && sleep 3 && \
    add mysql '{"engine":"mysql","env":{"host":"127.0.0.1","port":63306,"database":"loja","user":"root","password":"My!pass1","tls":{"mode":"pin"}}}'
  wait_for MariaDB 120 docker exec codeck-test-maria mariadb -uroot -pMa!pass1 -e "select 1" && \
    add mariadb '{"engine":"mysql","env":{"host":"127.0.0.1","port":63307,"database":"loja","user":"root","password":"Ma!pass1","tls":{"mode":"off","offAck":true}}}'
  wait_for "SQL Server" 150 sh -c 'docker logs codeck-test-mssql 2>&1 | grep -q "Recovery is complete"' && sleep 5 && \
    add sqlserver '{"engine":"sqlserver","env":{"host":"127.0.0.1","port":61433,"database":"master","user":"sa","password":"Ms!pass12345","tls":{"mode":"pin","legacy":true}}}'
  wait_for MongoDB 90 docker exec codeck-test-mongo mongosh --quiet -u root -p 'Mo!pass1' --eval 'db.runCommand({ping:1})' && \
    add mongodb '{"engine":"mongodb","env":{"host":"127.0.0.1","port":63017,"database":"loja","user":"root","password":"Mo!pass1","tls":{"mode":"off","offAck":true}}}'
  wait_for Redis 30 docker exec codeck-test-redis redis-cli -a 'Re!pass1' ping && \
    add redis '{"engine":"redis","env":{"host":"127.0.0.1","port":63379,"database":"0","password":"Re!pass1","tls":{"mode":"off","offAck":true}}}'
  wait_for libSQL 60 curl -sf http://127.0.0.1:63080/health && \
    add libsql '{"engine":"libsql","env":{"host":"http://127.0.0.1:63080","tls":{"mode":"off","offAck":true}}}'
  if wait_for "SSH" 90 sh -c "ssh-keyscan -p 62222 127.0.0.1 2>/dev/null | grep -q ed25519"; then
    ssh-keyscan -p 62222 127.0.0.1 2>/dev/null > "$T/known_hosts"
    add tunel "{\"kind\":\"ssh\",\"engine\":\"postgres\",\"known_hosts\":\"$T/known_hosts\",\"env\":{\"host\":\"pgnet\",\"port\":5432,\"database\":\"postgres\",\"user\":\"postgres\",\"password\":\"Pg!pass1\",\"tls\":{\"mode\":\"off\",\"offAck\":true,\"offPublicAck\":true}},\"ssh\":{\"host\":\"127.0.0.1\",\"port\":62222,\"user\":\"dev\",\"key\":\"$T/id_teste\"}}"
  fi
else
  $FULL && warn "Docker indisponível: bancos reais pulados"
fi

if $FULL && command -v java >/dev/null && command -v npx >/dev/null; then
  say "Emuladores do Firebase (Firestore e Realtime Database)"
  mkdir -p "$CACHE/firebase" && cd "$CACHE/firebase"
  [ -d node_modules/firebase-tools ] || { npm init -y >/dev/null; npm i firebase-tools@13 --silent >/dev/null 2>&1; }
  echo '{"emulators":{"firestore":{"port":58081,"host":"127.0.0.1"},"database":{"port":59000,"host":"127.0.0.1"},"ui":{"enabled":false},"singleProjectMode":true}}' > firebase.json
  npx firebase emulators:start --only firestore,database --project demo-codeck > "$T/firebase.log" 2>&1 &
  FB_PID=$!
  cd "$ROOT"
  if wait_for "Firebase" 120 sh -c "curl -s -o /dev/null http://127.0.0.1:58081 && curl -s -o /dev/null 'http://127.0.0.1:59000/.json?ns=x'"; then
    export CODECK_FIREBASE_EMULATOR="firestore=127.0.0.1:58081,database=127.0.0.1:59000"
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$T/sa.pem" 2>/dev/null
    SA="$(python3 -c 'import json,sys; print(json.dumps(json.dumps({"type":"service_account","project_id":"demo-codeck","client_email":"teste@demo-codeck.iam.gserviceaccount.com","private_key":open(sys.argv[1]).read()})))' "$T/sa.pem")"
    add firestore "{\"engine\":\"firebase\",\"env\":{\"host\":\"demo-codeck\",\"database\":\"(default)\",\"password\":$SA}}"
    add rtdb "{\"engine\":\"firebase\",\"env\":{\"host\":\"https://demo-codeck-default-rtdb.firebaseio.com\",\"password\":$SA}}"
  fi
else
  $FULL && warn "Java/Node indisponíveis: Firebase pulado"
fi

APP="$CACHE/codeck_db_teste"
build_app() {   # o app Flutter de teste (sqflite + Hive + shared_preferences), uma vez — fica no cache
  [ -f "$APP/pubspec.yaml" ] && return 0
  command -v flutter >/dev/null || return 1
  rm -rf "$APP"; mkdir -p "$CACHE"
  (cd "$CACHE" && flutter create --org br.com.codeck --project-name codeck_db_teste --platforms android,macos codeck_db_teste >/dev/null &&
   cd "$APP" && flutter pub add sqflite path path_provider hive shared_preferences >/dev/null &&
   cp "$ROOT/tests/db/flutter_app/main.dart" lib/main.dart &&
   sed -i '' "s/^# platform :osx.*/platform :osx, '12.0'/; s/^platform :osx.*/platform :osx, '12.0'/" macos/Podfile &&
   sed -i '' 's/MACOSX_DEPLOYMENT_TARGET = 10.1[0-9];/MACOSX_DEPLOYMENT_TARGET = 12.0;/g' macos/Runner.xcodeproj/project.pbxproj)
}

if $ANDROID && [ -x "$ADB" ] && [ -x "$SDK/emulator/emulator" ] && build_app; then
  AVD="$("$SDK/emulator/emulator" -list-avds | head -1)"
  if [ -n "$AVD" ]; then
    say "Android: emulador $AVD + app de teste"
    (cd "$APP" && [ -f build/app/outputs/flutter-apk/app-debug.apk ] || flutter build apk --debug >/dev/null 2>&1)
    "$SDK/emulator/emulator" -avd "$AVD" -port 5580 -no-window -no-audio -no-snapshot-save -no-boot-anim > "$T/emu.log" 2>&1 &
    EMU_PID=$!
    if wait_for "emulador" 240 sh -c "\"$ADB\" -s emulator-5580 shell getprop sys.boot_completed | grep -q 1"; then
      "$ADB" -s emulator-5580 install -r "$APP/build/app/outputs/flutter-apk/app-debug.apk" >/dev/null
      "$ADB" -s emulator-5580 shell monkey -p br.com.codeck.codeck_db_teste -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
      sleep 8
      add android "{\"kind\":\"android\",\"project\":\"$APP\",\"device\":\"emulator-5580\"}"
    fi
  fi
else
  $ANDROID && warn "Android pulado (sem Flutter, SDK ou AVD)"
fi

if $FULL && build_app && command -v pod >/dev/null; then
  say "macOS: app de teste aberto direto no arquivo"
  (cd "$APP" && [ -d build/macos/Build/Products/Debug/codeck_db_teste.app ] || flutter build macos --debug >/dev/null 2>&1)
  if [ -d "$APP/build/macos/Build/Products/Debug/codeck_db_teste.app" ]; then
    open -g "$APP/build/macos/Build/Products/Debug/codeck_db_teste.app" && DESK_APP=1 && sleep 6
    add macos "{\"kind\":\"desktop\",\"project\":\"$APP\",\"device\":\"macos\"}"
  else
    warn "o app de macOS não compilou"
  fi
fi

say "Testes (backend de verdade, pela API)"
python3 -I "$ROOT/tests/db/run_tests.py" --plugins "$T/plugins" --targets "$TARGETS" --report "$T/relatorio.txt"
CODE=$?
cp "$T/relatorio.txt" "$ROOT/dist/test-db-relatorio.txt" 2>/dev/null || { mkdir -p "$ROOT/dist" && cp "$T/relatorio.txt" "$ROOT/dist/test-db-relatorio.txt"; }

if $UI && command -v node >/dev/null && [ -d "/Applications/Google Chrome.app" ]; then
  say "Tela (Chrome headless)"
  mkdir -p "$CACHE/pw" && (cd "$CACHE/pw" && [ -d node_modules/playwright ] || { npm init -y >/dev/null; npm i playwright@1.49.1 --silent >/dev/null 2>&1; })
  (cd "$ROOT/ui" && [ -d node_modules ] || npm ci --silent; npm run build --silent >/dev/null 2>&1)
  CODECK_PLAYWRIGHT="$CACHE/pw/node_modules/playwright/index.mjs" node "$ROOT/tests/db/ui_test.mjs" "$T/plugins" "$T/ui" || CODE=1
fi
say "Relatório: $ROOT/dist/test-db-relatorio.txt"
exit $CODE
