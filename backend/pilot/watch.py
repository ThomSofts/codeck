"""Tempo real (local): vigia rápida dos repositórios ativos, só desta máquina, só com o PAT/login que o app já tem.

Nada de servidor, relay, túnel ou webhook: o app pergunta ao GitHub e ao Azure, a cada poucos segundos, se algo mudou
nos repositórios que importam agora — e só relê a fonte certa (PRs, builds, deploys, issues) quando mudou.

  Repositórios ativos (até 40, os mais recentes primeiro): os de PRs acompanhadas até o deploy, os dos projetos
  abertos no app, os das minhas PRs abertas e os das PRs que pedem a minha revisão.

  GitHub (~10 s, de 5 a 60 s): listas baratas com ETag/If-None-Match — o 304 ("nada mudou") não conta na cota:
      pulls abertas por atualização, últimos runs do Actions, últimos deployments (e issues, num ritmo menor).
  Azure DevOps (~15 s): consultas pequenas e filtradas — PRs ativas do repositório, últimos builds e deployments
      de release do projeto — comparadas por uma assinatura (ids + estado), já que o Azure não tem ETag nelas.

Mudou (200 com conteúdo diferente da última vez): acorda a leitura daquela fonte (engine.refresh) e o acompanhamento
em cascata do repositório. Para não esbarrar no limite secundário do GitHub: no máximo 4 pedidos ao mesmo tempo,
até 240 por minuto por conta, espalhados pelo intervalo, e recuo em 403/429/Retry-After. Com a janela escondida,
espaça (6×); com economia de bateria, 3×; com a tela bloqueada, para.
"""
import hashlib
import json
import os
import random
import threading
import time
import urllib.parse
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from . import git, github, power
from .core import DATA, ctx, http_code, is_network_error, load_json, lock, now_iso, state

LIVE_MIN, LIVE_MAX, LIVE_DEFAULT = 5, 60, 10
AZURE_MIN = 15
MAX_REPOS = 40
WORKERS = 4
PER_MIN = 240
# (fonte, caminho depois de repos/{dono}/{repo}/, de quantos em quantos ciclos — repositório "quente" lê tudo todo ciclo)
GH_PROBES = [("prs", "pulls?state=open&sort=updated&direction=desc&per_page=20", 1),
             ("builds", "actions/runs?per_page=10", 1),
             ("deploys", "deployments?per_page=5", 3),
             ("issues", "issues?state=open&sort=updated&direction=desc&per_page=10", 3)]

_sig = {}          # chave da sonda -> assinatura do último conteúdo (None = ainda sem base)
_due = {}          # chave da sonda -> monotônico da próxima vez
_busy = set()      # sondas em andamento
_calls = {}        # conta -> deque de monotônicos das chamadas no último minuto
_backoff = {}      # conta -> (até quando, vezes seguidas)
_stats = {"calls": deque(), "free": deque(), "changes": 0, "lastChange": None}
_changed = set()   # fontes a reler (juntadas a cada volta)
_hot_changed = {"on": False}
_mx = threading.Lock()
_pool = ThreadPoolExecutor(WORKERS, thread_name_prefix="watch")


def settings(cfg=None):
    cfg = ctx.config if cfg is None else cfg
    try:
        sec = min(max(int(cfg.get("liveSeconds") or LIVE_DEFAULT), LIVE_MIN), LIVE_MAX)
    except (TypeError, ValueError):
        sec = LIVE_DEFAULT
    return {"on": cfg.get("liveWatch", True) is not False, "seconds": sec}


def pace():
    """(segundos do GitHub, motivo) — None = parada agora."""
    from . import engine
    st = settings()
    if not st["on"]:
        return None, "desligado"
    if power.away() or power.paused():
        return None, "parado: tela bloqueada ou computador fora"
    if engine.idle():
        return min(st["seconds"] * 6, 120), "janela escondida"
    if power.saver():
        return st["seconds"] * 3, "economia de bateria"
    return st["seconds"], "tempo real"


# ---------------------------------------------------------------- repositórios ativos
def _az_org(owner):
    o = (owner or "").lower()
    for name, org in list(ctx.orgs.items()):
        if name.lower() == o or org.url.rstrip("/").rsplit("/", 1)[-1].lower() == o:
            return name
    return None


def active_repos():
    """[{provider, org|slug, project, repo, account, hot}] — ordem de importância, sem repetir, até MAX_REPOS."""
    from . import cascade
    out, seen = [], set()

    def add(provider, hot=False, slug=None, org=None, project=None, repo=None, account=None):
        key = (provider, (slug or f"{org}/{project}/{repo}").lower())
        if key in seen or len(out) >= MAX_REPOS or (provider == "azure" and org not in ctx.orgs) or (provider == "github" and not slug):
            return
        seen.add(key)
        out.append({"provider": provider, "slug": slug, "org": org, "project": project, "repo": repo, "account": account, "hot": hot})

    for c in cascade.public():
        if c["stage"] != "finished":
            if c["provider"] == "github":
                add("github", True, slug=c["project"], account=c.get("account"))
            else:
                add("azure", True, org=c["org"], project=c["project"], repo=c["repo"])
    ws = load_json(os.path.join(DATA, "workspace.json"), {})
    ids = [ws.get("active")] + list(reversed(ws.get("open") or []))
    repos = {r.get("id"): r for r in load_json(git.REPOS_FILE, [])}
    for rid in ids:
        info = git.parse_remote((repos.get(rid) or {}).get("remoteUrl"))
        if info.get("provider") == "github":
            add("github", slug=info["slug"])
        elif info.get("provider") == "azure":
            add("azure", org=_az_org(info["owner"]), project=info["project"], repo=info["name"])
    with lock:
        mine = list(state["myPrs"])
        review = [p for p in state["prs"] if not p.get("archived") and p.get("myVote") == 0
                  and (p.get("provider") != "github" or p.get("reviewRequested"))]
    for p in mine + review:
        if p.get("provider") == "github":
            add("github", slug=p["project"], account=p.get("account"))
        else:
            add("azure", org=p["org"], project=p["project"], repo=p["repo"])
    return out


def _gh_account(r):
    from . import engine
    return engine.gh_by_login(r.get("account")) or engine.gh_by_login(r["slug"].split("/")[0]) or next(iter(ctx.gh.values()), None)


def probes():
    """Sondas a fazer: {key, cat, acc, path, mult, hot, repo}."""
    out, seen = [], set()
    for r in active_repos():
        if r["provider"] == "github":
            acc = _gh_account(r)
            if not acc:
                continue
            for cat, ep, mult in GH_PROBES:
                out.append({"key": f"gh:{acc.id}:{r['slug'].lower()}:{cat}", "cat": cat, "acc": acc, "path": f"repos/{r['slug']}/{ep}",
                            "mult": 1 if r["hot"] else mult, "hot": r["hot"], "repo": r, "etag": True})
            continue
        acc = ctx.orgs.get(r["org"])
        if not acc:
            continue
        from .azure import API
        proj = urllib.parse.quote(r["project"])
        items = [("prs", f"{proj}/_apis/git/repositories/{urllib.parse.quote(r['repo'])}/pullrequests?searchCriteria.status=active&$top=30&{API}",
                  f"az:{r['org']}:{r['project']}/{r['repo']}:prs".lower()),
                 ("builds", f"{proj}/_apis/build/builds?$top=10&queryOrder=queueTimeDescending&{API}", f"az:{r['org']}:{r['project']}:builds".lower()),
                 ("deploys", f"{acc.vsrm}/{proj}/_apis/release/deployments?$top=10&queryOrder=descending&{API}", f"az:{r['org']}:{r['project']}:deploys".lower())]
        for cat, path, key in items:
            if key not in seen:
                seen.add(key)
                out.append({"key": key, "cat": cat, "acc": acc, "path": path, "mult": 1, "hot": r["hot"], "repo": r, "etag": False})
    return out


# ---------------------------------------------------------------- assinaturas: o que conta como "mudou"
def signature(provider, cat, data):
    rows = data if isinstance(data, list) else (data or {}).get("workflow_runs") if provider == "github" and cat == "builds" \
        else (data or {}).get("value") if isinstance(data, dict) else []
    rows = rows or []
    if provider == "github":
        pick = {"prs": lambda p: (p.get("number"), p.get("updated_at"), (p.get("head") or {}).get("sha")),
                "builds": lambda r: (r.get("id"), r.get("status"), r.get("conclusion"), r.get("updated_at")),
                "deploys": lambda d: (d.get("id"), d.get("updated_at")),
                "issues": lambda i: (i.get("number"), i.get("updated_at"))}[cat]
    else:
        pick = {"prs": lambda p: (p.get("pullRequestId"), (p.get("lastMergeSourceCommit") or {}).get("commitId"), p.get("mergeStatus"),
                                  p.get("isDraft"), sorted((rv.get("id") or "", rv.get("vote", 0)) for rv in p.get("reviewers") or [])),
                "builds": lambda b: (b.get("id"), b.get("status"), b.get("result")),
                "deploys": lambda d: (d.get("id"), d.get("deploymentStatus"), d.get("operationStatus"), d.get("lastModifiedOn"))}[cat]
    return hashlib.sha1(json.dumps([pick(x) for x in rows], default=str).encode()).hexdigest()


def _also(provider, cat, data):
    """Fontes extras que a mudança acorda: run do Actions esperando environment, build do Azure → deploys também."""
    if cat != "builds":
        return set()
    if provider == "github":
        return {"deploys"} if any(r.get("status") == "waiting" for r in (data or {}).get("workflow_runs") or []) else set()
    return {"deploys"}


# ---------------------------------------------------------------- uma sonda
def _budget_ok(aid):
    t = time.monotonic()
    q = _calls.setdefault(aid, deque())
    while q and t - q[0] > 60:
        q.popleft()
    if len(q) >= PER_MIN or _backoff.get(aid, (0, 0))[0] > t:
        return False
    q.append(t)
    return True


def probe(p, every):
    """Faz a sonda e devolve True se o conteúdo mudou desde a última vez (a 1ª só guarda a base)."""
    acc, key = p["acc"], p["key"]
    provider = "github" if isinstance(acc, github.GitHub) else "azure"
    aid = getattr(acc, "id", None) or acc.name
    try:
        if provider == "github":
            h = {}
            data = acc.req("GET", p["path"], etag=True, headers_out=h)
            free = not h   # 304: o cache do ETag respondeu, não gastou cota
        else:
            data, free = acc.req("GET", p["path"]), False
        with _mx:
            _stats["calls"].append(time.monotonic())
            if free:
                _stats["free"].append(time.monotonic())
        _backoff.pop(aid, None)
        if free and _sig.get(key) is not None:
            return False
        sig = signature(provider, p["cat"], data)
        before = _sig.get(key)
        _sig[key] = sig
        if before is None or before == sig:
            return False
        with _mx:
            _changed.add(p["cat"])
            _changed.update(_also(provider, p["cat"], data))
            if p["hot"]:
                _hot_changed["on"] = True
            _stats["changes"] += 1
            _stats["lastChange"] = now_iso()
        return True
    except Exception as e:  # noqa: BLE001
        code = http_code(e)
        if code in (403, 429):   # limite secundário/cota: a conta descansa (dobra a cada vez, até 15 min)
            n = _backoff.get(aid, (0, 0))[1] + 1
            _backoff[aid] = (time.monotonic() + min(60 * 2 ** (n - 1), 900), n)
        elif code in (404, 410) or (code and not is_network_error(e)):
            _due[key] = time.monotonic() + 1800   # sem Actions/deployments/release aqui: tenta de novo em 30 min
        return False
    finally:
        _busy.discard(key)


# ---------------------------------------------------------------- laço
def tick(every):
    """Uma volta: dispara as sondas vencidas (respeitando concorrência e cota) e acorda as fontes que mudaram."""
    from . import engine
    t = time.monotonic()
    ps = probes()
    live = {p["key"] for p in ps}
    for k in [k for k in _sig if k not in live]:   # repositório saiu da lista ativa: esquece a base
        _sig.pop(k, None)
        _due.pop(k, None)
    due = sorted((p for p in ps if p["key"] not in _busy and _due.get(p["key"], 0) <= t), key=lambda p: (not p["hot"], _due.get(p["key"], 0)))
    for p in due:
        if len(_busy) >= WORKERS * 2:
            break
        if engine.throttled(p["acc"]):
            continue
        low = isinstance(p["acc"], github.GitHub) and (p["acc"].rate or {}).get("limit") and \
            p["acc"].rate.get("remaining", 0) < p["acc"].rate["limit"] * 0.15
        if low and not p["hot"]:
            continue   # cota baixa: só os repositórios com PR acompanhada até o deploy
        if not _budget_ok(getattr(p["acc"], "id", None) or p["acc"].name):
            continue
        step = (every if isinstance(p["acc"], github.GitHub) else max(AZURE_MIN, every * 1.5)) * p["mult"]
        first = p["key"] not in _due
        # 1ª vez: espalha pelo intervalo (não sai tudo junto); depois, a cada `step` com uma folga aleatória
        _due[p["key"]] = t + (random.uniform(0, step) if first else step * random.uniform(0.9, 1.1))
        if first and _due[p["key"]] > t + 0.5 and p["key"] not in _sig:
            _sig[p["key"]] = None
            continue
        _busy.add(p["key"])
        _pool.submit(probe, p, every)
    flush()
    return len(ps)


def flush():
    from . import cascade, engine
    with _mx:
        cats, hot = set(_changed), _hot_changed["on"]
        _changed.clear()
        _hot_changed["on"] = False
    for c in cats:
        engine.refresh(c)
    if hot:
        cascade.poke()
    return cats


def _publish(every, why, repos):
    t = time.monotonic()
    with _mx:
        for q in (_stats["calls"], _stats["free"]):
            while q and t - q[0] > 60:
                q.popleft()
        info = {"on": every is not None, "every": every, "why": why, "repos": repos, "callsMin": len(_stats["calls"]),
                "freeMin": len(_stats["free"]), "changes": _stats["changes"], "lastChange": _stats["lastChange"]}
    with lock:
        state.setdefault("schedule", {})["live"] = info


def loop():
    time.sleep(12)
    while True:
        every, why, n = None, "desligado", 0
        try:
            every, why = pace()
            if every is not None and (ctx.gh or ctx.orgs):
                n = tick(every)
        except Exception as e:  # noqa: BLE001 — a vigia nunca derruba o app; a leitura normal continua
            print(f"[watch] {e}", flush=True)
        _publish(every, why, n)
        time.sleep(1 if every is not None else 5)
