#!/usr/bin/env bash
# Autoteste do Codeck no DESKTOP (macOS): compila o app, monta repositórios Git de verdade numa pasta temporária,
# abre o app com dados e porta próprios (não toca na sua instalação) e roda tests/desktop/selftest.js DENTRO da janela,
# com teclas reais do sistema. Resultado em dist/selftest/result.json + screenshots da janela.
#
#   scripts/test-desktop.sh                 tudo, menos o agente de IA
#   AGENT_ACCOUNT=dematec2 TRUSTED_DIR=~/x scripts/test-desktop.sh   inclui um agente Claude de verdade (custa 1 resposta)
#   SKIP_BUILD=1 scripts/test-desktop.sh    usa o dist/Codeck.app já compilado
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist/selftest"
WORK="$(mktemp -d /tmp/codeck-selftest.XXXXXX)"
PORT="${PORT:-47860}"
rm -rf "$OUT"; mkdir -p "$OUT"

[ "${SKIP_BUILD:-}" = 1 ] || bash "$ROOT/scripts/build-macos.sh" --no-install >/dev/null

# ---- repositórios de teste (origem "bare" + dois clones)
FX="$WORK/repos"; mkdir -p "$FX"
git init -q --bare -b main "$FX/origin.git"
git clone -q "$FX/origin.git" "$FX/demo-api" 2>/dev/null
(
  cd "$FX/demo-api"
  git config user.email teste@codeck && git config user.name Teste
  printf 'a\n' > a.txt
  printf 'export function soma(a: number, b: number): number {\n  return a + b;\n}\n' > util.ts
  printf 'import { soma } from "./util";\n\nconst total: string = soma(1, 2);\nconsole.log(total);\n' > main.ts
  printf '{"compilerOptions":{"strict":true,"target":"es2020","module":"commonjs"}}\n' > tsconfig.json
  printf 'workspace.local.json\n' > .gitignore
  printf '{"name":"demo","scripts":{"ola":"echo script-ok"}}\n' > package.json
  mkdir -p .vscode && printf '{\n  // comentário como no VS Code\n  "version": "0.2.0",\n  "configurations": [\n    { "name": "Rodar demo", "type": "node-terminal", "request": "launch", "command": "echo launch-ok" },\n  ],\n}\n' > .vscode/launch.json
  git add -A && git commit -qm inicial && git push -q -u origin main
  printf '{"segredo":"local"}\n' > workspace.local.json
)
git clone -q "$FX/origin.git" "$FX/demo-web" 2>/dev/null

# ---- servidor de linguagem do TypeScript (só para o teste; fica em cache)
LSP_DIR="${HOME}/Library/Caches/codeck-selftest-lsp"
if [ ! -x "$LSP_DIR/node_modules/.bin/typescript-language-server" ] && command -v npm >/dev/null; then
  mkdir -p "$LSP_DIR" && (cd "$LSP_DIR" && npm init -y >/dev/null && npm i --silent typescript-language-server@4.3.3 typescript@5.6.3 >/dev/null 2>&1) || true
fi
LSP=false; [ -x "$LSP_DIR/node_modules/.bin/typescript-language-server" ] && LSP=true

CTX=$(python3 -c "import json,os,sys; print(json.dumps({'fixture': sys.argv[1], 'lsp': sys.argv[2] == 'true',
  'trusted': os.path.expanduser(os.environ.get('TRUSTED_DIR','')) or None, 'account': os.environ.get('AGENT_ACCOUNT','')}))" "$FX" "$LSP")

echo "▸ abrindo o app de desktop com o autoteste (porta $PORT, dados em $WORK/data)…"
env -u CLAUDECODE $(env | grep -o '^CLAUDE_CODE_[A-Z_]*' | sed 's/^/-u /') \
  CODECK_PORT="$PORT" CODECK_DATA="$WORK/data" CODECK_LSP_PATH="$LSP_DIR/node_modules/.bin" \
  CODECK_SELFTEST="${SCRIPT:-$ROOT/tests/desktop/selftest.js}" CODECK_SELFTEST_OUT="$OUT" CODECK_SELFTEST_CTX="$CTX" \
  "$ROOT/dist/Codeck.app/Contents/MacOS/Codeck" >"$OUT/app.log" 2>&1 &
APP=$!
for _ in $(seq 1 600); do
  [ -f "$OUT/result.json" ] && break
  kill -0 $APP 2>/dev/null || break
  sleep 1
done
# o roteiro termina pedindo para sair (o mesmo do ⌘Q): o app tem de sair sozinho e não deixar processo nenhum
QUIT_OK=false
for _ in $(seq 1 20); do kill -0 $APP 2>/dev/null || { QUIT_OK=true; break; }; sleep 1; done
kill -9 $APP 2>/dev/null || true
LEFT=""
for _ in $(seq 1 10); do LEFT=$(pgrep -f "sleep 4244" || true); [ -z "$LEFT" ] && break; sleep 0.5; done   # até 5 s
[ -n "$LEFT" ] && kill $LEFT 2>/dev/null
[ -f "$OUT/result.json" ] || { echo "✗ o autoteste não terminou (veja $OUT/app.log)"; exit 1; }

set +e
python3 - "$OUT/result.json" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
if "fatal" in r:
    print("✗ erro ao injetar o roteiro:", r["fatal"]); sys.exit(1)
for x in r["results"]:
    print(("✓" if x["ok"] else "✗"), x["name"], f"({x['ms']} ms)", ("— " + x["detail"]) if x["detail"] else "")
print(f"\n{r['ok']}/{r['total']} etapas OK no {r['platform']} (janela visível no início/fim: {r.get('visible')})")
if r["jsErrors"]:
    print("erros de JavaScript:", *r["jsErrors"][:10], sep="\n  ")
sys.exit(0 if r["ok"] == r["total"] else 1)
EOF
RC=$?
$QUIT_OK && echo "✓ o app saiu sozinho ao fechar (⌘Q)" || { echo "✗ o app NÃO saiu sozinho ao fechar (travou)"; RC=1; }
[ -z "$LEFT" ] && echo "✓ nenhum processo dos terminais ficou rodando" || { echo "✗ sobrou processo dos terminais: $LEFT"; RC=1; }
exit $RC
