"""Bancos de dados: o cadastro, o vínculo com projetos, as conexões abertas e as regras de produção.

Cadastro (databases.json, só do seu usuário):
  - Banco: o que os projetos usam ("Cifal · Atual"). Tem pasta (etiqueta para organizar), cor, o motor (SQL Server,
    Postgres…) e os ambientes;
  - Ambiente: dev / hml / prod, cada um com host, porta, banco, usuário e a senha — que vai para o cofre do sistema
    (Keychain / DPAPI) e nunca volta para a tela;
  - Vínculo: cada banco tem a lista de projetos que o usam; um projeto pode usar vários bancos. O vínculo guarda o
    apelido no projeto e o ambiente ativo. É sempre explícito — o agente de um projeto só enxerga os bancos dele.

Produção: abre somente leitura (o plugin roda a consulta numa transação desfeita no fim, e somente leitura onde o
banco tem). Para alterar, a tela destrava a conexão; cada alteração roda numa transação que espera Confirmar ou
Desfazer, e se ninguém responder em 5 minutos é desfeita.

Conexão sem criptografia: só com o seu aceite explícito, e num IP público só com um segundo aceite (a senha iria
legível pela internet).
"""
import base64
import ipaddress
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import uuid

from . import dbplugins, dbtunnel, git, secrets
from .core import DATA, load_json, lock, now_iso, save_json
from .dbplugins import PluginError

FILE = os.path.join(DATA, "databases.json")
HISTORY_FILE = os.path.join(DATA, "db-history.jsonl")
KINDS = ("dev", "hml", "prod")
COLORS = ["#6F8CFF", "#3CCF91", "#F5B84F", "#FF6B7D", "#B07CFF", "#4FC3F7", "#FF8A50", "#9AA4B2"]
DEFAULT_PREFS = {"maxRows": 1000, "timeoutSec": 0, "history": True, "historyProd": False, "copyFormat": "tsv",
                 "png": {"dest": "clipboard", "dir": ""}, "queries": "local"}
TLS_MODES = ("verify", "pin", "off")


def _load():
    d = load_json(FILE, {})
    d.setdefault("banks", [])
    d["prefs"] = {**DEFAULT_PREFS, **(d.get("prefs") or {})}
    return d


def _save(d):
    save_json(FILE, d, private=True)


def _bank(d, bank_id):
    b = next((x for x in d["banks"] if x["id"] == bank_id), None)
    if not b:
        raise LookupError("Banco não encontrado")
    return b


def _env(b, env_id):
    e = next((x for x in b["envs"] if x["id"] == env_id), None)
    if not e:
        raise LookupError("Ambiente não encontrado")
    return e


def _public_env(e):
    out = {k: v for k, v in e.items() if k != "secret"}
    out["hasPassword"] = bool(e.get("secret"))
    return out


def _public_bank(b):
    return {**{k: v for k, v in b.items() if k != "envs"}, "envs": [_public_env(e) for e in b["envs"]]}


def public():
    d = _load()
    folders = sorted({b.get("folder") or "" for b in d["banks"]} - {""}, key=str.lower)
    return {"banks": [_public_bank(b) for b in d["banks"]], "folders": folders, "prefs": d["prefs"], "plugins": dbplugins.status(),
            "kinds": KINDS}


# ---------------------------------------------------------------- cadastro

def _clean_str(v, n=200):
    return str(v or "").strip()[:n]


def _clean_tls(t, prev=None):
    t = t or {}
    prev = prev or {}
    mode = t.get("mode") if t.get("mode") in TLS_MODES else prev.get("mode") or "verify"
    pin = re.sub(r"[^0-9a-f]", "", str(t.get("pin", prev.get("pin")) or "").lower())[:64]
    out = {"mode": mode, "pin": pin if len(pin) == 64 else "", "legacy": bool(t.get("legacy", prev.get("legacy")))}
    if out["legacy"] and t.get("rc4", prev.get("rc4")):   # compatibilidade RC4: só junto do modo de servidor antigo
        out["rc4"] = True
    if mode == "off":
        out["offAck"] = bool(t.get("offAck"))
        out["offPublicAck"] = bool(t.get("offPublicAck"))
    return out


def save_bank(body):
    """Cria ou altera um banco. A senha de cada ambiente vem só quando muda ("password"); "clearPassword" apaga."""
    name = _clean_str(body.get("name"), 80)
    if not name:
        raise ValueError("Dê um nome ao banco")
    engine = body.get("engine")
    if engine not in dbplugins.ENGINES:
        raise ValueError("Escolha o tipo de banco")
    with lock:
        d = _load()
        b = next((x for x in d["banks"] if x["id"] == body.get("id")), None) if body.get("id") else None
        if b is None:
            b = {"id": "b_" + uuid.uuid4().hex[:10], "created": now_iso(), "projects": [], "envs": [],
                 "color": COLORS[len(d["banks"]) % len(COLORS)]}
            d["banks"].append(b)
        elif b["engine"] != engine and b["envs"]:
            raise ValueError("O tipo do banco não muda depois de criado")
        b.update({"name": name, "engine": engine, "folder": _clean_str(body.get("folder"), 60), "notes": _clean_str(body.get("notes"), 2000)})
        if body.get("color") and re.fullmatch(r"#[0-9a-fA-F]{6}", body["color"]):
            b["color"] = body["color"]
        envs = []
        old = {e["id"]: e for e in b["envs"]}
        for raw in body.get("envs") or []:
            prev = old.pop(raw.get("id"), None) or {}
            kind = raw.get("kind") if raw.get("kind") in KINDS else "dev"
            e = {"id": prev.get("id") or "e_" + uuid.uuid4().hex[:10], "kind": kind, "label": _clean_str(raw.get("label"), 40),
                 "host": _clean_str(raw.get("host"), 255), "port": _port(raw.get("port")), "database": _clean_str(raw.get("database"), 128),
                 "user": _clean_str(raw.get("user"), 128), "file": _clean_str(raw.get("file"), 1024),
                 "tls": _clean_tls(raw.get("tls"), prev.get("tls")), "secret": prev.get("secret"),
                 "readOnly": bool(raw.get("readOnly", kind == "prod")), "timeoutSec": _port(raw.get("timeoutSec")) or None,
                 "ssh": dbtunnel.clean(raw.get("ssh")) if engine not in ("sqlite", "firebase", "libsql") else None}
            if engine == "sqlite":
                e["host"] = e["user"] = ""
                e["tls"] = {"mode": "off", "pin": "", "legacy": False}
            if engine == "libsql":   # a URL e o token bastam
                e["user"] = ""
            if engine == "firebase":   # HTTPS do Google, sempre verificado
                e["user"] = ""
                e["tls"] = {"mode": "verify", "pin": "", "legacy": False}
            if raw.get("clearPassword") and e["secret"]:
                secrets.delete(e["id"], e["secret"])
                e["secret"] = None
            if raw.get("password"):
                e["secret"] = secrets.put_text(e["id"], raw["password"])
            envs.append(e)
        for gone in old.values():   # ambiente removido: a senha sai do cofre também
            if gone.get("secret"):
                secrets.delete(gone["id"], gone["secret"])
        b["envs"] = envs
        _save(d)
    return {"bank": _public_bank(b), **public()}


def _port(v):
    try:
        n = int(v)
        return n if 0 < n < 65536 else None
    except (TypeError, ValueError):
        return None


def delete_bank(bank_id):
    with lock:
        d = _load()
        b = _bank(d, bank_id)
        for e in b["envs"]:
            if e.get("secret"):
                secrets.delete(e["id"], e["secret"])
        d["banks"] = [x for x in d["banks"] if x["id"] != bank_id]
        _save(d)
    for sid, s in list(_sessions.items()):
        if s["bank"] == bank_id:
            close(sid)
    return public()


def set_links(bank_id, add=(), remove=()):
    """Vincula/desvincula projetos de um banco (a tela manda vários de uma vez)."""
    known = {r["id"] for r in git._repos()}
    with lock:
        d = _load()
        b = _bank(d, bank_id)
        have = {p["repo"] for p in b["projects"]}
        for rid in add:
            if rid in known and rid not in have:
                b["projects"].append({"repo": rid, "alias": "", "env": None})
        b["projects"] = [p for p in b["projects"] if p["repo"] not in set(remove)]
        _save(d)
    return public()


def set_project_banks(repo_id, bank_ids):
    """O inverso: os bancos de um projeto (visão "Projetos" do Gerenciar)."""
    git.get_repo(repo_id)
    want = set(bank_ids)
    with lock:
        d = _load()
        for b in d["banks"]:
            linked = any(p["repo"] == repo_id for p in b["projects"])
            if b["id"] in want and not linked:
                b["projects"].append({"repo": repo_id, "alias": "", "env": None})
            elif b["id"] not in want and linked:
                b["projects"] = [p for p in b["projects"] if p["repo"] != repo_id]
        _save(d)
    return public()


LINK_FLAGS = ("agents", "agentsProdRead", "agentsWrite")   # agentes de IA (MCP): liberado / não perguntar de novo


def set_link(bank_id, repo_id, alias=None, env=None, flags=None):
    with lock:
        d = _load()
        b = _bank(d, bank_id)
        link = next((p for p in b["projects"] if p["repo"] == repo_id), None)
        if not link:
            raise LookupError("Este projeto não está vinculado ao banco")
        if alias is not None:
            link["alias"] = _clean_str(alias, 40)
        if env is not None:
            _env(b, env)
            link["env"] = env
        for k, v in (flags or {}).items():
            if k in LINK_FLAGS:
                link[k] = bool(v)
                if k == "agents" and not v:   # desligou: as permissões lembradas também saem
                    link.pop("agentsProdRead", None)
                    link.pop("agentsWrite", None)
        _save(d)
    return public()


def for_project(repo_id):
    """Os bancos do projeto, com o apelido e o ambiente ativo (o 1º não-prod, se nada foi escolhido)."""
    out = []
    for b in _load()["banks"]:
        link = next((p for p in b["projects"] if p["repo"] == repo_id), None)
        if not link:
            continue
        env = link.get("env") if any(e["id"] == link.get("env") for e in b["envs"]) else None
        if not env and b["envs"]:
            env = next((e["id"] for e in b["envs"] if e["kind"] != "prod"), b["envs"][0]["id"])
        out.append({**_public_bank(b), "link": {**link, "env": env}})
    return {"banks": out}


def set_rc4(bank_id, env_id, on=True):
    """Compatibilidade RC4 (SQL Server 2008/2008 R2 sem Service Pack): só por escolha, e liga o modo de servidor antigo."""
    with lock:
        d = _load()
        e = _env(_bank(d, bank_id), env_id)
        e["tls"] = {**e.get("tls", {}), "legacy": True, "rc4": bool(on)}
        if not on:
            e["tls"].pop("rc4", None)
        _save(d)
    return public()


def set_tls_off(bank_id, env_id):
    """Servidor sem TLS e você aceitou conectar assim (a tela já disse se o endereço é público): grava os dois aceites."""
    with lock:
        d = _load()
        e = _env(_bank(d, bank_id), env_id)
        e["tls"] = {**e.get("tls", {}), "mode": "off", "pin": "", "offAck": True, "offPublicAck": not _is_private(e["host"])}
        e["tls"].pop("rc4", None)
        _save(d)
    return public()


def pin_certificate(bank_id, env_id, sha256):
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        raise ValueError("Impressão digital inválida")
    with lock:
        d = _load()
        e = _env(_bank(d, bank_id), env_id)
        e["tls"] = {**e.get("tls", {}), "mode": "pin", "pin": sha256}
        _save(d)
    return public()


# ---------------------------------------------------------------- conexão

def _is_private(host):
    if "://" in (host or ""):   # URL (libSQL, MongoDB): vale o servidor dela
        import urllib.parse
        host = urllib.parse.urlparse(host).hostname or ""
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        cgnat = ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10")   # Tailscale e outras VPNs
        if not (ip.is_private or ip.is_loopback or ip.is_link_local or cgnat):
            return False
    return bool(addrs)


def _conn_params(b, e, database=None, password=None):
    tls = dict(e.get("tls") or {})
    if tls.get("mode") == "off" and b["engine"] != "sqlite":
        pub = not _is_private(e["host"])
        if not tls.get("offAck"):
            raise PluginError("tls-off-denied", "Conexão sem criptografia precisa do seu aceite nas configurações do ambiente", {"public": pub})
        if pub and not tls.get("offPublicAck"):
            raise PluginError("tls-off-public", f"{e['host']} é um endereço público: sem criptografia, a senha iria legível pela "
                              "internet. Use TLS (fixando o certificado) ou confirme o risco nas configurações do ambiente", {"public": True})
        tls["allowOff"] = True
    if password is None and e.get("secret"):
        password = secrets.get_text(e["id"], e["secret"])
    p = {"host": e.get("host"), "port": e.get("port") or 0, "database": database or e.get("database"), "user": e.get("user"),
         "password": password or "", "file": e.get("file"), "tls": tls, "timeoutSec": 20}
    if e.get("ssh") and b["engine"] not in ("sqlite", "firebase", "libsql"):   # pelo túnel: a conexão vai ao 127.0.0.1, o certificado é o do servidor real
        port = e.get("port") or dbplugins.ENGINES[b["engine"]]["port"]
        p["host"], p["port"] = "127.0.0.1", dbtunnel.acquire(e.get("id") or "test", e["ssh"], e["host"], port)
        p["options"] = {"tlsHost": e["host"]}
        p["_tunnel"] = e.get("id") or "test"
    return p


def _no_tls(err, e):
    """Servidor sem TLS: a tela pergunta se conecta sem criptografia — e avisa mais alto se o endereço é público."""
    if isinstance(err, PluginError) and err.code == "tls-unsupported":
        err.data = {**(err.data or {}), "public": not _is_private(e.get("host"))}
    return err


def test(body):
    """Testa uma conexão ainda não salva (ou o ambiente salvo, com a senha do cofre se não vier outra)."""
    engine = body.get("engine")
    b = {"engine": engine}
    e = dict(body.get("env") or {})
    e["tls"] = _clean_tls(e.get("tls"))
    if body.get("bank") and body.get("envId"):
        saved = _env(_bank(_load(), body["bank"]), body["envId"])
        e["id"], e["secret"] = saved["id"], saved.get("secret")
    e["ssh"] = dbtunnel.clean(e.get("ssh")) if engine not in ("sqlite", "firebase", "libsql") else None
    e["id"] = e.get("id") or "test"
    p = _conn_params(b, e, password=e.get("password") or None)
    tunnel = p.pop("_tunnel", None)
    try:
        plug = dbplugins.get(engine)
        res = plug.call("open", p, timeout=60)
        plug.call("close", {"session": res["session"]}, timeout=10)
    except PluginError as err:
        raise _no_tls(err, e)
    finally:
        if tunnel:
            dbtunnel.release(tunnel)
    return {"ok": True, "server": res.get("server"), "tls": res.get("tls"), "ssh": bool(tunnel)}


_sessions = {}
_slock = threading.Lock()


def open_session(bank_id, env_id, repo_id=None, database=None):
    d = _load()
    b = _bank(d, bank_id)
    e = _env(b, env_id)
    if repo_id and not any(p["repo"] == repo_id for p in b["projects"]):
        raise PluginError("not-linked", "Este banco não está vinculado ao projeto")
    plug = dbplugins.get(b["engine"])
    params = _conn_params(b, e, database)
    tunnel = params.pop("_tunnel", None)
    try:
        res = plug.call("open", params, timeout=60)
    except Exception as err:
        if tunnel:
            dbtunnel.release(tunnel)
        raise _no_tls(err, e)
    sid = "s_" + uuid.uuid4().hex
    prod = e["kind"] == "prod"
    s = {"id": sid, "bank": bank_id, "env": env_id, "engine": b["engine"], "kind": e["kind"], "plugin": res["session"], "repo": repo_id,
         "database": database or e.get("database") or "", "readOnly": prod and e.get("readOnly", True), "unlocked": False,
         "opened": time.time(), "server": res.get("server"), "tls": res.get("tls"), "pendingTx": None, "tunnel": tunnel}
    with _slock:
        _sessions[sid] = s
    return _public_session(s)


def _public_session(s):
    return {k: s.get(k) for k in ("id", "bank", "env", "engine", "kind", "repo", "database", "readOnly", "unlocked", "server", "tls", "pendingTx", "noWrite")}


def open_file_session(path, label, read_only=False, repo_id=None, bank_id=None, onwrite=None):
    """Sessão num arquivo SQLite fora do cadastro (banco do app Flutter). read_only: formato convertido (Hive…) ou
    aparelho que não recebe o banco de volta — a cópia é nossa, então o bloqueio é pela análise dos comandos."""
    plug = dbplugins.get("sqlite")
    res = plug.call("open", {"file": path}, timeout=60)
    sid = "s_" + uuid.uuid4().hex
    s = {"id": sid, "bank": bank_id, "env": "app", "engine": "sqlite", "kind": "dev", "plugin": res["session"], "repo": repo_id,
         "database": label, "readOnly": False, "unlocked": False, "opened": time.time(), "server": res.get("server"), "tls": None,
         "pendingTx": None, "noWrite": "Este banco abre só para leitura aqui" if read_only else None, "onwrite": onwrite}
    with _slock:
        _sessions[sid] = s
    return _public_session(s)


def reopen_file_session(sid, path):
    s = _get(sid)
    plug = dbplugins.get("sqlite")
    res = plug.call("open", {"file": path}, timeout=60)
    old, s["plugin"] = s["plugin"], res["session"]
    try:
        plug.call("close", {"session": old}, timeout=10)
    except PluginError:
        pass


def _get(sid):
    s = _sessions.get(sid)
    if not s:
        raise PluginError("no-session", "Conexão fechada — abra de novo")
    return s


def close(sid):
    with _slock:
        s = _sessions.pop(sid, None)
    if s:
        try:
            dbplugins.get(s["engine"]).call("close", {"session": s["plugin"]}, timeout=10)
        except PluginError:
            pass
        if s.get("onclose"):
            s["onclose"]()   # banco do app: apaga a pasta temporária com as cópias
        if s.get("tunnel"):
            dbtunnel.release(s["tunnel"])
    return {"ok": True}


def set_unlocked(sid, unlocked):
    """Produção: destravar (a tela já confirmou com você) libera alterações — cada uma ainda pede Confirmar."""
    s = _get(sid)
    s["unlocked"] = bool(unlocked)
    return _public_session(s)


def _plugin(s):
    return dbplugins.get(s["engine"])


def analyze(sid, sql):
    return _plugin(_get(sid)).call("analyze", {"sql": sql}, timeout=20)


def query(sid, sql, query_id=None, max_rows=None, confirm=False):
    """Roda o script com as regras do ambiente.

    - produção travada: só leitura; uma alteração volta "read-only" (a tela oferece destravar);
    - produção destravada: alteração só com confirm (a tela mostra o que vai rodar) e numa transação que espera
      Confirmar/Desfazer;
    - qualquer ambiente: UPDATE/DELETE sem WHERE, DROP e TRUNCATE pedem confirm.
    """
    s = _get(sid)
    if not (sql or "").strip():
        raise ValueError("Nada para executar")
    plug = _plugin(s)
    found = plug.call("analyze", {"sql": sql}, timeout=20) or []
    writes = any(a["write"] for a in found)
    risky = [a for a in found if a.get("noWhere") or a.get("drop")]
    prod = s["kind"] == "prod"
    if writes and s.get("noWrite"):
        raise PluginError("read-only-format", s["noWrite"], {"analysis": found})
    if prod and writes and (s["readOnly"] and not s["unlocked"]):
        raise PluginError("read-only", "Produção está em somente leitura — destrave esta conexão para alterar", {"analysis": found})
    if (risky or (prod and writes)) and not confirm:
        raise PluginError("confirm", "Confirme antes de executar", {"analysis": found, "prod": prod})
    prefs = _load()["prefs"]
    params = {"session": s["plugin"], "sql": sql, "queryId": query_id or "", "maxRows": int(max_rows or prefs["maxRows"]),
              "timeoutSec": prefs.get("timeoutSec") or 0}
    if prod and not writes:
        params["readOnly"] = True
    elif prod and s["engine"] not in dbplugins.DOCUMENTS:   # banco de documentos: a alteração vale na hora (confirmada antes)
        params["holdTx"] = True
    started = time.time()
    ok = False
    try:
        res = plug.call("query", params)
        ok = True
        if writes and s.get("onwrite"):
            s["onwrite"](sid)
        if res.get("txId"):
            s["pendingTx"] = {"id": res["txId"], "expires": res.get("txExpires")}
            res["pendingTx"] = s["pendingTx"]
        return res
    finally:
        _history(s, sql, ok, time.time() - started, prefs)


def finish_tx(sid, tx_id, commit):
    s = _get(sid)
    try:
        res = _plugin(s).call("commit" if commit else "rollback", {"session": s["plugin"], "txId": tx_id}, timeout=60)
    finally:
        s["pendingTx"] = None
    return res


def cancel(sid, query_id):
    s = _get(sid)
    return _plugin(s).call("cancel", {"queryId": query_id}, timeout=10)


def catalog(sid, what, schema=None, name=None):
    if what not in ("databases", "objects", "table"):
        raise ValueError("Pedido inválido")
    s = _get(sid)
    return _plugin(s).call(what, {"session": s["plugin"], "schema": schema or "", "name": name or ""}, timeout=90)


def apply(sid, changes, dry_run=False, confirm=False):
    s = _get(sid)
    if not isinstance(changes, list) or not changes:
        raise ValueError("Nenhuma edição para aplicar")
    if len(changes) > 5000:
        raise ValueError("Edições demais de uma vez (máximo 5.000)")
    if not dry_run and s.get("noWrite"):
        raise PluginError("read-only-format", s["noWrite"])
    if not dry_run and s["kind"] == "prod":
        if s["readOnly"] and not s["unlocked"]:
            raise PluginError("read-only", "Produção está em somente leitura — destrave esta conexão para alterar")
        if not confirm:
            raise PluginError("confirm", "Confirme antes de aplicar em produção", {"prod": True})
    res = _plugin(s).call("apply", {"session": s["plugin"], "changes": changes, "dryRun": bool(dry_run)}, timeout=180)
    if not dry_run and s.get("onwrite"):
        s["onwrite"](sid)
    return res


# ---------------------------------------------------------------- histórico (só neste computador)

_hlock = threading.Lock()


def _history(s, sql, ok, secs, prefs):
    if not prefs.get("history") or (s["kind"] == "prod" and not prefs.get("historyProd")):
        return
    import json
    line = json.dumps({"at": now_iso(), "bank": s["bank"], "env": s["env"], "repo": s["repo"], "ok": ok, "ms": int(secs * 1000),
                       "sql": sql[:20000]}, ensure_ascii=False)
    with _hlock:
        new = not os.path.exists(HISTORY_FILE)
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if new:
            os.chmod(HISTORY_FILE, 0o600)
        if os.path.getsize(HISTORY_FILE) > 8 << 20:   # guarda os ~8 MB mais recentes
            with open(HISTORY_FILE, encoding="utf-8") as f:
                keep = f.readlines()[-5000:]
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                f.writelines(keep)


def history(bank_id=None, repo_id=None, limit=200):
    import json
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            lines = f.readlines()[-5000:]
    except FileNotFoundError:
        return {"items": []}
    out = []
    for ln in reversed(lines):
        try:
            h = json.loads(ln)
        except ValueError:
            continue
        if (bank_id and h.get("bank") != bank_id) or (repo_id and h.get("repo") != repo_id):
            continue
        out.append(h)
        if len(out) >= limit:
            break
    return {"items": out}


def save_prefs(body):
    with lock:
        d = _load()
        p = d["prefs"]
        for k in ("history", "historyProd"):
            if k in body:
                p[k] = bool(body[k])
        if body.get("copyFormat") in ("tsv", "csv", "json", "markdown", "insert"):
            p["copyFormat"] = body["copyFormat"]
        if "maxRows" in body:
            p["maxRows"] = max(10, min(100000, int(body["maxRows"] or 1000)))
        if "timeoutSec" in body:
            p["timeoutSec"] = max(0, min(3600, int(body["timeoutSec"] or 0)))
        if isinstance(body.get("png"), dict):
            dest = body["png"].get("dest")
            p["png"] = {"dest": dest if dest in ("clipboard", "file", "both") else "clipboard", "dir": _clean_str(body["png"].get("dir"), 1024)}
        if body.get("queries") in ("local", "repo"):
            p["queries"] = body["queries"]
        _save(d)
    return public()


# ---------------------------------------------------------------- imagem do resultado (PNG)

def save_png(data_b64, name=None, copy=None, save=None):
    """Recebe o PNG desenhado pela tela: grava na pasta escolhida e/ou põe na área de transferência (conforme os
    ajustes, ou o que a tela pedir desta vez). Devolve o caminho do arquivo gravado."""
    png = base64.b64decode((data_b64 or "").split(",")[-1], validate=False)
    if not png.startswith(b"\x89PNG") or len(png) > 40 << 20:
        raise ValueError("Imagem inválida")
    dest = _load()["prefs"]["png"]
    copy = dest["dest"] in ("clipboard", "both") if copy is None else bool(copy)
    save = dest["dest"] in ("file", "both") if save is None else bool(save)
    slug = re.sub(r"[^\w\-]+", "-", (name or "resultado"))[:60].strip("-") or "resultado"
    path = None
    if save:
        folder = os.path.expanduser(dest.get("dir") or "~/Downloads")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}.png")
        with open(path, "wb") as f:
            f.write(png)
    if copy:
        src = path
        if not src:
            fd, src = tempfile.mkstemp(suffix=".png")
            with os.fdopen(fd, "wb") as f:
                f.write(png)
        try:
            _png_to_clipboard(src)
        finally:
            if not path:
                os.remove(src)
    return {"ok": True, "path": path, "copied": copy}


def _png_to_clipboard(path):
    if os.name == "nt":
        ps = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
              "$i = [System.Drawing.Image]::FromFile($env:CODECK_PNG); [System.Windows.Forms.Clipboard]::SetImage($i); $i.Dispose()")
        subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], env={**os.environ, "CODECK_PNG": path}, timeout=20, check=True,
                       capture_output=True, creationflags=0x08000000)
    else:
        # o caminho vai como argumento (argv), nunca colado dentro do script
        script = 'on run argv\nset the clipboard to (read (POSIX file (item 1 of argv)) as «class PNGf»)\nend run'
        subprocess.run(["/usr/bin/osascript", "-e", script, path], timeout=20, check=True, capture_output=True)
