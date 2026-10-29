"""Projetos abertos no app (abas), tarefas em worktree e acesso aos arquivos do projeto.

Projeto = um repositório local registrado (git.add_repo), aberto como aba. Cada projeto tem:
  · tarefas: uma branch + um worktree próprio + os terminais/agentes dela. Assim várias tarefas (e vários agentes)
    andam em paralelo sem stash nem troca de branch;
  · ajustes: arquivos que o Git não leva e que o worktree precisa (workspace.local.json, nuget.config, .env…),
    o script de preparação e onde ficam os worktrees.

workspace.json: {"open": [repoId…], "active": repoId, "projects": {repoId: {settings, tasks: [...]}}}
Os worktrees ficam em <pasta-base da conta, ou a pasta-mãe do repo>/.worktrees/<repo>/<slug> — pasta oculta, que a
busca de clones ignora.
"""
import fnmatch
import os
import re
import shutil
import subprocess
import unicodedata
import uuid

from . import agents, catalogs, git, terminals
from .core import DATA, load_json, now_iso, save_json

FILE = os.path.join(DATA, "workspace.json")
DEFAULT_COPY = ["workspace.local.json", "nuget.config", "NuGet.Config", ".env", ".env.local", "appsettings.Development.json",
                "**/appsettings.Development.json", "**/appsettings.Local.json", ".claude/settings.local.json"]
MAX_FILE = 2_000_000


def _load():
    d = load_json(FILE, {})
    d.setdefault("open", [])
    d.setdefault("projects", {})
    d.setdefault("groups", [])
    d.setdefault("lastOpened", {})
    d.setdefault("opens", {})
    return d


def _save(d):
    save_json(FILE, d)


def _proj(d, rid):
    p = d["projects"].setdefault(rid, {})
    p.setdefault("tasks", [])
    p.setdefault("settings", {"copy": DEFAULT_COPY, "setup": "", "worktreeRoot": ""})
    return p


# ---------------------------------------------------------------- projetos (abas)
def state():
    d = _load()
    repos = {r["id"]: r for r in git.list_repos(with_status=False)}
    out = []
    for rid in d["open"]:
        r = repos.get(rid)
        if not r:
            continue
        p = _proj(d, rid)
        live = {x["meta"].get("sid") for x in terminals.list_all(project=rid)}
        tasks = []
        for t in p["tasks"]:
            tasks.append({**t, "exists": os.path.isdir(t["path"]),
                          "terms": [x for x in terminals.list_all(task=t["id"])],
                          "resumable": agents.resumable(rid, t["id"], live)})
        out.append({"id": rid, "name": r["name"], "path": r["path"], "provider": r.get("provider"), "slug": r.get("slug"),
                    "webUrl": r.get("webUrl"), "settings": p["settings"], "tasks": tasks,
                    "terms": [x for x in terminals.list_all(project=rid) if not x["meta"].get("task")],
                    "resumable": agents.resumable(rid, None, live)})
    return {"projects": out, "active": d.get("active"), "sessions": agents.all_sessions(), "groups": d["groups"]}


def open_project(repo_id=None, path=None):
    r = git.get_repo(repo_id) if repo_id else git.add_repo(path)
    d = _load()
    if r["id"] not in d["open"]:
        d["open"].append(r["id"])
    d["active"] = r["id"]
    _touch(d, r["id"], opened=True)
    p = _proj(d, r["id"])
    _save(d)
    live = {x["id"] for x in terminals.list_all()}
    for path in [r["path"]] + [t["path"] for t in p["tasks"]]:
        _sweep_drops(path, live)   # sobras de quando o app fechou com terminais abertos
    return {"id": r["id"]}


def _touch(d, rid, opened=False):
    """Último acesso (e quantas vezes abriu) — o hub de projetos ordena por isso."""
    d["lastOpened"][rid] = now_iso()
    if opened:
        d["opens"][rid] = int(d["opens"].get(rid) or 0) + 1


def close_project(repo_id):
    d = _load()
    d["open"] = [x for x in d["open"] if x != repo_id]
    if d.get("active") == repo_id:
        d["active"] = d["open"][-1] if d["open"] else None
    _save(d)
    # todos ao mesmo tempo (cada um espera até ~0,5 s o processo sair): fechar um projeto com vários agentes não segura
    # a resposta
    import threading
    ths = [threading.Thread(target=close_terminal, args=(t["id"],), daemon=True) for t in terminals.list_all(project=repo_id)]
    for th in ths:
        th.start()
    for th in ths:
        th.join(5)


def activate(repo_id):
    d = _load()
    d["active"] = repo_id
    _touch(d, repo_id)
    _save(d)


# ---------------------------------------------------------------- grupos de projetos (como grupos de abas do navegador)
# Um grupo tem nome, cor e projetos (repositórios). Nas abas de projeto, os abertos aparecem juntos sob o grupo, que
# recolhe/expande; no hub, filtra e agrupa; no quadro, o cartão diz a qual grupo pertence e quais projetos referenciar.
GROUP_COLORS = ["#6F8CFF", "#3CCF91", "#F5B84F", "#FF6B7D", "#B07CFF", "#4FC3F7", "#FF8A50", "#9AA4B2"]


def save_group(body):
    d = _load()
    gid = body.get("id") or uuid.uuid4().hex[:8]
    g = next((x for x in d["groups"] if x["id"] == gid), None)
    if not g:
        name = (body.get("name") or "").strip()
        if not name:
            raise ValueError("Dê um nome ao grupo")
        g = {"id": gid, "name": name[:40], "color": body.get("color") or GROUP_COLORS[len(d["groups"]) % len(GROUP_COLORS)],
             "collapsed": False, "repoIds": []}
        d["groups"].append(g)
    if body.get("name"):
        g["name"] = str(body["name"]).strip()[:40]
    if body.get("color"):
        g["color"] = str(body["color"])[:20]
    if "collapsed" in body:
        g["collapsed"] = bool(body["collapsed"])
    if "description" in body:
        g["description"] = str(body.get("description") or "")[:400]
    if isinstance(body.get("repoIds"), list):
        ids = [str(x) for x in body["repoIds"]]
        for other in d["groups"]:   # um projeto fica em um grupo só (como uma aba)
            if other is not g:
                other["repoIds"] = [x for x in other["repoIds"] if x not in ids]
        g["repoIds"] = list(dict.fromkeys(ids))
    _save(d)
    return g


def delete_group(gid):
    d = _load()
    d["groups"] = [g for g in d["groups"] if g["id"] != gid]
    _save(d)


def assign_group(repo_id, gid):
    """Põe o projeto no grupo (tira de qualquer outro). gid vazio = sem grupo."""
    d = _load()
    for g in d["groups"]:
        g["repoIds"] = [x for x in g["repoIds"] if x != repo_id]
        if g["id"] == gid:
            g["repoIds"].append(repo_id)
    _save(d)


def reorder_groups(ids):
    d = _load()
    by = {g["id"]: g for g in d["groups"]}
    d["groups"] = [by[i] for i in ids if i in by] + [g for g in d["groups"] if g["id"] not in ids]
    _save(d)


def open_group(gid):
    d = _load()
    g = next((x for x in d["groups"] if x["id"] == gid), None)
    if not g:
        raise LookupError("Grupo não encontrado")
    known = {r["id"] for r in git.list_repos(with_status=False) if r.get("exists")}
    for rid in g["repoIds"]:
        if rid in known and rid not in d["open"]:
            d["open"].append(rid)
    g["collapsed"] = False
    _save(d)
    return {"opened": [x for x in g["repoIds"] if x in known]}


def hub():
    """Para o hub de projetos: uso de cada repositório local — último acesso, vezes aberto, seu tempo com ele na tela
    (total e 30 dias), sessões de IA e custo nos últimos 30 dias e a última vez que um agente trabalhou nele."""
    import time
    d = _load()
    focus = load_json(agents.FOCUS_FILE, {})
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - 29 * 86400))
    stats = {}
    for day, per in focus.items():
        for rid, e in per.items():
            st = stats.setdefault(rid, {"focusS": 0, "focus30": 0, "sessions30": 0, "cost30": 0.0, "lastAgent": None})
            st["focusS"] += e.get("s") or 0
            if day >= since:
                st["focus30"] += e.get("s") or 0
    for r in agents._history().values():
        rid = r.get("projectId")
        if not rid:
            continue
        st = stats.setdefault(rid, {"focusS": 0, "focus30": 0, "sessions30": 0, "cost30": 0.0, "lastAgent": None})
        if r.get("day", "") >= since:
            st["sessions30"] += 1
            st["cost30"] += r.get("cost") or 0
        if not st["lastAgent"] or (r.get("updated") or "") > st["lastAgent"]:
            st["lastAgent"] = r.get("updated")
    for rid, ts in d["lastOpened"].items():
        stats.setdefault(rid, {"focusS": 0, "focus30": 0, "sessions30": 0, "cost30": 0.0, "lastAgent": None})["lastOpened"] = ts
    for rid, n in d["opens"].items():
        stats.setdefault(rid, {"focusS": 0, "focus30": 0, "sessions30": 0, "cost30": 0.0, "lastAgent": None})["opens"] = n
    # tarefas em aberto (worktrees) de cada projeto, mesmo fechado: o "Em andamento" do hub mostra o que ficou pela metade
    for rid, p in d["projects"].items():
        ts = [t for t in p.get("tasks") or [] if os.path.isdir(t.get("path") or "")]
        if ts:
            st = stats.setdefault(rid, {"focusS": 0, "focus30": 0, "sessions30": 0, "cost30": 0.0, "lastAgent": None})
            st["tasks"] = [{"title": t["title"], "branch": t["branch"], "createdAt": t.get("createdAt")} for t in ts[-5:]]
    return {"stats": stats, "groups": d["groups"], "open": d["open"]}


def reorder(ids):
    d = _load()
    d["open"] = [x for x in ids if x in d["open"]] + [x for x in d["open"] if x not in ids]
    _save(d)


def save_settings(repo_id, body):
    d = _load()
    s = _proj(d, repo_id)["settings"]
    if isinstance(body.get("copy"), list):
        s["copy"] = [str(x).strip() for x in body["copy"] if str(x).strip()][:60]
    if "setup" in body:
        s["setup"] = str(body.get("setup") or "")[:2000]
    if "worktreeRoot" in body:
        s["worktreeRoot"] = os.path.expanduser(str(body.get("worktreeRoot") or "").strip())
    if "shell" in body:
        s["shell"] = str(body.get("shell") or "").strip()[:300]
    if isinstance(body.get("addDirs"), list):
        s["addDirs"] = [os.path.abspath(os.path.expanduser(str(x))) for x in body["addDirs"] if str(x).strip()][:20]
    if "bypass" in body:   # pular as permissões em TODO agente aberto neste projeto (desligado por padrão)
        s["bypass"] = bool(body.get("bypass"))
    if "account" in body:   # a conta de IA deste projeto (a última usada; trocar no painel do agente também grava aqui)
        s["account"] = str(body.get("account") or "")[:40] or None
    _save(d)
    return s


# ---------------------------------------------------------------- tarefas (branch + worktree + agentes)
def slugify(text):
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:48].strip("-") or "tarefa"


def _worktree_root(repo, settings):
    if settings.get("worktreeRoot"):
        return settings["worktreeRoot"]
    acc = catalogs.account_dirs(f"{repo.get('provider')}:{(repo.get('slug') or '').split('/')[0]}") if repo.get("provider") else []
    parent = next((b for b in acc if os.path.normcase(repo["path"]).startswith(os.path.normcase(b))), None) or os.path.dirname(repo["path"])
    return os.path.join(parent, ".worktrees", repo["name"])


def _exclude_from_enclosing_repo(wt_root):
    """Se a pasta .worktrees fica dentro de OUTRO repositório (ex.: cifal/apis é o repo orquestrador), ela apareceria
    como "não versionada" nele. Põe a pasta no .git/info/exclude desse repo — local, nunca vai para commit."""
    try:
        top = git.run(os.path.dirname(wt_root), "rev-parse", "--show-toplevel").strip()
        gitdir = git.run(top, "rev-parse", "--absolute-git-dir").strip()
    except Exception:  # noqa: BLE001 — não está dentro de repositório nenhum
        return
    rel = "/" + os.path.relpath(wt_root, top).replace(os.sep, "/") + "/"
    excl = os.path.join(gitdir, "info", "exclude")
    os.makedirs(os.path.dirname(excl), exist_ok=True)
    current = open(excl, encoding="utf-8").read() if os.path.exists(excl) else ""
    if rel not in current.split("\n"):
        with open(excl, "a", encoding="utf-8") as f:
            f.write(("" if current.endswith("\n") or not current else "\n") + f"# worktrees do Codeck\n{rel}\n")


def _exclude_copied(wt, files):
    """Os arquivos copiados (segredos locais: workspace.local.json, nuget.config…) NUNCA podem ir para commit — nem por um
    `git add -A` do agente. Vão para o exclude do repositório (vale para os worktrees dele; local, não versionado)."""
    if not files:
        return
    excl = git.run(wt, "rev-parse", "--git-path", "info/exclude").strip()
    excl = excl if os.path.isabs(excl) else os.path.join(wt, excl)
    os.makedirs(os.path.dirname(excl), exist_ok=True)
    current = open(excl, encoding="utf-8").read().split("\n") if os.path.exists(excl) else []
    new = [f"/{f}" for f in files if f"/{f}" not in current]
    if new:
        with open(excl, "a", encoding="utf-8") as fh:
            fh.write(("\n" if current and current[-1] else "") + "# copiados pelo Codeck para os worktrees (não versionar)\n" + "\n".join(new) + "\n")


def _copy_untracked(src, dst, patterns):
    """Copia para o worktree os arquivos locais que o Git não leva (só os que existem e não estão versionados)."""
    tracked = set(git.run(src, "ls-files", "-z").split("\0"))
    copied = []
    for root, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x not in {".git", "node_modules", "bin", "obj", ".worktrees", "dist", ".venv"}]
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), src).replace(os.sep, "/")
            if rel in tracked or not any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(f, p) and "/" not in p for p in patterns):
                continue
            target = os.path.join(dst, rel)
            if os.path.exists(target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(os.path.join(root, f), target)
            copied.append(rel)
            if len(copied) > 200:
                return copied
    return copied


def create_task(repo_id, body):
    """Nova tarefa: branch a partir da base, worktree, arquivos locais, preparação e (opcional) agente com o prompt."""
    repo = git.get_repo(repo_id)
    d = _load()
    p = _proj(d, repo_id)
    title = (body.get("title") or "").strip()
    if not title:
        raise ValueError("Diga o que é a tarefa")
    kind = body.get("kind") if body.get("kind") in ("feature", "fix", "review", "plan", "chore") else "feature"
    slug = slugify(body.get("slug") or title)
    branch = body.get("branch") or f"{kind}/{slug}"
    git._check_branch(branch)
    base = body.get("base") or _default_base(repo)
    path, copied, wt = _make_worktree(repo, p["settings"], slug, branch, base)
    # mesma tarefa em outros repositórios (ex.: entidades → infra → API): mesmo slug e branch, base padrão de cada um
    linked = []
    for lid in body.get("linked") or []:
        if lid == repo_id:
            continue
        lrepo = git.get_repo(lid)
        lp, _lc, lwt = _make_worktree(lrepo, _proj(d, lid)["settings"], slug, branch, _default_base(lrepo))
        linked.append({"repoId": lid, "name": lrepo["name"], "path": lp, "wtRepoId": lwt["id"]})
    # projetos só de consulta (o agente enxerga a pasta, mas a tarefa não mexe neles): o checkout principal de cada um
    refs = []
    for rid in body.get("refs") or []:
        if rid == repo_id or any(x["repoId"] == rid for x in linked):
            continue
        try:
            rr = git.get_repo(rid)
            refs.append({"repoId": rid, "name": rr["name"], "path": rr["path"]})
        except ValueError:
            continue
    prompt = body.get("prompt") or ""
    if linked:
        prompt += "\n\nEsta tarefa atravessa repositórios — cada um tem um worktree na branch " + branch + ":\n" + \
            "\n".join([f"- {repo['name']}: {path} (este)"] + [f"- {x['name']}: {x['path']}" for x in linked])
    task = {"id": uuid.uuid4().hex[:10], "title": title, "slug": slug, "branch": branch, "base": base, "path": path,
            "repoId": wt["id"], "createdAt": now_iso(), "status": "open", "workItem": body.get("workItem"),
            "prompt": prompt, "copied": copied, "group": body.get("group"), "linked": linked, "reviewOf": body.get("reviewOf"),
            "card": body.get("card"), "refs": refs}
    p["tasks"].append(task)
    _save(d)
    if (p["settings"].get("setup") or "").strip():
        terminals.create(path, "preparação", p["settings"]["setup"], "setup", {"project": repo_id, "task": task["id"]})
    agent_ids = body.get("agents") or ([body["agent"]] if body.get("agent") else [])
    for aid in agent_ids:
        start_agent(repo_id, task["id"], aid, task["prompt"] or title, body.get("mode"))
    return task


def start_in_checkout(repo_id, body):
    """Tarefa SEM worktree (o mais comum): o agente trabalha no seu checkout. Com `branch`, cria a branch a partir da
    base e troca para ela antes — só com o checkout limpo, para não levar alterações de outra coisa junto."""
    repo = git.get_repo(repo_id)
    title = (body.get("title") or "").strip()
    if not title:
        raise ValueError("Diga o que é a tarefa")
    branch = None
    if body.get("newBranch"):
        kind = body.get("kind") if body.get("kind") in ("feature", "fix", "review", "plan", "chore") else "feature"
        branch = body.get("branch") or f"{kind}/{slugify(body.get('slug') or title)}"
        st = git.status(path=repo["path"])
        if st["staged"] or st["unstaged"] or st["conflicts"]:
            raise ValueError("O checkout tem alterações não commitadas — commite/guarde antes de trocar de branch, "
                             "ou rode sem branch nova")
        try:
            git.run(repo["path"], "fetch", "origin", "--prune", timeout=30, auth=git.auth_for(repo))
        except Exception:  # noqa: BLE001 — sem rede (ou demorou): segue com o que tem
            pass
        if git.run(repo["path"], "branch", "--list", branch).strip():
            git.checkout(repo_id, branch)
        else:
            git.checkout(repo_id, None, create=branch, start=body.get("base") or _default_base(repo))
    terms = [start_agent(repo_id, None, aid, body.get("prompt") or title, body.get("mode"), title=title[:40])
             for aid in (body.get("agents") or [])]
    return {"id": None, "branch": branch, "terms": [t["id"] for t in terms]}


def cleanup_info(repo_id):
    """Para a faxina dos worktrees: cada tarefa com o estado (pasta existe? alterações? branch já entrou na base? agente
    vivo?) e os worktrees órfãos — os que o Git conhece na pasta de worktrees mas nenhuma tarefa usa."""
    d = _load()
    repo = git.get_repo(repo_id)
    p = _proj(d, repo_id)
    out = []
    for t in p["tasks"]:
        exists = os.path.isdir(t["path"])
        dirty = 0
        if exists:
            try:
                st = git.status(path=t["path"])
                dirty = len(st["staged"]) + len(st["unstaged"]) + len(st["untracked"]) + len(st["conflicts"])
            except Exception:  # noqa: BLE001
                dirty = 0
        base = t.get("base") or _default_base(repo)
        try:   # a branch já entrou na base (código de saída 0): dá para apagar sem perder nada
            git.run(repo["path"], "merge-base", "--is-ancestor", t["branch"], base)
            merged = True
        except git.GitError:
            merged = False
        alive = any(x["alive"] for x in terminals.list_all(task=t["id"]))
        out.append({"id": t["id"], "title": t["title"], "branch": t["branch"], "path": t["path"], "exists": exists,
                    "dirty": dirty, "merged": merged, "agents": alive, "createdAt": t.get("createdAt")})
    known = {os.path.normcase(os.path.realpath(t["path"])) for t in p["tasks"]}
    known |= {os.path.normcase(os.path.realpath(x["path"])) for t in p["tasks"] for x in t.get("linked") or []}
    root = os.path.normcase(os.path.realpath(_worktree_root(repo, p["settings"])))
    orphans = []
    for line in git.run(repo["path"], "worktree", "list", "--porcelain", check=False).splitlines():
        if line.startswith("worktree "):
            wt = line[9:].strip()
            n = os.path.normcase(os.path.realpath(wt))
            if n.startswith(root + os.sep) and n not in known:
                orphans.append({"path": wt, "exists": os.path.isdir(wt)})
    return {"tasks": out, "orphans": orphans}


def cleanup(repo_id, task_ids=(), orphans=(), delete_branch=False, force=False):
    """Remove de uma vez as tarefas escolhidas (worktree + terminais) e os worktrees órfãos. A branch local só sai junto
    (com `delete_branch`) se já entrou na base — a de trabalho não terminado fica. Devolve o que falhou."""
    info = cleanup_info(repo_id)
    merged = {t["id"] for t in info["tasks"] if t["merged"]}
    failed = []
    for tid in task_ids:
        try:
            remove_task(repo_id, tid, force=force, delete_branch=delete_branch and tid in merged)
        except Exception as e:  # noqa: BLE001
            failed.append({"id": tid, "error": str(e)})
    repo = git.get_repo(repo_id)
    allowed = {o["path"] for o in info["orphans"]}   # só órfãos de verdade, nunca um caminho qualquer
    for path in orphans:
        if path not in allowed:
            continue
        try:
            if os.path.isdir(path):
                _remove_worktree(repo["path"], path, force)
            for r in git._repos():
                if os.path.normcase(os.path.realpath(r["path"])) == os.path.normcase(os.path.realpath(path)):
                    git.remove_repo(r["id"])
        except Exception as e:  # noqa: BLE001
            failed.append({"path": path, "error": str(e)})
    git.run(repo["path"], "worktree", "prune", check=False)
    return {"failed": failed}


def _default_base(repo):
    try:
        return git.run(repo["path"], "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
    except Exception:  # noqa: BLE001
        return git.status(repo["id"])["branch"] or "HEAD"


def _make_worktree(repo, settings, slug, branch, base):
    path = os.path.join(_worktree_root(repo, settings), slug)
    if os.path.exists(path):
        path = f"{path}-{uuid.uuid4().hex[:4]}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _exclude_from_enclosing_repo(os.path.dirname(os.path.dirname(path)))
    try:
        # só o que a base precisa e com prazo curto: rede lenta segurava o "criar tarefa" por até 3 min
        git.run(repo["path"], "fetch", "origin", "--prune", timeout=30, auth=git.auth_for(repo))
    except Exception:  # noqa: BLE001 — sem rede (ou demorou): segue com o que tem
        pass
    if git.run(repo["path"], "branch", "--list", branch).strip():
        git.run(repo["path"], "worktree", "add", path, branch, timeout=120)
    else:
        git.run(repo["path"], "worktree", "add", "-b", branch, path, git._check_ref(base), timeout=120)
    copied = _copy_untracked(repo["path"], path, settings.get("copy") or [])
    _exclude_copied(path, copied)
    return path, copied, git.add_repo(path)


def close_task(repo_id, task_id):
    """Fechar a tarefa sem remover nada: encerra todos os agentes e terminais dela (processos e filhos; a sessão do
    agente é limpa) ao mesmo tempo. O worktree e a branch ficam — dá para abrir um agente de novo nela."""
    import threading
    _task(_load(), repo_id, task_id)
    ids = [x["id"] for x in terminals.list_all(task=task_id)]
    ths = [threading.Thread(target=close_terminal, args=(i,), daemon=True) for i in ids]
    for th in ths:
        th.start()
    for th in ths:
        th.join(6)
    return len(ids)


def _close_terms_and_wait(task_id, timeout=6):
    """Encerra os terminais/agentes da tarefa e ESPERA os processos saírem: no Windows, um processo que ainda tem a
    pasta como diretório atual trava a remoção do worktree (medido no autoteste do desktop no GitHub Actions)."""
    import time
    terms = [terminals.get(x["id"]) for x in terminals.list_all(task=task_id)]
    for t in terms:
        close_terminal(t.id)
    end = time.time() + timeout
    while time.time() < end and any(t.pty.alive() for t in terms):
        time.sleep(0.2)


def _remove_worktree(main_path, wt_path, force):
    """`git worktree remove`, tentando de novo por alguns segundos se a pasta ainda estiver presa (Windows)."""
    import time
    last = None
    for attempt in range(8):
        try:
            git.run(main_path, "worktree", "remove", *(["--force"] if force else []), wt_path, timeout=120)
            return
        except git.GitError as e:
            last = e
            if not os.path.isdir(wt_path):
                return
            time.sleep(0.5 + attempt * 0.5)
    raise last


def _task(d, repo_id, task_id):
    t = next((x for x in _proj(d, repo_id)["tasks"] if x["id"] == task_id), None)
    if not t:
        raise LookupError("Tarefa não encontrada")
    return t


def update_task(repo_id, task_id, body):
    d = _load()
    t = _task(d, repo_id, task_id)
    for k in ("title", "status", "prompt", "pr"):
        if k in body:
            t[k] = body[k]
    _save(d)
    return t


def remove_task(repo_id, task_id, force=False, delete_branch=False):
    d = _load()
    t = _task(d, repo_id, task_id)
    repo = git.get_repo(repo_id)
    if os.path.isdir(t["path"]) and not force:
        st = git.status(path=t["path"])
        if st["staged"] or st["unstaged"] or st["untracked"] or st["conflicts"]:
            raise ValueError("O worktree tem alterações não commitadas — commite, descarte ou force a remoção")
    _close_terms_and_wait(task_id)
    if os.path.isdir(t["path"]):
        _remove_worktree(repo["path"], t["path"], force)
    git.run(repo["path"], "worktree", "prune")
    try:
        git.remove_repo(t["repoId"])
    except Exception:  # noqa: BLE001
        pass
    for x in t.get("linked") or []:
        try:
            lr = git.get_repo(x["repoId"])
            if os.path.isdir(x["path"]):
                _remove_worktree(lr["path"], x["path"], force)
            git.run(lr["path"], "worktree", "prune")
            git.remove_repo(x["wtRepoId"])
            if delete_branch:
                git.run(lr["path"], "branch", "-D" if force else "-d", t["branch"], check=False)
        except Exception as e:  # noqa: BLE001
            if not force:
                raise ValueError(f"{x['name']}: {e}") from None
    if delete_branch:
        try:
            git.run(repo["path"], "branch", "-D" if force else "-d", t["branch"])
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"Worktree removido; a branch {t['branch']} ficou: {e}") from None
    _proj(d, repo_id)["tasks"] = [x for x in _proj(d, repo_id)["tasks"] if x["id"] != task_id]
    _save(d)


# ---------------------------------------------------------------- terminais e agentes de um projeto/tarefa
def _cwd(repo_id, task_id=None):
    if task_id:
        return _task(_load(), repo_id, task_id)["path"]
    return git.get_repo(repo_id)["path"]


def _settings(repo_id):
    return _proj(_load(), repo_id)["settings"]


# ---------------------------------------------------------------- arquivos de referência soltos no terminal
# Arrastar arquivos (do Finder/Explorer ou da árvore) para cima de um terminal: eles vão para DENTRO da pasta do
# terminal — o agente lê sem pedir permissão de pasta extra — e o caminho é digitado no prompt. Temporários ficam em
# .codeck/tmp/<terminal> e somem ao fechar o terminal; os fixos ficam em .codeck/refs, para usar de novo. A pasta
# .codeck/ vai para o exclude do Git: nunca entra num commit.
DROP_MAX = 50 * 1024 * 1024


def _drop_dir(cwd, term_id=None, keep=False):
    return os.path.join(cwd, ".codeck", "refs") if keep else os.path.join(cwd, ".codeck", "tmp", term_id)


def _exclude_codeck(cwd):
    try:
        excl = git.run(cwd, "rev-parse", "--git-path", "info/exclude").strip()
    except Exception:  # noqa: BLE001 — pasta fora de um repositório: nada a excluir
        return
    excl = excl if os.path.isabs(excl) else os.path.join(cwd, excl)
    os.makedirs(os.path.dirname(excl), exist_ok=True)
    current = open(excl, encoding="utf-8").read().split("\n") if os.path.exists(excl) else []
    if ".codeck/" not in current and "/.codeck/" not in current:
        with open(excl, "a", encoding="utf-8") as fh:
            fh.write(("\n" if current and current[-1] else "") + "# referências soltas nos terminais do Codeck (não versionar)\n.codeck/\n")


def drop_file(term_id, name, data_b64, keep=False):
    """Grava um arquivo solto no terminal e devolve o caminho relativo à pasta dele (o que vai no prompt)."""
    import base64
    t = terminals.get(term_id)
    data = base64.b64decode(data_b64 or "")
    if len(data) > DROP_MAX:
        raise ValueError("Arquivo grande demais para referência (máx. 50 MB)")
    name = os.path.basename((name or "").replace("\\", "/")).strip().lstrip(".") or "arquivo"
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)[:120]
    folder = _drop_dir(t.cwd, term_id, keep)
    os.makedirs(folder, exist_ok=True)
    _exclude_codeck(t.cwd)
    stem, ext = os.path.splitext(name)
    path, n = os.path.join(folder, name), 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(folder, f"{stem} ({n}){ext}")
    with open(path, "wb") as f:
        f.write(data)
    return {"path": os.path.relpath(path, t.cwd).replace("\\", "/"), "abs": path, "keep": bool(keep)}


def drop_refs(term_id):
    """As referências do terminal: as temporárias dele e as fixas da pasta."""
    t = terminals.get(term_id)
    out = []
    for keep in (False, True):
        folder = _drop_dir(t.cwd, term_id, keep)
        if os.path.isdir(folder):
            out += [{"name": n, "path": os.path.relpath(os.path.join(folder, n), t.cwd).replace("\\", "/"), "keep": keep}
                    for n in sorted(os.listdir(folder)) if os.path.isfile(os.path.join(folder, n))]
    return out


def drop_remove(term_id, rel):
    t = terminals.get(term_id)
    full = _safe(os.path.realpath(t.cwd), rel)
    if f"{os.sep}.codeck{os.sep}" not in full:
        raise ValueError("Só dá para apagar referências")
    os.remove(full)


def _sweep_drops(cwd, live=()):
    """Apaga as referências temporárias de terminais que já não existem (o app fechou com eles abertos)."""
    base = os.path.join(cwd, ".codeck", "tmp")
    if not os.path.isdir(base):
        return
    for d in os.listdir(base):
        if d not in live:
            shutil.rmtree(os.path.join(base, d), ignore_errors=True)
    try:
        os.rmdir(base)   # vazia: sai também
    except OSError:
        pass


def close_terminal(term_id):
    """Fechar um terminal de propósito: mata o processo (e os filhos dele) e, se for agente, limpa a sessão — estado,
    contexto e a oferta de retomar. Sair do app não passa por aqui (lá as conversas continuam retomáveis)."""
    try:
        t = terminals.get(term_id)
        sid, cwd = t.meta.get("sid"), t.cwd
    except LookupError:
        sid = cwd = None
    terminals.close(term_id)
    agents.discard(sid)
    if cwd:   # as referências temporárias soltas nele vão junto
        shutil.rmtree(_drop_dir(cwd, term_id), ignore_errors=True)
        _sweep_drops(cwd, {x["id"] for x in terminals.list_all()})


def start_shell(repo_id, task_id=None, title=None, command=None):
    meta = {"project": repo_id, **({"task": task_id} if task_id else {})}
    return terminals.create(_cwd(repo_id, task_id), title or "terminal", command, "shell", meta,
                            shell=_settings(repo_id).get("shell") or None).info()


def start_agent(repo_id, task_id, account_id, prompt=None, mode=None, title=None, resume_sid=None, card=None, resume_cli=None,
                extra_dirs=(), meta_extra=None):
    """Abre um agente num terminal. `resume_cli` = id de uma conversa da CLI para retomar (passagem entre contas da
    mesma CLI); `extra_dirs` = pastas que ele lê sem pedir (o histórico da passagem)."""
    a = agents.get_account(account_id)
    resume = resume_cli
    if resume_sid:   # retomar a conversa de uma sessão anterior (o app foi fechado): mesma sessão da CLI
        rec = agents._resume_db().get(resume_sid) or {}
        resume, account_id = rec.get("cliSession"), rec.get("account") or account_id
        a = agents.get_account(account_id)
        agents.forget_resume(resume_sid)
    sid = uuid.uuid4().hex[:12]
    extra = list(_settings(repo_id).get("addDirs") or []) + list(extra_dirs or ())
    if task_id:
        t_ = _task(_load(), repo_id, task_id)
        extra += [x["path"] for x in (t_.get("linked") or []) + (t_.get("refs") or [])]   # tarefa em vários repos + consulta
        card = card or t_.get("card")
    if card:   # anexos do cartão do quadro: o agente lê sem pedir permissão (pasta extra, como as de consulta)
        files = os.path.join(DATA, "kanban-files", os.path.basename(str(card)))
        if os.path.isdir(files):
            extra.append(files)
    d = _load()
    st = _proj(d, repo_id)["settings"]
    bypass = bool(st.get("bypass"))
    command, env = agents.launch_spec(account_id, prompt, mode, sid, extra_dirs=extra, resume=resume, bypass=bypass)
    if st.get("account") != account_id:   # lembra a conta do projeto: a próxima vez já abre nela
        st["account"] = account_id
        _save(d)
    meta = {"project": repo_id, "account": account_id, "provider": a["provider"], "sid": sid,
            **({"task": task_id} if task_id else {}), **({"bypass": True} if bypass else {})}
    label = title or f"{agents.PROVIDERS[a['provider']]['label']} · {a['name']}"
    cwd = _cwd(repo_id, task_id)
    t = terminals.create(cwd, label, command, "agent", {**meta, **(meta_extra or {})}, env)
    t.attach(agents.output_watcher(sid))   # a mensagem de limite da CLI no terminal → oferecer outra conta
    agents.set_title(sid, label)
    agents.set_meta(sid, projectName=git.get_repo(repo_id)["name"], project=repo_id, task=task_id, cwd=cwd,
                    prompt=(prompt or "")[:20000] or None, **({"continuedFrom": meta_extra["continuedFrom"]} if (meta_extra or {}).get("continuedFrom") else {}))
    agents.remember(sid, account=account_id, provider=a["provider"], project=repo_id, task=task_id, title=label,
                    cliSession=resume, started=now_iso())
    if prompt and a["provider"] == "claude":
        _ensure_prompt(t, sid, prompt)
    return t.info()


def _ensure_prompt(t, sid, prompt, wait=90, idle_for=6):
    """Rede de segurança do pedido inicial: o Claude abriu (SessionStart) e ficou parado sem receber o pedido
    (UserPromptSubmit nunca veio) — antes o terminal novo ficava "aberto, parado e limpo". Aqui o próprio terminal novo
    recebe o pedido colado, como se você tivesse colado e dado Enter. Só o Claude avisa os dois momentos pelos hooks."""
    import threading
    import time

    def watch():
        end = time.time() + wait
        while time.time() < end and t.alive:
            time.sleep(1)
            s = agents.session_info(sid) or {}
            st = s.get("status")
            if st not in ("starting", "idle"):
                return   # já recebeu o pedido (ou você escreveu outro)
            if st == "idle" and time.time() - (s.get("statusAt") or time.time()) >= idle_for:
                try:
                    send_input(t.id, prompt)
                except Exception:  # noqa: BLE001 — o terminal fechou nesse meio tempo
                    pass
                return
    threading.Thread(target=watch, daemon=True, name=f"prompt-{sid}").start()


def handoff(term_id, account_id, mode="auto"):
    """Continua o trabalho de um agente (parado pelo limite, ou quando você quiser) em OUTRA conta, num terminal novo
    no mesmo checkout/tarefa, já trabalhando:
      · mode "resume" (mesma CLI): a conversa é copiada para a conta nova e retomada — contexto inteiro;
      · mode "brief": um pedido curto (pedido original, últimos passos, estado do git) + o histórico completo num
        arquivo que o agente só lê se precisar — gasta bem menos tokens, e funciona entre CLIs diferentes;
      · "auto": retoma quando é a mesma CLI e o contexto está abaixo de 50%; senão, o resumo."""
    t = terminals.get(term_id)
    sid = t.meta.get("sid")
    if t.kind != "agent" or not sid:
        raise ValueError("Só dá para continuar a sessão de um agente")
    if account_id == t.meta.get("account"):
        raise ValueError("Escolha outra conta — esta é a que está no limite")
    new = agents.get_account(account_id)
    old = agents.session_info(sid) or {}
    repo_id, task_id = t.meta.get("project"), t.meta.get("task")
    same = new["provider"] == t.meta.get("provider") and new["provider"] in ("claude", "codex")
    if mode == "auto":
        mode = "resume" if same and ((old.get("context") or {}).get("used") or 0) < 50 else "brief"
    cli, prompt, extra = None, None, []
    if mode == "resume" and same:
        cli = agents.carry_session(sid, account_id)
    if cli:
        prompt = agents.continue_prompt(sid, account_id)
    else:
        mode = "brief"
        with t.lock:
            scroll = bytes(t.scroll).decode("utf-8", "replace")
        prompt, full = agents.handoff_context(sid, scroll)
        extra.append(os.path.dirname(full))
    src = {"sid": sid, "termId": term_id, "account": t.meta.get("account"), "mode": mode}
    title = f"{agents.PROVIDERS[new['provider']]['label']} · {new['name']} (continuação)"
    info = start_agent(repo_id, task_id, account_id, prompt, None, title, resume_cli=cli, extra_dirs=extra,
                       meta_extra={"continuedFrom": src})
    agents.set_meta(sid, handedOff={"termId": info["id"], "account": account_id, "mode": mode, "at": now_iso()})
    return {**info, "mode": mode}


def send_input(term_id, text, submit=True):
    """Manda um texto para um agente aberto, como se fosse colado: colagem delimitada (o agente recebe o bloco inteiro,
    com as quebras de linha) e, um instante depois, o Enter sozinho — junto, o Enter virava quebra de linha."""
    import threading
    t = terminals.get(term_id)
    if t.kind != "agent":
        raise ValueError("Só dá para mandar pedidos para um agente")
    if not t.alive:
        raise ValueError("Esta sessão já terminou — abra uma nova")
    text = (text or "").replace("\r\n", "\n").replace("\0", "")
    if not text.strip():
        raise ValueError("Escreva o que mandar")
    t.write(("\x1b[200~" + text + "\x1b[201~").encode("utf-8"))
    if submit:
        threading.Timer(0.3, lambda: t.write(b"\r")).start()
    return {"ok": True}


# ---------------------------------------------------------------- arquivos
def _root(repo_id, task_id=None):
    return os.path.realpath(_cwd(repo_id, task_id))


def _safe(root, rel):
    full = os.path.realpath(os.path.join(root, rel or ""))
    if full != root and not full.startswith(root + os.sep):
        raise ValueError("Caminho fora do projeto")
    return full


# o que o explorador esconde (o files.exclude padrão do VS Code)
HIDE = {".git", ".hg", ".svn", ".DS_Store", "Thumbs.db"}
# pastas pesadas que nunca são percorridas de uma vez, mesmo sem estar no .gitignore: abrem sob demanda
HEAVY = {"node_modules", ".dart_tool", ".gradle", "Pods", ".venv", "venv", "__pycache__", ".next", ".nuxt", ".turbo"}
MAX_TREE = 200_000


def _ignored(repo_dir):
    """O que o .gitignore deste repositório ignora (pasta ignorada inteira vem com a barra no fim: "bin/")."""
    out = git.run(repo_dir, "ls-files", "-o", "-i", "--exclude-standard", "--directory", "-z", timeout=30, check=False)
    return {x for x in out.split("\0") if x}


def files(repo_id, task_id=None, under=None):
    """Todos os arquivos do projeto, como o explorador do VS Code: inclusive os ignorados pelo .gitignore (vão em
    `ignored`, a tela mostra apagados) e os repositórios dentro dele — uma pasta "workspace" que reúne vários repos
    (cada um no .gitignore do orquestrador) mostra os arquivos de todos. Pasta ignorada inteira (bin/, obj/,
    node_modules/…) não é percorrida: vem em `lazy` e a tela lê o conteúdo ao abrir (under=<pasta>/, um nível)."""
    root = _root(repo_id, task_id)
    out = {"root": root, "files": [], "dirs": [], "ignored": [], "lazy": [], "truncated": False}
    if under:
        full = _safe(root, under)
        rel = os.path.relpath(full, root).replace(os.sep, "/") + "/"
        try:
            entries = sorted(os.scandir(full), key=lambda e: e.name)
        except OSError:
            return out
        for e in entries:
            if e.name in HIDE:
                continue
            (out["lazy"] if e.is_dir() else out["files"]).append(rel + e.name + ("/" if e.is_dir() else ""))
        return out
    count = [0]

    def visit(full, rel, base, ign):
        try:
            entries = [e for e in os.scandir(full) if e.name not in HIDE]
        except OSError:
            return
        if not entries and rel:
            out["dirs"].append(rel)
        for e in entries:
            count[0] += 1
            if count[0] > MAX_TREE:
                out["truncated"] = True
                return
            r, inrepo = rel + e.name, rel[len(base):] + e.name
            try:
                isdir = e.is_dir()
            except OSError:
                continue
            if not isdir:
                out["files"].append(r)
                if inrepo in ign:
                    out["ignored"].append(r)
                continue
            d = r + "/"
            if os.path.exists(os.path.join(e.path, ".git")):   # outro repositório aqui dentro (workspace de repos, submódulo)
                visit(e.path, d, d, _ignored(e.path))
            elif inrepo + "/" in ign or e.is_symlink() or e.name in HEAVY:
                out["lazy"].append(d)
                if inrepo + "/" in ign:
                    out["ignored"].append(d)
            else:
                visit(e.path, d, base, ign)

    visit(root, "", "", _ignored(root))
    out["files"].sort()
    return out


def read_file(repo_id, rel, task_id=None):
    full = _safe(_root(repo_id, task_id), rel)
    size = os.path.getsize(full)
    if size > MAX_FILE:
        return {"path": rel, "size": size, "tooLarge": True}
    with open(full, "rb") as f:
        raw = f.read()
    if b"\0" in raw[:8000]:
        return {"path": rel, "size": size, "binary": True}
    return {"path": rel, "size": size, "text": raw.decode("utf-8", errors="replace"), "mtime": os.path.getmtime(full),
            "crlf": b"\r\n" in raw[:20000], "root": _root(repo_id, task_id)}


def write_file(repo_id, rel, text, task_id=None, mtime=None):
    full = _safe(_root(repo_id, task_id), rel)
    if mtime and os.path.exists(full) and abs(os.path.getmtime(full) - float(mtime)) > 0.001:
        raise ValueError("O arquivo mudou no disco desde que foi aberto (o agente pode ter editado) — recarregue antes de salvar")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return {"mtime": os.path.getmtime(full)}


def search(repo_id, query, task_id=None, regex=False, case=False, limit=400):
    """Busca no projeto: ripgrep se houver; senão git grep (que já respeita o .gitignore)."""
    root = _root(repo_id, task_id)
    if not query:
        return {"results": []}
    rg = shutil.which("rg") or next((p for p in ("/opt/homebrew/bin/rg", "/usr/local/bin/rg") if os.path.exists(p)), None)
    if rg:
        args = [rg, "--line-number", "--column", "--no-heading", "--color=never", "--max-count=50", "--max-columns=300"]
        args += ([] if case else ["-i"]) + ([] if regex else ["-F"]) + ["--", query, "."]
    else:
        args = ["git", "grep", "-n", "--column", "-I"] + ([] if case else ["-i"]) + ([] if regex else ["-F"]) + ["-e", query]
    r = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=30,
                       creationflags=0x08000000 if os.name == "nt" else 0)
    res = []
    for line in r.stdout.splitlines()[:limit]:
        m = re.match(r"^(?:\./)?(.+?):(\d+):(\d+):(.*)$", line)
        if m:
            res.append({"path": m.group(1), "line": int(m.group(2)), "col": int(m.group(3)), "text": m.group(4)[:300]})
    return {"results": res, "truncated": len(r.stdout.splitlines()) > limit}


def diff_summary(repo_id, task_id):
    """Resumo do que a tarefa mudou em relação à base (para revisar antes do PR)."""
    t = _task(_load(), repo_id, task_id)
    base = t["base"]
    try:
        mb = git.run(t["path"], "merge-base", "HEAD", base).strip()
    except Exception:  # noqa: BLE001
        mb = base
    stat = git.run(t["path"], "diff", "--numstat", mb, timeout=60)
    files_ = []
    for line in stat.splitlines():
        a, b, f = (line.split("\t") + ["", "", ""])[:3]
        files_.append({"path": f, "add": int(a) if a.isdigit() else None, "del": int(b) if b.isdigit() else None})
    ahead = git.run(t["path"], "rev-list", "--count", f"{mb}..HEAD").strip()
    return {"base": base, "mergeBase": mb, "files": files_, "commits": int(ahead or 0), "status": git.status(path=t["path"])}



def base_file(repo_id, task_id, rel):
    """Conteúdo do arquivo no ponto em que a tarefa saiu da base (merge-base) — o lado "antes" da revisão."""
    t = _task(_load(), repo_id, task_id)
    _safe(os.path.realpath(t["path"]), rel)
    try:
        mb = git.run(t["path"], "merge-base", "HEAD", t["base"]).strip()
    except Exception:  # noqa: BLE001
        mb = t["base"]
    try:
        text = git.run(t["path"], "show", f"{mb}:{rel}", timeout=30)
        return {"path": rel, "text": text, "exists": True}
    except Exception:  # noqa: BLE001 — arquivo novo na tarefa
        return {"path": rel, "text": "", "exists": False}


def changed_files(repo_id, task_id):
    """Tudo que a tarefa mudou em relação à base: commits + alterações ainda sem commit + arquivos novos."""
    d = diff_summary(repo_id, task_id)
    t = _task(_load(), repo_id, task_id)
    out = git.run(t["path"], "diff", "--numstat", d["mergeBase"], timeout=60)   # base × árvore de trabalho
    files = []
    for line in out.splitlines():
        a, b, f = (line.split("\t") + ["", "", ""])[:3]
        files.append({"path": f, "add": int(a) if a.isdigit() else None, "del": int(b) if b.isdigit() else None, "status": "M"})
    names = {f["path"] for f in files}
    for u in d["status"]["untracked"]:
        if u["path"] not in names:
            files.append({"path": u["path"], "add": None, "del": None, "status": "A"})
    deleted = set(git.run(t["path"], "diff", "--name-only", "--diff-filter=D", d["mergeBase"]).split())
    for f in files:
        if f["path"] in deleted:
            f["status"] = "D"
        elif not git.run(t["path"], "cat-file", "-t", f"{d['mergeBase']}:{f['path']}", check=False).strip():
            f["status"] = "A"
    return {"files": sorted(files, key=lambda x: x["path"]), "base": t["base"], "mergeBase": d["mergeBase"]}


# ---------------------------------------------------------------- executar o projeto (como no VS Code)
def _jsonc(text):
    """JSON com comentários e vírgula sobrando (launch.json, launchSettings.json)."""
    import json
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True; out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2); i = n if j < 0 else j + 2; continue
        else:
            out.append(c)
        i += 1
    clean = re.sub(r",(\s*[}\]])", r"\1", "".join(out))
    return json.loads(clean or "{}")


def _vars(s, root):
    """Variáveis do VS Code nas configurações: ${workspaceFolder}, ${env:X}, ${userHome}."""
    if not isinstance(s, str):
        return s
    s = s.replace("${workspaceFolder}", root).replace("${workspaceRoot}", root).replace("${userHome}", os.path.expanduser("~"))
    return re.sub(r"\$\{env:([^}]+)\}", lambda m: os.environ.get(m.group(1), ""), s)


def _q(x):
    """Um argumento para o shell do terminal. No Windows o shell é o PowerShell: aspas simples (dentro delas nada é
    interpretado — $, crase, ;). As aspas duplas do cmd (list2cmdline) expandiam $ e, no começo da linha, viravam
    uma expressão em vez de um comando."""
    import shlex
    if os.name != "nt":
        return shlex.quote(x)
    return x if x and re.fullmatch(r"[\w%+=:./\\-]+", x) else agents._ps_lit(x)


def _join(parts):
    """Linha de comando: no PowerShell um comando entre aspas precisa do & para ser executado."""
    cmd = " ".join(_q(p) for p in parts)
    return "& " + cmd if os.name == "nt" and cmd.startswith("'") else cmd


def _and(*cmds):
    """Encadeia comandos que só seguem se o anterior deu certo. O Windows PowerShell 5.1 não tem && (só o 7 tem)."""
    cmds = [c for c in cmds if c]
    if os.name != "nt":
        return " && ".join(cmds)
    out = cmds[-1]
    for c in reversed(cmds[:-1]):
        out = f"{c}; if ($?) {{ {out} }}"
    return out


def run_configs(repo_id, task_id=None):
    """O que a tela recebe: as configurações SEM valores de ambiente (o envFile pode ter credenciais — só o nome vai)."""
    r = _run_configs(repo_id, task_id)
    safe = []
    for c in r["configs"]:
        x = {k: v for k, v in c.items() if k not in ("env", "envFile")}
        if c.get("envFile"):
            x["envFile"] = os.path.basename(c["envFile"])
        if c.get("env"):
            x["envKeys"] = sorted(c["env"])
        safe.append(x)
    return {"configs": safe, "root": r["root"]}


def _env_file(path):
    """Arquivo .env (CHAVE=valor, # comentário, aspas opcionais) — lido só na hora de executar."""
    out = {}
    if not path or not os.path.isfile(path):
        return out
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        out[k] = v
    return out


def _run_configs(repo_id, task_id=None):
    """Tudo que dá para executar no projeto: launch.json, scripts do package.json, perfis do .NET, Go, Rust, Compose."""
    root = _root(repo_id, task_id)
    out = []
    # 1) .vscode/launch.json
    lj = os.path.join(root, ".vscode", "launch.json")
    if os.path.isfile(lj):
        try:
            data = _jsonc(open(lj, encoding="utf-8").read())
        except Exception:  # noqa: BLE001 — launch.json inválido: só não lista
            data = {}
        by_name = {}
        tasks = _vscode_tasks(root)
        for c in data.get("configurations") or []:
            cwd = _vars(c.get("cwd"), root) or root
            env = {k: _vars(v, root) for k, v in (c.get("env") or {}).items()}
            t, cmd = c.get("type"), None
            if c.get("request") == "attach":
                continue
            if t == "node-terminal" and c.get("command"):
                cmd = _vars(c["command"], root)
            elif t in ("node", "pwa-node"):
                exe = c.get("runtimeExecutable") or "node"
                parts = [exe] + [_vars(a, root) for a in c.get("runtimeArgs") or []]
                if c.get("program"):
                    parts.append(_vars(c["program"], root))
                parts += [_vars(a, root) for a in c.get("args") or []]
                cmd = _join(parts)
            elif t in ("debugpy", "python"):
                if c.get("module"):
                    cmd = _join(["python3" if os.name != "nt" else "python", "-m", c["module"]] + [_vars(a, root) for a in c.get("args") or []])
                elif c.get("program"):
                    cmd = _join(["python3" if os.name != "nt" else "python", _vars(c["program"], root)] + [_vars(a, root) for a in c.get("args") or []])
            elif t in ("coreclr", "dotnet"):
                if c.get("program", "").endswith(".exe") or c.get("program", "").endswith(".dll"):
                    prog = _vars(c["program"], root)
                    cmd = _join((["dotnet", prog] if prog.endswith(".dll") else [prog]) + [_vars(a, root) for a in c.get("args") or []])
                elif c.get("projectPath"):
                    cmd = "dotnet run --project " + _q(_vars(c["projectPath"], root))
            elif t == "go":
                cmd = "go run " + _q(_vars(c.get("program") or ".", root))
            if cmd and c.get("preLaunchTask"):
                pre = tasks.get(c["preLaunchTask"])   # como no VS Code: compila antes (sem isto rodaria a DLL antiga)
                if not pre and t in ("coreclr", "dotnet") and "/bin/" in _vars(c.get("program", ""), root).replace("\\", "/"):
                    # o "build" do C# costuma vir da extensão do VS Code (sem tasks.json): compila o projeto do programa
                    pre = "dotnet build " + _q(_vars(c["program"], root).replace("\\", "/").split("/bin/")[0])
                if pre:
                    cmd = _and(pre, cmd)
            if cmd:
                item = {"id": "launch:" + c.get("name", ""), "label": c.get("name", "?"), "group": "launch.json", "command": cmd,
                        "cwd": cwd, "env": env, "envFile": _vars(c.get("envFile"), root) or None}
                out.append(item)
                by_name[c.get("name")] = item
        for comp in data.get("compounds") or []:
            parts = [by_name[n] for n in comp.get("configurations") or [] if n in by_name]
            if parts:
                out.append({"id": "compound:" + comp.get("name", ""), "label": comp.get("name", "?"), "group": "launch.json",
                            "compound": [p["id"] for p in parts]})
    # 2) package.json (raiz e um nível abaixo — monorepos simples)
    for pj in [os.path.join(root, "package.json")] + sorted(glob_one(root, "*/package.json")):
        try:
            import json
            scripts = (json.load(open(pj, encoding="utf-8")).get("scripts") or {})
        except Exception:  # noqa: BLE001
            continue
        d = os.path.dirname(pj)
        pm = "pnpm" if os.path.exists(os.path.join(d, "pnpm-lock.yaml")) else "yarn" if os.path.exists(os.path.join(d, "yarn.lock")) else \
             "bun" if os.path.exists(os.path.join(d, "bun.lockb")) else "npm"
        rel = os.path.relpath(d, root)
        for name in scripts:
            out.append({"id": f"script:{rel}:{name}", "label": name, "group": f"scripts{'' if rel == '.' else ' · ' + rel}",
                        "command": f"{pm} run {name}", "cwd": d, "detail": str(scripts[name])[:120]})
    # 3) .NET: perfis do launchSettings.json de cada projeto (ex.: Local/Dev/Prod)
    for ls in sorted(glob_one(root, "**/Properties/launchSettings.json", limit=40)):
        proj_dir = os.path.dirname(os.path.dirname(ls))
        try:
            profiles = _jsonc(open(ls, encoding="utf-8").read()).get("profiles") or {}
        except Exception:  # noqa: BLE001
            continue
        name = os.path.basename(proj_dir)
        for prof, cfg in profiles.items():
            if (cfg or {}).get("commandName") not in (None, "Project"):
                continue
            out.append({"id": f"dotnet:{name}:{prof}", "label": f"{name} · {prof}", "group": ".NET",
                        "command": f"dotnet run --project {_q(proj_dir)} --launch-profile {_q(prof)}", "cwd": root})
    # 4) outros
    if os.path.exists(os.path.join(root, "go.mod")):
        out.append({"id": "go:run", "label": "go run .", "group": "Go", "command": "go run .", "cwd": root})
    if os.path.exists(os.path.join(root, "Cargo.toml")):
        out.append({"id": "cargo:run", "label": "cargo run", "group": "Rust", "command": "cargo run", "cwd": root})
    for f in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        if os.path.exists(os.path.join(root, f)):
            out.append({"id": "compose:up", "label": "docker compose up", "group": "Docker", "command": "docker compose up", "cwd": root})
            break
    return {"configs": out, "root": root}


def _vscode_tasks(root):
    """label → comando, do .vscode/tasks.json (para o preLaunchTask). Segue dependsOn de um nível."""
    tj = os.path.join(root, ".vscode", "tasks.json")
    if not os.path.isfile(tj):
        return {}
    try:
        data = _jsonc(open(tj, encoding="utf-8").read())
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for t in data.get("tasks") or []:
        if not t.get("command"):
            continue
        parts = [_vars(t["command"], root)] + [_vars(a if isinstance(a, str) else a.get("value", ""), root) for a in t.get("args") or []]
        cwd = _vars((t.get("options") or {}).get("cwd"), root)
        cmd = _join(parts) if t.get("type") == "process" else " ".join(parts)
        out[t.get("label") or t["command"]] = _and(f"cd {_q(cwd)}", cmd) if cwd else cmd
    for t in data.get("tasks") or []:
        deps = t.get("dependsOn")
        if deps and t.get("label"):
            deps = [deps] if isinstance(deps, str) else deps
            chain = [out[d] for d in deps if d in out] + ([out[t["label"]]] if t["label"] in out else [])
            if chain:
                out[t["label"]] = _and(*chain)
    return out


def glob_one(root, pattern, limit=200):
    """glob que não entra em node_modules/bin/obj/.git/.worktrees (repositórios grandes continuam rápidos)."""
    import fnmatch
    skip = {"node_modules", "bin", "obj", ".git", ".worktrees", "dist", "build", ".venv", "venv", "packages"}
    out, depth_max = [], (pattern.count("/") + 3 if "**" in pattern else pattern.count("/"))
    base = root.rstrip(os.sep).count(os.sep)
    pat = pattern.replace("**/", "")
    for cur, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in skip and not x.startswith(".") or x == ".vscode"]
        if cur.count(os.sep) - base >= depth_max:
            dirs[:] = []
        for f in files:
            rel = os.path.relpath(os.path.join(cur, f), root).replace(os.sep, "/")
            if fnmatch.fnmatch(rel, pattern) or ("**" in pattern and fnmatch.fnmatch(rel, "*" + pat if "/" not in pat else "*/" + pat)) \
                    or ("**" in pattern and rel.endswith("/" + pat)) or ("**" in pattern and rel == pat):
                out.append(os.path.join(cur, f))
                if len(out) >= limit:
                    return out
    return out


def run(repo_id, task_id, config_id):
    """Executa uma configuração num terminal do projeto (compound = um terminal por configuração)."""
    cfgs = {c["id"]: c for c in _run_configs(repo_id, task_id)["configs"]}
    c = cfgs.get(config_id)
    if not c:
        raise LookupError("Configuração não encontrada")
    started = []
    for cid in c.get("compound") or [config_id]:
        x = cfgs[cid]
        meta = {"project": repo_id, "run": cid, **({"task": task_id} if task_id else {})}
        env = {**_env_file(x.get("envFile")), **(x.get("env") or {})}   # envFile primeiro; "env" do launch.json por cima
        t = terminals.create(x["cwd"], "▶ " + x["label"], x["command"], "run", meta, env or None,
                             shell=_settings(repo_id).get("shell") or None)
        started.append(t.info())
    return {"terms": started}
