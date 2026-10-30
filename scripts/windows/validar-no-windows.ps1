# Validação do Codeck no Windows — o que só dá para conferir num PC de verdade, com as suas contas e CLIs.
#
#   powershell -ExecutionPolicy Bypass -File validar-no-windows.ps1
#
# Usa o Python e o backend do Codeck INSTALADO (atualize para a 4.10.0 ou mais nova antes), numa CÓPIA dos seus dados
# (%APPDATA%\Codeck fica intocada). Não abre o app, não manda nada para a internet e não gasta uso das contas de IA.
# Confere:
#   1. Consumo das IAs: lê as conversas do Claude Code e do Codex e o banco do Cursor, nas pastas do Windows;
#   2. as CLIs de IA: onde estão e como o Codeck as chama sem janela (a revisão automática de PR);
#   3. janelas de console: toda chamada que a aba IA e a leitura do consumo fazem sai com a janela escondida;
#   4. os projetos: cada conversa cai no projeto certo (caminhos do Windows, worktrees).
# No fim grava um relatório na Área de trabalho (codeck-validacao.txt) — mande para o Claude no Codeck.
$ErrorActionPreference = 'Stop'
$app = Join-Path $env:LOCALAPPDATA 'Programs\Codeck'
$python = Join-Path $app 'python\python.exe'
$backend = Join-Path $app 'backend'
$data = Join-Path $env:APPDATA 'Codeck'
if (-not (Test-Path $python) -or -not (Test-Path (Join-Path $backend 'pilot\aiusage.py'))) {
  Write-Host "✗ Não achei o Codeck 4.10.0+ instalado em $app — atualize o Codeck e rode de novo." -ForegroundColor Red
  exit 1
}
$office = Get-Content (Join-Path $app 'office.json') -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
Write-Host "▸ Codeck $($office.version)+$($office.build) em $app" -ForegroundColor Cyan

# a cópia dos dados: só o que a validação lê
$work = Join-Path $env:TEMP "codeck-validacao-$([DateTime]::Now.ToString('yyyyMMdd-HHmmss'))"
New-Item -ItemType Directory -Force $work | Out-Null
foreach ($f in 'ai-accounts.json', 'repos.json', 'ai-sessions.json', 'ai-resume.json', 'ai-usage.json', 'config.json', 'workspace.json') {
  $src = Join-Path $data $f
  if (Test-Path $src) { Copy-Item $src $work }
}

$py = @'
import json, os, subprocess, sys, time, traceback
sys.path.insert(0, os.environ["CODECK_BACKEND"])
out = []
def say(s=""):
    print(s); out.append(s)
ok_all = True
def check(cond, what):
    global ok_all
    ok_all = ok_all and bool(cond)
    say(("  ✓ " if cond else "  ✗ ") + what)

# janelas de console: toda chamada de processo é anotada (e roda de verdade)
calls = []
_run, _popen = subprocess.run, subprocess.Popen
class Spy(_popen):
    def __init__(self, args, *a, **k):
        calls.append(((args if isinstance(args, str) else " ".join(map(str, args)))[:120], k.get("creationflags", 0)))
        super().__init__(args, *a, **k)
subprocess.Popen = Spy

from pilot import agents, aitools, aiusage, git

say("== 1. Consumo das IAs")
try:
    t = time.time(); n = aiusage.scan(); dt = time.time() - t
    r = aiusage.report(30)
    say(f"  {n} arquivos lidos em {dt:.1f}s · base desde {r['scan']['oldest']} · erro: {r['scan']['error'] or 'nenhum'}")
    for p, g in sorted(r["provider"].items(), key=lambda kv: -kv[1]["tokens"]):
        say(f"  {p}: {g['n']} respostas, {g['tokens']/1e6:.1f} M tokens, {g['sessions']} sessões, cache {g['cacheHit']}%")
    for k, g in sorted(r["effort"].items(), key=lambda kv: -kv[1]["tokens"])[:6]:
        say(f"    {k}: {g['n']} respostas, {g['outPerCall']} de saída/resposta")
    cc = r["cursor"]["commits"]
    say(f"  Cursor: {len(r['cursor']['models'])} modelos, {cc['commits']} commits ({cc['ai']} linhas da IA × {cc['human']} suas)")
    check(r["total"]["n"] > 0 or r["cursor"]["models"], "o consumo leu alguma coisa (Claude, Codex ou Cursor)")
    for i in r["insights"]:
        say(f"  · {i['title']}")
except Exception:
    check(False, "leitura do consumo — " + traceback.format_exc().splitlines()[-1])

say(); say("== 2. CLIs de IA (como a revisão automática as chama)")
try:
    bins = agents.which_all(force=True)
    for b, path in bins.items():
        if path:
            exe, pre, via_cmd = agents.win_resolve(path)
            say(f"  {b}: {path}")
            say(f"      roda como: {exe} {' '.join(pre)}{'  (pelo cmd.exe — pode abrir janela)' if via_cmd else ''}")
    check(bins.get("claude") or bins.get("codex"), "achei o Claude Code ou o Codex")
except Exception:
    check(False, "CLIs — " + traceback.format_exc().splitlines()[-1])

say(); say("== 3. Janelas de console (aba IA de cada projeto)")
try:
    repos = [r for r in git.list_repos(with_status=False) if r["exists"]][:8]
    for rp in repos:
        try:
            aitools.inventory(rp["id"])
        except Exception as e:
            say(f"  (aviso) {rp['name']}: {e}")
    bad = [c for c in calls if not (c[1] & 0x08000000)]
    say(f"  {len(calls)} processos chamados em {len(repos)} projeto(s)")
    for c, _f in bad[:10]:
        say(f"    sem esconder a janela: {c}")
    check(not bad, "nenhuma chamada abriria janela de console")
except Exception:
    check(False, "janelas — " + traceback.format_exc().splitlines()[-1])

say(); say("== 4. Projetos das conversas (caminhos do Windows)")
try:
    d = aiusage._load()
    projs = {}
    for s in d["sessions"].values():
        projs[s["pr"]] = projs.get(s["pr"], 0) + 1
    say("  " + ", ".join(f"{k} ({v})" for k, v in sorted(projs.items(), key=lambda kv: -kv[1])[:12]))
    check(not any(("\\" in k or "/" in k) for k in projs), "os projetos saem pelo nome, não pelo caminho")
except Exception:
    check(False, "projetos — " + traceback.format_exc().splitlines()[-1])

say()
say("RESULTADO: " + ("tudo certo" if ok_all else "há itens com ✗ — mande este relatório"))
open(os.environ["CODECK_REPORT"], "w", encoding="utf-8").write("\n".join(out) + "\n")
sys.exit(0 if ok_all else 1)
'@
$report = Join-Path ([Environment]::GetFolderPath('Desktop')) 'codeck-validacao.txt'
$env:CODECK_DATA = $work
$env:CODECK_BACKEND = $backend
$env:CODECK_REPORT = $report
$env:PYTHONIOENCODING = 'utf-8'
$pyFile = Join-Path $work 'validar.py'
Set-Content -Path $pyFile -Value $py -Encoding utf8
& $python $pyFile
$code = $LASTEXITCODE
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Relatório: $report" -ForegroundColor Cyan
exit $code
