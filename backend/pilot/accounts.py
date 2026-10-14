"""Contas e preferências: organizações do Azure DevOps, contas do GitHub (token, gh CLI ou login pelo navegador),
intervalo de leitura, editor preferido e tema. Credenciais vão para o cofre (secrets.py); a tela nunca as recebe de volta."""
import os
import re
import time
import uuid

from . import catalogs, engine, git, github, secrets
from .azure import normalize_org_url
from .core import CONFIG_FILE, DATA, DEFAULT_PORT, ctx, load_json, save_json

THEMES = ("system", "dark", "light")
STORE_LABEL = {"keychain": "Keychain do macOS", "dpapi": "cofre do Windows (DPAPI)"}


def public_config():
    cfg = load_json(CONFIG_FILE, {})
    return {
        "pollSeconds": cfg.get("pollSeconds", 60),
        "editor": cfg.get("editor") or "vscode",
        "theme": cfg.get("theme") or "system",
        "workspaceRoots": cfg.get("workspaceRoots") or [],
        "editors": git.available_editors(),
        "port": cfg.get("port", DEFAULT_PORT),
        "dataDir": DATA,
        "orgs": [{"name": o["name"], "url": o["url"], "enabled": o.get("enabled", True),
                  "hasPat": bool(o.get("secret") or o.get("patCommand")), "patCommand": bool(o.get("patCommand")),
                  "patStore": STORE_LABEL.get((o.get("secret") or {}).get("store"), ""),
                  "me": (ctx.orgs[o["name"]].me if o["name"] in ctx.orgs else None)} for o in cfg.get("orgs", [])],
        "github": [{k: a.get(k) for k in ("id", "login", "name", "avatar", "scopes", "connectedAt", "source", "expiresAt", "renewedAt")} |
                   {"autoRenew": bool(a.get("refreshSecret")) or a.get("source") == "gh-cli",
                    "authError": (ctx.gh[a["id"]].auth_error if a["id"] in ctx.gh else None)} |
                   {"enabled": a.get("enabled", True), "store": STORE_LABEL.get((a.get("secret") or {}).get("store"), ""),
                    "rate": (ctx.gh[a["id"]].rate if a["id"] in ctx.gh else None)} for a in cfg.get("github", [])],
        "githubLogin": bool(github.client_id()),
        "ghCli": bool(github.gh_cli_path()),
        "ui": ui_prefs(cfg),
    }


UI_MAX = 120   # chaves de preferência da tela (editor, terminal, barra lateral…): só tipos simples, sem segredo


def ui_prefs(cfg=None):
    return dict((cfg if cfg is not None else load_json(CONFIG_FILE, {})).get("ui") or {})


def save_azure(body):
    current = load_json(CONFIG_FILE, {})
    old = {o["name"]: o for o in current.get("orgs", [])}
    orgs, names = [], set()
    for o in body.get("orgs", []):
        name, url = (o.get("name") or "").strip(), normalize_org_url(o.get("url"))
        if not name or not url.startswith("https://"):
            raise ValueError("Cada organização precisa de nome e URL https://")
        if name.lower() in names:
            raise ValueError(f"Nome repetido: {name}")
        names.add(name.lower())
        prev = old.get(o.get("originalName") or name, {})
        entry = {"id": prev.get("id") or uuid.uuid4().hex[:12], "name": name, "url": url, "enabled": bool(o.get("enabled", True))}
        pat = (o.get("pat") or "").strip()
        if pat:
            if not re.fullmatch(r"[A-Za-z0-9]{20,200}", pat):
                raise ValueError(f"{name}: o PAT tem caracteres inesperados — copie de novo do Azure")
            entry["secret"] = secrets.put(entry["id"], pat, secrets.AZURE)
        elif prev.get("secret"):
            entry["secret"] = prev["secret"]
        elif prev.get("patCommand"):
            entry["patCommand"] = prev["patCommand"]
        else:
            raise ValueError(f"{name}: informe o PAT")
        orgs.append(entry)
    kept = {e["id"] for e in orgs}
    for o in current.get("orgs", []):
        if o.get("id") and o["id"] not in kept:
            secrets.delete(o["id"], o.get("secret"))  # organização removida: some do cofre também
    cfg = {**current, "orgs": orgs, "pollSeconds": min(max(int(body.get("pollSeconds") or 60), 15), 3600)}
    save_json(CONFIG_FILE, cfg, private=True)
    engine.reload_accounts()




def add_github_token(token, source="token", grant=None):
    """Conecta (ou reconecta, mantendo o id e os ajustes) uma conta do GitHub. `grant` é a resposta do login pelo
    navegador: quando o GitHub entrega token que expira, vem junto o refresh token — o app renova sozinho depois."""
    token = (token or "").strip()
    if not re.fullmatch(r"(gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,250}|[a-f0-9]{40}", token):
        raise ValueError("Isso não parece um token do GitHub (começa com ghp_, gho_ ou github_pat_)")
    probe = github.GitHub({"id": "teste", "token": token})
    me = probe.identity()
    cfg = load_json(CONFIG_FILE, {})
    accounts = cfg.get("github", [])
    prev = next((a for a in accounts if a.get("login", "").lower() == me["login"].lower()), None)
    aid = prev["id"] if prev else uuid.uuid4().hex[:12]
    entry = {"id": aid, "login": me["login"], "name": me["name"], "avatar": me["avatar"], "scopes": probe.scopes,
             "secret": secrets.put(aid, token, secrets.GITHUB), "enabled": True, "source": source,
             "connectedAt": github.now_iso()}
    grant = grant or {}
    if grant.get("refresh_token"):
        entry["refreshSecret"] = secrets.put(aid + "-r", grant["refresh_token"], secrets.GITHUB)
    elif prev and prev.get("refreshSecret"):
        secrets.delete(aid + "-r", prev["refreshSecret"])   # reconectou com token que não expira: o refresh antigo sai
    if grant.get("expires_in"):
        entry["expiresAt"] = int(time.time() + int(grant["expires_in"]))
    if grant.get("refresh_token_expires_in"):
        entry["refreshExpiresAt"] = int(time.time() + int(grant["refresh_token_expires_in"]))
    cfg["github"] = [a for a in accounts if a["id"] != aid] + [entry]
    save_json(CONFIG_FILE, cfg, private=True)
    engine.reload_accounts()
    return {k: entry[k] for k in ("id", "login", "name", "avatar", "scopes")}


def remove_github(aid):
    cfg = load_json(CONFIG_FILE, {})
    for a in cfg.get("github", []):
        if a["id"] == aid:
            secrets.delete(aid, a.get("secret"))
            if a.get("refreshSecret"):
                secrets.delete(aid + "-r", a["refreshSecret"])
    cfg["github"] = [a for a in cfg.get("github", []) if a["id"] != aid]
    save_json(CONFIG_FILE, cfg, private=True)
    engine.reload_accounts()


def test_github(body):
    if body.get("token"):
        return github.test_account(github.GitHub({"id": "teste", "token": body["token"].strip()}))
    acc = ctx.gh.get(body.get("id"))
    if not acc:
        raise ValueError("Conta do GitHub não encontrada")
    acc.me = None   # força ler de novo (escopos podem ter mudado)
    return github.test_account(acc)


def save_prefs(body):
    cfg = load_json(CONFIG_FILE, {})
    if "pollSeconds" in body:
        cfg["pollSeconds"] = min(max(int(body.get("pollSeconds") or 60), 15), 3600)
    if body.get("editor") in git.EDITORS:
        cfg["editor"] = body["editor"]
    if body.get("theme") in THEMES:
        cfg["theme"] = body["theme"]
    if isinstance(body.get("workspaceRoots"), list):
        roots = []
        for p in body["workspaceRoots"][:30]:
            p = os.path.abspath(os.path.expanduser(str(p).strip()))
            if p not in roots and os.path.isdir(p):
                roots.append(p)
        cfg["workspaceRoots"] = roots
        ctx.config = cfg
        import threading
        threading.Thread(target=catalogs.discover, kwargs={"force": True}, daemon=True).start()   # já procura clones nelas
    if isinstance(body.get("ui"), dict):
        ui = dict(cfg.get("ui") or {})
        for k, v in body["ui"].items():
            k = str(k)[:60]
            if v is None:
                ui.pop(k, None)
            elif isinstance(v, (bool, int, float)) or (isinstance(v, str) and len(v) <= 2000):
                ui[k] = v
            elif isinstance(v, list) and len(v) <= 200 and all(isinstance(x, (str, int, float, bool)) for x in v):
                ui[k] = v
        cfg["ui"] = dict(list(ui.items())[-UI_MAX:])
    save_json(CONFIG_FILE, cfg, private=True)
    ctx.config = cfg
