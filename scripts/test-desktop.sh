#!/usr/bin/env bash
# Autoteste do Codeck no DESKTOP (macOS): compila o app, monta repositórios Git de verdade numa pasta temporária,
# abre o app com dados e porta próprios (não toca na sua instalação) e roda tests/desktop/selftest.js DENTRO da janela,
# com teclas reais do sistema. Resultado em dist/selftest/result.json + screenshots da janela.
#
#   scripts/test-desktop.sh                 tudo, menos o agente de IA
#   AGENT_ACCOUNT=dematec2 TRUSTED_DIR=~/x scripts/test-desktop.sh   inclui um agente Claude de verdade (custa 1 resposta)
#   SKIP_BUILD=1 scripts/test-desktop.sh    usa o dist/Codeck.app já compilado
#   SCRIPT=tests/desktop/selftest-editor.js scripts/test-desktop.sh   o roteiro do editor (LSP, atalhos, abas, Issues)
#   EXTRA_LSP_PATH=<pasta com o csharp-ls> …  inclui o C# (dotnet tool install csharp-ls --tool-path <pasta>)
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
  # ignorados: o explorador mostra (apagados) — inclusive um repositório inteiro dentro deste (pasta "workspace")
  printf 'workspace.local.json\n/nested-repo/\nbin/\n' > .gitignore
  printf '{"name":"demo","scripts":{"ola":"echo script-ok"}}\n' > package.json
  mkdir -p .vscode && printf '{\n  // comentário como no VS Code\n  "version": "0.2.0",\n  "configurations": [\n    { "name": "Rodar demo", "type": "node-terminal", "request": "launch", "command": "echo launch-ok" },\n  ],\n}\n' > .vscode/launch.json
  git add -A && git commit -qm inicial && git push -q -u origin main
  printf '{"segredo":"local"}\n' > workspace.local.json
  mkdir -p bin && printf 'saida\n' > bin/out.txt
  # repositório aninhado (ignorado pelo de fora) com uma solução .NET: Gerenciador de Soluções e explorador entram nele
  mkdir -p nested-repo/App/bin/Debug && cd nested-repo && git init -q -b main
  printf 'aninhado\n' > nested.txt
  printf 'Microsoft Visual Studio Solution File, Format Version 12.00\nProject("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "App", "App\\App.csproj", "{11111111-1111-1111-1111-111111111111}"\nEndProject\n' > App.sln
  # o framework do SDK desta máquina (o servidor de linguagem do C# só entende o projeto se ele existir)
  TF="net8.0"; command -v dotnet >/dev/null && TF="net$(dotnet --version 2>/dev/null | cut -d. -f1).0"
  printf '<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup><OutputType>Exe</OutputType><TargetFramework>%s</TargetFramework></PropertyGroup>\n</Project>\n' "$TF" > App/App.csproj
  printf 'System.Console.WriteLine("oi");\n' > App/Program.cs
  printf 'x' > App/bin/Debug/App.dll
)
git clone -q "$FX/origin.git" "$FX/demo-web" 2>/dev/null

# ---- servidor de linguagem do TypeScript (só para o teste; fica em cache)
LSP_DIR="${HOME}/Library/Caches/codeck-selftest-lsp"
if [ ! -x "$LSP_DIR/node_modules/.bin/typescript-language-server" ] && command -v npm >/dev/null; then
  mkdir -p "$LSP_DIR" && (cd "$LSP_DIR" && npm init -y >/dev/null && npm i --silent typescript-language-server@4.3.3 typescript@5.6.3 >/dev/null 2>&1) || true
fi
LSP=false; [ -x "$LSP_DIR/node_modules/.bin/typescript-language-server" ] && LSP=true

CS=false; [ -n "${EXTRA_LSP_PATH:-}" ] && [ -x "$EXTRA_LSP_PATH/csharp-ls" ] && CS=true
CTX=$(CS=$CS python3 -c "import json,os,sys; print(json.dumps({'fixture': sys.argv[1], 'lsp': sys.argv[2] == 'true', 'cs': os.environ.get('CS') == 'true',
  'trusted': os.path.expanduser(os.environ.get('TRUSTED_DIR','')) or None, 'account': os.environ.get('AGENT_ACCOUNT','')}))" "$FX" "$LSP")

echo "▸ abrindo o app de desktop com o autoteste (porta $PORT, dados em $WORK/data)…"
env -u CLAUDECODE $(env | grep -o '^CLAUDE_CODE_[A-Z_]*' | sed 's/^/-u /') \
  CODECK_PORT="$PORT" CODECK_DATA="$WORK/data" CODECK_LSP_PATH="$LSP_DIR/node_modules/.bin${EXTRA_LSP_PATH:+:$EXTRA_LSP_PATH}" \
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
