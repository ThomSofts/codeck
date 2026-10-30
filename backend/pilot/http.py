"""HTTP local (127.0.0.1): a tela (ui/ compilada em static/) e a API que ela usa.

Toda rota /api exige a chave da execução (X-Codeck-Token) e os POSTs exigem também o header X-Codeck: 1 —
header custom força preflight de CORS, que não respondemos, então nenhum site consegue agir por você.
"""
import ctypes
import hmac
import json
import mimetypes
import os
import socket
import struct
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import accounts, agents, aitools, aiusage, analytics, azure, boards, cascade, catalogs, debug, dotnet, editor, engine, extensions, git, github, kanban, launch, library, lsp, power, prreview, rules, terminals, tracking, update, workspace, ws
from .core import (APP_BUILD, APP_PLATFORM, APP_VERSION, ARCHIVE_FILE, CONFIG_FILE, DATA, DEFAULT_PORT, PRODUCT, RULES_FILE, OfflineError,
                   STATIC_DIR, TOKEN, ctx, load_json, lock, log_activity, log_build, log_deploy, notifications, notify_seq,
                   now_iso, pr_summary, read_activity, save_json, state, wake)

GET, POST = {}, {}


def route(method, path):
    def deco(fn):
        (GET if method == "GET" else POST)[path] = fn
        return fn
    return deco


def q1(qs, name, default=None):
    return (qs.get(name) or [default])[0]


def find_item(kind, key):
    with lock:
        pool = {"pr": state["prs"] + state["myPrs"], "deploy": state["deploys"], "build": state["builds"]}[kind]
        return next((x for x in pool if x["key"] == key), None)


# ---------------------------------------------------------------- estado geral
@route("GET", "/api/state")
def get_state(qs, body):
    with lock:
        payload = {k: state[k] for k in ("prs", "myPrs", "builds", "buildErrors", "errors", "lastPoll", "me", "pollMs",
                                         "deploys", "releases", "deployErrors", "lastDeployPoll", "lastBuildPoll",
                                         "issues", "issueErrors", "lastIssuePoll", "polling", "offline", "loading", "updated")}
        payload = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v) for k, v in payload.items()}
    payload["orgs"] = list(ctx.orgs.keys())
    payload["githubAccounts"] = [{"id": a.id, "login": a.login, "avatar": (a.me or {}).get("avatar") or a.cfg.get("avatar")}
                                 for a in ctx.gh.values()]
    payload["sources"] = sorted({p["org"] for p in payload["prs"] + payload["myPrs"] + payload["builds"]} | set(ctx.orgs), key=str.lower)
    payload["pollSeconds"] = ctx.config.get("pollSeconds", 60)
    payload["pollIntervals"] = engine.intervals()   # um por fonte; schedule = próxima leitura de cada uma e por quê
    payload["schedule"] = dict(state.get("schedule") or {})
    payload["cascade"] = cascade.public()           # PRs acompanhadas até o deploy
    payload["editor"] = ctx.config.get("editor") or "vscode"
    payload["theme"] = ctx.config.get("theme") or "system"
    payload["ui"] = accounts.ui_prefs(ctx.config)
    payload["rules"] = rules.get_rules()
    payload["archive"] = load_json(ARCHIVE_FILE, {})
    payload["activity"] = read_activity(300)
    seen = {}
    for p in payload["prs"]:
        seen.setdefault(p["creatorUnique"] or p["creatorName"], p["creatorName"])
    hist = [p for c in list(analytics.analytics_cache.values()) for p in c["prs"]]
    my_ids = {o.me["id"] for o in ctx.orgs.values() if o.me}
    for p in hist:
        if p["creatorId"] not in my_ids:
            seen.setdefault(p["creatorUnique"] or p["creatorName"], p["creatorName"])
    payload["creators"] = sorted({v for v in seen.values() if v}, key=str.lower)
    payload["repos"] = sorted({p["repo"] for p in payload["prs"] + hist}, key=str.lower)
    counts = {}
    for p in payload["prs"] + hist:
        counts[p["target"]] = counts.get(p["target"], 0) + 1
    payload["targets"] = [t for t, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:12]
    payload["ruleStats"] = rules.rule_stats()
    payload["aiReviews"] = prreview.public()        # revisão da IA de cada PR (regra "Revisar com IA")
    payload["configured"] = bool(ctx.orgs or ctx.gh)
    payload["app"] = {"version": APP_VERSION, "build": APP_BUILD, "platform": APP_PLATFORM, "product": PRODUCT}
    payload["update"] = dict(update.update_state)
    return payload


@route("GET", "/api/summary")
def get_summary(qs, body):
    with lock:
        prs = sum(1 for p in state["prs"] if not p.get("archived") and p["myVote"] == 0
                  and (p.get("provider") != "github" or p.get("reviewRequested")))
        deploys = sum(1 for d in state["deploys"] if d.get("mine", True))
        errors = bool(state["errors"] or state["deployErrors"])
        out = {"prs": prs, "deploys": deploys, "total": prs + deploys, "errors": errors,
               "configured": bool(ctx.orgs or ctx.gh), "lastPoll": state["lastPoll"], "notifySeq": notify_seq()}
    out["power"] = power.summary()   # o app nativo segura (ou não) o computador acordado conforme o modo
    return out


# ---------------------------------------------------------------- tela bloqueada, protetor de tela, suspensão
@route("GET", "/api/power")
def get_power(qs, body):
    return power.summary()


@route("POST", "/api/power/event")
def post_power_event(qs, body):
    """O app nativo avisa: sleep, wake, lock, unlock, screensaver-start/-stop, display-sleep/-wake."""
    return power.event(str(body.get("event") or ""), body.get("at"))


@route("GET", "/api/notifications")
def get_notifications(qs, body):
    after = int(q1(qs, "after", "0"))
    with lock:
        return {"seq": notify_seq(), "items": [n for n in notifications if n["seq"] > after]}


@route("GET", "/api/analytics")
def get_analytics(qs, body):
    days = min(max(int(q1(qs, "days", "30")), 1), 90)
    return analytics.analytics(days, q1(qs, "org") or None, force=q1(qs, "force", "0") == "1")


@route("POST", "/api/refresh")
def post_refresh(qs, body):
    if body.get("source"):   # só uma fonte (prs, builds, deploys, issues): as outras seguem o próprio ciclo
        engine.refresh(body["source"])
    else:
        wake.set()
        cascade.poke()
    return {"ok": True}


@route("POST", "/api/presence")
def post_presence(qs, body):
    """A tela avisa foco/visibilidade: sem ninguém olhando, as leituras espaçam; ao voltar, relê o que envelheceu."""
    return engine.set_presence(body.get("focused", True), body.get("visible", True))


# ---------------------------------------------------------------- acompanhar em cascata (PR → merge → build → deploy)
@route("POST", "/api/cascade/follow")
def post_cascade_follow(qs, body):
    pr = find_item("pr", body.get("key"))
    if not pr:
        raise ValueError("PR não está mais na lista — atualize")
    return cascade.follow(pr, "manual")


@route("POST", "/api/cascade/stop")
def post_cascade_stop(qs, body):
    cascade.stop(body.get("key"))
    return {"ok": True}


# ---------------------------------------------------------------- PRs, deploys, builds
@route("POST", "/api/vote")
def post_vote(qs, body):
    vote = int(body["vote"])
    if vote not in (10, 5, 0, -5, -10):
        raise ValueError("voto inválido")
    pr = find_item("pr", body.get("key"))
    if not pr:
        raise ValueError("PR não está mais na lista — atualize")
    engine.vote_pr(engine.account_for_item(pr), pr, vote, (body.get("comment") or "").strip())
    with lock:
        pr["myVote"] = vote
    log_activity("manual", "vote", pr, vote=vote)
    if vote >= 5:
        cascade.on_approved(pr, "approve")   # "Acompanhar até o deploy ao aprovar" (Configurações → Leitura e automação)
    return {"ok": True}


@route("POST", "/api/pr/comment")
def post_pr_comment(qs, body):
    text = (body.get("text") or "").strip()
    if not text:
        raise ValueError("Comentário vazio")
    pr = find_item("pr", body.get("key"))
    if not pr:
        raise ValueError("PR não está mais na lista — atualize")
    acc = engine.account_for_item(pr)
    if pr.get("provider") == "github":
        acc.comment(pr["project"], pr["prId"], text)
    else:
        acc.comment(pr["project"], pr["repoId"], pr["prId"], text)
    log_activity("manual", "comment", pr)
    return {"ok": True}


@route("GET", "/api/ws/agent/last")
def get_ws_agent_last(qs, body):
    return {"text": agents.last_message(q1(qs, "sid"))}


@route("POST", "/api/archive")
def post_archive(qs, body):
    archive = load_json(ARCHIVE_FILE, {})
    for key in body.get("keys", []):
        pr = find_item("pr", key)
        if body.get("archive", True):
            if pr:
                archive[key] = {"ts": now_iso(), "commit": pr["commit"], "reason": "manual", **pr_summary(pr)}
                pr["archived"] = True
                log_activity("manual", "archive", pr)
        elif key in archive:
            info = archive.pop(key)
            if pr:
                pr["archived"] = False
            log_activity("manual", "unarchive", pr or info)
    save_json(ARCHIVE_FILE, archive)
    return {"ok": True}


@route("POST", "/api/deploy")
def post_deploy(qs, body):
    item = find_item("deploy", body.get("key"))
    if not item:
        raise ValueError("Item não está mais pendente — atualize")
    approve = body.get("decision") == "approve"
    engine.account_for_item(item).decide_deploy(item, approve, (body.get("comment") or "").strip())
    with lock:
        state["deploys"] = [d for d in state["deploys"] if d["key"] != item["key"]]
    action = {("permission", True): "permit", ("permission", False): "cancel"}.get((item["kind"], approve),
                                                                                  "deploy-approve" if approve else "deploy-reject")
    log_deploy("manual", action, item, detail=body.get("comment") or None)
    wake.set()
    return {"ok": True}


@route("GET", "/api/build")
def get_build(qs, body):
    b = find_item("build", q1(qs, "key", ""))
    if not b:
        raise LookupError("build não está mais na lista")
    acc = engine.account_for_item(b)
    return acc.run_detail(b["project"], b["id"]) if b.get("provider") == "github" else acc.build_detail(b["project"], b["id"])


@route("POST", "/api/build-action")
def post_build_action(qs, body):
    b = find_item("build", body.get("key"))
    if not b:
        raise ValueError("Build não está mais na lista — atualize")
    acc = engine.account_for_item(b)
    (acc.run_action if b.get("provider") == "github" else acc.build_action)(b, body.get("action"))
    log_build("manual", body.get("action"), b)
    wake.set()
    return {"ok": True}


# ---------------------------------------------------------------- regras
@route("POST", "/api/rules")
def post_rules(qs, body):
    save_json(RULES_FILE, rules.clean_rules(body))
    wake.set()
    return {"ok": True}


@route("POST", "/api/simulate")
def post_simulate(qs, body):
    return rules.simulate_rule(body)


@route("POST", "/api/simulate-deploy")
def post_simulate_deploy(qs, body):
    return rules.simulate_deploy_rule(body)


# ---------------------------------------------------------------- contas e preferências
@route("GET", "/api/config")
def get_config(qs, body):
    return accounts.public_config()


@route("POST", "/api/config")
def post_config(qs, body):
    accounts.save_azure(body)
    return {"ok": True}


@route("POST", "/api/config/test")
def post_config_test(qs, body):
    return azure.test_org(body)


@route("POST", "/api/prefs")
def post_prefs(qs, body):
    accounts.save_prefs(body)
    return {"ok": True}


@route("POST", "/api/github/token")
def post_github_token(qs, body):
    return accounts.add_github_token(body.get("token"))


@route("POST", "/api/github/cli")
def post_github_cli(qs, body):
    return accounts.add_github_token(github.gh_cli_token(), source="gh-cli")


@route("POST", "/api/github/device/start")
def post_github_device(qs, body):
    return github.device_start(lambda tok, grant: accounts.add_github_token(tok, source="device", grant=grant))


@route("GET", "/api/github/device")
def get_github_device(qs, body):
    f = github.device_flows.get(q1(qs, "id", ""))
    if not f:
        raise LookupError("login não encontrado")
    return {k: f[k] for k in ("id", "status", "userCode", "verificationUri", "error", "account")}


@route("POST", "/api/github/remove")
def post_github_remove(qs, body):
    accounts.remove_github(body.get("id"))
    return {"ok": True}


@route("POST", "/api/github/test")
def post_github_test(qs, body):
    return accounts.test_github(body)


# ---------------------------------------------------------------- atualização do app
@route("POST", "/api/update/check")
def post_update_check(qs, body):
    return update.check_update()


@route("GET", "/api/update/progress")
def get_update_progress(qs, body):
    return {"downloading": update.update_state.get("downloading", False), "progress": update.update_state.get("progress")}


@route("POST", "/api/update/download")
def post_update_download(qs, body):
    return update.download_update()


# ---------------------------------------------------------------- repositórios locais
@route("GET", "/api/repos")
def get_repos(qs, body):
    catalogs.discover()   # clones novos nas pastas base aparecem na lista (no máximo a cada 2 min)
    return {"repos": git.list_repos(with_status=q1(qs, "status", "1") == "1")}


@route("POST", "/api/repos/discover")
def post_repos_discover(qs, body):
    """Procurar agora: vasculha de novo todas as pastas base das contas."""
    return catalogs.discover(force=True)


@route("POST", "/api/repos/add")
def post_repos_add(qs, body):
    return git.add_repo(body.get("path") or "")


@route("POST", "/api/repos/scan")
def post_repos_scan(qs, body):
    return git.scan(body.get("path") or "", int(body.get("depth") or 3))


@route("POST", "/api/repos/clone")
def post_repos_clone(qs, body):
    url = (body.get("url") or "").strip()
    info = git.parse_remote(url)
    auth = engine.git_auth(info.get("provider"), info.get("owner")) if url.startswith("https://") else None
    return git.clone(url, body.get("dest") or "", auth=auth)


@route("POST", "/api/repos/move")
def post_repos_move(qs, body):
    from . import terminals
    rid = body.get("id")
    live = [t for t in terminals.list_all(project=rid) if t.get("alive")]
    if live:
        raise ValueError(f"Feche os {len(live)} terminal(is)/agente(s) abertos neste projeto antes de mover a pasta")
    return git.move_repo(rid, body.get("dest"))


@route("POST", "/api/repos/remove")
def post_repos_remove(qs, body):
    git.remove_repo(body.get("id"))
    return {"ok": True}


@route("POST", "/api/repos/pin")
def post_repos_pin(qs, body):
    git.set_pinned(body.get("id"), body.get("pinned"))
    return {"ok": True}


@route("GET", "/api/repo/status")
def get_repo_status(qs, body):
    return git.status(q1(qs, "id"))


@route("GET", "/api/repo/graph")
def get_repo_graph(qs, body):
    return git.graph(q1(qs, "id"), int(q1(qs, "limit", "400")), q1(qs, "ref") or None, q1(qs, "all", "1") == "1",
                     q1(qs, "author") or None, q1(qs, "search") or None, int(q1(qs, "skip", "0")))


@route("GET", "/api/repo/commit")
def get_repo_commit(qs, body):
    return git.commit_detail(q1(qs, "id"), q1(qs, "sha", ""))


@route("GET", "/api/repo/diff")
def get_repo_diff(qs, body):
    return git.diff(q1(qs, "id"), q1(qs, "path") or None, q1(qs, "sha") or None, q1(qs, "staged", "0") == "1",
                    int(q1(qs, "context", "3")))


@route("GET", "/api/repo/refs")
def get_repo_refs(qs, body):
    return git.refs(q1(qs, "id"))


@route("GET", "/api/repo/clean-check")
def get_repo_clean_check(qs, body):
    return {"blockers": git.clean_blockers(q1(qs, "id"))}


@route("GET", "/api/activity")
def get_activity(qs, body):
    """Histórico de uma PR (o arquivo inteiro, não só os 300 do estado): pela chave, mais builds/deploys com o número dela."""
    key, num, org = q1(qs, "key"), q1(qs, "prId") or "", q1(qs, "org")
    items = read_activity()
    if key:
        n = int(num) if num.isdigit() else None
        items = [e for e in items if e.get("key") == key or (n and e.get("prNumber") == n and (not org or e.get("org") == org))]
    return {"activity": items[:2000]}


@route("GET", "/api/repo/branch-cleanup")
def get_repo_branch_cleanup(qs, body):
    """Plano de limpeza das branches locais: busca no servidor (com prune) e classifica pela principal."""
    return git.cleanup_plan(q1(qs, "id"), q1(qs, "fetch", "1") == "1")


REPO_ACTIONS = {
    "stage": lambda b: git.stage(b["id"], b.get("paths")),
    "stage-all": lambda b: git.stage_all(b["id"]),
    "unstage": lambda b: git.unstage(b["id"], b.get("paths")),
    "discard": lambda b: git.discard(b["id"], b.get("paths")),
    "commit": lambda b: git.commit(b["id"], b.get("message"), bool(b.get("amend")), bool(b.get("stageAll"))),
    "checkout": lambda b: git.checkout(b["id"], b.get("ref"), track=b.get("track")),
    "branch-create": lambda b: git.create_branch(b["id"], b.get("name"), b.get("start"), b.get("switch", True)),
    "branch-delete": lambda b: git.delete_branch(b["id"], b.get("name"), bool(b.get("force")), bool(b.get("remote"))),
    "branch-rename": lambda b: git.rename_branch(b["id"], b.get("old"), b.get("new")),
    "fetch": lambda b: git.fetch(b["id"]),
    "pull": lambda b: git.pull(b["id"], bool(b.get("rebase"))),
    "push": lambda b: git.push(b["id"], bool(b.get("force"))),
    "merge": lambda b: git.merge(b["id"], b.get("ref")),
    "rebase": lambda b: git.rebase(b["id"], b.get("onto")),
    "branch-push": lambda b: git.push_branch(b["id"], b.get("name"), bool(b.get("force"))),
    "branch-update": lambda b: git.update_branch(b["id"], b.get("name")),
    "tag-delete": lambda b: git.delete_tag(b["id"], b.get("name"), bool(b.get("remote"))),
    "tag-push": lambda b: git.push_tag(b["id"], b.get("name")),
    "cherry-pick": lambda b: git.cherry_pick(b["id"], b.get("sha")),
    "revert": lambda b: git.revert(b["id"], b.get("sha")),
    "stash": lambda b: git.stash(b["id"], b.get("action"), b.get("ref"), b.get("message")),
    "tag": lambda b: git.create_tag(b["id"], b.get("name"), b.get("sha"), b.get("message")),
    "reset": lambda b: git.reset(b["id"], b.get("sha"), b.get("mode", "mixed")),
    "abort": lambda b: git.abort_operation(b["id"]),
    "continue": lambda b: git.continue_operation(b["id"]),
    "clean": lambda b: git.clean_local(b["id"]),
    "branch-cleanup": lambda b: git.cleanup_branches(b["id"], b.get("branches"), bool(b.get("remote"))),
}
for _name, _fn in REPO_ACTIONS.items():
    POST[f"/api/repo/{_name}"] = (lambda fn: lambda qs, body: fn(body) or {"ok": True})(_fn)


@route("POST", "/api/open")
def post_open(qs, body):
    path = git.get_repo(body["id"])["path"] if body.get("id") else body.get("path")
    git.open_in(path, body.get("target"), body.get("editor") or ctx.config.get("editor") or "vscode", body.get("file"))
    return {"ok": True}


@route("GET", "/api/jobs")
def get_job(qs, body):
    job = git.jobs.get(q1(qs, "id", ""))
    if not job:
        raise LookupError("tarefa não encontrada")
    return job


@route("POST", "/api/pr/create")
def post_pr_create(qs, body):
    repo = git.get_repo(body["repoId"])
    info = git.parse_remote(repo.get("remoteUrl"))
    title = (body.get("title") or "").strip()
    if not title:
        raise ValueError("Dê um título para a PR")
    source, target = body.get("source"), body.get("target")
    if not source or not target or source == target:
        raise ValueError("Escolha a branch de origem e a de destino (diferentes)")
    if info.get("provider") == "github":
        acc = engine.gh_by_login(info["owner"]) or next(iter(ctx.gh.values()), None)
        if not acc:
            raise ValueError("Conecte uma conta do GitHub para criar PRs neste repositório")
        res = acc.create_pr(info["slug"], source, target, title, body.get("description") or "", body.get("draft"))
    elif info.get("provider") == "azure":
        org = next((o for o in ctx.orgs.values() if o.url.rstrip("/").rsplit("/", 1)[-1].lower() == info["owner"].lower()
                    or o.name.lower() == info["owner"].lower()), None)
        if not org:
            raise ValueError(f"A organização {info['owner']} do Azure não está conectada")
        res = org.create_pr(info["project"], info["name"], source, target, title, body.get("description") or "", body.get("draft"))
    else:
        raise ValueError("O remoto deste repositório não é do GitHub nem do Azure DevOps")
    log_activity("manual", "pr-create", {"key": None, "provider": info["provider"], "org": info["owner"], "prId": res["id"],
                                         "title": title, "target": target, "repo": info["name"], "url": res["url"]})
    wake.set()
    return res


# ---------------------------------------------------------------- catálogos
# ---------------------------------------------------------------- favoritos e tags (qualquer conta)
@route("GET", "/api/library")
def get_library(qs, body):
    return library.view()


@route("GET", "/api/library/search")
def get_library_search(qs, body):
    return library.search(q1(qs, "q", ""), force=q1(qs, "force", "0") == "1")


@route("POST", "/api/library/favorite")
def post_library_favorite(qs, body):
    return library.favorite(body)


@route("POST", "/api/library/tags")
def post_library_tags(qs, body):
    return library.set_tags(body)


@route("POST", "/api/library/tag")
def post_library_tag(qs, body):
    return library.save_tag(body)


@route("POST", "/api/library/tag/delete")
def post_library_tag_delete(qs, body):
    library.delete_tag(body.get("name"))
    return {"ok": True}


@route("POST", "/api/library/clone")
def post_library_clone(qs, body):
    return library.clone(body.get("key"), body.get("dest"))


# ---------------------------------------------------------------- quadro (kanban)
# ---------------------------------------------------------------- issues e work items: ler inteiro e comentar
def _issue_acc(body):
    """A conta da issue/work item: GitHub pelo login (ou a 1ª), Azure pelo nome da organização."""
    return engine.account_for_item({"provider": body.get("provider"), "account": body.get("account"), "org": body.get("org") or ""})


@route("GET", "/api/issues/browse")
def get_issues_browse(qs, body):
    return engine.browse_issues(q1(qs, "scope", "all"), q1(qs, "state", "open"), q1(qs, "fresh") == "1")


@route("GET", "/api/issue")
def get_issue(qs, body):
    q = {k: q1(qs, k) for k in ("provider", "account", "org", "repo", "number")}
    acc = _issue_acc(q)
    return acc.issue(q["repo"], q["number"]) if q["provider"] == "github" else acc.work_item(q["number"])


@route("POST", "/api/issue/comment")
def post_issue_comment(qs, body):
    text = (body.get("text") or "").strip()
    if not text:
        raise ValueError("Escreva o comentário")
    acc = _issue_acc(body)
    if body.get("provider") == "github":
        acc.comment_issue(body.get("repo"), body.get("number"), text)
    else:
        acc.comment_work_item(body.get("number"), text)
    return {"ok": True}


def _patch_issue_lists(key, d):
    """Depois de editar: a issue nas listas da memória (a leitura de fundo e a consulta sob demanda) já com o que
    mudou — a tela relê o estado e não volta a mostrar o antigo até a próxima leitura."""
    if not key:
        return
    fields = {"title": d.get("title"), "state": d.get("state"), "updated": d.get("updated") or now_iso(),
              "labels": [{"name": n, "color": None} for n in d.get("labels") or []]}
    who = [a.strip() for a in (d.get("assignee") or "").split(",") if a.strip()]
    with lock:
        pools = [state.get("issues") or []] + [hit[1].get("issues") or [] for hit in getattr(engine, "_browse", {}).values()]
        for pool in pools:
            for i in pool:
                if i.get("key") != key:
                    continue
                colors = {l["name"]: l.get("color") for l in i.get("labels") or []}
                i.update(fields, labels=[{"name": l["name"], "color": colors.get(l["name"])} for l in fields["labels"]])
                old = {a.get("login"): a for a in i.get("assignees") or []}
                i["assignees"] = [old.get(n) or {"login": n, "avatar": None} for n in who]


@route("POST", "/api/issue/edit")
def post_issue_edit(qs, body):
    changes = body.get("changes") or {}
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Nada para salvar")
    acc = _issue_acc(body)
    if body.get("provider") == "github":
        d = acc.edit_issue(body.get("repo"), body.get("number"), changes)
    else:
        d = acc.edit_work_item(body.get("number"), changes)
    _patch_issue_lists(body.get("key"), d)
    return d


@route("GET", "/api/issue/options")
def get_issue_options(qs, body):
    q = {k: q1(qs, k) for k in ("provider", "account", "org", "repo", "project", "type")}
    acc = _issue_acc(q)
    return acc.issue_options(q["repo"]) if q["provider"] == "github" else acc.work_item_options(q["project"] or q["repo"], q["type"] or "Task")


# ---------------------------------------------------------------- PR: arquivos modificados e o diff de cada um
def _pr_of(key):
    pr = find_item("pr", key)
    if not pr:
        raise LookupError("PR não está mais na lista — atualize")
    return pr, engine.account_for_item(pr)


@route("GET", "/api/pr/files")
def get_pr_files(qs, body):
    pr, acc = _pr_of(q1(qs, "key"))
    if pr.get("provider") == "github":
        return acc.pr_files(pr["project"], pr["prId"])
    return acc.pr_files(pr["project"], pr["repoId"], pr["prId"])


@route("GET", "/api/pr/file")
def get_pr_file(qs, body):
    """O arquivo na base e na cabeça da PR (cada lado vazio se não existe nele), para o diff lado a lado."""
    pr, acc = _pr_of(q1(qs, "key"))
    path, old, base, head = q1(qs, "path"), q1(qs, "oldPath") or q1(qs, "path"), q1(qs, "base"), q1(qs, "head")
    if not path or not base or not head:
        raise ValueError("Faltou o arquivo ou os commits")
    if pr.get("provider") == "github":
        a, b = acc.file_at(pr["project"], old, base), acc.file_at(pr["project"], path, head)
    else:
        a, b = acc.file_at(pr["project"], pr["repoId"], old, base), acc.file_at(pr["project"], pr["repoId"], path, head)
    binary = any(x is not None and "\0" in x[:8000] for x in (a, b))
    big = any(x is not None and len(x) > 3_000_000 for x in (a, b))
    return {"original": "" if binary or big or a is None else a, "modified": "" if binary or big or b is None else b,
            "binary": binary, "tooBig": big, "existsBefore": a is not None, "existsAfter": b is not None}


# ---------------------------------------------------------------- Sprints e projetos (Azure Boards / GitHub Projects)
@route("GET", "/api/boards")
def get_boards(qs, body):
    return boards.list_boards()


@route("GET", "/api/board")
def get_board(qs, body):
    return boards.board(q1(qs, "id"), q1(qs, "sprint") or None)


@route("POST", "/api/board/move")
def post_board_move(qs, body):
    return boards.move(body.get("id"), body.get("item") or {}, body.get("column"))


@route("POST", "/api/board/draft-to-issue")
def post_board_draft(qs, body):
    return boards.draft_to_issue(body.get("id"), body.get("itemId"), body.get("repo"))


# ---------------------------------------------------------------- PR: revisão da IA, abrir no projeto, ajustar a minha
@route("POST", "/api/pr/ai-review")
def post_pr_ai_review(qs, body):
    return prreview.rerun(body.get("key"))


@route("POST", "/api/pr/open-workspace")
def post_pr_open_workspace(qs, body):
    pr, _acc = _pr_of(body.get("key"))
    with lock:
        mine = any(p["key"] == pr["key"] for p in state["myPrs"])
    return prreview.open_workspace(pr, mine)


@route("GET", "/api/pr/feedback")
def get_pr_feedback(qs, body):
    pr, _acc = _pr_of(q1(qs, "key"))
    return {"items": prreview.feedback(pr)}


@route("POST", "/api/pr/fix")
def post_pr_fix(qs, body):
    terminals.hint_size(body.get("cols"), body.get("rows"))
    pr, _acc = _pr_of(body.get("key"))
    return prreview.fix(pr, body.get("accountId"))


@route("GET", "/api/kanban")
def get_kanban(qs, body):
    return kanban.view()


@route("POST", "/api/kanban/card")
def post_kanban_card(qs, body):
    return kanban.save_card(body)


@route("POST", "/api/kanban/card/delete")
def post_kanban_card_delete(qs, body):
    kanban.delete_card(body.get("id"))
    return {"ok": True}


@route("POST", "/api/kanban/move")
def post_kanban_move(qs, body):
    return kanban.move(body.get("id"), body.get("column"), body.get("index"))


@route("POST", "/api/kanban/columns")
def post_kanban_columns(qs, body):
    return kanban.save_columns(body)


@route("POST", "/api/kanban/link")
def post_kanban_link(qs, body):
    return kanban.link_task(body.get("id"), body.get("repoId"), body.get("taskId"), body.get("flow"))


@route("GET", "/api/kanban/context")
def get_kanban_context(qs, body):
    return {"text": kanban.context(q1(qs, "id"))}


@route("POST", "/api/kanban/unlink")
def post_kanban_unlink(qs, body):
    return kanban.unlink_task(body.get("id"), body.get("taskId"))


# anexos do cartão: sobem em base64 (a API só fala JSON); a tela lê com fetch (a chave vai no cabeçalho) → blob URL
@route("POST", "/api/kanban/file")
def post_kanban_file(qs, body):
    return kanban.add_file(body.get("id"), body.get("name"), body.get("data"), body.get("type"))


@route("GET", "/api/kanban/file")
def get_kanban_file(qs, body):
    return kanban.get_file(q1(qs, "id"), q1(qs, "f"))


@route("POST", "/api/kanban/file/delete")
def post_kanban_file_delete(qs, body):
    return kanban.remove_file(body.get("id"), body.get("f"))


@route("POST", "/api/kanban/file/open")
def post_kanban_file_open(qs, body):
    return kanban.open_file(body.get("id"), body.get("f"), bool(body.get("reveal")))


# ---------------------------------------------------------------- quais repositórios acompanhar
@route("GET", "/api/tracking")
def get_tracking(qs, body):
    return tracking.view()


@route("POST", "/api/tracking/account")
def post_tracking_account(qs, body):
    out = tracking.set_account(body.get("key"), body.get("mode"))
    wake.set()   # relê já com o filtro novo
    return out


@route("POST", "/api/tracking/repo")
def post_tracking_repo(qs, body):
    out = tracking.set_repo(body.get("key"), body)
    wake.set()
    return out


@route("POST", "/api/tracking/many")
def post_tracking_many(qs, body):
    out = tracking.set_many(body.get("keys") or [], bool(body.get("track")))
    wake.set()
    return out


@route("GET", "/api/catalogs")
def get_catalogs(qs, body):
    return catalogs.summary()


# ---------------------------------------------------------------- terminais
@route("GET", "/api/terms")
def get_terms(qs, body):
    return {"terms": terminals.list_all()}


@route("POST", "/api/terms/new")
def post_term_new(qs, body):
    t = terminals.create(body.get("cwd"), body.get("title"), body.get("command"), body.get("kind") or "shell",
                         body.get("meta"), None, body.get("cols"), body.get("rows"))
    return t.info()


@route("POST", "/api/terms/close")
def post_term_close(qs, body):
    workspace.close_terminal(body.get("id"))
    return {"ok": True}


@route("POST", "/api/terms/drop")
def post_term_drop(qs, body):
    return workspace.drop_file(body.get("id"), body.get("name"), body.get("data"), bool(body.get("keep")))


@route("GET", "/api/terms/refs")
def get_term_refs(qs, body):
    return {"refs": workspace.drop_refs(q1(qs, "id"))}


@route("POST", "/api/terms/refs/remove")
def post_term_refs_remove(qs, body):
    workspace.drop_remove(body.get("id"), body.get("path"))
    return {"ok": True}


@route("POST", "/api/terms/rename")
def post_term_rename(qs, body):
    terminals.rename(body.get("id"), body.get("title"))
    return {"ok": True}


# ---------------------------------------------------------------- projetos abertos, tarefas e arquivos (v3)
@route("GET", "/api/ws")
def get_ws(qs, body):
    agents.refresh_codex()
    return workspace.state()


@route("POST", "/api/ws/open")
def post_ws_open(qs, body):
    return workspace.open_project(body.get("repoId"), body.get("path"))


@route("POST", "/api/ws/close")
def post_ws_close(qs, body):
    workspace.close_project(body.get("repoId"))
    return {"ok": True}


@route("POST", "/api/ws/focus")
def post_ws_focus(qs, body):
    try:
        r = git.get_repo(body.get("repoId"))
    except (ValueError, LookupError, KeyError, TypeError):
        return {"ok": False}
    agents.focus(r["id"], r["name"], body.get("seconds"))
    return {"ok": True}


@route("POST", "/api/ws/activate")
def post_ws_activate(qs, body):
    workspace.activate(body.get("repoId"))
    return {"ok": True}


@route("POST", "/api/ws/reorder")
def post_ws_reorder(qs, body):
    workspace.reorder(body.get("ids") or [])
    return {"ok": True}


@route("GET", "/api/ws/hub")
def get_ws_hub(qs, body):
    return workspace.hub()


@route("POST", "/api/ws/groups/save")
def post_ws_group_save(qs, body):
    return workspace.save_group(body)


@route("POST", "/api/ws/groups/delete")
def post_ws_group_delete(qs, body):
    workspace.delete_group(body.get("id"))
    return {"ok": True}


@route("POST", "/api/ws/groups/assign")
def post_ws_group_assign(qs, body):
    workspace.assign_group(body.get("repoId"), body.get("groupId") or None)
    return {"ok": True}


@route("POST", "/api/ws/groups/reorder")
def post_ws_group_reorder(qs, body):
    workspace.reorder_groups(body.get("ids") or [])
    return {"ok": True}


@route("POST", "/api/ws/groups/open")
def post_ws_group_open(qs, body):
    return workspace.open_group(body.get("id"))


@route("POST", "/api/ws/settings")
def post_ws_settings(qs, body):
    return workspace.save_settings(body.get("repoId"), body)


@route("POST", "/api/ws/task")
def post_ws_task(qs, body):
    terminals.hint_size(body.get("cols"), body.get("rows"))
    return workspace.create_task(body.get("repoId"), body)


@route("POST", "/api/ws/task/here")
def post_ws_task_here(qs, body):
    terminals.hint_size(body.get("cols"), body.get("rows"))
    return workspace.start_in_checkout(body.get("repoId"), body)


@route("GET", "/api/ws/task/cleanup")
def get_ws_task_cleanup(qs, body):
    return workspace.cleanup_info(q1(qs, "repoId"))


@route("POST", "/api/ws/task/cleanup")
def post_ws_task_cleanup(qs, body):
    return workspace.cleanup(body.get("repoId"), body.get("taskIds") or [], body.get("orphans") or [],
                             bool(body.get("deleteBranch")), bool(body.get("force")))


@route("POST", "/api/ws/task/update")
def post_ws_task_update(qs, body):
    return workspace.update_task(body.get("repoId"), body.get("taskId"), body)


@route("POST", "/api/ws/task/close")
def post_ws_task_close(qs, body):
    return {"closed": workspace.close_task(body.get("repoId"), body.get("taskId"))}


@route("POST", "/api/ws/task/remove")
def post_ws_task_remove(qs, body):
    workspace.remove_task(body.get("repoId"), body.get("taskId"), bool(body.get("force")), bool(body.get("deleteBranch")))
    return {"ok": True}


@route("GET", "/api/ws/task/diff")
def get_ws_task_diff(qs, body):
    return workspace.diff_summary(q1(qs, "repoId"), q1(qs, "taskId"))


@route("GET", "/api/ws/task/changes")
def get_ws_task_changes(qs, body):
    return workspace.changed_files(q1(qs, "repoId"), q1(qs, "taskId"))


@route("GET", "/api/ws/task/base-file")
def get_ws_task_base_file(qs, body):
    return workspace.base_file(q1(qs, "repoId"), q1(qs, "taskId"), q1(qs, "path"))


@route("POST", "/api/ws/shell")
def post_ws_shell(qs, body):
    terminals.hint_size(body.get("cols"), body.get("rows"))
    return workspace.start_shell(body.get("repoId"), body.get("taskId"), body.get("title"), body.get("command"))


@route("POST", "/api/ws/agent")
def post_ws_agent(qs, body):
    terminals.hint_size(body.get("cols"), body.get("rows"))
    return workspace.start_agent(body.get("repoId"), body.get("taskId"), body.get("accountId"), body.get("prompt"),
                                 body.get("mode"), body.get("title"), body.get("resume"), body.get("card"))


@route("POST", "/api/ws/agent/handoff")
def post_ws_agent_handoff(qs, body):
    return workspace.handoff(body.get("termId"), body.get("accountId"), body.get("mode") or "auto")


@route("POST", "/api/ws/agent/limit/dismiss")
def post_ws_agent_limit_dismiss(qs, body):
    agents.clear_limit(body.get("sid"))
    return {"ok": True}


@route("POST", "/api/ws/agent/input")
def post_ws_agent_input(qs, body):
    return workspace.send_input(body.get("termId"), body.get("text"), body.get("submit", True) is not False)


@route("GET", "/api/ws/run-configs")
def get_ws_run_configs(qs, body):
    return workspace.run_configs(q1(qs, "repoId"), q1(qs, "taskId"))


@route("POST", "/api/ws/run")
def post_ws_run(qs, body):
    terminals.hint_size(body.get("cols"), body.get("rows"))
    return workspace.run(body.get("repoId"), body.get("taskId"), body.get("configId"))


@route("GET", "/api/ws/files")
def get_ws_files(qs, body):
    return workspace.files(q1(qs, "repoId"), q1(qs, "taskId"), q1(qs, "under"))


@route("GET", "/api/ws/file")
def get_ws_file(qs, body):
    return workspace.read_file(q1(qs, "repoId"), q1(qs, "path"), q1(qs, "taskId"))


@route("POST", "/api/ws/file")
def post_ws_file(qs, body):
    return workspace.write_file(body.get("repoId"), body.get("path"), body.get("text", ""), body.get("taskId"), body.get("mtime"))


@route("GET", "/api/ws/search")
def get_ws_search(qs, body):
    return workspace.search(q1(qs, "repoId"), q1(qs, "q", ""), q1(qs, "taskId"), q1(qs, "regex") == "1", q1(qs, "case") == "1")


# ---------------------------------------------------------------- editor (estilo VS Code): base do diff e explorador
@route("GET", "/api/ws/base")
def get_ws_base(qs, body):
    return editor.base_text(q1(qs, "repoId"), q1(qs, "path"), q1(qs, "taskId"), q1(qs, "ref", "HEAD"))


@route("POST", "/api/ws/fs/create")
def post_ws_fs_create(qs, body):
    return editor.create(body.get("repoId"), body.get("path"), body.get("taskId"), bool(body.get("folder")))


@route("POST", "/api/ws/fs/rename")
def post_ws_fs_rename(qs, body):
    return editor.rename(body.get("repoId"), body.get("from"), body.get("to"), body.get("taskId"))


@route("POST", "/api/ws/fs/delete")
def post_ws_fs_delete(qs, body):
    return editor.delete(body.get("repoId"), body.get("path"), body.get("taskId"), body.get("paths"), bool(body.get("permanent")))


@route("POST", "/api/ws/fs/reveal")
def post_ws_fs_reveal(qs, body):
    return editor.reveal(body.get("repoId"), body.get("path") or "", body.get("taskId"))


@route("POST", "/api/ws/fs/clipboard")
def post_ws_fs_clipboard(qs, body):
    return editor.clipboard(body.get("text"))


@route("POST", "/api/ws/fs/move")
def post_ws_fs_move(qs, body):
    return editor.move(body.get("repoId"), body.get("paths"), body.get("dest"), body.get("taskId"), bool(body.get("overwrite")))


@route("POST", "/api/ws/fs/copy")
def post_ws_fs_copy(qs, body):
    return editor.copy(body.get("repoId"), body.get("paths"), body.get("dest"), body.get("taskId"))


@route("POST", "/api/ws/fs/free")
def post_ws_fs_free(qs, body):
    return editor.free_name(body.get("repoId"), body.get("dest"), body.get("name"), body.get("taskId"))


@route("POST", "/api/ws/fs/upload")
def post_ws_fs_upload(qs, body):
    return editor.upload(body.get("repoId"), body.get("path"), body.get("data"), body.get("offset"), body.get("taskId"), bool(body.get("folder")))


# ---------------------------------------------------------------- .NET como no Visual Studio
@route("GET", "/api/dotnet/solution")
def get_dotnet_solution(qs, body):
    if q1(qs, "refresh") == "1":
        dotnet.toolchain(force=True)
    return dotnet.solution(q1(qs, "repoId"), q1(qs, "taskId"))


@route("POST", "/api/dotnet/build")
def post_dotnet_build(qs, body):
    terminals.hint_size(body.get("cols"), body.get("rows"))
    return dotnet.build(body.get("repoId"), body.get("taskId"), body.get("target"), body.get("config"), body.get("action") or "Build")


@route("POST", "/api/dotnet/start")
def post_dotnet_start(qs, body):
    terminals.hint_size(body.get("cols"), body.get("rows"))
    return dotnet.start(body.get("repoId"), body.get("taskId"), body.get("projects") or [], body.get("config"), body.get("profile"))


# ---------------------------------------------------------------- executar e depurar (launch.json, DAP)
@route("GET", "/api/launch/configs")
def get_launch_configs(qs, body):
    return launch.configs(q1(qs, "repoId"), q1(qs, "taskId"))


@route("GET", "/api/launch/raw")
def get_launch_raw(qs, body):
    return launch.raw_config(q1(qs, "repoId"), q1(qs, "taskId"), q1(qs, "id"))


@route("POST", "/api/launch/save")
def post_launch_save(qs, body):
    return launch.save_config(body.get("repoId"), body.get("taskId"), body.get("config") or {}, body.get("oldName"))


@route("POST", "/api/launch/compound")
def post_launch_compound(qs, body):
    return launch.save_compound(body.get("repoId"), body.get("taskId"), body.get("name"), body.get("names") or [], body.get("oldName"))


@route("POST", "/api/launch/delete")
def post_launch_delete(qs, body):
    return launch.delete_config(body.get("repoId"), body.get("taskId"), body.get("id") or "")


@route("POST", "/api/launch/settings")
def post_launch_settings(qs, body):
    return launch.save_project_settings(body.get("repoId"), body)


@route("GET", "/api/launch/export-preview")
def get_launch_export_preview(qs, body):
    return launch.preview_export(q1(qs, "repoId"), q1(qs, "taskId"), (q1(qs, "ids") or "").split("\n") if q1(qs, "ids") else [])


@route("POST", "/api/launch/export")
def post_launch_export(qs, body):
    return launch.export_vscode(body.get("repoId"), body.get("taskId"), body.get("ids") or None)


@route("POST", "/api/launch/import")
def post_launch_import(qs, body):
    return launch.import_vscode(body.get("repoId"), body.get("taskId"))


@route("GET", "/api/debug/adapters")
def get_debug_adapters(qs, body):
    return debug.adapters()


@route("POST", "/api/debug/install")
def post_debug_install(qs, body):
    return debug.install(body.get("kind"))


@route("POST", "/api/debug/start")
def post_debug_start(qs, body):
    terminals.hint_size(body.get("cols"), body.get("rows"))
    return debug.start(body.get("repoId"), body.get("taskId"), body.get("configId"), bool(body.get("noDebug")), body.get("device") or None)


@route("POST", "/api/debug/stop")
def post_debug_stop(qs, body):
    return debug.stop(body.get("sid"), body.get("group"), body.get("repoId"))


@route("POST", "/api/debug/restart")
def post_debug_restart(qs, body):
    return debug.restart(body.get("sid"))


@route("POST", "/api/debug/control")
def post_debug_control(qs, body):
    return debug.control(body.get("sid"), body.get("action"), body.get("threadId"))


@route("GET", "/api/debug/poll")
def get_debug_poll(qs, body):
    return debug.poll(int(q1(qs, "after", "0") or 0), float(q1(qs, "wait", "25") or 0), q1(qs, "repoId"))


@route("GET", "/api/debug/stack")
def get_debug_stack(qs, body):
    return debug.stack(q1(qs, "sid"), q1(qs, "threadId"))


@route("GET", "/api/debug/scopes")
def get_debug_scopes(qs, body):
    return debug.scopes(q1(qs, "sid"), q1(qs, "frameId"))


@route("GET", "/api/debug/variables")
def get_debug_variables(qs, body):
    return debug.variables(q1(qs, "sid"), q1(qs, "ref"))


@route("POST", "/api/debug/evaluate")
def post_debug_evaluate(qs, body):
    return debug.evaluate(body.get("sid"), str(body.get("expression") or ""), body.get("frameId"), body.get("context") or "repl")


@route("POST", "/api/debug/set-variable")
def post_debug_set_variable(qs, body):
    return debug.set_variable(body.get("sid"), body.get("ref"), body.get("name"), str(body.get("value") or ""))


@route("GET", "/api/debug/output")
def get_debug_output(qs, body):
    return debug.output(q1(qs, "sid"), q1(qs, "after", "0"))


@route("GET", "/api/debug/source")
def get_debug_source(qs, body):
    return debug.source(q1(qs, "sid"), q1(qs, "ref"), q1(qs, "path"))


@route("GET", "/api/debug/breakpoints")
def get_debug_breakpoints(qs, body):
    return debug.breakpoints(q1(qs, "repoId"))


@route("POST", "/api/debug/breakpoints")
def post_debug_breakpoints(qs, body):
    return debug.set_breakpoints(body.get("repoId"), body.get("path"), body.get("breakpoints") or [])


@route("POST", "/api/debug/breakpoints/clear")
def post_debug_breakpoints_clear(qs, body):
    return debug.clear_breakpoints(body.get("repoId"), body.get("path"))


@route("POST", "/api/debug/exceptions")
def post_debug_exceptions(qs, body):
    return debug.set_exception_filters(body.get("repoId"), body.get("kind"), body.get("filters") or [])


@route("GET", "/api/debug/devices")
def get_debug_devices(qs, body):
    return debug.devices(q1(qs, "force") == "1")


@route("POST", "/api/debug/emulator")
def post_debug_emulator(qs, body):
    return debug.launch_emulator(body.get("id"))


@route("POST", "/api/debug/devtools")
def post_debug_devtools(qs, body):
    return debug.devtools(body.get("sid"), body.get("page") or "", body.get("theme") or "dark", bool(body.get("embed")))


@route("POST", "/api/debug/service")
def post_debug_service(qs, body):
    return debug.service(body.get("sid"), body.get("method"), body.get("params"))


@route("POST", "/api/debug/saved")
def post_debug_saved(qs, body):
    return debug.on_saved(body.get("repoId"), body.get("taskId"), body.get("path") or "")


@route("GET", "/api/dotnet/problems")
def get_dotnet_problems(qs, body):
    return dotnet.problems(q1(qs, "termId"))


@route("POST", "/api/dotnet/open-vs")
def post_dotnet_open_vs(qs, body):
    return dotnet.open_in_vs(body.get("repoId"), body.get("taskId"), body.get("target"))


# ---------------------------------------------------------------- extensões do VS Code (temas, ícones, snippets)
@route("GET", "/api/ext/list")
def get_ext_list(qs, body):
    return extensions.public_list(q1(qs, "refresh") == "1")


@route("GET", "/api/ext/vscode-settings")
def get_ext_vscode_settings(qs, body):
    return {"apps": extensions.vscode_settings()}


@route("POST", "/api/ext/vscode-settings")
def post_ext_vscode_settings(qs, body):
    return extensions.write_vscode_settings(body.get("app"), body.get("values") or {})


@route("GET", "/api/ext/file")
def get_ext_file(qs, body):
    return extensions.file(q1(qs, "key"), q1(qs, "path"))


@route("GET", "/api/ext/json")
def get_ext_json(qs, body):
    return extensions.json_file(q1(qs, "key"), q1(qs, "path"))


@route("GET", "/api/ext/theme")
def get_ext_theme(qs, body):
    return extensions.theme(q1(qs, "key"), q1(qs, "path"))


@route("GET", "/api/ext/snippets")
def get_ext_snippets(qs, body):
    return extensions.snippets(q1(qs, "key"))


@route("GET", "/api/ext/languages")
def get_ext_languages(qs, body):
    return extensions.language_configs(q1(qs, "key"))


@route("GET", "/api/ext/search")
def get_ext_search(qs, body):
    return extensions.search(q1(qs, "q", ""), q1(qs, "category"), q1(qs, "size", 30))


@route("POST", "/api/ext/install")
def post_ext_install(qs, body):
    return extensions.install(body.get("namespace"), body.get("name"), body.get("version"))


@route("POST", "/api/ext/uninstall")
def post_ext_uninstall(qs, body):
    return extensions.uninstall(body.get("key"))


# ---------------------------------------------------------------- contas de IA
@route("GET", "/api/ai")
def get_ai(qs, body):
    agents.refresh_codex()
    if q1(qs, "rescan") == "1":
        from . import userpath
        userpath.get(force=True)
        agents.which_all(force=True)
    return agents.accounts()


@route("GET", "/api/ai/activity")
def get_ai_activity(qs, body):
    return {"activity": agents.activity()}


@route("POST", "/api/ai/login")
def post_ai_login(qs, body):
    return agents.open_login(body.get("id"))


@route("POST", "/api/ai/probe")
def post_ai_probe(qs, body):
    """Ler o limite agora: uma conta (id) ou todas as do Claude (all=true)."""
    if body.get("all"):
        ok, errors = 0, {}
        for a in [x for x in agents._load()["accounts"] if x["provider"] == "claude"]:
            try:
                agents.probe_limits(a["id"])
                ok += 1
            except Exception as e:  # noqa: BLE001
                errors[a["id"]] = str(e)[:200]
        agents._activity["at"] = 0
        return {"ok": ok, "errors": errors}
    r = agents.probe_limits(body.get("id"))
    agents._activity["at"] = 0
    return r


@route("GET", "/api/lsp")
def get_lsp(qs, body):
    return {"servers": {k: v["name"] for k, v in lsp.available().items()}, "known": {k: [c[0] for c in v] for k, v in lsp.SERVERS.items()}}


@route("GET", "/api/ai/usage")
def get_ai_usage(qs, body):
    return agents.usage_report(int(q1(qs, "days", "30") or 30))


@route("GET", "/api/ai/detect")
def get_ai_detect(qs, body):
    return {"found": agents.detect()}


@route("POST", "/api/ai/save")
def post_ai_save(qs, body):
    return agents.save_account(body)


@route("POST", "/api/ai/update")
def post_ai_update(qs, body):
    return agents.update_account(body)


@route("POST", "/api/ai/delete")
def post_ai_delete(qs, body):
    agents.delete_account(body.get("id"))
    return {"ok": True}


@route("POST", "/api/ai/default")
def post_ai_default(qs, body):
    agents.set_default(body.get("scope") or "*", body.get("id"))
    return {"ok": True}


# ---------------------------------------------------------------- consumo das IAs (modelo, effort, tokens)
@route("GET", "/api/ai/consumption")
def get_ai_consumption(qs, body):
    aiusage.start()
    return aiusage.report(int(q1(qs, "days") or 30))


@route("POST", "/api/ai/consumption/scan")
def post_ai_consumption_scan(qs, body):
    n = aiusage.scan()
    return {"ok": True, "files": n, "busy": n is None}


# ---------------------------------------------------------------- skills e MCPs (projeto × contas)
@route("GET", "/api/ai/tools")
def get_ai_tools(qs, body):
    return aitools.inventory(q1(qs, "repoId"))


@route("POST", "/api/ai/tools/copy")
def post_ai_tools_copy(qs, body):
    try:
        return aitools.copy(body.get("repoId"), body.get("type"), body.get("name"), body.get("from"), body.get("to"),
                            bool(body.get("overwrite")), bool(body.get("envRefs")))
    except FileExistsError as e:
        return {"ok": False, "exists": True, "error": str(e)}


@route("POST", "/api/ai/tools/remove")
def post_ai_tools_remove(qs, body):
    return aitools.remove(body.get("repoId"), body.get("type"), body.get("name"), body.get("loc"))


@route("GET", "/api/ai/tools/skill")
def get_ai_tools_skill(qs, body):
    return aitools.skill_text(q1(qs, "repoId"), q1(qs, "loc"), q1(qs, "name"))


@route("GET", "/api/clone-targets")
def get_clone_targets(qs, body):
    return {"targets": catalogs.clone_targets(q1(qs, "account"))}


@route("POST", "/api/accounts/dirs")
def post_account_dirs(qs, body):
    """Pastas base de uma conta: {key, dirs: [...]} substitui a lista; {key, add: pasta} acrescenta uma."""
    if body.get("add"):
        return {"dirs": catalogs.add_account_dir(body.get("key"), body["add"])}
    return {"dirs": catalogs.set_account_dirs(body.get("key"), body.get("dirs") or [])}


@route("GET", "/api/catalog")
def get_catalog(qs, body):
    return catalogs.view(q1(qs, "id"), force=q1(qs, "force", "0") == "1")


@route("GET", "/api/catalogs/suggestions")
def get_catalog_suggestions(qs, body):
    return {"suggestions": catalogs.suggestions()}


@route("POST", "/api/catalogs/save")
def post_catalog_save(qs, body):
    out = catalogs.upsert(body)
    catalogs.warm_async()   # contador do catálogo novo/editado
    return out


@route("POST", "/api/catalogs/delete")
def post_catalog_delete(qs, body):
    catalogs.delete(body.get("id"))
    return {"ok": True}


@route("POST", "/api/catalogs/clone")
def post_catalog_clone(qs, body):
    return catalogs.clone(body.get("id"), body.get("repoKey"), body.get("dest") or None)


@route("GET", "/api/remote-repos")
def get_remote_repos(qs, body):
    src = {"provider": q1(qs, "provider"), "account": q1(qs, "account", ""), "owner": q1(qs, "owner"), "project": q1(qs, "project")}
    return {"repos": catalogs.remote_repos(src, force=q1(qs, "force", "0") == "1")}


# ---------------------------------------------------------------- servidor
def _send_deadline(conn, secs):
    """Prazo para cada envio no socket (só no envio — a leitura do WebSocket espera o quanto for preciso)."""
    try:
        val = struct.pack("I", secs * 1000) if os.name == "nt" else struct.pack("ll", secs, 0)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, val)
    except (OSError, AttributeError, struct.error):
        pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="application/json", cache=False):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text/", "application/json", "application/javascript")) else ""))
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        return not TOKEN or hmac.compare_digest(self.headers.get("X-Codeck-Token") or "", TOKEN)

    def static(self, path):
        rel = urllib.parse.unquote(path).lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            full = os.path.join(STATIC_DIR, "index.html")   # app de página única
        if not os.path.isfile(full):
            return self.send(503, b"<h1>Tela n\xc3\xa3o compilada</h1><p>Rode: cd ui && npm install && npm run build</p>", "text/html")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".js"):
            ctype = "application/javascript"
        with open(full, "rb") as f:
            return self.send(200, f.read(), ctype, cache="/assets/" in full.replace(os.sep, "/"))

    def dispatch(self, table, body):
        url = urllib.parse.urlparse(self.path)
        fn = table.get(url.path)
        if not fn:
            return self.send(404, {"error": "rota não encontrada"})
        try:
            res = fn(urllib.parse.parse_qs(url.query), body)
            if isinstance(res, extensions.RawFile):   # arquivo de extensão (ícone, fonte, tema): bytes com o tipo certo
                return self.send(200, res.data, res.ctype)
            return self.send(200, res)
        except LookupError as e:
            return self.send(404, {"error": str(e).strip("'")})
        except (ValueError, git.GitError) as e:
            return self.send(400, {"error": str(e)})
        except OfflineError:
            return self.send(503, {"error": "Sem conexão com a internet — tente de novo quando ela voltar", "offline": True})
        except Exception as e:  # noqa: BLE001
            return self.send(500, {"error": str(e)[:600]})

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/ws/term/"):
            return self.terminal_socket(path[len("/ws/term/"):])
        if path.startswith("/ws/lsp/"):
            return self.lsp_socket(path[len("/ws/lsp/"):])
        if not path.startswith("/api/"):
            return self.static(path)
        if not self.authorized():
            return self.send(401, {"error": "abra pelo app"})
        return self.dispatch(GET, None)

    def terminal_socket(self, tid):
        """WebSocket de um terminal. A chave vem no subprotocolo "codeck.<token>" (o navegador não manda cabeçalho)."""
        offered = ws.WebSocket.offered_protocols(self)
        proto = next((p for p in offered if p.startswith("codeck.")), "")
        if TOKEN and not hmac.compare_digest(proto[len("codeck."):], TOKEN):
            return self.send(401, {"error": "abra pelo app"})
        try:
            term = terminals.get(tid)
        except LookupError:
            return self.send(404, {"error": "Terminal não encontrado"})
        sock = ws.WebSocket.accept(self, proto or None)
        # quem manda a saída ao vivo é a thread que lê o PTY: uma tela que parou de ler (janela suspensa, conexão
        # meio morta) travava essa thread no envio — o processo parava de ser lido, o agente travava na escrita e
        # nem os pedidos colados chegavam mais. Com prazo, a conexão cai e a tela reconecta de onde parou.
        _send_deadline(self.connection, 15)
        gate = threading.Lock()

        def hang_up():
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        def out(data):
            # a saída ao vivo espera o "hello" e o histórico (ver abaixo); antes chegava ANTES deles quando o processo
            # escrevia logo após assinar (agente recém-aberto): a tela apagava (reset) o que já tinha e ficava preta
            with gate:
                try:
                    if data is None:
                        sock.send_text(json.dumps({"t": "exit", "code": term.exit}))
                    else:
                        sock.send_bytes(data)
                except ws.Closed:
                    hang_up()
                    raise
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        since = q1(qs, "from")
        try:
            with gate:
                history, start, resumed = term.attach(out, int(since) if since and since.isdigit() else None)
                sock.send_text(json.dumps({"t": "hello", "start": start, "resume": resumed, **term.info()}))
                if history:
                    sock.send_bytes(history)
                if not term.alive:
                    sock.send_text(json.dumps({"t": "exit", "code": term.exit}))
            while True:
                op, data = sock.recv()
                if op == ws.BINARY:
                    term.write(data)
                    continue
                msg = json.loads(data or b"{}")
                if msg.get("t") == "in":
                    term.write(msg.get("d", "").encode("utf-8"))
                elif msg.get("t") == "resize":
                    term.resize(msg.get("c", 120), msg.get("r", 32))
        except (ws.Closed, OSError, ValueError):
            pass
        finally:
            term.detach(out)
            sock.closed = True

    def agent_hook(self, path):
        parts = path.strip("/").split("/")
        if len(parts) != 3:
            return self.send(404, {"error": "rota não encontrada"})
        length = min(int(self.headers.get("Content-Length") or 0), 2_000_000)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            return self.send(200, agents.hook(parts[1], parts[2], payload))
        except PermissionError:
            return self.send(403, {"error": "forbidden"})
        except (ValueError, json.JSONDecodeError):
            return self.send(400, {"error": "JSON inválido"})

    def lsp_socket(self, lang):
        """WebSocket de um servidor de linguagem na pasta do projeto/tarefa (?repoId=…&taskId=…)."""
        offered = ws.WebSocket.offered_protocols(self)
        proto = next((p for p in offered if p.startswith("codeck.")), "")
        if TOKEN and not hmac.compare_digest(proto[len("codeck."):], TOKEN):
            return self.send(401, {"error": "abra pelo app"})
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            root = workspace._root(q1(qs, "repoId"), q1(qs, "taskId"))
        except Exception as e:  # noqa: BLE001
            return self.send(400, {"error": str(e)})
        sock = ws.WebSocket.accept(self, proto or None)
        try:
            bridge = lsp.Bridge(lang, root, sock)
        except LookupError as e:
            sock.send_text(json.dumps({"codeck": "unavailable", "message": str(e)}))
            sock.close()
            return
        try:
            while True:
                op, data = sock.recv()
                bridge.send(data.decode("utf-8", "replace"))
        except (ws.Closed, OSError):
            pass
        finally:
            bridge.close()
            sock.closed = True

    def do_POST(self):
        if self.path.startswith("/hook/"):
            return self.agent_hook(urllib.parse.urlparse(self.path).path)
        if self.headers.get("X-Codeck") != "1" or not self.authorized():
            return self.send(403, {"error": "forbidden"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.send(400, {"error": "JSON inválido"})
        return self.dispatch(POST, body)


def _watch_parent(parent):
    def alive(pid):
        if os.name != "nt":
            return os.getppid() == pid
        k32 = ctypes.windll.kernel32  # no Windows o getppid não muda quando o pai morre
        h = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) != 0  # 0 = sinalizado = processo terminou
        finally:
            k32.CloseHandle(h)
    while True:
        time.sleep(3)
        if not alive(int(parent)):
            debug.kill_now()
            terminals.close_all()   # shells e agentes vivem em sessão própria: fecham junto com o app
            os._exit(0)  # o app fechou (ou caiu): não fica processo órfão segurando a porta


def main():
    from .core import backup_on_upgrade
    backup_on_upgrade()   # antes de tudo: nenhuma migração roda sem a cópia dos dados da versão anterior
    if not os.path.exists(RULES_FILE):
        save_json(RULES_FILE, rules.DEFAULT_RULES)
    port = int(os.environ.get("CODECK_PORT") or load_json(CONFIG_FILE, {}).get("port") or DEFAULT_PORT)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        print(f"Porta {port} em uso — já há um {PRODUCT} rodando.", flush=True)
        raise SystemExit(1)
    server.daemon_threads = True
    ctx.port = port   # os hooks dos agentes chamam de volta nesta porta
    import atexit
    import signal
    atexit.register(terminals.close_all)
    atexit.register(debug.shutdown)

    def _stop(*_):
        # o app pede para sair com SIGTERM: sem isto o Python morria na hora e os terminais (dotnet run, agentes…)
        # ficavam rodando em segundo plano, órfãos
        debug.kill_now()
        terminals.close_all()
        os._exit(0)
    signal.signal(signal.SIGTERM, _stop)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _stop)
    if os.environ.get("CODECK_PARENT_PID"):
        threading.Thread(target=_watch_parent, args=(os.environ["CODECK_PARENT_PID"],), daemon=True).start()
    engine.start()
    threading.Thread(target=agents.which_all, daemon=True).start()   # acha as CLIs de IA (PATH do usuário) antes da 1ª tela
    threading.Thread(target=agents.auto_limits_loop, daemon=True).start()   # limite das contas sem abrir sessão (opcional)
    threading.Thread(target=agents.limit_watch_loop, daemon=True).start()   # agente parado pelo limite → oferecer outra conta
    threading.Thread(target=update.update_loop, daemon=True).start()
    aiusage.start()   # consumo das IAs: lê os registros das CLIs (o que é novo) a cada 10 min
    print(f"{PRODUCT} {APP_VERSION} ({APP_BUILD}, {APP_PLATFORM}) em http://127.0.0.1:{port} — Azure: {', '.join(ctx.orgs) or '-'}"
          f" — GitHub: {', '.join(a.login for a in ctx.gh.values()) or '-'} — dados em {DATA}{' — token ativo' if TOKEN else ''}", flush=True)
    server.serve_forever()
