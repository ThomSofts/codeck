"""Agentes de IA: contas (Claude Code, Codex, cursor-agent, Gemini CLI, OpenCode…), como abrir cada um num terminal e
a telemetria de cada sessão — contexto usado, custo, limite de uso e quando ele reseta.

Conta = uma pasta de configuração isolada. Claude: CLAUDE_CONFIG_DIR (~/.claude, ~/.claude-cifal…). Codex: CODEX_HOME.
As credenciais ficam onde a própria CLI guarda (Keychain/arquivo dela) — o app nunca lê token de IA.

Telemetria:
  · Claude Code: o app abre a sessão com --settings contendo uma linha de status e hooks que fazem POST no servidor
    local (/hook/<sessão>/<segredo>) com o JSON que o Claude entrega: modelo, janela de contexto (% usado), custo e,
    quando o plano tem, rate_limits (5 h / semanal, % e reset). Os hooks dizem quando ele está trabalhando, quando
    terminou e quando precisa de você. O segredo é por sessão e só vale para essa rota: o terminal não ganha acesso à API.
  · Codex: lê o log da sessão (CODEX_HOME/sessions/AAAA/MM/DD/*.jsonl), eventos token_count — contexto
    (last_token_usage / model_context_window) e rate_limits (primary/secondary).
  · Demais: só o estado pelo terminal (saindo texto = trabalhando).
"""
import glob
import json
import os
import re
import secrets as pysecrets
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid

from . import userpath
from .core import DATA, DEFAULT_PORT, ctx, load_json, notify, now_iso, save_json

ACCOUNTS_FILE = os.path.join(DATA, "ai-accounts.json")
USAGE_FILE = os.path.join(DATA, "ai-usage.json")   # última leitura de limites por conta (sobrevive ao reinício)
HISTORY_FILE = os.path.join(DATA, "ai-sessions.json")   # uma linha por sessão: dia, projeto, conta, custo, tokens
FOCUS_FILE = os.path.join(DATA, "project-time.json")   # seu tempo com cada projeto na tela: {dia: {repoId: {name, s}}}
HOME = os.path.expanduser("~")

PROVIDERS = {
    "claude": {"label": "Claude Code", "bin": "claude", "env": "CLAUDE_CONFIG_DIR", "home": ".claude", "telemetry": "hooks"},
    "codex": {"label": "Codex", "bin": "codex", "env": "CODEX_HOME", "home": ".codex", "telemetry": "log"},
    "cursor": {"label": "Cursor Agent", "bin": "cursor-agent", "env": None, "home": ".cursor", "telemetry": None},
    "gemini": {"label": "Gemini CLI", "bin": "gemini", "env": None, "home": ".gemini", "telemetry": None},
    "opencode": {"label": "OpenCode", "bin": "opencode", "env": None, "home": ".config/opencode", "telemetry": None},
}

# ---------------------------------------------------------------- binários (PATH real do usuário, não o do app)
_which = {"at": 0, "map": {}}


def which_all(force=False):
    """Onde está cada CLI. O app aberto pelo Finder tem PATH mínimo — userpath descobre o do usuário (.zshrc incluso)."""
    if not force and time.time() - _which["at"] < 300:
        return _which["map"]
    found = {p["bin"]: userpath.which(p["bin"], force=force) for p in PROVIDERS.values()}
    _which.update(at=time.time(), map=found)
    return found


# ---------------------------------------------------------------- contas
def _claude_email(d):
    cj = os.path.join(HOME, ".claude.json") if d == os.path.join(HOME, ".claude") else os.path.join(d, ".claude.json")
    try:
        return (load_json(cj, {}).get("oauthAccount") or {}).get("emailAddress")
    except Exception:  # noqa: BLE001
        return None


def detect():
    """Pastas de configuração encontradas na máquina (sem ler credencial nenhuma)."""
    out = []
    for prov, spec in PROVIDERS.items():
        base = os.path.join(HOME, spec["home"])
        dirs = [base] + (sorted(glob.glob(base + "-*")) if spec["env"] else [])
        for d in dirs:
            if not os.path.isdir(d):
                continue
            suffix = os.path.basename(d)[len(os.path.basename(base)):].lstrip("-")
            email = _claude_email(d) if prov == "claude" else None
            out.append({"provider": prov, "dir": d, "name": suffix or "padrão", "email": email})
    return out


def _load():
    return load_json(ACCOUNTS_FILE, {"accounts": [], "imported": False})


def accounts():
    """Contas configuradas. Na 1ª vez, importa tudo que foi detectado."""
    d = _load()
    if not d.get("imported"):
        for x in detect():
            d["accounts"].append({"id": uuid.uuid4().hex[:10], **x, "color": None})
        d["imported"] = True
        save_json(ACCOUNTS_FILE, d)
    bins = which_all()
    usage = {aid: u for aid, u in _usage.items()}
    out = []
    for a in d["accounts"]:
        spec = PROVIDERS.get(a["provider"], {})
        out.append({**a, "label": spec.get("label"), "installed": bool(bins.get(spec.get("bin"))), "bin": bins.get(spec.get("bin")),
                    "telemetry": spec.get("telemetry"), "usage": usage.get(a["id"])})
    return {"accounts": out, "providers": {k: {"label": v["label"], "installed": bool(bins.get(v["bin"])), "bin": bins.get(v["bin"])} for k, v in PROVIDERS.items()},
            "defaults": d.get("defaults", {})}


def save_account(body):
    d = _load()
    prov = body.get("provider")
    if prov not in PROVIDERS:
        raise ValueError("Provedor desconhecido")
    folder = os.path.abspath(os.path.expanduser((body.get("dir") or "").strip() or os.path.join(HOME, PROVIDERS[prov]["home"])))
    entry = {"id": body.get("id") or uuid.uuid4().hex[:10], "provider": prov, "dir": folder,
             "name": (body.get("name") or "").strip()[:40] or os.path.basename(folder),
             "email": _claude_email(folder) if prov == "claude" else body.get("email"), "color": body.get("color"),
             "group": (str(body.get("group") or "").strip()[:30] or None)}
    d["accounts"] = [a for a in d["accounts"] if a["id"] != entry["id"]] + [entry]
    save_json(ACCOUNTS_FILE, d)
    return entry


def update_account(body):
    """Apelido, grupo (o cliente: Dematec, Pessoal…) e cor de uma conta — só o que vier; o resto fica."""
    d = _load()
    a = next((x for x in d["accounts"] if x["id"] == body.get("id")), None)
    if not a:
        raise LookupError("Conta de IA não encontrada")
    if "name" in body:
        name = str(body.get("name") or "").strip()[:40]
        if not name:
            raise ValueError("Dê um nome para a conta")
        a["name"] = name
    if "group" in body:
        a["group"] = str(body.get("group") or "").strip()[:30] or None
    if "color" in body:
        c = str(body.get("color") or "").strip()
        if c and not re.fullmatch(r"#[0-9a-fA-F]{6}|var\(--cat[1-6]\)", c):
            raise ValueError("Cor inválida")
        a["color"] = c or None
    save_json(ACCOUNTS_FILE, d)
    return a


def delete_account(aid):
    d = _load()
    d["accounts"] = [a for a in d["accounts"] if a["id"] != aid]
    save_json(ACCOUNTS_FILE, d)


def set_default(scope, aid):
    """Conta padrão por escopo: "*" (geral) ou a org/dono do repositório (ex.: "azure:GlorySoft")."""
    d = _load()
    d.setdefault("defaults", {})[scope] = aid
    save_json(ACCOUNTS_FILE, d)


def default_for(scope):
    defs = _load().get("defaults", {})
    return defs.get(scope) or defs.get("*")


def get_account(aid):
    a = next((x for x in _load()["accounts"] if x["id"] == aid), None)
    if not a:
        raise LookupError("Conta de IA não encontrada")
    return a


# ---------------------------------------------------------------- abrir uma sessão de agente
_sessions = {}   # sessão (id do terminal) -> {account, secret, status, statusline, events…}
_usage = load_json(USAGE_FILE, {})   # conta -> {rateLimits, updated, source, plan}
_lock = threading.Lock()


def _hook_cmd(sid, secret, nt=None):
    """POST da linha de status/hook no servidor local. A resposta vai para o nulo: no SessionStart/UserPromptSubmit o
    que o hook imprime entra no CONTEXTO do agente (antes o {"ok": true} ia parar na conversa)."""
    nt = os.name == "nt" if nt is None else nt
    url = f"http://127.0.0.1:{getattr(ctx, 'port', None) or DEFAULT_PORT}/hook/{sid}/{secret}"
    return f"curl -s -m 2 -o /dev/null -X POST -H 'Content-Type: application/json' --data-binary @- {url}" if not nt else \
        f"curl.exe -s -m 2 -o NUL -X POST -H \"Content-Type: application/json\" --data-binary @- {url}"


# Pular as permissões (por projeto, desligado por padrão). O OpenCode não tem flag de linha de comando para isso — as
# permissões dele ficam no opencode.json ("permission") — então lá não muda nada.
BYPASS = {"claude": ["--dangerously-skip-permissions"], "codex": ["--dangerously-bypass-approvals-and-sandbox"],
          "gemini": ["--yolo"], "cursor": ["--force"]}
PROMPT_MAX = {"posix": 100_000, "nt": 24_000}   # acima disso o pedido vai num arquivo (limite de 32.767 da linha no Windows)
PROMPT_DIR = os.path.join(DATA, "prompts")


def agent_argv(prov, exe, prompt=None, mode=None, settings=None, extra_dirs=(), resume=None, bypass=False):
    """argv do agente (sem shell) — puro, para dar para testar. `exe` = executável (ou só o nome)."""
    args = [exe]
    if prov == "claude":
        if settings is not None:
            # dict vai como JSON; str é o caminho de um arquivo com ele (quando o cmd.exe estragaria as aspas e o &&)
            args += ["--settings", settings if isinstance(settings, str) else json.dumps(settings, ensure_ascii=False)]
        if bypass and mode == "plan":
            # planeja primeiro (modo plano); ao aprovar o plano dá para seguir sem pedir permissão
            args += ["--allow-dangerously-skip-permissions", "--permission-mode", "plan"]
        elif bypass:
            args += BYPASS["claude"]
        elif mode in ("plan", "acceptEdits", "default"):
            args += ["--permission-mode", mode]
        for d in extra_dirs or ():
            args += ["--add-dir", d]
    elif prov == "codex":
        if mode in ("readonly", "plan"):
            args += ["--sandbox", "read-only"]   # planejar não mexe em nada: sem bypass
        elif bypass:
            args += BYPASS["codex"]
    elif bypass and prov in BYPASS:
        args += BYPASS[prov]
    if resume and prov == "claude":
        args += ["--resume", resume]
    elif resume and prov == "codex":
        args = args + ["resume", resume]   # as opções (bypass/sandbox) valem antes do subcomando
    if prompt and (not resume or prov in ("claude", "codex")):
        # o pedido inicial (Claude/Codex também ao retomar: "continue de onde parou" na conversa retomada): Claude/Codex/cursor-agent aceitam como argumento (sessão interativa). O Gemini sem -i roda uma
        # vez e sai; o OpenCode trata o argumento solto como a PASTA do projeto — os dois pedem a flag.
        args += (["-i", prompt] if prov == "gemini" else ["--prompt", prompt] if prov == "opencode" else [prompt])
    return args


# ---------------------------------------------------------------- Windows: abrir o agente pelo PowerShell sem quebrar o pedido
# O jeito antigo (`claude --settings "{\"…\"}" "pedido"` dentro do -Command do PowerShell) quebrava de várias formas:
#   · o PowerShell não entende \" — o JSON das configurações e qualquer pedido com aspas viravam outros argumentos;
#   · $variável, `crase` e aspas “curvas” do pedido eram interpretados pelo PowerShell;
#   · o Windows PowerShell 5.1 não escapa aspas ao chamar programas (bug antigo) e bloqueia o claude.ps1 do npm
#     ("execução de scripts foi desabilitada");
#   · o claude.cmd do npm passa pelo cmd.exe, que CORTA o argumento na 1ª quebra de linha e mexe em %, ^, &, |, <, >.
# Agora: o executável de verdade (claude.exe, ou node + o .js que o .cmd do npm chamaria) é aberto pelo .NET
# (ProcessStartInfo) com a linha de comando montada aqui no padrão do Windows (list2cmdline), dentro de um script
# lido de arquivo — o PowerShell só vê textos entre aspas simples, sem interpretar nada do pedido.
def _ps_lit(s):
    """Texto literal do PowerShell (aspas simples). As aspas simples "curvas" (‘ ’ ‚ ‛) também fecham a string no
    PowerShell — dobradas como a reta."""
    return "'" + re.sub(r"(['‘’‚‛])", r"\1\1", s.replace("\0", "")) + "'"


def _ver_key(name):
    """'2025.10.02-a1b2c3' → (2025, 10, 2, …): ordena as pastas de versão pelo número, não pelo texto."""
    return tuple(int(x) for x in re.findall(r"\d+", name)[:6]) or (0,)


def win_resolve(path):
    """Executável real por trás de uma CLI no Windows: (programa, argumentos antes dos do usuário, passa_pelo_cmd).
    .exe → ele mesmo; .cmd/.bat do npm (cmd-shim) → o .exe/.js que ele chamaria (node + script); senão o próprio .cmd."""
    low = (path or "").lower()
    if not low.endswith((".cmd", ".bat")):
        return path, [], False
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return path, [], True
    # a linha que repassa os argumentos (%*): o último caminho relativo a %dp0% nela é o alvo (o 1º costuma ser o node.exe)
    hits = [h for line in text.splitlines() if "%*" in line
            for h in re.findall(r'"%~?dp0%?\\([^"%]+?\.(?:exe|js|cjs|mjs))"', line, re.I)]
    if not hits:
        # instalador do próprio CLI (cursor-agent): o .cmd chama um .ps1 que escolhe a versão em versions\<v>\ e roda o
        # node.exe dela. Pela cadeia cmd → PowerShell → node o agente abria janelas de console e se embaralhava no
        # terminal: vai direto no node + index.js da versão mais nova, quando estão lá
        vers = os.path.join(os.path.dirname(path), "versions")
        if os.path.isdir(vers):
            for v in sorted(os.listdir(vers), key=_ver_key, reverse=True):
                node, js = os.path.join(vers, v, "node.exe"), os.path.join(vers, v, "index.js")
                if os.path.isfile(node) and os.path.isfile(js):
                    return node, [js], False
        return path, [], True
    base = os.path.dirname(path)
    target = os.path.normpath(os.path.join(base, hits[-1].replace("\\", os.sep)))
    if not os.path.isfile(target):
        return path, [], True
    if target.lower().endswith(".exe"):
        return target, [], False
    node = os.path.join(base, "node.exe")
    node = node if os.path.isfile(node) else userpath.which("node")
    return (node, [target], False) if node else (path, [], True)


def win_launcher(argv, script_path):
    """(texto do script .ps1, comando curto para o -Command do PowerShell). argv[0] já resolvido (win_resolve)."""
    exe, rest = argv[0], argv[1:]
    lines = [
        "try { [Console]::OutputEncoding = $OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch {}",
        f"Remove-Item -LiteralPath {_ps_lit(script_path)} -ErrorAction SilentlyContinue",
        "$psi = New-Object System.Diagnostics.ProcessStartInfo",
        f"$psi.FileName = {_ps_lit(exe)}",
        f"$psi.Arguments = {_ps_lit(subprocess.list2cmdline(rest))}",
        "$psi.UseShellExecute = $false",
        "$psi.WorkingDirectory = (Get-Location).ProviderPath",
        "try { $p = [System.Diagnostics.Process]::Start($psi); $p.WaitForExit() }",
        f"catch {{ Write-Host ('Codeck: não abriu ' + {_ps_lit(os.path.basename(exe))} + ' — ' + $_.Exception.Message) -ForegroundColor Red }}",
    ]
    command = f"& ([scriptblock]::Create([IO.File]::ReadAllText({_ps_lit(script_path)})))"
    return "\r\n".join(lines) + "\r\n", command


def _sweep_prompts():
    os.makedirs(PROMPT_DIR, exist_ok=True)
    cutoff = time.time() - 7 * 86400
    for f in glob.glob(os.path.join(PROMPT_DIR, "*")):   # faxina: pedidos/lançadores de mais de 7 dias
        try:
            if os.path.getmtime(f) < cutoff:
                os.remove(f)
        except OSError:
            pass


def _prompt_to_file(sid, prompt):
    """Pedido grande demais para a linha de comando (ou que o cmd.exe estragaria): vai num arquivo e o agente lê."""
    _sweep_prompts()
    path = os.path.join(PROMPT_DIR, f"{sid}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(prompt)
    return path, f"Leia o pedido completo no arquivo {path} e siga-o."


def launch_spec(aid, prompt=None, mode=None, sid=None, extra_dirs=None, resume=None, bypass=False):
    """Comando + variáveis de ambiente para abrir o agente desta conta. `sid` = id da sessão (para a telemetria)."""
    a = get_account(aid)
    prov, spec = a["provider"], PROVIDERS[a["provider"]]
    nt = os.name == "nt"
    env = {}
    if spec["env"] and os.path.normpath(a["dir"]) != os.path.join(HOME, spec["home"]):
        env[spec["env"]] = a["dir"]   # a pasta padrão (~/.claude, ~/.codex) é a que a CLI já usa sem variável
    exe = which_all().get(spec["bin"]) or spec["bin"]
    via_cmd = False
    pre = []
    if nt:
        exe, pre, via_cmd = win_resolve(exe)
    secret = pysecrets.token_urlsafe(18)
    settings = None
    dirs = [d for d in extra_dirs or [] if os.path.isdir(d)]
    if prov == "claude":
        post = _hook_cmd(sid, secret)
        # a linha de status pode rodar no sh (macOS/Linux), no cmd ou no Git Bash (Windows): "a && b || b" vale nos três
        status_cmd = (f"{post} >/dev/null 2>&1; echo 'Codeck'" if not nt else f"{post} && echo Codeck || echo Codeck")
        settings = {"statusLine": {"type": "command", "command": status_cmd, "padding": 0},
                    "hooks": {ev: [{"hooks": [{"type": "command", "command": post}]}]
                              for ev in ("UserPromptSubmit", "Stop", "StopFailure", "Notification", "SubagentStop", "SessionStart", "PreCompact")}}
    if prompt:
        prompt = prompt.replace("\r\n", "\n").replace("\0", "")
        # pelo cmd.exe (sem achar o .exe/.js por trás do .cmd) o argumento não pode ter quebra de linha nem %^&|<>!"
        if len(prompt) > PROMPT_MAX["nt" if nt else "posix"] or (via_cmd and re.search(r'[\n%^&|<>!"]', prompt)):
            ppath, prompt = _prompt_to_file(sid, prompt)
            if prov == "claude":
                dirs.append(os.path.dirname(ppath))
    if settings is not None and via_cmd:
        # pelo cmd.exe as aspas do JSON e o "&&" da linha de status virariam outros comandos: vai num arquivo
        _sweep_prompts()
        spath = os.path.join(PROMPT_DIR, f"settings-{sid}.json")
        with open(spath, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False)
        settings = spath
    argv = agent_argv(prov, exe, prompt, mode, settings, dirs, resume, bypass)
    args = argv[:1] + pre + argv[1:]   # node + script.js do .cmd do npm, quando é o caso
    if not nt:
        command = " ".join(shlex.quote(x) for x in args)
    else:
        _sweep_prompts()
        script = os.path.join(PROMPT_DIR, f"launch-{sid}.ps1")
        text, command = win_launcher(args, script)
        with open(script, "w", encoding="utf-8-sig") as f:   # com BOM: o ReadAllText e o PowerShell 5.1 leem UTF-8 certo
            f.write(text)
    with _lock:
        _sessions[sid] = {"account": aid, "provider": prov, "secret": secret, "status": "starting", "started": time.time(),
                          "statusline": None, "events": [], "context": None, "model": None, "cost": None, "bypass": bool(bypass)}
    return command, env


# ---------------------------------------------------------------- telemetria
def hook(sid, secret, payload):
    """Recebe a linha de status e os hooks do Claude Code de uma sessão. Valida o segredo da sessão."""
    import hmac
    s = _sessions.get(sid)
    if not s or not hmac.compare_digest(secret or "", s["secret"]):
        raise PermissionError("sessão desconhecida")
    ev = payload.get("hook_event_name")
    with _lock:
        if ev:
            s["events"] = (s["events"] + [{"at": now_iso(), "event": ev, "message": payload.get("message")}])[-30:]
            s["claudeSession"] = payload.get("session_id") or s.get("claudeSession")
            was = s["status"]
            if ev == "UserPromptSubmit" and s.get("limit"):
                s.pop("limit", None)   # voltou a trabalhar (o limite resetou ou você seguiu nesta conta)
            limited = ev == "StopFailure" and (payload.get("error") in ("rate_limit", "billing_error") or bool(_LIMIT_RE.search(
                f"{payload.get('error_details') or ''} {payload.get('last_assistant_message') or ''}")))
            s["status"] = {"UserPromptSubmit": "working", "SessionStart": "idle", "Stop": "done", "StopFailure": "done",
                           "SubagentStop": s["status"], "Notification": "needs-you", "PreCompact": "compacting"}.get(ev, s["status"])
            if s.get("limit") and s["status"] != "working":
                s["status"] = "limited"
            # tempo trabalhando = da pergunta (UserPromptSubmit) até parar ou pedir você — medido aqui, pelos hooks
            if was == "working" and s["status"] != "working" and s.get("workSince"):
                s["workMs"] = (s.get("workMs") or 0) + int((time.time() - s.pop("workSince")) * 1000)
            elif s["status"] == "working" and not s.get("workSince"):
                s["workSince"] = time.time()
            s["statusAt"] = time.time()
            _record(sid, s)
        else:   # linha de status
            cw = payload.get("context_window") or {}
            s["model"] = (payload.get("model") or {}).get("display_name") or s["model"]
            cu = cw.get("current_usage") or {}
            s["context"] = {"used": cw.get("used_percentage"), "size": cw.get("context_window_size"),
                            "tokens": sum(v for k, v in cu.items() if isinstance(v, (int, float)) and "input" in k) if cu else None}
            cost = payload.get("cost") or {}
            s["cost"] = cost.get("total_cost_usd")
            s["lines"] = [cost.get("total_lines_added"), cost.get("total_lines_removed")] if "total_lines_added" in cost else s.get("lines")
            s["claudeSession"] = payload.get("session_id") or s.get("claudeSession")
            s["transcript"] = payload.get("transcript_path") or s.get("transcript")
            rl = payload.get("rate_limits")
            if rl:
                lim = _norm_claude_limits(rl)
                if lim:
                    _attribute(s, lim)
                    _usage[s["account"]] = {"rateLimits": lim, "updated": now_iso(), "source": "claude"}
                    save_json(USAGE_FILE, _usage)
                    _check_alerts(s["account"], lim)
            _record(sid, s)
    if s.get("claudeSession") and s.get("_remembered") != s["claudeSession"]:
        s["_remembered"] = s["claudeSession"]
        remember(sid, cliSession=s["claudeSession"])
    if ev == "StopFailure" and limited:
        text = _short(payload.get("error_details") or payload.get("last_assistant_message") or "", 260) or "limite de uso atingido"
        flag_limit(sid, text, parse_reset(text), source="hook")
        return {"ok": True}
    ui = (ctx.config or {}).get("ui") or {}
    if ev == "Notification" and ui.get("notify.agentNeedsYou", True):
        notify("Agente precisa de você", s.get("title") or "", (payload.get("message") or "")[:140], target=f"term/{sid}")
    elif ev == "Stop" and ui.get("notify.agentDone", True):
        notify("Agente terminou", s.get("title") or "", "Pronto para revisar", target=f"term/{sid}")
    return {"ok": True}


def _attribute(s, limits):
    """Quanto do limite a sessão gastou: a diferença entre esta leitura e a anterior da conta vai para a sessão que a
    trouxe (na mesma janela; janela nova = conta do zero). Com duas sessões da mesma conta ao mesmo tempo é uma estimativa:
    a leitura é da conta inteira, e quem reporta primeiro leva a diferença."""
    prev = {w["window"]: w for w in (_usage.get(s["account"]) or {}).get("rateLimits") or []}
    got = s.setdefault("limitUsed", {})
    for w in limits:
        used, p = w.get("used") or 0, prev.get(w["window"])
        if p and p.get("resetsAt") == w.get("resetsAt"):
            d = used - (p.get("used") or 0)
        elif p and w.get("resetsAt") and p.get("resetsAt") and _ts(w["resetsAt"]) - _ts(p["resetsAt"]) < 60:
            d = used - (p.get("used") or 0)   # o mesmo reset arredondado diferente
        else:
            d = used if p else 0   # janela nova: tudo dela é desta; sem leitura anterior não dá para saber
        if d > 0:
            k = f"{w['window']}|{w.get('resetsAt') or ''}"
            got[k] = round(got.get(k, 0) + d, 2)


def _ts(iso):
    import calendar
    try:
        return calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return 0


def _norm_claude_limits(rl):
    """Medido na linha de status do Claude Code 2.1.296: {"five_hour": {"used_percentage": 48, "resets_at": <epoch s>},
    "seven_day": {...}}. Aceita também a forma {utilization, resets_at ISO} que aparece em outras partes da CLI."""
    out = []
    for key, label in (("five_hour", "5 h"), ("seven_day", "semanal"), ("seven_day_opus", "semanal Opus"), ("seven_day_sonnet", "semanal Sonnet")):
        w = rl.get(key) or {}
        used = w.get("used_percentage", w.get("utilization"))
        if used is None:
            continue
        reset = w.get("resets_at")
        if isinstance(reset, (int, float)):
            reset = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(reset))
        out.append({"window": label, "used": used, "resetsAt": reset})
    return out


def _codex_scan(a, since=0):
    """Último token_count dos logs desta conta do Codex (sessões a partir de `since`)."""
    root = os.path.join(a["dir"], "sessions")
    files = sorted(glob.glob(os.path.join(root, "*", "*", "*", "*.jsonl")), key=os.path.getmtime, reverse=True)[:6]
    for f in files:
        if os.path.getmtime(f) < since:
            break
        last, cwd = None, None
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"token_count"' not in line and '"session_meta"' not in line:
                        continue
                    o = json.loads(line)
                    p = o.get("payload") or {}
                    if o.get("type") == "session_meta":
                        cwd = p.get("cwd")
                        a["_lastCodexSession"] = p.get("id") or p.get("session_id")
                    elif p.get("type") == "token_count":
                        last = p
        except (OSError, ValueError):
            continue
        if last:
            return last, cwd, os.path.getmtime(f)
    return None, None, 0


def _norm_codex_limits(rl):
    out = []
    for key, label in (("primary", "5 h"), ("secondary", "semanal")):
        w = (rl or {}).get(key)
        if not w:
            continue
        reset = w.get("resets_at")
        if reset is None and w.get("resets_in_seconds") is not None:
            reset = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + float(w["resets_in_seconds"])))
        elif isinstance(reset, (int, float)):
            reset = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(reset))
        mins = w.get("window_minutes")
        out.append({"window": (f"{mins // 60} h" if mins and mins < 1440 else "semanal") if mins else label,
                    "used": w.get("used_percent"), "resetsAt": reset})
    return out


def refresh_codex():
    for a in (x for x in _load()["accounts"] if x["provider"] == "codex"):
        tc, cwd, mtime = _codex_scan(a)
        if not tc:
            continue
        limits = _norm_codex_limits(tc.get("rate_limits"))
        if limits and (_usage.get(a["id"]) or {}).get("rateLimits") != limits:
            mine = [v for v in _sessions.values() if v["account"] == a["id"] and v["started"] - 5 <= mtime]
            if mine:
                _attribute(max(mine, key=lambda v: v["started"]), limits)
            _usage[a["id"]] = {"rateLimits": limits, "updated": now_iso(), "source": "codex",
                               "plan": (tc.get("rate_limits") or {}).get("plan_type")}
            save_json(USAGE_FILE, _usage)
            _check_alerts(a["id"], limits)
        info = tc.get("info") or {}
        for s in (v for v in _sessions.values() if v["account"] == a["id"] and v["started"] - 5 <= mtime):
            last, win = (info.get("last_token_usage") or {}).get("input_tokens"), info.get("model_context_window")
            if last and win:
                s["context"] = {"used": round(100 * last / win, 1), "size": win, "tokens": last}
            s["tokensTotal"] = (info.get("total_token_usage") or {}).get("total_tokens")
            _record_sid_of(s)
            sid = next((k for k, v in _sessions.items() if v is s), None)
            if sid and a.get("_lastCodexSession") and s.get("_remembered") != a["_lastCodexSession"]:
                s["_remembered"] = a["_lastCodexSession"]
                remember(sid, cliSession=a["_lastCodexSession"])


def session_info(sid):
    s = _sessions.get(sid)
    if not s:
        return None
    return {k: v for k, v in s.items() if k != "secret"}


def all_sessions():
    return {sid: session_info(sid) for sid in list(_sessions)}


def forget(sid):
    _sessions.pop(sid, None)


def discard(sid):
    """Você fechou o terminal do agente (ou o projeto): a sessão sai de tudo — estado, contexto e custo ao vivo, a oferta
    de retomar a conversa e os arquivos de pedido/lançador dela. O histórico de uso (custo por dia) fica. Ao SAIR do app
    não passa por aqui: lá a sessão continua retomável."""
    if not sid:
        return
    with _lock:
        _sessions.pop(sid, None)
    forget_resume(sid)
    _activity["at"] = 0   # as contas deixam de mostrar a sessão já na próxima leitura
    for name in (f"{sid}.md", f"settings-{sid}.json", f"launch-{sid}.ps1"):
        try:
            os.remove(os.path.join(PROMPT_DIR, name))
        except OSError:
            pass


def set_title(sid, title):
    if sid in _sessions:
        _sessions[sid]["title"] = title


# ---------------------------------------------------------------- alertas de limite e histórico de uso
_alerted = load_json(os.path.join(DATA, "ai-alerts.json"), {})


def _check_alerts(aid, limits):
    """Avisa (uma vez por janela) quando uma conta passa de 80% e de 95% de um limite."""
    try:
        a = get_account(aid)
    except LookupError:
        return
    for w in limits:
        used = w.get("used") or 0
        for th in (95, 80):
            if used >= th:
                key = f"{aid}|{w['window']}|{th}|{w.get('resetsAt')}"
                if key not in _alerted:
                    _alerted[key] = now_iso()
                    save_json(os.path.join(DATA, "ai-alerts.json"), dict(list(_alerted.items())[-200:]))
                    reset = ""
                    if w.get("resetsAt"):
                        try:
                            import calendar
                            reset = " — reseta " + time.strftime("%d/%m %H:%M", time.localtime(calendar.timegm(time.strptime(w["resetsAt"], "%Y-%m-%dT%H:%M:%SZ"))))
                        except ValueError:
                            pass
                    notify(f"{a['name']}: limite {w['window']} em {round(used)}%", PROVIDERS[a["provider"]]["label"],
                           ("Perto do fim — considere outra conta para tarefas novas" if th == 80 else "Quase esgotado") + reset, target="settings/ai")
                break


_hist = None
_hist_lock = threading.Lock()


def _history():
    global _hist
    if _hist is None:
        _hist = load_json(HISTORY_FILE, {})
    return _hist


def set_meta(sid, **meta):
    with _lock:
        if sid in _sessions:
            _sessions[sid].update(meta)


def _record(sid, s):
    """Guarda (com folga) o consumo da sessão: dia, projeto, conta, custo e tokens — a base da página de uso."""
    rec = {"day": time.strftime("%Y-%m-%d", time.localtime(s["started"])), "account": s["account"], "provider": s["provider"],
           "project": s.get("projectName"), "projectId": s.get("project"), "model": s.get("model"), "cost": s.get("cost"),
           "workMs": (s.get("workMs") or 0) + (int((time.time() - s["workSince"]) * 1000) if s.get("workSince") else 0),
           "lines": s.get("lines"), "limitUsed": dict(s.get("limitUsed") or {}),
           "tokens": (s.get("context") or {}).get("tokens"), "tokensTotal": s.get("tokensTotal"), "updated": now_iso()}
    with _hist_lock:
        h = _history()
        prev = h.get(sid)
        h[sid] = rec
        if not prev or any(prev.get(k) != rec[k] for k in ("cost", "limitUsed", "lines")) or s.get("status") != "working":
            if len(h) > 5000:
                for k in sorted(h, key=lambda k: h[k]["updated"])[: len(h) - 5000]:
                    h.pop(k, None)
            save_json(HISTORY_FILE, h)


def _record_sid_of(s):
    sid = next((k for k, v in _sessions.items() if v is s), None)
    if sid:
        _record(sid, s)


_focus = None
_focus_lock = threading.Lock()


def focus(repo_id, name, seconds):
    """Seu tempo com o projeto na tela: a tela manda um pulso a cada 30 s enquanto o projeto está à vista."""
    global _focus
    seconds = max(0, min(int(seconds or 0), 60))
    if not repo_id or not seconds:
        return
    with _focus_lock:
        if _focus is None:
            _focus = load_json(FOCUS_FILE, {})
        day = _focus.setdefault(time.strftime("%Y-%m-%d"), {})
        e = day.setdefault(repo_id, {"name": name, "s": 0})
        e["s"] += seconds
        e["name"] = name or e["name"]
        for k in sorted(_focus)[:-400]:
            _focus.pop(k, None)
        save_json(FOCUS_FILE, _focus)


def usage_report(days=30):
    """Uso de IA no período: por dia, conta e projeto — custo informado pela CLI, tokens, tempo do agente trabalhando,
    linhas alteradas, quanto de cada limite cada projeto gastou e seu tempo com cada projeto na tela."""
    global _focus
    days = max(1, int(days))
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - (days - 1) * 86400))
    rows = [r for r in _history().values() if r["day"] >= since]
    accs = {a["id"]: a for a in _load()["accounts"]}
    with _focus_lock:
        if _focus is None:
            _focus = load_json(FOCUS_FILE, {})
        focus_rows = [(d, rid, e) for d, v in _focus.items() if d >= since for rid, e in v.items()]
    blank = lambda: {"cost": 0.0, "sessions": 0, "tokens": 0, "workMs": 0, "added": 0, "removed": 0, "focusS": 0, "limits": {}}

    def add(g, r):
        g["cost"] += r.get("cost") or 0
        g["sessions"] += 1
        g["tokens"] += r.get("tokensTotal") or r.get("tokens") or 0
        g["workMs"] += r.get("workMs") or 0
        ln = r.get("lines") or [0, 0]
        g["added"] += ln[0] or 0
        g["removed"] += ln[1] or 0
        for k, v in (r.get("limitUsed") or {}).items():   # "5 h|reset" → soma por conta e janela
            kk = f"{r['account']}|{k.split('|')[0]}"
            g["limits"][kk] = round(g["limits"].get(kk, 0) + v, 2)

    projects, by_day, by_acc = {}, {}, {}
    for r in rows:
        key = r.get("projectId") or r.get("project") or "—"
        g = projects.setdefault(key, {**blank(), "name": r.get("project") or "sem projeto"})
        add(g, r)
        add(by_day.setdefault(r["day"], blank()), r)
        add(by_acc.setdefault(r["account"], blank()), r)
    for d, rid, e in focus_rows:
        projects.setdefault(rid, {**blank(), "name": e["name"]})["focusS"] += e["s"]
        by_day.setdefault(d, blank())["focusS"] += e["s"]
    # janela de limite em andamento: quanto dela cada projeto gastou (mesmo reset da leitura atual)
    current = []
    for aid, u in _usage.items():
        a = accs.get(aid)
        if not a:
            continue
        for w in u.get("rateLimits") or []:
            if w.get("resetsAt") and _ts(w["resetsAt"]) < time.time():
                continue   # já resetou e ainda não houve leitura nova
            k = f"{w['window']}|{w.get('resetsAt') or ''}"
            share = {}
            for r in _history().values():
                v = (r.get("limitUsed") or {}).get(k) if r["account"] == aid else None
                if v:
                    pk = r.get("projectId") or r.get("project") or "—"
                    share[pk] = {"name": r.get("project") or "sem projeto", "used": round((share.get(pk) or {}).get("used", 0) + v, 2)}
            current.append({"account": aid, "accountName": a["name"], "provider": a["provider"], "window": w["window"],
                            "used": w.get("used"), "resetsAt": w.get("resetsAt"), "projects": share})
    out_days = []
    for i in range(days):
        d = time.strftime("%Y-%m-%d", time.localtime(time.time() - (days - 1 - i) * 86400))
        out_days.append({"day": d, **by_day.get(d, blank())})
    tot = blank()
    for r in rows:
        add(tot, r)
    tot["focusS"] = sum(e["s"] for _, _, e in focus_rows)
    return {"days": out_days, "projects": projects, "total": tot["cost"], "sessions": len(rows), "totals": tot,
            "accounts": {(accs[k]["name"] if k in accs else k): v for k, v in by_acc.items()},
            "accountInfo": {k: {"name": a["name"], "provider": a["provider"]} for k, a in accs.items()}, "current": current}


# ---------------------------------------------------------------- sessões retomáveis (sobrevivem ao fechar o app)
RESUME_FILE = os.path.join(DATA, "ai-resume.json")


def _resume_db():
    return load_json(RESUME_FILE, {})


def remember(sid, **info):
    """Guarda o que é preciso para retomar a conversa depois (id da sessão da CLI, conta, projeto, tarefa, pasta)."""
    db = _resume_db()
    rec = db.get(sid, {})
    rec.update({k: v for k, v in info.items() if v is not None}, updated=now_iso())
    db[sid] = rec
    if len(db) > 400:
        for k in sorted(db, key=lambda k: db[k].get("updated", ""))[: len(db) - 400]:
            db.pop(k, None)
    save_json(RESUME_FILE, db)


def resumable(project=None, task=None, live_sids=()):
    out = []
    for sid, r in _resume_db().items():
        if sid in live_sids or not r.get("cliSession") or r.get("project") != project or (r.get("task") or None) != (task or None):
            continue
        out.append({"sid": sid, **r})
    return sorted(out, key=lambda r: r.get("updated", ""), reverse=True)[:6]


def forget_resume(sid):
    db = _resume_db()
    if db.pop(sid, None) is not None:
        save_json(RESUME_FILE, db)


def last_message(sid):
    """Última resposta do agente (texto), para publicar uma revisão na PR. Claude: o transcript da sessão; Codex: o log."""
    s = _sessions.get(sid) or {}
    path = s.get("transcript")
    if s.get("provider") == "codex" and not path:
        a = get_account(s["account"])
        files = sorted(glob.glob(os.path.join(a["dir"], "sessions", "*", "*", "*", "*.jsonl")), key=os.path.getmtime, reverse=True)[:1]
        path = files[0] if files else None
    if not path or not os.path.exists(path):
        raise LookupError("Ainda não há resposta desta sessão")
    last = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("type") == "assistant":   # Claude Code: {"type":"assistant","message":{"content":[{"type":"text","text":…}]}}
                parts = [c.get("text", "") for c in (o.get("message") or {}).get("content", []) if c.get("type") == "text"]
                if any(p.strip() for p in parts):
                    last = "\n".join(parts).strip()
            p = o.get("payload") or {}
            if p.get("type") == "agent_message" and p.get("message"):   # Codex
                last = p["message"].strip()
    if not last:
        raise LookupError("Ainda não há resposta desta sessão")
    return last


# ---------------------------------------------------------------- limite atingido no meio do trabalho → outra conta
# Quando a conta de um agente acaba (5 h, semanal, cota diária…), a sessão fica "limited": a tela mostra quanto falta
# para o reset e as outras contas para CONTINUAR o trabalho. Como se descobre que acabou:
#   · Claude Code: o hook StopFailure com error "rate_limit"/"billing_error" (o turno parou por causa do limite);
#   · qualquer CLI: a mensagem dela no terminal ("You've hit your limit · resets 3pm", "usage limit reached",
#     "Quota exceeded"…), lida no fim da saída depois que o terminal fica quieto — o agente para quando o limite acaba.
# O reset vem do texto ("resets 3pm", "try again in 2 hours") ou da última leitura de limite da conta.
_LIMIT_RE = re.compile(
    r"you['’]ve (?:hit|reached) your (?!fast\b|context\b)[\w' -]{0,30}?(?:limit|quota|budget)"
    r"|(?:usage|session|weekly|daily|5-hour|opus|sonnet|request|credit)[ -]?limits? (?:reached|exceeded|hit)"
    r"|(?:claude|codex|gemini|cursor)(?: ai)? usage limit reached"
    r"|you['’]re out of (?:usage )?(?:credits|requests)"
    r"|quota (?:exceeded|exhausted)|exhausted your (?:daily |monthly )?quota|resource[_ ]exhausted"
    r"|(?:usage|rate) limit (?:has been )?(?:reached|exceeded)"
    r"|limit will reset at", re.I)
_ANSI_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[PX^_][^\x1b]*\x1b\\|\x1b[@-Z\\-_]|[\x00-\x08\x0b-\x1f\x7f]")
_tails = {}   # sessão -> {"buf": últimos caracteres da saída, "at": última saída, "dirty": mudou desde a última olhada}


def strip_ansi(text):
    """Texto puro de uma saída de terminal: sem cores/movimentos de cursor; \\r volta ao começo da linha."""
    text = _ANSI_RE.sub(lambda m: "\n" if m.group(0) == "\r" else "", text.replace("\r\n", "\n"))
    return "\n".join(ln.rstrip() for ln in text.split("\n"))


def output_watcher(sid):
    """Assinante da saída do terminal do agente: guarda o fim dela para procurar a mensagem de limite."""
    def fn(data):
        if data is None:
            _tails.pop(sid, None)
            return
        t = _tails.setdefault(sid, {"buf": "", "at": 0.0, "dirty": False})
        t["buf"] = (t["buf"] + data.decode("utf-8", "replace"))[-16000:]
        t["at"], t["dirty"] = time.time(), True
    return fn


_MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}


def parse_reset(text, now=None):
    """Quando o limite reseta, pelo texto da CLI: "resets 3pm", "resets 3:30pm", "reset at 15:00", "resets Oct 24, 3pm",
    "try again in 1 hour 23 minutes", "try again at 3:05 PM". ISO UTC ou None."""
    now = now or time.time()
    low = text.lower()
    m = re.search(r"(?:try again|again|resets?|available) in ((?:\d+\s*(?:days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b[\s,and]*)+)", low)
    if m:
        secs = 0
        for n, unit in re.findall(r"(\d+)\s*(days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", m.group(1)):
            secs += int(n) * (86400 if unit.startswith("d") else 3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1)
        if secs:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + secs))
    m = re.search(r"(?:resets?|reset at|try again at|until|available at)\s+(?:at\s+)?(?:on\s+)?"
                  r"(?:(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(?:at\s+)?)?"
                  r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", low)
    if not m:
        return None
    mon, day, hh, mm, ap = m.groups()
    if not ap and not mm:
        return None   # "resets 5" sem hora clara
    hh, mm = int(hh), int(mm or 0)
    if ap:
        hh = hh % 12 + (12 if ap.startswith("p") else 0)
    if hh > 23 or mm > 59:
        return None
    lt = time.localtime(now)
    year, month, mday = lt.tm_year, (_MONTHS[mon] if mon else lt.tm_mon), (int(day) if day else lt.tm_mday)
    ts = time.mktime((year, month, mday, hh, mm, 0, 0, 0, -1))
    if ts <= now - 60:
        ts = time.mktime((year + 1, month, mday, hh, mm, 0, 0, 0, -1)) if mon else ts + 86400
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def find_limit(text):
    """A mensagem de limite no fim da saída (texto puro): (linha, reset ISO|None) ou None."""
    tail = text[-3500:]
    hit = None
    for m in _LIMIT_RE.finditer(tail):
        hit = m
    if not hit:
        return None
    start = tail.rfind("\n", 0, hit.start()) + 1
    end = tail.find("\n", hit.end())
    line = tail[start: end if end >= 0 else len(tail)].strip(" │|╭╰─⎿●✻*>·\t")
    if len(line) > 260:
        line = tail[max(0, hit.start() - 60): hit.end() + 120].strip()
    near = tail[hit.start(): hit.end() + 260]
    return line[:260], parse_reset(near)


def _limit_reset(aid):
    """O reset da janela que segurou a conta, pela última leitura de limite (a mais gasta)."""
    ws = [w for w in (_usage.get(aid) or {}).get("rateLimits") or [] if w.get("resetsAt") and _ts(w["resetsAt"]) > time.time()]
    if not ws:
        return None, None
    w = max(ws, key=lambda w: (w.get("used") or 0, -_ts(w["resetsAt"])))
    return w.get("resetsAt"), w.get("window")


def flag_limit(sid, text=None, reset=None, source="output"):
    """Marca a sessão como parada pelo limite e avisa (uma vez por parada)."""
    s = _sessions.get(sid)
    if not s:
        return
    with _lock:
        if s.get("limit") and s["status"] == "limited":
            if reset and not s["limit"].get("resetsAt"):
                s["limit"]["resetsAt"] = reset
            return
        known, window = _limit_reset(s["account"])
        if s.get("workSince"):
            s["workMs"] = (s.get("workMs") or 0) + int((time.time() - s.pop("workSince")) * 1000)
        s["limit"] = {"at": now_iso(), "text": text, "resetsAt": reset or known, "window": window, "source": source}
        s["status"], s["statusAt"] = "limited", time.time()
    _activity["at"] = 0
    try:
        a = get_account(s["account"])
    except LookupError:
        return
    when = ""
    if s["limit"]["resetsAt"]:
        when = " — reseta " + time.strftime("%d/%m %H:%M", time.localtime(_ts(s["limit"]["resetsAt"])))
    notify(f"{a['name']} atingiu o limite", s.get("title") or PROVIDERS[a["provider"]]["label"],
           f"O agente parou{when}. Continue em outra conta.", target=f"term/{sid}")


def clear_limit(sid):
    """Você dispensou o aviso (vai esperar o reset) ou a sessão voltou a trabalhar."""
    s = _sessions.get(sid)
    if s and s.get("limit"):
        with _lock:
            s.pop("limit", None)
            if s["status"] == "limited":
                s["status"] = "idle"
        t = _tails.get(sid)
        if t:
            t["buf"], t["dirty"] = "", False   # a mensagem velha não marca de novo
        _activity["at"] = 0


def limit_watch_loop():
    """Olha o fim da saída dos agentes que acabaram de ficar quietos (a CLI para quando o limite acaba)."""
    while True:
        time.sleep(1.5)
        try:
            for sid, t in list(_tails.items()):
                if not t["dirty"] or time.time() - t["at"] < 1.2:
                    continue
                t["dirty"] = False
                s = _sessions.get(sid)
                if not s or s.get("status") == "limited":
                    continue
                hit = find_limit(strip_ansi(t["buf"]))
                if hit:
                    flag_limit(sid, hit[0], hit[1])
        except Exception:  # noqa: BLE001 — o vigia não pode morrer
            pass


# ---------------------------------------------------------------- passar o trabalho para outra conta
HANDOFF_DIR = os.path.join(DATA, "handoffs")
# Economia de tokens: o pedido para o agente novo é CURTO (pedido original, os últimos passos e o estado do git); o
# histórico inteiro vai num arquivo que ele só lê se precisar. Retomar a conversa inteira (mesma CLI) é opção à parte.
BRIEF_ORIGINAL, BRIEF_RECENT, FULL_MAX = 6_000, 7_000, 200_000


def _short(v, n=160):
    v = re.sub(r"\s+", " ", str(v or "")).strip()
    return v if len(v) <= n else v[: n - 1] + "…"


def _tool_line(name, args):
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {"cmd": args}
    args = args if isinstance(args, dict) else {}
    key = next((args[k] for k in ("file_path", "path", "command", "cmd", "pattern", "url", "description", "prompt", "query") if args.get(k)), "")
    if isinstance(key, list):
        key = " ".join(map(str, key))
    return f"→ {name}" + (f": {_short(key)}" if key else "")


def _claude_turns(path):
    """(quem, texto) de um transcript do Claude Code — pedidos, respostas e as ferramentas usadas (sem as saídas)."""
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("isMeta") or o.get("isSidechain") or o.get("type") not in ("user", "assistant"):
                continue
            content = (o.get("message") or {}).get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            for c in content or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text" and (c.get("text") or "").strip():
                    txt = c["text"].strip()
                    if o["type"] == "user" and re.match(r"<(?:command-|local-command|system-reminder)", txt):
                        continue
                    out.append(("user" if o["type"] == "user" else "agent", txt))
                elif c.get("type") == "tool_use":
                    out.append(("tool", _tool_line(c.get("name"), c.get("input"))))
    return out


def _codex_rollout(a, session_id):
    files = glob.glob(os.path.join(a["dir"], "sessions", "*", "*", "*", f"*{session_id}*.jsonl"))
    return max(files, key=os.path.getmtime) if files else None


def _codex_turns(path):
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                p = (json.loads(line) or {}).get("payload") or {}
            except ValueError:
                continue
            if p.get("type") == "message" and p.get("role") in ("user", "assistant"):
                txt = "\n".join(c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict)).strip()
                if txt and not re.match(r"<(?:environment_context|user_instructions|permissions)", txt):
                    out.append(("user" if p["role"] == "user" else "agent", txt))
            elif p.get("type") in ("function_call", "custom_tool_call", "local_shell_call"):
                out.append(("tool", _tool_line(p.get("name") or "shell", p.get("arguments") or p.get("input") or p.get("action"))))
    return out


def _scrub(text):
    """Tira do histórico a própria mensagem de limite: senão o agente novo a mostra na tela e parece parado também."""
    return _LIMIT_RE.sub("[limite de uso atingido]", text)


def _git_state(cwd):
    def run(*args):
        try:
            r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL,
                               creationflags=0x08000000 if os.name == "nt" else 0)
            return r.stdout.rstrip()
        except (OSError, subprocess.SubprocessError):
            return ""
    branch = run("rev-parse", "--abbrev-ref", "HEAD")
    status = run("status", "--short")
    stat = run("diff", "HEAD", "--stat")
    log = run("log", "-3", "--format=%h %<(70,trunc)%s")
    return branch, status, stat, log


def _render_turns(turns, budget, newest_first_cut=True):
    """Os turnos em markdown, do fim para o começo, até caber em `budget` caracteres."""
    out, size = [], 0
    for who, txt in reversed(turns):
        piece = txt if who == "tool" else f"**{'Usuário' if who == 'user' else 'Agente'}:** {txt}"
        if size + len(piece) > budget:
            if not out:   # o último turno sozinho já não cabe: vai o fim dele
                out.append(piece[-budget:])
            out.append("… (antes disso: no arquivo do histórico completo)")
            break
        out.append(piece)
        size += len(piece) + 1
    return out[::-1]


def handoff_context(sid, scrollback=""):
    """Para outra conta continuar o trabalho: grava o histórico completo num arquivo e devolve (pedido curto, caminho).
    O pedido curto traz o pedido original, os últimos passos e o estado do git — o agente lê o arquivo só se precisar.
    Claude/Codex: do transcript/log da sessão; as demais: do que apareceu no terminal."""
    s = _sessions.get(sid) or {}
    rec = _resume_db().get(sid) or {}
    a = get_account(s.get("account") or rec.get("account"))
    turns = []
    try:
        if a["provider"] == "claude" and s.get("transcript") and os.path.isfile(s["transcript"]):
            turns = _claude_turns(s["transcript"])
        elif a["provider"] == "codex" and (s.get("cliSession") or rec.get("cliSession")):
            path = _codex_rollout(a, s.get("cliSession") or rec.get("cliSession"))
            if path:
                turns = _codex_turns(path)
    except OSError:
        turns = []
    if not turns:   # sem transcript: o terminal (texto puro), como um turno só do agente
        txt = re.sub(r"\n{3,}", "\n\n", strip_ansi(scrollback)).strip()
        turns = [("agent", "Saída do terminal:\n```\n" + txt[-FULL_MAX:] + "\n```")] if txt else []
    original = (s.get("prompt") or "").strip() or next((t for who, t in turns if who == "user"), "")
    cwd = s.get("cwd") or ""
    branch, status, stat, log = _git_state(cwd) if cwd and os.path.isdir(cwd) else ("", "", "", "")
    lim = s.get("limit") or {}
    reset = f" (reseta {time.strftime('%d/%m %H:%M', time.localtime(_ts(lim['resetsAt'])))})" if lim.get("resetsAt") else ""
    why = f"parou porque atingiu o limite de uso{reset}" if lim else "foi interrompido para trocar de conta"

    os.makedirs(HANDOFF_DIR, exist_ok=True)
    for f in glob.glob(os.path.join(HANDOFF_DIR, "*.md")):   # faxina: mais de 14 dias
        try:
            if os.path.getmtime(f) < time.time() - 14 * 86400:
                os.remove(f)
        except OSError:
            pass
    full = os.path.join(HANDOFF_DIR, f"{sid}-{time.strftime('%Y%m%d-%H%M%S')}.md")
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(_scrub("\n".join([f"# Histórico completo — {PROVIDERS[a['provider']]['label']} · {a['name']}", f"Pasta: {cwd}", "",
                                    "## Pedido original", original or "(não registrado)", "", "## Conversa",
                                    *_render_turns(turns, FULL_MAX)]) + "\n"))

    parts = [
        "# Continuação de trabalho (Codeck)",
        f"Você está assumindo o trabalho de outro agente de IA ({PROVIDERS[a['provider']]['label']} · {a['name']}), que {why}. "
        "CONTINUE de onde ele parou — não recomece e não desfaça o que já foi feito.",
        "",
        "1. Leia o pedido original e os últimos passos abaixo.",
        "2. Confira o estado atual dos arquivos (git status / git diff): as alterações dele já estão no disco.",
        "3. Siga a partir do último passo; se a última ação ficou pela metade, refaça só ela.",
        f"4. Só se faltar contexto, consulte o histórico completo em {full} (leia apenas as partes necessárias, para economizar tokens).",
        "5. Ao terminar, resuma o que foi concluído (incluindo o que o agente anterior já tinha feito).",
        "",
        f"Pasta: {cwd}" + (f" · branch {branch}" if branch else ""),
    ]
    if original:
        parts += ["", "## Pedido original", original if len(original) <= BRIEF_ORIGINAL else original[:BRIEF_ORIGINAL] + f" … (inteiro em {full})"]
    recent = _render_turns([t for t in turns if not (t[0] == "user" and t[1].strip() == original)], BRIEF_RECENT)
    last_ask = next((t for who, t in reversed(turns) if who == "user"), "")
    if last_ask and last_ask.strip() != original and not any(last_ask[:200] in r for r in recent):
        parts += ["", "## Último pedido do usuário", last_ask[:BRIEF_ORIGINAL]]
    if recent:
        parts += ["", "## Últimos passos (o mais recente no fim)", *recent]
    if status or stat or log:
        parts += ["", "## Estado do repositório agora"]
        if status:
            parts += ["git status --short:", "```", status[:3000], "```"]
        if stat:
            parts += ["git diff HEAD --stat:", "```", stat[-2000:], "```"]
        if log:
            parts += ["últimos commits:", "```", log, "```"]
    return _scrub("\n".join(parts) + "\n"), full


def carry_session(sid, new_aid):
    """Mesma CLI em outra conta: copia a conversa da sessão para a pasta da conta nova e devolve o id para retomar —
    o agente novo continua com o contexto inteiro. None quando não dá (aí vai o resumo)."""
    s = _sessions.get(sid) or {}
    rec = _resume_db().get(sid) or {}
    old, new = get_account(s.get("account") or rec.get("account")), get_account(new_aid)
    cli = s.get("claudeSession") or s.get("cliSession") or rec.get("cliSession")
    if not cli or old["provider"] != new["provider"]:
        return None
    try:
        if old["provider"] == "claude":
            src = s.get("transcript") or next(iter(glob.glob(os.path.join(old["dir"], "projects", "*", f"{cli}.jsonl"))), None)
            if not src or not os.path.isfile(src):
                return None
            dst_dir = os.path.join(new["dir"], "projects", os.path.basename(os.path.dirname(src)))
            os.makedirs(dst_dir, exist_ok=True)
            if os.path.normpath(os.path.dirname(src)) != os.path.normpath(dst_dir):
                shutil.copy2(src, os.path.join(dst_dir, os.path.basename(src)))
                side = os.path.splitext(src)[0]   # subagentes/anexos da sessão ficam numa pasta com o mesmo id
                if os.path.isdir(side):
                    shutil.copytree(side, os.path.join(dst_dir, os.path.basename(side)), dirs_exist_ok=True)
            return cli
        if old["provider"] == "codex":
            src = _codex_rollout(old, cli)
            if not src:
                return None
            rel = os.path.relpath(src, os.path.join(old["dir"], "sessions"))
            dst = os.path.join(new["dir"], "sessions", rel)
            if os.path.normpath(src) != os.path.normpath(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
            return cli
    except OSError:
        return None
    return None


def continue_prompt(sid, new_aid):
    """O pedido curto para quem retoma a MESMA conversa em outra conta."""
    s = _sessions.get(sid) or {}
    old = get_account(s["account"]) if s.get("account") else None
    who = f" ({old['name']})" if old else ""
    return ("A conta anterior" + who + " atingiu o limite de uso e esta conversa agora continua em outra conta. "
            "Continue exatamente de onde parou: confira o estado atual dos arquivos (git status / git diff) e siga com o que "
            "faltava, sem refazer o que já foi feito. Se a última ação ficou pela metade, refaça só ela.")


# ---------------------------------------------------------------- limite sem abrir sessão (sonda) e atividade das contas
PROBE_DIR = os.path.join(DATA, "probe")   # pasta vazia: a sonda não lê CLAUDE.md de projeto nenhum
_probing = {}   # conta -> início da sonda em andamento
_probe_err = {}   # conta -> {"error", "at"} da última sonda que falhou


def probe_limits(aid):
    """Lê o limite (5 h / semanal) de uma conta do Claude sem o usuário abrir sessão: um prompt mínimo no Haiku em modo
    -p com saída stream-json, que traz o evento rate_limit_event (o mesmo dado da linha de status). Custa uma fração de
    centavo e quase nada do limite. Não grava sessão (--no-session-persistence), sem ferramentas nem MCP. O app continua
    sem ler token nenhum: quem fala com a Anthropic é a própria CLI, com o login dela."""
    a = get_account(aid)
    if a["provider"] != "claude":
        raise ValueError("Só as contas do Claude Code dão para ler sem abrir sessão (o Codex lê pelo log das sessões)")
    exe = which_all().get("claude")
    if not exe:
        raise ValueError("Claude Code não encontrado nesta máquina")
    if _probing.get(aid) and time.time() - _probing[aid] < 120:
        raise ValueError("Já estou lendo o limite desta conta")
    from . import terminals
    env = terminals.clean_env()
    if os.path.normpath(a["dir"]) != os.path.join(HOME, ".claude"):
        env["CLAUDE_CONFIG_DIR"] = a["dir"]
    os.makedirs(PROBE_DIR, exist_ok=True)
    args = [exe, "-p", "Responda apenas: ok", "--model", "haiku", "--output-format", "stream-json", "--verbose",
            "--no-session-persistence", "--tools", "", "--strict-mcp-config"]
    _probing[aid] = time.time()
    try:
        r = subprocess.run(args, cwd=PROBE_DIR, env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                           creationflags=0x08000000 if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        _probe_err[aid] = {"error": "a CLI não respondeu em 2 min", "at": now_iso()}
        raise ValueError("A CLI do Claude não respondeu em 2 minutos") from None
    finally:
        _probing.pop(aid, None)
    info, error, cost = None, None, None
    for line in r.stdout.splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("type") == "rate_limit_event":
            info = o.get("rate_limit_info") or info
        elif o.get("type") == "result":
            cost = o.get("total_cost_usd")
            if o.get("is_error"):
                error = (o.get("result") or o.get("subtype") or "erro").strip()
    if not info:
        msg = error or (r.stderr or "").strip().splitlines()[-1:] or ["a CLI não informou o limite"]
        msg = msg if isinstance(msg, str) else msg[0]
        if re.search(r"expired|could not be refreshed", msg, re.I):
            msg = "o login desta conta expirou — abra o Claude com ela (botão Entrar) e faça /login"
        elif re.search(r"login|logged|auth|api key|401", msg, re.I):
            msg = "conta sem login — abra o Claude com ela (botão Entrar) e faça /login"
        _probe_err[aid] = {"error": msg[:200], "at": now_iso()}
        raise ValueError(f"{a['name']}: {msg[:200]}")
    wins = info.get("unifiedWindows") or {}
    raw = {k: {"used_percentage": round(float(v.get("utilization") or 0) * 100, 1), "resets_at": v.get("resetsAt")}
           for k, v in wins.items() if isinstance(v, dict)}
    if not raw and info.get("rateLimitType"):   # versões sem unifiedWindows: só a janela que está valendo
        raw = {info["rateLimitType"]: {"used_percentage": round(float(info.get("utilization") or 0) * 100, 1), "resets_at": info.get("resetsAt")}}
    lim = _norm_claude_limits(raw)
    with _lock:
        _usage[aid] = {"rateLimits": lim, "updated": now_iso(), "source": "probe", "status": info.get("status"),
                       "overage": info.get("isUsingOverage")}
        save_json(USAGE_FILE, _usage)
    _probe_err.pop(aid, None)
    _check_alerts(aid, lim)
    return {"rateLimits": lim, "cost": cost}


def _usage_age(aid):
    u = _usage.get(aid) or {}
    try:
        import calendar
        return time.time() - calendar.timegm(time.strptime(u["updated"][:19], "%Y-%m-%dT%H:%M:%S"))
    except (KeyError, TypeError, ValueError):
        return float("inf")


def auto_limits_loop():
    """Liga/desliga em Configurações → IA e agentes. Lê o limite das contas do Claude sem leitura recente (nem sessão
    aberta pelo app trazendo a linha de status), uma conta por vez."""
    time.sleep(20)
    while True:
        try:
            ui = (ctx.config or {}).get("ui") or {}
            from . import power
            if ui.get("ai.autoLimits", True) and not power.paused() and which_all().get("claude"):
                every = max(15, int(ui.get("ai.autoLimitsMinutes") or 60)) * 60
                live = {v["account"] for v in _sessions.values() if v.get("status") in ("working", "idle", "done", "needs-you")}
                for a in [x for x in _load()["accounts"] if x["provider"] == "claude"]:
                    err = _probe_err.get(a["id"])
                    if a["id"] in live or _usage_age(a["id"]) < every:
                        continue
                    if err and _ts(err["at"][:19] + "Z") > time.time() - max(every, 3 * 3600):
                        continue   # sem login/fora do ar: não insiste a cada volta
                    try:
                        probe_limits(a["id"])
                    except Exception:  # noqa: BLE001 — registrado em _probe_err; segue para a próxima conta
                        pass
        except Exception:  # noqa: BLE001
            pass
        time.sleep(300)


def _tail_json(path, max_bytes=65536):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            lines = f.read().decode("utf-8", "replace").splitlines()[1 if size > max_bytes else 0:]
    except OSError:
        return []
    out = []
    for ln in lines[-40:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def _external_sessions(a, known, repos_by_path):
    """Sessões desta conta abertas FORA do app (terminal, IDE): os transcripts modificados nos últimos 20 min."""
    out, now_t = [], time.time()
    if a["provider"] == "claude":
        files = glob.glob(os.path.join(a["dir"], "projects", "*", "*.jsonl"))
    elif a["provider"] == "codex":
        day = time.strftime("%Y/%m/%d")
        files = glob.glob(os.path.join(a["dir"], "sessions", *day.split("/"), "*.jsonl"))
    else:
        return out
    for f in files:
        try:
            age = now_t - os.path.getmtime(f)
        except OSError:
            continue
        sess = os.path.splitext(os.path.basename(f))[0]
        if age > 1200 or sess in known:
            continue
        tail = _tail_json(f)
        cwd, last, waiting = None, None, False
        for o in tail:
            cwd = o.get("cwd") or (o.get("payload") or {}).get("cwd") or cwd
            if o.get("sessionId") in known:
                cwd = None
                break
            t = o.get("type")
            if t in ("assistant", "user", "response_item", "event_msg"):
                last = o
        if a["provider"] == "codex" and not cwd:
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    first = json.loads(fh.readline() or "{}")
                cwd = (first.get("payload") or {}).get("cwd")
            except (OSError, ValueError):
                pass
        if not cwd or os.path.normpath(cwd) == os.path.normpath(PROBE_DIR):
            continue
        msg = (last or {}).get("message") or {}
        stop = msg.get("stop_reason") if isinstance(msg, dict) else None
        if last and last.get("type") == "assistant" and stop == "tool_use" and age > 25:
            waiting = True   # pediu para usar uma ferramenta e nada aconteceu: provavelmente esperando permissão
        status = "needs-you" if waiting else "working" if age < 25 else "done" if stop == "end_turn" else "idle"
        repo = repos_by_path.get(os.path.normcase(os.path.normpath(cwd)))
        out.append({"session": sess, "cwd": cwd, "project": repo["name"] if repo else os.path.basename(cwd.rstrip("/\\")),
                    "repoId": repo["id"] if repo else None, "status": status, "updatedAgo": int(age), "external": True})
    return sorted(out, key=lambda x: x["updatedAgo"])[:8]


_activity = {"at": 0, "data": {}}


def activity():
    """Para cada conta: o que ela está fazendo agora — sessões abertas pelo app (projeto, tarefa, estado) e sessões
    abertas fora dele —, o limite e a última sonda que falhou. Cache de 15 s."""
    if time.time() - _activity["at"] < 15:
        return _activity["data"]
    from . import git
    repos_by_path = {os.path.normcase(os.path.normpath(r["path"])): r for r in git._repos()}
    known = {v.get("claudeSession") for v in _sessions.values() if v.get("claudeSession")}
    known |= {r.get("cliSession") for r in _resume_db().values() if r.get("cliSession")}
    out = {}
    for a in _load()["accounts"]:
        mine = []
        for sid, v in list(_sessions.items()):
            if v["account"] != a["id"]:
                continue
            mine.append({"sid": sid, "project": v.get("projectName"), "repoId": v.get("project"), "task": v.get("task"),
                         "title": v.get("title"), "status": v.get("status"), "model": v.get("model"),
                         "context": (v.get("context") or {}).get("used"), "since": v.get("statusAt") or v.get("started")})
        try:
            ext = _external_sessions(a, known, repos_by_path)
        except Exception:  # noqa: BLE001
            ext = []
        states = [x["status"] for x in mine + ext]
        state_ = "needs-you" if "needs-you" in states else "working" if any(x in ("working", "compacting", "starting") for x in states) \
            else "done" if "done" in states else "idle" if states else "free"
        out[a["id"]] = {"sessions": mine, "external": ext, "state": state_, "probing": a["id"] in _probing,
                        "probeError": _probe_err.get(a["id"])}
    _activity.update(at=time.time(), data=out)
    return out


def open_login(aid):
    """Abre o terminal do sistema já na conta (CLAUDE_CONFIG_DIR/CODEX_HOME) com a CLI pronta para o login. O login é o
    da própria CLI: o app não vê nem guarda credencial."""
    a = get_account(aid)
    spec = PROVIDERS[a["provider"]]
    exe = which_all().get(spec["bin"]) or spec["bin"]
    env_line = {} if not spec["env"] or os.path.normpath(a["dir"]) == os.path.join(HOME, spec["home"]) else {spec["env"]: a["dir"]}
    args = [exe] + (["login"] if a["provider"] in ("codex", "cursor") else [])
    if sys.platform == "darwin":
        folder = os.path.join(DATA, "login")
        os.makedirs(folder, exist_ok=True)
        script = os.path.join(folder, f"{a['provider']}-{aid}.command")
        lines = ["#!/bin/zsh -l", "clear", f"echo 'Codeck · {spec['label']} · {a['name']}'"]
        lines += [f"export {k}={shlex.quote(v)}" for k, v in env_line.items()]
        if a["provider"] == "claude":
            lines.append("echo 'Digite /login, entre na conta e depois /exit.'")
        lines.append(" ".join(shlex.quote(x) for x in args))
        with open(script, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(script, 0o700)
        subprocess.Popen(["open", "-a", "iTerm" if os.path.isdir("/Applications/iTerm.app") else "Terminal", script], start_new_session=True)
    elif os.name == "nt":
        sets = " && ".join(f'set "{k}={v}"' for k, v in env_line.items())
        cmd = (sets + " && " if sets else "") + subprocess.list2cmdline(args)
        subprocess.Popen(["cmd", "/c", "start", "cmd", "/K", cmd], creationflags=0x00000008 | 0x08000000)
    else:
        raise ValueError("Abra um terminal e rode: " + " ".join(f"{k}={v}" for k, v in env_line.items()) + " " + " ".join(args))
    _probe_err.pop(aid, None)
    return {"ok": True}
