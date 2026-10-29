"""Acompanhar em cascata: PR aprovada → merge → build → deploy, numa via rápida.

Ao aprovar uma PR (pelo app ou por uma regra, com "Acompanhar até o deploy ao aprovar" ligado) ou ao clicar em
"Acompanhar até o deploy", a PR entra aqui. Um laço próprio lê só o que interessa a cada passo, em poucos segundos:
  merge   a PR até ser integrada ou fechada (GitHub: /pulls/N com ETag — o 304 não gasta cota; Azure: pullrequests/N)
  build   o CI do commit de merge (GitHub: runs do Actions por head_sha; Azure: builds da branch de destino com
          sourceVersion = commit). Pipeline YAML com vários estágios: o 1º estágio é o build, os seguintes são o deploy
  deploy  GitHub: deployments do commit (environments, inclusive os criados por jobs do Actions); Azure: os estágios
          seguintes do YAML e as releases clássicas disparadas pelo build
Cada mudança de passo vira notificação (core.notify, clicável) e acorda a leitura de fundo da fonte certa. Os itens
ficam em cascade.json (sobrevivem a reiniciar o app); terminados somem depois de 24 h, e cada passo tem prazo.

Passo: {"status": pending|waiting|running|done|failed|skipped, "label", "url", "at", "parts": [{name, status, url}]}.
"""
import copy
import os
import threading
import time
import urllib.parse
from datetime import timedelta

from . import power
from .core import DATA, is_network_error, load_json, notify, now, now_iso, parse_dt, save_json, wants

CASCADE_FILE = os.path.join(DATA, "cascade.json")
ACTIVE = ("merge", "build", "deploy")
EVERY = {"merge": 12, "build": 10, "deploy": 15}   # s entre leituras de cada passo
TIMEOUT = {"merge": timedelta(days=7), "build": timedelta(hours=3), "deploy": timedelta(hours=12)}
NO_CI = 180        # merge sem nenhum build em 3 min: o destino não tem CI
NO_DEPLOY = 300    # build terminou e nenhum deploy apareceu em 5 min: sem deploy automático
KEEP_DONE = timedelta(hours=24)
MAX_ITEMS = 40

_lock = threading.RLock()
_items = {}       # chave da PR -> item
_due = {}         # chave -> monotônico da próxima leitura
_errs = {}        # chave -> falhas seguidas (a espera dobra, até 2 min)
_tl_cache = {}    # (org, build) -> timeline de build já terminado (não muda mais)
_wake = threading.Event()
_loaded = {"ok": False}

GH_DEPLOY = {"success": "done", "inactive": "done", "failure": "failed", "error": "failed", "in_progress": "running",
             "queued": "running", "pending": "running", "waiting": "waiting"}
AZ_ENV = {"succeeded": "done", "partiallySucceeded": "done", "rejected": "failed", "canceled": "failed", "inProgress": "running",
          "queued": "running", "scheduled": "running", "notStarted": "pending", "undefined": "pending"}
GH_MERGE = {"dirty": "conflito com o destino", "blocked": "bloqueada: aprovações ou checks obrigatórios", "draft": "rascunho",
            "behind": "desatualizada com o destino", "unstable": "checks falhando", "clean": "pronta para o merge"}


# ---------------------------------------------------------------- estado
def _load():
    if _loaded["ok"]:
        return
    with _lock:
        for it in load_json(CASCADE_FILE, []):
            if it.get("key"):
                _items[it["key"]] = it
        _loaded["ok"] = True


def _save():
    with _lock:
        save_json(CASCADE_FILE, list(_items.values()))


def public():
    """Para a tela: os em andamento primeiro, depois os terminados (mais recentes primeiro)."""
    _load()
    with _lock:
        out = copy.deepcopy(list(_items.values()))
    out.sort(key=lambda i: (i["stage"] in ACTIVE, i.get("updatedAt") or ""), reverse=True)
    return out


def active_stage(stage):
    with _lock:
        return any(i["stage"] == stage for i in _items.values())


def _st(status="pending", label=""):
    return {"status": status, "label": label, "url": None, "at": None, "parts": []}


def _set(it, step, status, label=None, url=None, parts=None, at=None):
    s = it["steps"][step]
    if s["status"] != status:
        s["at"] = at or now_iso()
    s["status"] = status
    if label is not None:
        s["label"] = label
    if url is not None:
        s["url"] = url
    if parts is not None:
        s["parts"] = parts


def _advance(it, stage):
    if it["stage"] != stage:
        it["stage"], it["stageSince"] = stage, now_iso()


def _finish(it, result):
    it["stage"], it["result"], it["finishedAt"] = "finished", result, now_iso()


def _since(iso):
    d = parse_dt(iso)
    return (now() - d).total_seconds() if d else 0


# ---------------------------------------------------------------- seguir / parar
def follow(pr, by="manual"):
    """Começa a acompanhar uma PR (das listas do app). Já acompanhando: devolve o que já existe."""
    _load()
    key = pr["key"]
    with _lock:
        cur = _items.get(key)
        if cur and cur["stage"] in ACTIVE:
            return copy.deepcopy(cur)
        approved = by in ("approve", "auto") or (pr.get("myVote") or 0) >= 5 or (pr.get("approvals") or 0) > 0
        it = {k: pr.get(k) for k in ("key", "provider", "account", "org", "project", "repo", "repoId", "prId", "title", "url",
                                     "source", "target")}
        it.update(by=by, startedAt=now_iso(), updatedAt=now_iso(), stage="merge", stageSince=now_iso(), result=None,
                  commit=None, error=None, told=[],
                  steps={"approved": _st("done" if approved else "waiting", "aprovada" if approved else "esperando aprovação"),
                         "merge": _st("waiting", "esperando o merge"), "build": _st(), "deploy": _st()})
        if approved:
            it["steps"]["approved"]["at"] = now_iso()
        _items[key] = it
        _due[key] = 0
        _trim()
        _save()
    _wake.set()
    return copy.deepcopy(it)


def on_approved(pr, by):
    """Aprovou (você pelo app ou uma regra): segue até o deploy se a preferência estiver ligada."""
    try:
        from .rules import get_rules
        if get_rules()["settings"].get("cascadeOnApprove", True):
            follow(pr, by)
    except Exception as e:  # noqa: BLE001 — acompanhar é extra: nunca atrapalha o voto
        print(f"[cascade] não comecei a acompanhar {pr.get('key')}: {e}", flush=True)


def stop(key):
    with _lock:
        _items.pop(key, None)
        _due.pop(key, None)
        _save()


def poke(key=None):
    """Lê agora (um item ou todos) — chamado quando uma notificação do GitHub indica mudança."""
    with _lock:
        for k in ([key] if key else list(_items)):
            _due[k] = 0
    _wake.set()


def _trim():
    done = sorted((i for i in _items.values() if i["stage"] not in ACTIVE), key=lambda i: i.get("finishedAt") or "")
    for i in done:
        if len(_items) <= MAX_ITEMS and _since(i.get("finishedAt")) < KEEP_DONE.total_seconds():
            continue
        _items.pop(i["key"], None)


# ---------------------------------------------------------------- laço
def loop():
    _load()
    while True:
        _wake.wait(3)
        _wake.clear()
        if power.paused():
            continue
        t = time.monotonic()
        with _lock:
            keys = [k for k, i in _items.items() if i["stage"] in ACTIVE and _due.get(k, 0) <= t]
        for k in keys:
            _tick(k)
        with _lock:
            n = len(_items)
            _trim()
            if len(_items) != n:
                _save()


def _tick(key):
    from . import engine
    with _lock:
        cur = _items.get(key)
        it = copy.deepcopy(cur) if cur else None
    if not it:
        return
    before = {s: v["status"] for s, v in it["steps"].items()}
    stage0 = it["stage"]
    try:
        acc = engine.account_for_item(it)
        if engine.throttled(acc):
            _due[key] = time.monotonic() + 60
            return
        (_github if it["provider"] == "github" else _azure)(acc, it)
        _errs.pop(key, None)
        it["error"] = None
    except Exception as e:  # noqa: BLE001
        n = _errs[key] = _errs.get(key, 0) + 1
        it["error"] = "sem conexão" if is_network_error(e) else str(e)[:200]
        _due[key] = time.monotonic() + min(EVERY.get(it["stage"], 15) * 2 ** n, 120)
        with _lock:
            if key in _items and _items[key]["stage"] in ACTIVE:
                _items[key]["error"] = it["error"]
        return
    if it["stage"] in ACTIVE and _since(it["stageSince"]) > TIMEOUT[it["stage"]].total_seconds():
        _set(it, it["stage"], "skipped", "parou de acompanhar: passou do prazo deste passo")
        _finish(it, "timeout")
    after = {s: v["status"] for s, v in it["steps"].items()}
    changed = after != before or it["stage"] != stage0
    if changed:
        it["updatedAt"] = now_iso()
        _announce(it, before)
        if before["merge"] != after["merge"]:
            engine.refresh("prs")
        if before["build"] != after["build"] or before["merge"] != after["merge"]:
            engine.refresh("builds")
        if before["deploy"] != after["deploy"]:
            engine.refresh("deploys")
    with _lock:
        if key not in _items or _items[key].get("startedAt") != it["startedAt"]:
            return   # parado (ou reiniciado) enquanto lia
        _items[key] = it
        if changed:
            _save()
        if it["stage"] in ACTIVE:
            _due[key] = time.monotonic() + EVERY[it["stage"]]


def _announce(it, before):
    if not wants("cascade"):
        return
    sub = f"{it['org']}/{it['repo']} #{it['prId']} → {it['target']}"
    texts = {("merge", "done"): "PR integrada", ("merge", "failed"): "PR fechada sem merge",
             ("build", "done"): "Build passou", ("build", "failed"): "Build falhou depois do merge",
             ("deploy", "waiting"): "Deploy aguardando aprovação", ("deploy", "running"): "Deploy em andamento",
             ("deploy", "done"): "Deploy concluído", ("deploy", "failed"): "Deploy falhou",
             ("deploy", "skipped"): "Concluído — sem deploy automático"}
    for step in ("merge", "build", "deploy"):
        st = it["steps"][step]
        tag = f"{step}:{st['status']}"
        if st["status"] == before[step] or tag in it["told"] or (step, st["status"]) not in texts:
            continue
        it["told"].append(tag)
        notify(texts[(step, st["status"])], sub, f"{it['title']} — {st['label']}" if st["label"] else it["title"], f"cascade/{it['key']}", kind="cascade")
    if it.get("result") == "timeout" and "timeout" not in it["told"]:
        it["told"].append("timeout")
        notify("Acompanhamento encerrado", sub, f"{it['title']} — passou do prazo", f"cascade/{it['key']}", kind="cascade")


# ---------------------------------------------------------------- passos em comum
def _merged(it, at, target, url):
    if it["steps"]["approved"]["status"] != "done":
        _set(it, "approved", "done", "aprovada")
    _set(it, "merge", "done", f"integrada em {target}" if target else "integrada", url=url, at=at)
    _advance(it, "build")


def _build(it, parts, deployed=False):
    """Passo do build a partir dos runs/builds do commit de merge."""
    if not parts:
        if _since(it["steps"]["merge"]["at"]) > NO_CI:
            _set(it, "build", "skipped", "nenhum build rodou no commit do merge", parts=[])
        else:
            _set(it, "build", "pending", "esperando o CI começar", parts=[])
        return
    bad = [p for p in parts if p["status"] == "failed"]
    live = [p for p in parts if p["status"] in ("running", "waiting", "pending")]
    if bad:
        _set(it, "build", "failed", f"falhou: {bad[0]['name']}", bad[0].get("url"), parts)
    elif live and not deployed:
        _set(it, "build", "running", live[0].get("label") or f"{live[0]['name']} rodando", live[0].get("url"), parts)
    elif all(p["status"] == "skipped" for p in parts):
        _set(it, "build", "failed", "cancelado", parts[0].get("url"), parts)
    else:
        ok = [p for p in parts if p["status"] == "done"]
        _set(it, "build", "done", ok[0]["name"] if len(ok) == 1 else f"{len(ok)} builds ok", (ok or parts)[0].get("url"), parts)


def _deploy(it, parts, url=None):
    build = it["steps"]["build"]
    if build["status"] in ("done", "skipped"):
        _advance(it, "deploy")
    names = lambda ps: ", ".join(dict.fromkeys(p["name"] for p in ps))   # noqa: E731
    by = {s: [p for p in parts if p["status"] == s] for s in ("failed", "waiting", "running", "done", "pending", "skipped")}
    late = build["status"] in ("done", "skipped") and _since(build["at"]) > NO_DEPLOY
    if by["failed"]:
        _set(it, "deploy", "failed", f"falhou em {names(by['failed'])}", by["failed"][0].get("url") or url, parts)
    elif by["waiting"]:
        _set(it, "deploy", "waiting", f"aguardando aprovação · {names(by['waiting'])}", by["waiting"][0].get("url") or url, parts)
    elif by["running"]:
        _set(it, "deploy", "running", f"{names(by['running'])} em andamento", by["running"][0].get("url") or url, parts)
    elif by["done"]:
        _set(it, "deploy", "done", names(by["done"]), by["done"][0].get("url") or url, parts)
    elif parts and (late or not by["pending"]):
        _set(it, "deploy", "skipped", "estágios não disparados (manuais ou pulados)", url, parts)
    elif not parts and late:
        _set(it, "deploy", "skipped", "nenhum deploy automático para este commit", url, parts)
    elif build["status"] in ("done", "skipped"):
        _set(it, "deploy", "pending", "esperando o deploy começar", url, parts)
    b, d = build["status"], it["steps"]["deploy"]["status"]
    if b == "failed" or d == "failed":
        _finish(it, "failed")
    elif b in ("done", "skipped") and d in ("done", "skipped"):
        _finish(it, "succeeded")


# ---------------------------------------------------------------- GitHub
def _gh_run(r):
    if r.get("status") == "completed":
        c = r.get("conclusion")
        return "failed" if c in ("failure", "timed_out", "startup_failure") else "skipped" if c in ("cancelled", "skipped", "stale") else "done"
    return "waiting" if r.get("status") == "waiting" else "running"


def _github(acc, it):
    full, n = it["project"], it["prId"]
    if it["stage"] == "merge":
        pr = acc.req("GET", f"repos/{full}/pulls/{n}", etag=True) or {}
        if pr.get("merged"):
            it["commit"] = pr.get("merge_commit_sha")
            _merged(it, pr.get("merged_at"), (pr.get("base") or {}).get("ref"), pr.get("html_url"))
        elif pr.get("state") == "closed":
            _set(it, "merge", "failed", "PR fechada sem merge")
            _finish(it, "abandoned")
            return
        else:
            label = GH_MERGE.get(pr.get("mergeable_state"), "esperando o merge")
            _set(it, "merge", "waiting", ("auto-merge ligado · " if pr.get("auto_merge") else "") + label, pr.get("html_url"))
            return
    sha = it["commit"]
    runs = [r for r in (acc.req("GET", f"repos/{full}/actions/runs?head_sha={sha}&per_page=30", etag=True) or {}).get("workflow_runs", [])
            if r.get("event") not in ("pull_request", "pull_request_target")]
    deps = acc.req("GET", f"repos/{full}/deployments?sha={sha}&per_page=20", etag=True) or []
    parts = [{"name": r.get("name") or "workflow", "status": _gh_run(r), "url": r.get("html_url"), "id": r["id"]} for r in runs]
    live = [p for p in parts if p["status"] == "running"]
    if live and not deps:
        try:   # o que o run está fazendo agora (job › passo) — com ETag, quase sempre 304
            live[0]["label"] = acc.run_phase(full, live[0]["id"])["label"]
        except Exception:  # noqa: BLE001
            pass
    _build(it, parts, deployed=bool(deps))
    if not (deps or it["steps"]["build"]["status"] in ("done", "skipped")) or it["steps"]["build"]["status"] == "failed":
        if it["steps"]["build"]["status"] == "failed":
            _finish(it, "failed")
        return
    dparts, seen = [], set()
    for d in deps:   # mais novos primeiro: fica o último deployment de cada environment
        env = d.get("environment") or "deploy"
        if env in seen or len(dparts) >= 6:
            continue
        seen.add(env)
        sts = acc.req("GET", f"repos/{full}/deployments/{d['id']}/statuses?per_page=1", etag=True) or []
        raw = sts[0].get("state") if sts else "pending"
        link = (sts[0].get("log_url") or sts[0].get("target_url") or sts[0].get("environment_url")) if sts else None
        dparts.append({"name": env, "status": GH_DEPLOY.get(raw, "running"), "url": link})
    _deploy(it, dparts, f"https://github.com/{full}/deployments")


# ---------------------------------------------------------------- Azure DevOps
def _az_record(r):
    if r.get("state") == "completed":
        res = r.get("result")
        return "done" if res in ("succeeded", "succeededWithIssues") else "skipped" if res == "skipped" else "failed"
    return "running" if r.get("state") == "inProgress" else "pending"


def _az_build(b):
    if b.get("status") == "completed":
        return "done" if b.get("result") in ("succeeded", "partiallySucceeded") else "failed"
    return "running" if b.get("status") == "inProgress" else "pending"


def _timeline(acc, proj, b):
    ck = (acc.name, b["id"])
    if ck in _tl_cache:
        return _tl_cache[ck]
    from .azure import API
    records = (acc.req("GET", f"{proj}/_apis/build/builds/{b['id']}/timeline?{API}") or {}).get("records") or []
    if b.get("status") == "completed":
        _tl_cache[ck] = records
        if len(_tl_cache) > 200:
            _tl_cache.pop(next(iter(_tl_cache)))
    return records


def _az_releases(acc, proj, b):
    from .azure import API
    src = urllib.parse.quote(f"{b['project']['id']}:{b['definition']['id']}", safe="")
    rels = acc.req("GET", f"{acc.vsrm}/{proj}/_apis/release/releases?artifactTypeId=Build&sourceId={src}"
                          f"&artifactVersionId={b['id']}&$expand=environments&{API}").get("value") or []
    parts = []
    for r in rels[:3]:
        url = f"{acc.url}/{proj}/_releaseProgress?_a=release-pipeline-progress&releaseId={r['id']}"
        for e in r.get("environments") or []:
            st = AZ_ENV.get(e.get("status"), "running")
            if st in ("running", "pending") and any(a.get("status") == "pending" for a in e.get("preDeployApprovals") or []):
                st = "waiting"
            parts.append({"name": e.get("name") or "estágio", "status": st, "url": url})
    return parts


def _azure(acc, it):
    from .azure import API, phase_from_records
    if it["stage"] == "merge":
        pr = acc.req("GET", f"_apis/git/pullrequests/{it['prId']}?{API}") or {}
        st = pr.get("status")
        if any((rv.get("vote") or 0) >= 5 for rv in pr.get("reviewers") or []) and it["steps"]["approved"]["status"] != "done":
            _set(it, "approved", "done", "aprovada")
        if st == "completed" and (pr.get("lastMergeCommit") or {}).get("commitId"):
            it["commit"] = pr["lastMergeCommit"]["commitId"]
            _merged(it, pr.get("closedDate"), (pr.get("targetRefName") or "").removeprefix("refs/heads/"), it["url"])
        elif st == "abandoned":
            _set(it, "merge", "failed", "PR abandonada")
            _finish(it, "abandoned")
            return
        else:
            label = "conflito com o destino" if pr.get("mergeStatus") == "conflicts" else \
                "auto-complete ligado · esperando as policies" if pr.get("autoCompleteSetBy") else "esperando o merge"
            _set(it, "merge", "waiting", label, it["url"])
            return
    proj = urllib.parse.quote(it["project"])
    branch = urllib.parse.quote(f"refs/heads/{it['target']}", safe="")
    data = acc.req("GET", f"{proj}/_apis/build/builds?repositoryId={it['repoId']}&repositoryType=TfsGit&branchName={branch}"
                          f"&$top=30&queryOrder=queueTimeDescending&{API}") or {}
    builds = [b for b in data.get("value") or [] if b.get("sourceVersion") == it["commit"]][:4]
    bparts, dparts = [], []
    for b in builds:
        url = f"{acc.url}/{proj}/_build/results?buildId={b['id']}"
        records = _timeline(acc, proj, b)
        stages = sorted((r for r in records if r.get("type") == "Stage"), key=lambda r: r.get("order") or 0)
        phase = phase_from_records(records) if records and b.get("status") != "completed" else None
        if len(stages) > 1:   # YAML com estágios: o 1º é o build, os outros são o deploy
            bparts.append({"name": f"{b['definition']['name']} · {stages[0]['name']}", "status": _az_record(stages[0]), "url": url,
                           "label": phase["label"] if phase and phase.get("stage") == stages[0]["name"] else None})
            for sg in stages[1:]:
                s = _az_record(sg)
                if s in ("running", "pending") and phase and phase["state"] in ("approval", "check") and phase.get("stage") == sg["name"]:
                    s = "waiting"
                dparts.append({"name": sg["name"], "status": s, "url": url})
        else:
            s = _az_build(b)
            bparts.append({"name": b["definition"]["name"], "status": s, "url": url, "label": phase["label"] if phase else None})
            if s == "done":
                dparts += _az_releases(acc, proj, b)
    _build(it, bparts, deployed=any(p["status"] != "pending" for p in dparts))
    if it["steps"]["build"]["status"] == "failed":
        _finish(it, "failed")
        return
    if dparts or it["steps"]["build"]["status"] in ("done", "skipped"):
        _deploy(it, dparts, bparts[0]["url"] if bparts else None)
