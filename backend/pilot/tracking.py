"""Quais repositórios acompanhar: PRs, builds/Actions, deploys e issues/work items só dos repositórios escolhidos.

tracking.json: {"accounts": {"github:LMThomaz": {"mode": "all" | "selected"}},
                "repos": {"github:lmthomaz/codeck": {"track": bool, "prs": bool, "builds": bool, "deploys": bool,
                                                     "issues": bool, "notify": bool, "note": str}}}
  · Conta em "all" (o padrão, como sempre foi): acompanha tudo, menos os repositórios marcados para deixar de acompanhar.
  · Conta em "selected": só os repositórios marcados para acompanhar.
  · Por repositório dá para desligar só uma parte (ex.: acompanhar PRs e builds, mas não issues) e as notificações.
  · Work item do Azure e release sem build de Git não têm repositório: valem pelo PROJETO ("azure:org/projeto", sem o
    repo). Uma entrada do projeto com a categoria (ex.: {"issues": false}) decide por ele — acompanhar o deploy de um
    repositório não obriga a acompanhar os work items do projeto inteiro.
A chave do repositório é o remoto normalizado (git.normalize_remote): "github:dono/repo" ou "azure:org/projeto/repo",
em minúsculas — a mesma que casa catálogo, favorito e clone local.
"""
import os
import re
import threading

from .core import DATA, ctx, load_json, save_json

FILE = os.path.join(DATA, "tracking.json")
CATEGORIES = ("prs", "builds", "deploys", "issues")
_lock = threading.Lock()
_cache = {"data": None}


def _load():
    if _cache["data"] is None:
        d = load_json(FILE, {})
        _cache["data"] = {"accounts": d.get("accounts") or {}, "repos": d.get("repos") or {}}
    return _cache["data"]


def _save(d):
    _cache["data"] = d
    save_json(FILE, d)


def view():
    d = _load()
    return {"accounts": dict(d["accounts"]), "repos": dict(d["repos"])}


def set_account(key, mode):
    if mode not in ("all", "selected"):
        raise ValueError("modo inválido")
    with _lock:
        d = _load()
        d["accounts"][key] = {**d["accounts"].get(key, {}), "mode": mode}
        _save(d)
    return d["accounts"][key]


def set_repo(key, patch):
    key = (key or "").lower()
    if not key:
        raise ValueError("Repositório sem identificação")
    with _lock:
        d = _load()
        cur = dict(d["repos"].get(key) or {})
        for k in ("track", "notify", *CATEGORIES):
            if k in patch:   # None apaga a escolha: volta ao padrão (da conta ou do projeto)
                if patch[k] is None:
                    cur.pop(k, None)
                else:
                    cur[k] = bool(patch[k])
        if "note" in patch:
            cur["note"] = str(patch.get("note") or "")[:500]
        if patch.get("reset"):
            cur = {}
        if cur:
            d["repos"][key] = cur
        else:
            d["repos"].pop(key, None)
        _save(d)
    return cur


def set_many(keys, track):
    with _lock:
        d = _load()
        for k in keys or []:
            k = (k or "").lower()
            if k:
                d["repos"][k] = {**(d["repos"].get(k) or {}), "track": bool(track)}
        _save(d)
    return {"ok": True}


# ---------------------------------------------------------------- chave do repositório de cada item
def org_slug(name):
    """Organização do Azure pelo nome dado no app → o nome dela na URL (o que aparece no remoto do Git)."""
    org = ctx.orgs.get(name)
    url = (getattr(org, "url", "") or "").rstrip("/")
    m = re.match(r"https://([^./]+)\.visualstudio\.com", url)
    return (m.group(1) if m else url.rsplit("/", 1)[-1] or name).lower()


def item_key(item):
    """(chave do repositório, chave do projeto do Azure) de um PR/build/deploy/issue."""
    if item.get("provider") == "github":
        full = item.get("project") or item.get("repo") or ""
        return (f"github:{full}".lower() if "/" in full else None), None
    slug = org_slug(item.get("org"))
    proj = f"azure:{slug}/{item.get('project') or item.get('repo') or ''}".lower()
    repo = item.get("repo") if item.get("project") else None
    return (f"{proj}/{repo}".lower() if repo else None), proj


def account_key(item):
    return f"github:{item.get('account')}" if item.get("provider") == "github" else f"azure:{item.get('org')}"


def follows(item, category):
    """O item entra na lista? Considera o modo da conta, o repositório e a categoria."""
    d = _load()
    mode = (d["accounts"].get(account_key(item)) or {}).get("mode", "all")
    key, proj = item_key(item)
    if key:
        r = d["repos"].get(key)
        if r is not None and "track" in r:
            return r["track"] and r.get(category, True)
        if r is not None and not r.get(category, True):
            return False
        return mode == "all"
    # sem repositório (work item do Azure, release sem build de Git): vale o projeto — a escolha feita para o projeto,
    # senão entra se a conta acompanha tudo ou se algum repositório acompanhado é desse projeto
    p = d["repos"].get(proj) if proj else None
    if p is not None and category in p:
        return bool(p[category])
    if mode == "all":
        return True
    return bool(proj) and any(k.startswith(proj + "/") and v.get("track") and v.get(category, True) for k, v in d["repos"].items())


def quiet(item):
    key, _ = item_key(item)
    return bool(key) and (_load()["repos"].get(key) or {}).get("notify") is False


def apply(items, category):
    """Filtra a lista e marca em cada item a chave do repositório (a tela casa os itens com o repositório por ela)."""
    out = []
    for it in items:
        key, proj = item_key(it)
        it["repoKey"] = key
        it["scopeKey"] = key or proj   # o que a tela liga/desliga para este item (repositório ou projeto do Azure)
        if follows(it, category):
            if quiet(it):
                it["quiet"] = True
            out.append(it)
    return out


def watched_github():
    """Repositórios do GitHub marcados para acompanhar (entram na busca de PRs abertas e Actions)."""
    return [k[len("github:"):] for k, v in _load()["repos"].items() if k.startswith("github:") and v.get("track")]


def selected_accounts():
    return {k for k, v in _load()["accounts"].items() if v.get("mode") == "selected"}
