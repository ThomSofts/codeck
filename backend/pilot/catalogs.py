"""Catálogos de repositórios: agrupam repositórios remotos (de uma organização/projeto do Azure, de uma
organização/conta do GitHub ou avulsos) e mostram, para cada um, se está clonado nesta máquina.

catalogs.json: [{id, name, color, baseDir, sources: [{provider, account, owner, project}], extra: [chave], exclude: [chave]}]
Catálogos são MANUAIS e servem só para filtrar/agrupar. Quem gere é a CONTA: cada conta conectada lista todos os
repositórios dela (account_view) e guarda as PASTAS BASE onde os clones dela ficam (várias: …/apis, …/mobile…). As
pastas das contas servem para reconhecer clones existentes e são o destino sugerido ao clonar.

A lista remota de cada origem fica em cache (remote-cache.json, em disco): é relida após 10 minutos, mas a última
lista boa continua valendo sem internet e alimenta os contadores do painel. O casamento com o clone local é pela URL
do remoto normalizada (https/ssh/.git dão a mesma chave).
"""
import os
import re
import time
import uuid

from . import git
import threading

from .core import CATALOGS_FILE, DATA, ctx, is_network_error, load_json, save_json

CACHE_FILE = os.path.join(DATA, "remote-cache.json")
ACCOUNT_DIRS_FILE = os.path.join(DATA, "account-dirs.json")   # "provider:conta" -> [pastas base]
_cache_lock = threading.Lock()
_remote_cache = None   # "provider|conta|owner|projeto" -> [ts, repos]; carregado do disco na 1ª vez
COLORS = ["#3F8CF0", "#22C38E", "#F0A23F", "#E5577B", "#8B6CF0", "#2EC4D6", "#F06A3F", "#9AA4B2"]


def load():
    return load_json(CATALOGS_FILE, [])


def save(cats):
    save_json(CATALOGS_FILE, cats)


def _clean_source(s):
    prov = s.get("provider")
    if prov not in ("azure", "github"):
        raise ValueError("origem inválida")
    return {"provider": prov, "account": (s.get("account") or "").strip(), "owner": (s.get("owner") or "").strip() or None,
            "project": (s.get("project") or "").strip() or None}


def upsert(body):
    cats = load()
    name = (body.get("name") or "").strip()
    if not name:
        raise ValueError("Dê um nome ao catálogo")
    cid = body.get("id") or uuid.uuid4().hex[:10]
    entry = {
        "id": cid, "name": name[:60], "color": body.get("color") or COLORS[len(cats) % len(COLORS)],
        "baseDir": None,   # pasta-base é da conta (account-dirs); catálogo só filtra/agrupa
        "sources": [_clean_source(s) for s in body.get("sources", [])],
        "extra": [str(x) for x in body.get("extra", [])][:500], "exclude": [str(x) for x in body.get("exclude", [])][:500],
        "description": (body.get("description") or "").strip()[:200],
    }
    idx = next((i for i, c in enumerate(cats) if c["id"] == cid), None)
    if idx is None:
        cats.append(entry)
    else:
        cats[idx] = entry
    save(cats)
    return entry


def delete(cid):
    save([c for c in load() if c["id"] != cid])


def _account(provider, account):
    if provider == "azure":
        org = ctx.orgs.get(account) or next(iter(ctx.orgs.values()), None)
        if not org:
            raise ValueError(f"Organização do Azure {account} não está conectada")
        return org
    acc = next((a for a in ctx.gh.values() if a.login.lower() == (account or "").lower()), None) or next(iter(ctx.gh.values()), None)
    if not acc:
        raise ValueError("Nenhuma conta do GitHub conectada")
    return acc


def _cache():
    global _remote_cache
    if _remote_cache is None:
        _remote_cache = load_json(CACHE_FILE, {})
    return _remote_cache


def _ckey(source):
    return "|".join(str(source.get(k) or "") for k in ("provider", "account", "owner", "project")).lower()


def cached(source):
    hit = _cache().get(_ckey(source))
    return hit[1] if hit else None


def fetch(source, force=False):
    """(repos, desde_quando_sem_atualizar | None). Sem internet, devolve a última lista boa (marcada como antiga)."""
    k = _ckey(source)
    hit = _cache().get(k)
    if not force and hit and time.time() - hit[0] < 600:
        return hit[1], None
    try:
        acc = _account(source["provider"], source["account"])
        repos = acc.list_repos(source.get("project")) if source["provider"] == "azure" else acc.list_repos(source.get("owner"))
    except Exception as e:  # noqa: BLE001
        if hit and is_network_error(e):
            return hit[1], hit[0]
        raise
    with _cache_lock:
        _cache()[k] = [time.time(), repos]
        save_json(CACHE_FILE, _cache())
    return repos, None


def remote_repos(source, force=False):
    return fetch(source, force)[0]


# ---------------------------------------------------------------- pastas de trabalho (várias pastas base)
# Os clones vivem espalhados (…/cifal/apis, …/cifal/mobile…). Pastas de trabalho = as configuradas em Preferências +
# as pastas onde já há repositórios registrados. Elas servem para (1) reconhecer sozinho clones feitos fora do app e
# (2) oferecer o destino na hora de clonar.
_discover = {"at": 0.0}


def account_dirs(key):
    v = load_json(ACCOUNT_DIRS_FILE, {}).get(key)
    return [v] if isinstance(v, str) else list(v or [])   # versões anteriores guardavam uma pasta só


def set_account_dirs(key, dirs):
    clean = []
    for p in dirs or []:
        p = os.path.abspath(os.path.expanduser(str(p).strip())) if str(p).strip() else ""
        if p and p not in clean:
            clean.append(p)
    data = load_json(ACCOUNT_DIRS_FILE, {})
    data[key] = clean[:30]
    save_json(ACCOUNT_DIRS_FILE, data)
    _discover["at"] = 0   # já procura clones nas pastas novas na próxima leitura
    return clean


def add_account_dir(key, path):
    return set_account_dirs(key, account_dirs(key) + [path])


def workspace_roots():
    """Todas as pastas base: as das contas (+ as de Preferências de versões anteriores)."""
    out = []
    for v in load_json(ACCOUNT_DIRS_FILE, {}).values():
        out += [v] if isinstance(v, str) else (v or [])
    out += [os.path.expanduser(p) for p in (ctx.config.get("workspaceRoots") or []) if p]
    return list(dict.fromkeys(out))


def clone_targets(account=None):
    """Destinos para clonar: primeiro as pastas base da conta do repositório, depois as das outras contas e as pastas
    onde já há clones — cada uma com quantos repositórios tem."""
    counts = {}
    for r in git.list_repos(with_status=False):
        if r.get("exists"):
            parent = os.path.dirname(r["path"].rstrip(os.sep))
            counts[parent] = counts.get(parent, 0) + 1
    mine = account_dirs(account) if account else []
    out = [{"path": p, "count": counts.pop(p, 0), "configured": True, "account": True} for p in mine]
    out += [{"path": p, "count": counts.pop(p, 0), "configured": True, "account": False} for p in workspace_roots() if p not in mine]
    out += [{"path": p, "count": n, "configured": False, "account": False} for p, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    home = os.path.expanduser("~")
    for t in out:
        t["label"] = os.path.basename(t["path"].rstrip(os.sep)) or t["path"]
        t["short"] = t["path"].replace(home, "~", 1)
    return out


_discover_lock = threading.Lock()


def discover(force=False):
    """Registra os repositórios encontrados nas pastas de trabalho (no máximo a cada 2 min). Pastas base configuradas
    são vasculhadas 3 níveis abaixo (…/cifal/apis/<api>); as pastas onde já há clones, 1 nível."""
    if not force and time.time() - _discover["at"] < 120:
        return {"found": 0, "new": 0}
    with _discover_lock:
        _discover["at"] = time.time()
        found = new = 0
        for t in clone_targets():
            try:
                r = git.scan(t["path"], depth=3 if t["configured"] else 1)
                found, new = found + r["found"], new + r["new"]
            except Exception:  # noqa: BLE001 — pasta removida ou sem permissão
                continue
        return {"found": found, "new": new}


def local_index():
    """remoteKey normalizada -> repositório local registrado (com status resumido)."""
    out = {}
    for r in git.list_repos(with_status=True):
        if r.get("remoteKey"):
            out[r["remoteKey"]] = r
    return out


def _build(meta, sources, exclude=(), force=False):
    repos, errors, seen, stale = [], {}, set(), None
    for s in sources:
        try:
            got, old = fetch(s, force)
            stale = min(stale or old, old) if old else stale
            for r in got:
                if r["key"] not in seen:
                    seen.add(r["key"])
                    repos.append(r)
        except Exception as e:  # noqa: BLE001
            label = f"{s['provider']}:{s.get('owner') or s.get('project') or s['account']}"
            errors[label] = "sem conexão — a lista aparece quando a internet voltar" if is_network_error(e) else str(e)[:240]
    exclude = set(exclude or [])
    repos = [dict(r) for r in repos if r["key"] not in exclude]
    discover()
    local = local_index()
    for r in repos:
        lk = git.normalize_remote(r.get("cloneUrl") or r.get("sshUrl") or "")
        loc = local.get(lk)
        r["remoteKey"] = lk
        r["local"] = {k: loc.get(k) for k in ("id", "path", "status", "lastCommit", "exists", "pinned")} if loc else None
        r["cloned"] = bool(loc and loc.get("exists"))
        r["accountKey"] = f"{r['provider']}:{r['account']}"
    repos.sort(key=lambda r: (not r["cloned"], (r.get("updated") or "") == "", (r.get("name") or "").lower()))
    return {**meta, "repos": repos, "errors": errors, "staleSince": stale,
            "counts": {"total": len(repos), "cloned": sum(r["cloned"] for r in repos)}}


def view(cid, force=False):
    if cid and cid.startswith("account:"):
        return account_view(cid[8:], force)
    cat = next((c for c in load() if c["id"] == cid), None)
    if not cat:
        raise ValueError("Catálogo não encontrado")
    return _build(cat, cat["sources"], cat.get("exclude"), force)


# ---------------------------------------------------------------- contas: todos os repositórios de cada uma
def accounts():
    return [{"key": f"{p}:{n}", "provider": p, "name": n} for p, n in _connected()]


def _account_source(key):
    prov, _, name = key.partition(":")
    if (prov, name) not in _connected():
        raise ValueError("Conta não está conectada")
    return {"provider": prov, "account": name, "owner": None, "project": None}


def account_view(key, force=False):
    prov, _, name = key.partition(":")
    meta = {"id": "account:" + key, "name": name, "provider": prov, "account": True, "sources": [_account_source(key)],
            "color": "", "extra": [], "exclude": []}
    return {**_build(meta, meta["sources"], (), force), "dirs": account_dirs(key)}


def summary():
    """Catálogos e contas com a contagem de repositórios — do cache; None enquanto a lista ainda não foi lida."""
    def count(sources, exclude=()):
        keys = set()
        for s in sources:
            got = cached(s)
            if got is None:
                return None
            keys |= {r["key"] for r in got}
        return len(keys - set(exclude or []))
    return {"catalogs": [{**c, "count": count(c["sources"], c.get("exclude"))} for c in load()],
            "accounts": [{**a, "count": count([_account_source(a["key"])]), "dirs": account_dirs(a["key"])} for a in accounts()]}


def warm():
    """Lê (se o cache estiver velho) a lista de cada conta e de cada catálogo — os contadores do painel saem daqui."""
    srcs = [_account_source(a["key"]) for a in accounts()] + [s for c in load() for s in c["sources"]]
    for s in srcs:
        try:
            fetch(s)
        except Exception:  # noqa: BLE001 — sem rede ou sem permissão: o contador só fica vazio
            continue


def warm_async():
    threading.Thread(target=warm, daemon=True).start()


def cleanup_auto():
    """A 2.0.0+10 criava um catálogo por projeto/org ao conectar a conta; agora a conta lista tudo e os catálogos são
    só os do usuário. Remove os automáticos (marcados com "auto") e o registro deles."""
    cats = load()
    keep = [c for c in cats if not c.get("auto")]
    if len(keep) != len(cats):
        save(keep)
    if os.path.exists(os.path.join(DATA, "catalogs-auto.json")):
        os.remove(os.path.join(DATA, "catalogs-auto.json"))
    migrate_dirs()


def migrate_dirs():
    """Pasta-base agora é da CONTA. A pasta que um catálogo guardava vai para a(s) conta(s) das origens dele (uma vez)."""
    cats, changed = load(), False
    for c in cats:
        if c.get("baseDir"):
            for key in {f"{s['provider']}:{s['account']}" for s in c.get("sources", [])}:
                if c["baseDir"] not in account_dirs(key):
                    add_account_dir(key, c["baseDir"])
            c["baseDir"] = None
            changed = True
    if changed:
        save(cats)


def _account_suggestions(provider, name):
    """Catálogos naturais de UMA conta: um por projeto do Azure; no GitHub, o pessoal e um por organização."""
    out = []
    if provider == "azure":
        org = ctx.orgs[name]
        for p in org.projects():
            out.append({"name": p["name"] if p["name"].lower() != name.lower() else name,
                        "sources": [{"provider": "azure", "account": name, "owner": None, "project": p["name"]}],
                        "label": f"Azure · {name} / {p['name']}"})
    else:
        acc = next(a for a in ctx.gh.values() if a.login == name)
        me = acc.identity()
        out.append({"name": me["login"], "sources": [{"provider": "github", "account": acc.login, "owner": me["login"], "project": None}],
                    "label": f"GitHub · @{me['login']} (pessoal)"})
        for o in acc.orgs():
            out.append({"name": o["login"], "sources": [{"provider": "github", "account": acc.login, "owner": o["login"], "project": None}],
                        "label": f"GitHub · {o['login']}", "avatar": o.get("avatar")})
    return out


def _connected():
    return [("azure", n) for n in ctx.orgs] + [("github", a.login) for a in ctx.gh.values()]


def suggestions():
    """Um catálogo sugerido por organização/projeto do Azure e por organização/conta do GitHub conectados."""
    out = []
    for prov, name in _connected():
        try:
            out.extend(_account_suggestions(prov, name))
        except Exception:  # noqa: BLE001
            continue
    names = {c["name"].lower() for c in load()}
    for s in out:
        s["exists"] = s["name"].lower() in names
    return out


def clone(cid, repo_key, dest=None):
    cat = view(cid)   # "account:<provider:conta>" também vale
    r = next((x for x in cat["repos"] if x["key"] == repo_key), None)
    if not r:
        raise ValueError("Repositório não está no catálogo")
    if r["cloned"]:
        raise ValueError("Já está clonado")
    if not dest:
        raise ValueError("Escolha a pasta onde clonar")
    url = r.get("cloneUrl")
    if r["provider"] == "azure" and url:
        url = re.sub(r"^https://[^@/]+@", "https://", url)   # o Azure põe o usuário na URL; a credencial vai pelo header
    info = git.parse_remote(url)
    return git.clone(url, dest, auth=git._auth_lookup["fn"](info.get("provider"), info.get("owner")) if git._auth_lookup["fn"] else None)
