"""Bancos de dados para os agentes de IA (MCP). Desligado por padrão — liga por banco, em cada projeto.

Como chega ao agente: ao abrir o agente de um projeto que tem banco liberado, o Codeck passa um servidor MCP pequeno
(backend/mcp_db.py, stdio) pela linha de comando do agente (Claude: --mcp-config; Codex: -c mcp_servers…) — nada é
gravado no repositório. Ele repassa cada chamada a POST /dbmcp/<token>; o token é do projeto e só vale nessa rota.

O que o agente enxerga: só os bancos vinculados ao projeto e liberados para agentes, no ambiente ativo do projeto (o
mesmo da aba Banco). Leitura roda numa transação somente leitura (o banco desfaz qualquer escrita escondida).

Quando pergunta (a tela mostra o comando e quem pediu; o sistema notifica):
  - leitura em produção: pergunta, com "não perguntar de novo" para este banco neste projeto;
  - alteração em dev/hml: pergunta, com "não perguntar de novo" para este banco neste projeto;
  - alteração em produção: SEMPRE pergunta. Sem resposta em 30 minutos, é negada.
"""
import json
import os
import secrets as pysecrets
import sys
import threading
import time
import uuid

from . import databases, dbplugins
from .core import BACKEND_DIR, DATA, DEFAULT_PORT, ctx, load_json, lock, notify, now_iso, save_json
from .dbplugins import PluginError

TOKENS_FILE = os.path.join(DATA, "db-mcp.json")
APPROVAL_TIMEOUT = 30 * 60
MAX_ROWS = 1000
SCRIPT = os.path.join(BACKEND_DIR, "mcp_db.py")

_pending = {}     # id → {info…, event, answer}
_plock = threading.Lock()
_sessions = {}    # (repo, bank, env) → sessão do databases


def _token(repo_id):
    with lock:
        d = load_json(TOKENS_FILE, {})
        for t, r in d.items():
            if r == repo_id:
                return t
        t = pysecrets.token_urlsafe(24)
        d[t] = repo_id
        save_json(TOKENS_FILE, d, private=True)
        return t


def _repo_of(token):
    import hmac
    for t, r in load_json(TOKENS_FILE, {}).items():
        if hmac.compare_digest(t, token or ""):
            return r
    raise PermissionError("token desconhecido")


def _banks(repo_id):
    """Os bancos do projeto liberados para agentes, com o ambiente ativo."""
    out = []
    for b in databases.for_project(repo_id)["banks"]:
        link = b["link"]
        if not link.get("agents"):
            continue
        env = next((e for e in b["envs"] if e["id"] == link["env"]), None)
        if env:
            out.append((b, env, link))
    return out


def enabled(repo_id):
    try:
        return bool(_banks(repo_id))
    except Exception:  # noqa: BLE001
        return False


def agent_launch(repo_id, provider, sid):
    """Argumentos extras para o agente receber o MCP de banco (ou [] se o projeto não liberou nenhum banco)."""
    if provider not in ("claude", "codex") or not enabled(repo_id):
        return []
    url = f"http://127.0.0.1:{getattr(ctx, 'port', None) or DEFAULT_PORT}/dbmcp/{_token(repo_id)}"
    py = sys.executable
    if os.name == "nt" and py.lower().endswith("pythonw.exe"):
        py = py[:-len("pythonw.exe")] + "python.exe"   # o MCP fala pelo stdio
    server = {"command": py, "args": ["-I", "-B", SCRIPT], "env": {"CODECK_DB_MCP": url}}
    if provider == "claude":
        d = os.path.join(DATA, "prompts")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"mcp-{sid}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"codeck-db": server}}, f)
        os.chmod(path, 0o600)   # tem o token do projeto
        return ["--mcp-config", path]
    toml = lambda v: json.dumps(v)   # strings e listas JSON valem como TOML
    return ["-c", f"mcp_servers.codeck-db.command={toml(py)}", "-c", f"mcp_servers.codeck-db.args={toml(server['args'])}",
            "-c", f'mcp_servers.codeck-db.env={{CODECK_DB_MCP={toml(url)}}}']


# ---------------------------------------------------------------- aprovações (a tela pergunta)

def pending():
    with _plock:
        return {"items": [{k: v for k, v in p.items() if k not in ("event", "answer")} for p in _pending.values()]}


def answer(pid, allow, remember=False):
    with _plock:
        p = _pending.get(pid)
    if not p:
        raise LookupError("Esse pedido já expirou")
    if allow and remember and p["remember"]:
        databases.set_link(p["bank"], p["repo"], flags={p["remember"]: True})
    p["answer"] = bool(allow)
    p["event"].set()
    return {"ok": True}


def _ask(repo, bank, env, sql, analysis, why, remember_key):
    pid = "a_" + uuid.uuid4().hex[:10]
    from . import git
    try:
        repo_name = git.get_repo(repo)["name"]
    except Exception:  # noqa: BLE001
        repo_name = repo
    p = {"id": pid, "repo": repo, "repoName": repo_name, "bank": bank["id"], "bankName": bank["name"], "env": env["kind"],
         "envName": env.get("label") or env["kind"], "sql": sql[:20000], "why": why, "remember": remember_key,
         "write": any(a.get("write") for a in analysis), "created": now_iso(), "expires": time.time() + APPROVAL_TIMEOUT,
         "event": threading.Event(), "answer": None}
    with _plock:
        _pending[pid] = p
    notify("Agente pede acesso ao banco", f"{repo_name} · {bank['name']} ({p['envName']})", why, target="data")
    p["event"].wait(APPROVAL_TIMEOUT)
    with _plock:
        _pending.pop(pid, None)
    return bool(p["answer"])


# ---------------------------------------------------------------- ferramentas

TOOLS = [
    {"name": "list_databases", "description": "Bancos de dados deste projeto liberados para o agente (nome, tipo, ambiente).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_tables", "description": "Tabelas, views e procedures (ou coleções) de um banco.",
     "inputSchema": {"type": "object", "properties": {"database": {"type": "string", "description": "nome do banco (de list_databases)"}}, "required": ["database"]}},
    {"name": "describe_table", "description": "Colunas, chave primária, chaves estrangeiras e índices de uma tabela.",
     "inputSchema": {"type": "object", "properties": {"database": {"type": "string"}, "table": {"type": "string"}, "schema": {"type": "string"}},
                     "required": ["database", "table"]}},
    {"name": "query", "description": "Executa SQL (ou o comando do MongoDB/Firebase) no banco. Leitura roda somente leitura; "
     "alteração pede aprovação da pessoa no Codeck (em produção, sempre). Devolve colunas e linhas em JSON.",
     "inputSchema": {"type": "object", "properties": {"database": {"type": "string"}, "sql": {"type": "string"},
                                                      "max_rows": {"type": "integer", "description": "padrão 200, máximo 1000"}},
                     "required": ["database", "sql"]}},
]


def _find(repo, name):
    banks = _banks(repo)
    for b, env, link in banks:
        if name in (b["id"], b["name"], link.get("alias")) or (name or "").lower() in (b["name"].lower(), (link.get("alias") or "").lower()):
            return b, env, link
    raise ValueError(f"Banco {name!r} não está liberado para agentes neste projeto. Use list_databases.")


def _session(repo, b, env):
    k = (repo, b["id"], env["id"])
    s = _sessions.get(k)
    if s and s in databases._sessions:
        return s
    s = databases.open_session(b["id"], env["id"], repo)["id"]
    _sessions[k] = s
    return s


def _call(repo, b, env, fn):
    try:
        return fn(_session(repo, b, env))
    except PluginError as e:
        if e.code in ("no-session", "plugin-died"):
            _sessions.pop((repo, b["id"], env["id"]), None)
            return fn(_session(repo, b, env))
        raise


def _cell(v):
    return v[:1000] + "…" if isinstance(v, str) and len(v) > 1000 else v


def handle(token, payload):
    repo = _repo_of(token)
    tool, args = payload.get("tool"), payload.get("args") or {}
    if tool == "__tools__":
        return {"ok": True, "result": TOOLS}
    try:
        return {"ok": True, "result": _tool(repo, tool, args)}
    except PluginError as e:
        return {"ok": False, "error": f"{e} ({e.code})"}
    except (ValueError, LookupError) as e:
        return {"ok": False, "error": str(e)}


def _tool(repo, tool, args):
    if tool == "list_databases":
        return [{"database": link.get("alias") or b["name"], "engine": dbplugins.ENGINES[b["engine"]]["label"], "environment": env["kind"],
                 "name": env.get("database") or "", "readOnly": env["kind"] == "prod"} for b, env, link in _banks(repo)]
    b, env, link = _find(repo, args.get("database"))
    if tool == "list_tables":
        return _call(repo, b, env, lambda s: databases.catalog(s, "objects"))
    if tool == "describe_table":
        return _call(repo, b, env, lambda s: databases.catalog(s, "table", args.get("schema") or "", args.get("table")))
    if tool != "query":
        raise ValueError(f"ferramenta desconhecida: {tool}")
    sql = str(args.get("sql") or "").strip()
    if not sql:
        raise ValueError("sql vazio")
    max_rows = max(1, min(MAX_ROWS, int(args.get("max_rows") or 200)))
    analysis = _call(repo, b, env, lambda s: databases.analyze(s, sql)) or []
    writes = any(a.get("write") for a in analysis)
    prod = env["kind"] == "prod"
    if writes and any(a.get("txControl") for a in analysis):
        raise ValueError("Comandos de transação (BEGIN/COMMIT/ROLLBACK) não são aceitos pelo MCP")
    if writes:
        why = "Alteração em PRODUÇÃO" if prod else "Alteração de dados"
        remember = None if prod else "agentsWrite"
        if not (remember and link.get(remember)) and not _ask(repo, b, env, sql, analysis, why, remember):
            raise ValueError("A pessoa negou (ou não respondeu em 30 minutos). Não tente de novo sem pedir a ela.")
    elif prod and not link.get("agentsProdRead"):
        if not _ask(repo, b, env, sql, analysis, "Leitura em produção", "agentsProdRead"):
            raise ValueError("A pessoa negou a leitura em produção (ou não respondeu em 30 minutos).")

    def run(s):
        params = {"session": databases._get(s)["plugin"], "sql": sql, "maxRows": max_rows, "timeoutSec": 120}
        if not writes:
            params["readOnly"] = True   # o banco desfaz qualquer escrita escondida numa "leitura"
        return dbplugins.get(b["engine"]).call("query", params, timeout=180)
    res = _call(repo, b, env, run)
    out = []
    for r in res.get("results") or []:
        item = {"statement": r.get("statement", "")[:200]}
        if r.get("columns"):
            item["columns"] = [c["name"] for c in r["columns"]]
            item["rows"] = [[_cell(v) for v in row] for row in r.get("rows") or []]
            if r.get("truncated"):
                item["truncated"] = True
                if r.get("total") is not None:
                    item["total"] = r["total"]
        if r.get("affected") is not None:
            item["affected"] = r["affected"]
        if r.get("messages"):
            item["messages"] = r["messages"]
        out.append(item)
    return out
