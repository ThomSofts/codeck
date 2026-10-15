"""Git local: repositórios registrados, status, graph, diffs, stage/commit, branches, sincronização, stash,
cherry-pick/revert, clone e "limpar local" (manda a pasta para a Lixeira) — mais abrir no editor/Finder/Explorer/terminal.

Tudo roda o `git` da máquina com lista de argumentos (sem shell). O app só opera em repositórios registrados e só
aceita caminhos de arquivo DENTRO do repositório. GIT_TERMINAL_PROMPT=0 e ssh em BatchMode: se faltar credencial,
o comando falha com mensagem em vez de travar esperando senha.
"""
import base64
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from .core import REPOS_FILE, load_json, log_git, now_iso, save_json

FIELD, RECORD = "\x1f", "\x1e"
jobs = {}            # id -> {"status", "log", "error", "result"} (clone e outras operações longas)
_status_cache = {}   # repo id -> (ts, status)


def git_bin():
    for c in (shutil.which("git"), "/usr/bin/git", "/opt/homebrew/bin/git", r"C:\Program Files\Git\cmd\git.exe"):
        if c and os.path.exists(c):
            return c
    raise RuntimeError("Git não encontrado nesta máquina — instale o Git para usar os repositórios locais")


class GitError(RuntimeError):
    pass


def _env(auth_header=None):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": "ssh -o BatchMode=yes", "LC_ALL": "C.UTF-8",
           "GIT_OPTIONAL_LOCKS": "0"}
    if auth_header:
        # credencial pela configuração via ambiente: não aparece na linha de comando (ps)
        env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraHeader", "GIT_CONFIG_VALUE_0": auth_header})
    return env


def run(cwd, *args, input=None, timeout=60, check=True, auth=None, raw=False):
    flags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW: sem janela de console piscando no Windows
    r = subprocess.run([git_bin(), *args], cwd=cwd, input=input, capture_output=True, timeout=timeout,
                       env=_env(auth), creationflags=flags)
    out = r.stdout if raw else r.stdout.decode("utf-8", errors="replace")
    if check and r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace").strip() or (out if isinstance(out, str) else "").strip()
        raise GitError(clean_git_error(err) or f"git {args[0]} falhou")
    return out


def clean_git_error(err):
    lines = [ln for ln in err.splitlines() if ln.strip() and not ln.startswith("hint:")]
    msg = " ".join(lines)[:600]
    if "could not read Username" in msg or "Authentication failed" in msg or "terminal prompts disabled" in msg:
        msg = "o servidor pediu login — conecte a conta (GitHub/Azure) no app ou configure a credencial do Git"
    elif "Permission denied (publickey)" in msg:
        msg = "a chave SSH não foi aceita — confira o ssh-agent ou use a URL https"
    return msg


# ---------------------------------------------------------------- registro de repositórios
def _repos():
    return load_json(REPOS_FILE, [])


def _save(repos):
    save_json(REPOS_FILE, repos)


def get_repo(repo_id):
    r = next((x for x in _repos() if x["id"] == repo_id), None)
    if not r:
        raise ValueError("Repositório não registrado — atualize a lista")
    if not os.path.isdir(r["path"]):
        raise ValueError(f"A pasta {r['path']} não existe mais")
    return r


def toplevel(path):
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
        raise ValueError("Pasta não encontrada")
    return os.path.normpath(run(path, "rev-parse", "--show-toplevel").strip())


def remote_info(path):
    try:
        url = run(path, "remote", "get-url", "origin", check=True).strip()
    except GitError:
        return {"remoteUrl": None, "provider": None, "slug": None, "webUrl": None}
    return {"remoteUrl": url, **parse_remote(url)}


def parse_remote(url):
    """github.com/dono/repo → github; dev.azure.com/org/proj/_git/repo (ou visualstudio/ssh) → azure."""
    u = (url or "").strip()
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", u)
    if m:
        return {"provider": "github", "slug": f"{m.group(1)}/{m.group(2)}", "webUrl": f"https://github.com/{m.group(1)}/{m.group(2)}",
                "owner": m.group(1), "name": m.group(2)}
    m = re.search(r"dev\.azure\.com/([^/]+)/([^/]+)/_git/([^/?#]+)", u) or \
        re.search(r"ssh\.dev\.azure\.com:v3/([^/]+)/([^/]+)/([^/?#]+)", u)
    if m:
        org, proj, repo = (re.sub(r"%20", " ", g) for g in m.groups())
        return {"provider": "azure", "slug": f"{org}/{proj}/{repo}", "webUrl": f"https://dev.azure.com/{org}/{proj}/_git/{repo}",
                "owner": org, "project": proj, "name": repo}
    m = re.search(r"([^/.]+)\.visualstudio\.com/(?:DefaultCollection/)?([^/]+)/_git/([^/?#]+)", u)
    if m:
        org, proj, repo = m.groups()
        return {"provider": "azure", "slug": f"{org}/{proj}/{repo}", "webUrl": f"https://dev.azure.com/{org}/{proj}/_git/{repo}",
                "owner": org, "project": proj, "name": repo}
    return {"provider": None, "slug": None, "webUrl": None}


def normalize_remote(url):
    """Chave para casar repositório remoto (catálogo) com clone local, qualquer que seja https/ssh/.git."""
    info = parse_remote(url)
    return (info["provider"] + ":" + info["slug"]).lower() if info.get("slug") else (url or "").lower().rstrip("/").removesuffix(".git")


def add_repo(path, catalog=None):
    top = toplevel(path)
    repos = _repos()
    existing = next((r for r in repos if os.path.normcase(r["path"]) == os.path.normcase(top)), None)
    if existing:
        return existing
    info = remote_info(top)
    r = {"id": uuid.uuid4().hex[:10], "path": top, "name": os.path.basename(top), "pinned": False,
         "addedAt": now_iso(), "remoteUrl": info.get("remoteUrl"), "remoteKey": normalize_remote(info.get("remoteUrl"))}
    repos.append(r)
    _save(repos)
    return r


SCAN_SKIP = {"node_modules", "bin", "obj", ".venv", "venv", "dist", "build", "Pods", ".git", "packages", "target", "vendor",
             "__pycache__", "out", "coverage", "DerivedData", "Library", "Applications"}


def scan(path, depth=3):
    """Procura repositórios git dentro de uma pasta (sem entrar em node_modules, bin, obj…). Continua DENTRO dos
    repositórios encontrados: um repositório "workspace" (ex.: cifal/apis) costuma ter os repositórios das APIs dentro
    dele, ignorados pelo .gitignore — antes a busca parava no primeiro .git e não os via."""
    root = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(root):
        raise ValueError("Pasta não encontrada")
    found = []
    base_depth = root.rstrip(os.sep).count(os.sep)
    for cur, dirs, _files in os.walk(root):
        if ".git" in dirs or os.path.isfile(os.path.join(cur, ".git")):
            found.append(cur)
        if cur.count(os.sep) - base_depth >= depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in SCAN_SKIP and not d.startswith(".")]
    known = {os.path.normcase(r["path"]) for r in _repos()}
    added = []
    for p in found:
        try:
            added.append(add_repo(p))
        except Exception:  # noqa: BLE001 — pasta sem permissão, repositório corrompido: segue com os outros
            continue
    return {"found": len(found), "new": sum(1 for p in found if os.path.normcase(p) not in known), "repos": added}


def move_repo(repo_id, dest_base):
    """Move o clone para outra pasta (dest_base/<nome>), com os worktrees ligados de novo (git worktree repair).
    Recusa se há operação em andamento (merge/rebase…) ou se o destino já existe."""
    import shutil as _sh
    r = get_repo(repo_id)
    base = os.path.abspath(os.path.expanduser(dest_base or ""))
    if not os.path.isdir(base):
        raise ValueError("Escolha uma pasta de destino que exista")
    dest = os.path.join(base, os.path.basename(r["path"].rstrip(os.sep)))
    if os.path.normcase(dest) == os.path.normcase(r["path"]):
        raise ValueError("O repositório já está nesta pasta")
    if os.path.exists(dest):
        raise ValueError(f"Já existe {dest}")
    if os.path.normcase(base).startswith(os.path.normcase(r["path"].rstrip(os.sep) + os.sep)):
        raise ValueError("Não dá para mover o repositório para dentro dele mesmo")
    if current_operation(r["path"]):
        raise ValueError(f"Há um {current_operation(r['path'])} em andamento — termine ou aborte antes de mover")
    _sh.move(r["path"], dest)
    try:
        run(dest, "worktree", "repair", timeout=60)
    except GitError:
        pass
    repos = _repos()
    for x in repos:
        if x["id"] == repo_id:
            x["path"] = dest
    _save(repos)
    _status_cache.pop(repo_id, None)
    return {"path": dest}


def remove_repo(repo_id):
    _save([r for r in _repos() if r["id"] != repo_id])


def set_pinned(repo_id, pinned):
    repos = _repos()
    for r in repos:
        if r["id"] == repo_id:
            r["pinned"] = bool(pinned)
    _save(repos)


# ---------------------------------------------------------------- status
def status(repo_id=None, path=None, cache=False):
    r = get_repo(repo_id) if repo_id else {"id": None, "path": path}
    if cache and repo_id in _status_cache and time.time() - _status_cache[repo_id][0] < 8:
        return _status_cache[repo_id][1]
    out = run(r["path"], "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all", timeout=30)
    st = {"branch": None, "head": None, "upstream": None, "ahead": 0, "behind": 0, "staged": [], "unstaged": [],
          "untracked": [], "conflicts": [], "detached": False}
    entries = out.split("\0")
    i = 0
    while i < len(entries):
        e = entries[i]
        i += 1
        if not e:
            continue
        if e.startswith("# branch.oid "):
            st["head"] = e.split(" ", 2)[2]
        elif e.startswith("# branch.head "):
            b = e.split(" ", 2)[2]
            st["branch"], st["detached"] = (None, True) if b == "(detached)" else (b, False)
        elif e.startswith("# branch.upstream "):
            st["upstream"] = e.split(" ", 2)[2]
        elif e.startswith("# branch.ab "):
            m = re.match(r"# branch\.ab \+(\d+) -(\d+)", e)
            st["ahead"], st["behind"] = int(m.group(1)), int(m.group(2))
        elif e[0] in "12":
            parts = e.split(" ", 8 if e[0] == "1" else 9)
            xy, p = parts[1], parts[-1]
            orig = None
            if e[0] == "2":
                orig = entries[i]
                i += 1
            if xy[0] != ".":
                st["staged"].append({"path": p, "status": xy[0], "from": orig})
            if xy[1] != ".":
                st["unstaged"].append({"path": p, "status": xy[1], "from": orig})
        elif e[0] == "u":
            st["conflicts"].append({"path": e.split(" ", 10)[-1], "status": "U"})
        elif e[0] == "?":
            st["untracked"].append({"path": e[2:], "status": "?"})
    try:
        st["stashes"] = len([ln for ln in run(r["path"], "stash", "list", timeout=15).splitlines() if ln.strip()])
    except GitError:
        st["stashes"] = 0
    st["dirty"] = bool(st["staged"] or st["unstaged"] or st["untracked"] or st["conflicts"])
    st["operation"] = current_operation(r["path"])
    if repo_id:
        _status_cache[repo_id] = (time.time(), st)
    return st


def current_operation(path):
    gitdir = os.path.join(path, ".git")
    if os.path.isfile(gitdir):  # worktree/submódulo: .git é um arquivo apontando para o diretório real
        try:
            gitdir = os.path.join(path, open(gitdir).read().split(":", 1)[1].strip())
        except Exception:  # noqa: BLE001
            return None
    for name, label in (("MERGE_HEAD", "merge"), ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"),
                        ("rebase-merge", "rebase"), ("rebase-apply", "rebase")):
        if os.path.exists(os.path.join(gitdir, name)):
            return label
    return None


def list_repos(with_status=True):
    repos = _repos()

    def enrich(r):
        item = {**r, "exists": os.path.isdir(r["path"])}
        item.update({k: v for k, v in parse_remote(r.get("remoteUrl")).items() if k in ("provider", "slug", "webUrl")})
        if with_status and item["exists"]:
            try:
                st = status(r["id"], cache=True)
                item["status"] = {k: st[k] for k in ("branch", "upstream", "ahead", "behind", "dirty", "stashes", "detached", "operation")}
                item["status"]["changes"] = len(st["staged"]) + len(st["unstaged"]) + len(st["untracked"]) + len(st["conflicts"])
                last = run(r["path"], "log", "-1", f"--format=%H{FIELD}%s{FIELD}%an{FIELD}%aI", timeout=15).strip().split(FIELD)
                item["lastCommit"] = {"sha": last[0], "subject": last[1], "author": last[2], "date": last[3]} if len(last) == 4 else None
            except Exception as e:  # noqa: BLE001
                item["error"] = str(e)[:200]
        return item
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(enrich, repos))


# ---------------------------------------------------------------- graph e commits
def graph(repo_id, limit=400, ref=None, all_refs=True, author=None, search=None, skip=0):
    r = get_repo(repo_id)
    args = ["log", f"--max-count={min(int(limit), 2000)}", f"--skip={int(skip)}", "--date-order",
            f"--format=%H{FIELD}%P{FIELD}%an{FIELD}%ae{FIELD}%aI{FIELD}%cn{FIELD}%D{FIELD}%s{RECORD}"]
    if author:
        args.append(f"--author={author}")
    if search:
        args += ["-i", f"--grep={search}"]
    if ref:
        args.append(ref)
    elif all_refs:
        args += ["--branches", "--remotes", "--tags", "HEAD"]
    out = run(r["path"], *args, timeout=60)
    commits = []
    for rec in out.split(RECORD):
        rec = rec.strip("\n")
        if not rec:
            continue
        f = rec.split(FIELD)
        if len(f) < 8:
            continue
        refs = [x.strip() for x in f[6].split(",") if x.strip()]
        commits.append({"sha": f[0], "parents": f[1].split() if f[1] else [], "author": f[2], "email": f[3], "date": f[4],
                        "committer": f[5], "refs": refs, "subject": f[7]})
    st = status(repo_id, cache=True)
    return {"commits": commits, "head": st["head"], "branch": st["branch"], "hasMore": len(commits) >= int(limit)}


def commit_detail(repo_id, sha):
    r = get_repo(repo_id)
    if not re.fullmatch(r"[0-9a-fA-F]{4,64}", sha):
        raise ValueError("commit inválido")
    meta = run(r["path"], "show", "-s", f"--format=%H{FIELD}%P{FIELD}%an{FIELD}%ae{FIELD}%aI{FIELD}%cn{FIELD}%cI{FIELD}%D{FIELD}%B", sha).split(FIELD)
    files = []
    numstat = run(r["path"], "show", "--format=", "--numstat", "-z", "-M", sha)
    names = run(r["path"], "show", "--format=", "--name-status", "-z", "-M", sha).split("\0")
    status_by_path, i = {}, 0
    while i < len(names):
        code = names[i]
        if not code:
            i += 1
            continue
        if code[0] in "RC":
            status_by_path[names[i + 2]] = (code[0], names[i + 1])
            i += 3
        else:
            status_by_path[names[i + 1]] = (code[0], None)
            i += 2
    for path, (code, orig) in status_by_path.items():
        files.append({"path": path, "status": code, "from": orig, "add": None, "del": None})
    for chunk in re.finditer(r"(\d+|-)\t(\d+|-)\t([^\0]*)\0", numstat):
        add, dele, p = chunk.groups()
        f = next((x for x in files if x["path"] == p), None)
        if f:
            f["add"], f["del"] = (None if add == "-" else int(add)), (None if dele == "-" else int(dele))
    return {"sha": meta[0], "parents": meta[1].split(), "author": meta[2], "email": meta[3], "date": meta[4],
            "committer": meta[5], "committedAt": meta[6], "refs": [x.strip() for x in meta[7].split(",") if x.strip()],
            "message": meta[8].strip(), "files": files}


def _safe_path(repo, rel):
    full = os.path.normpath(os.path.join(repo["path"], rel))
    if not (full == repo["path"] or full.startswith(repo["path"] + os.sep)):
        raise ValueError("caminho fora do repositório")
    return os.path.relpath(full, repo["path"]).replace(os.sep, "/")


def diff(repo_id, path=None, sha=None, staged=False, context=3):
    r = get_repo(repo_id)
    rel = _safe_path(r, path) if path else None
    if sha:
        if not re.fullmatch(r"[0-9a-fA-F]{4,64}", sha):
            raise ValueError("commit inválido")
        args = ["show", "--format=", f"-U{int(context)}", "-M", sha]
    elif staged:
        args = ["diff", "--cached", f"-U{int(context)}", "-M"]
    else:
        args = ["diff", f"-U{int(context)}"]
    if rel:
        args += ["--", rel]
    text = run(r["path"], *args, timeout=60)
    if not text and rel and not sha and not staged:
        # arquivo novo (não rastreado): mostra o conteúdo inteiro como adição
        full = os.path.join(r["path"], rel)
        if os.path.isfile(full) and os.path.getsize(full) < 600_000:
            with open(full, "rb") as fh:
                data = fh.read()
            if b"\0" in data[:8000]:
                return {"diff": "", "binary": True, "truncated": False}
            lines = data.decode("utf-8", errors="replace").splitlines()
            text = f"diff --git a/{rel} b/{rel}\nnew file\n--- /dev/null\n+++ b/{rel}\n@@ -0,0 +1,{len(lines)} @@\n" + \
                   "\n".join("+" + ln for ln in lines)
    truncated = len(text) > 600_000
    return {"diff": text[:600_000], "binary": "Binary files" in text[:2000], "truncated": truncated}


# ---------------------------------------------------------------- branches, tags, stashes
def refs(repo_id):
    r = get_repo(repo_id)
    fmt = f"%(refname){FIELD}%(objectname){FIELD}%(upstream:short){FIELD}%(upstream:track){FIELD}%(committerdate:iso-strict){FIELD}%(authorname){FIELD}%(subject)"
    out = run(r["path"], "for-each-ref", f"--format={fmt}", "refs/heads", "refs/remotes", "refs/tags", timeout=30)
    local, remote, tags = [], [], []
    for ln in out.splitlines():
        f = ln.split(FIELD)
        if len(f) < 7:
            continue
        name, sha, up, track, date, author, subject = f
        if name.startswith("refs/heads/"):
            ahead = int(re.search(r"ahead (\d+)", track).group(1)) if "ahead" in track else 0
            behind = int(re.search(r"behind (\d+)", track).group(1)) if "behind" in track else 0
            local.append({"name": name[11:], "sha": sha, "upstream": up or None, "ahead": ahead, "behind": behind,
                          "gone": "gone" in track, "date": date, "author": author, "subject": subject})
        elif name.startswith("refs/remotes/"):
            if name.endswith("/HEAD"):
                continue
            remote.append({"name": name[13:], "sha": sha, "date": date, "author": author, "subject": subject})
        else:
            tags.append({"name": name[10:], "sha": sha, "date": date})
    stashes = []
    for ln in run(r["path"], "stash", "list", f"--format=%gd{FIELD}%H{FIELD}%gs{FIELD}%aI", timeout=15).splitlines():
        f = ln.split(FIELD)
        if len(f) == 4:
            stashes.append({"ref": f[0], "sha": f[1], "message": f[2], "date": f[3]})
    try:
        default = run(r["path"], "symbolic-ref", "--short", "refs/remotes/origin/HEAD", timeout=10).strip().removeprefix("origin/")
    except GitError:
        default = next((b for b in ("main", "master", "develop") if any(x["name"] == b for x in local)), None)
    local.sort(key=lambda b: b["date"], reverse=True)
    remote.sort(key=lambda b: b["date"], reverse=True)
    tags.sort(key=lambda t: t["date"], reverse=True)
    return {"local": local, "remote": remote, "tags": tags[:200], "stashes": stashes, "default": default,
            "current": status(repo_id)["branch"]}


# ---------------------------------------------------------------- ações
BRANCH_RE = re.compile(r"^(?!/|.*\.\.|.*//|.*@\{|.*\\)[\w./\-+]{1,200}(?<![./])$")


def _check_branch(name):
    if not name or not BRANCH_RE.match(name) or name.startswith("-"):
        raise ValueError(f"Nome de branch inválido: {name}")
    return name


def _check_ref(ref):
    if not ref or ref.startswith("-") or not re.fullmatch(r"[\w./\-+@^~{}]{1,250}", ref):
        raise ValueError("referência inválida")
    return ref


def _paths(repo, paths):
    if not paths:
        raise ValueError("nenhum arquivo selecionado")
    return [_safe_path(repo, p) for p in paths]


def _done(repo_id):
    _status_cache.pop(repo_id, None)


def stage(repo_id, paths):
    r = get_repo(repo_id)
    run(r["path"], "add", "-A", "--", *_paths(r, paths))
    _done(repo_id)


def stage_all(repo_id):
    r = get_repo(repo_id)
    run(r["path"], "add", "-A")
    _done(repo_id)


def unstage(repo_id, paths):
    r = get_repo(repo_id)
    try:
        run(r["path"], "restore", "--staged", "--", *_paths(r, paths))
    except GitError:   # repositório sem nenhum commit ainda
        run(r["path"], "rm", "--cached", "-r", "-q", "--", *_paths(r, paths))
    _done(repo_id)


def discard(repo_id, paths):
    """Descarta alterações de arquivos (rastreados voltam ao último commit; não rastreados vão para a Lixeira)."""
    r = get_repo(repo_id)
    rels = _paths(r, paths)
    st = status(repo_id)
    untracked = {f["path"] for f in st["untracked"]}
    tracked = [p for p in rels if p not in untracked]
    if tracked:
        run(r["path"], "restore", "--staged", "--worktree", "--", *tracked)
    for p in rels:
        if p in untracked:
            move_to_trash(os.path.join(r["path"], p))
    _done(repo_id)
    log_git("discard", r, f"descartou {len(rels)} arquivo(s)")


def commit(repo_id, message, amend=False, stage_all_first=False):
    r = get_repo(repo_id)
    if not (message or "").strip() and not amend:
        raise ValueError("Escreva a mensagem do commit")
    if stage_all_first:
        run(r["path"], "add", "-A")
    args = ["commit", "-F", "-"]
    if amend:
        args.append("--amend")
        if not (message or "").strip():
            args = ["commit", "--amend", "--no-edit"]
    run(r["path"], *args, input=(message or "").encode() if "-F" in args else None, timeout=120)
    _done(repo_id)
    sha = run(r["path"], "rev-parse", "HEAD").strip()
    log_git("commit", r, (message or "amend").split("\n")[0][:120])
    return {"sha": sha}


def checkout(repo_id, ref, create=None, start=None, track=None):
    r = get_repo(repo_id)
    if create:
        args = ["switch", "-c", _check_branch(create)]
        if start:
            args.append(_check_ref(start))
    elif track:   # branch remota → cria a local acompanhando
        local = track.split("/", 1)[1] if "/" in track else track
        args = ["switch", "-c", _check_branch(local), "--track", _check_ref(track)]
    else:
        args = ["switch", _check_ref(ref)] if not re.fullmatch(r"[0-9a-f]{7,40}", ref or "") else ["switch", "--detach", ref]
    run(r["path"], *args, timeout=120)
    _done(repo_id)
    log_git("checkout", r, create or track or ref)


def create_branch(repo_id, name, start=None, switch=True):
    if switch:
        return checkout(repo_id, None, create=name, start=start)
    r = get_repo(repo_id)
    run(r["path"], "branch", _check_branch(name), *([_check_ref(start)] if start else []))
    _done(repo_id)


def delete_branch(repo_id, name, force=False, remote=False):
    r = get_repo(repo_id)
    if remote:
        remote_name, branch = name.split("/", 1)
        run(r["path"], "push", _check_ref(remote_name), "--delete", _check_branch(branch), timeout=180, auth=auth_for(r))
    else:
        run(r["path"], "branch", "-D" if force else "-d", _check_branch(name))
    _done(repo_id)
    log_git("branch-delete", r, name)


def rename_branch(repo_id, old, new):
    r = get_repo(repo_id)
    run(r["path"], "branch", "-m", _check_branch(old), _check_branch(new))
    _done(repo_id)


def fetch(repo_id):
    r = get_repo(repo_id)
    run(r["path"], "fetch", "--all", "--prune", "--tags", timeout=300, auth=auth_for(r))
    _done(repo_id)


def pull(repo_id, rebase=False):
    r = get_repo(repo_id)
    run(r["path"], "pull", "--rebase" if rebase else "--ff-only", timeout=300, auth=auth_for(r))
    _done(repo_id)
    log_git("pull", r, status(repo_id)["branch"])


def push(repo_id, force=False):
    r = get_repo(repo_id)
    st = status(repo_id)
    if not st["branch"]:
        raise ValueError("Você está fora de uma branch (detached HEAD) — crie uma branch antes de enviar")
    args = ["push"]
    if force:
        args.append("--force-with-lease")
    if not st["upstream"]:
        args += ["--set-upstream", "origin", st["branch"]]
    run(r["path"], *args, timeout=300, auth=auth_for(r))
    _done(repo_id)
    log_git("push", r, st["branch"])


def push_branch(repo_id, name, force=False):
    """Envia uma branch local que não precisa ser a atual (cria a remota e passa a acompanhá-la, se ainda não houver)."""
    r = get_repo(repo_id)
    args = ["push", "--set-upstream"] + (["--force-with-lease"] if force else []) + ["origin", _check_branch(name)]
    run(r["path"], *args, timeout=300, auth=auth_for(r))
    _done(repo_id)
    log_git("push", r, name)


def update_branch(repo_id, name):
    """Traz os commits da remota para uma branch local SEM fazer checkout. Só avança (fast-forward): se as duas
    divergiram, o Git recusa e nada muda. A branch atual usa o pull normal."""
    r = get_repo(repo_id)
    st = status(repo_id)
    if name == st["branch"]:
        return pull(repo_id)
    up = run(r["path"], "rev-parse", "--abbrev-ref", f"{_check_branch(name)}@{{upstream}}").strip()
    remote, _, branch = up.partition("/")
    if not branch:
        raise ValueError(f"{name} não acompanha nenhuma branch remota")
    run(r["path"], "fetch", remote, f"{branch}:{name}", timeout=300, auth=auth_for(r))
    _done(repo_id)


def rebase(repo_id, onto):
    r = get_repo(repo_id)
    run(r["path"], "rebase", _check_ref(onto), timeout=300)
    _done(repo_id)
    log_git("rebase", r, onto)


def delete_tag(repo_id, name, remote=False):
    r = get_repo(repo_id)
    if remote:
        run(r["path"], "push", "origin", "--delete", f"refs/tags/{_check_branch(name)}", timeout=180, auth=auth_for(r))
    else:
        run(r["path"], "tag", "-d", _check_branch(name))
    _done(repo_id)


def push_tag(repo_id, name):
    r = get_repo(repo_id)
    run(r["path"], "push", "origin", f"refs/tags/{_check_branch(name)}", timeout=180, auth=auth_for(r))
    _done(repo_id)


def merge(repo_id, ref):
    r = get_repo(repo_id)
    run(r["path"], "merge", "--no-edit", _check_ref(ref), timeout=180)
    _done(repo_id)
    log_git("merge", r, ref)


def cherry_pick(repo_id, sha):
    r = get_repo(repo_id)
    run(r["path"], "cherry-pick", _check_ref(sha), timeout=120)
    _done(repo_id)
    log_git("cherry-pick", r, sha[:8])


def revert(repo_id, sha):
    r = get_repo(repo_id)
    run(r["path"], "revert", "--no-edit", _check_ref(sha), timeout=120)
    _done(repo_id)
    log_git("revert", r, sha[:8])


def abort_operation(repo_id):
    r = get_repo(repo_id)
    op = current_operation(r["path"])
    if not op:
        raise ValueError("Nenhuma operação em andamento")
    run(r["path"], op, "--abort")
    _done(repo_id)


def continue_operation(repo_id):
    r = get_repo(repo_id)
    op = current_operation(r["path"])
    if not op:
        raise ValueError("Nenhuma operação em andamento")
    if op == "merge":
        run(r["path"], "commit", "--no-edit")
    else:
        run(r["path"], op, "--continue", input=b"")
    _done(repo_id)


def stash(repo_id, action, ref=None, message=None, include_untracked=True):
    r = get_repo(repo_id)
    if action == "push":
        args = ["stash", "push"] + (["-u"] if include_untracked else []) + (["-m", message] if message else [])
    elif action in ("pop", "apply", "drop"):
        if ref and not re.fullmatch(r"stash@\{\d+\}", ref):
            raise ValueError("stash inválido")
        args = ["stash", action] + ([ref] if ref else [])
    else:
        raise ValueError("ação de stash inválida")
    run(r["path"], *args, timeout=120)
    _done(repo_id)
    log_git(f"stash-{action}", r, message or ref)


def create_tag(repo_id, name, sha=None, message=None):
    r = get_repo(repo_id)
    args = ["tag"] + (["-a", "-m", message] if message else []) + [_check_branch(name)] + ([_check_ref(sha)] if sha else [])
    run(r["path"], *args)
    _done(repo_id)


def reset(repo_id, sha, mode="mixed"):
    if mode not in ("soft", "mixed", "hard"):
        raise ValueError("modo inválido")
    r = get_repo(repo_id)
    run(r["path"], "reset", f"--{mode}", _check_ref(sha))
    _done(repo_id)
    log_git(f"reset-{mode}", r, sha[:8])


# ---------------------------------------------------------------- credenciais das contas conectadas no app
_auth_lookup = {"fn": None}   # o engine registra uma função (provider, owner) -> header ou None


def auth_for(repo):
    info = parse_remote(repo.get("remoteUrl"))
    url = repo.get("remoteUrl") or ""
    if not url.startswith("https://") or not _auth_lookup["fn"] or not info.get("provider"):
        return None
    return _auth_lookup["fn"](info["provider"], info.get("owner"))


def basic_header(user, secret):
    return "Authorization: Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()


# ---------------------------------------------------------------- clone (operação longa, com progresso)
def clone(url, dest, auth=None):
    if not re.match(r"^(https://|git@|ssh://)", url or ""):
        raise ValueError("URL de clone inválida")
    dest = os.path.abspath(os.path.expanduser(dest))
    if os.path.exists(dest) and os.listdir(dest):
        raise ValueError(f"A pasta {dest} já existe e não está vazia")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "status": "running", "progress": "", "percent": 0, "error": None, "result": None, "dest": dest}
    jobs[jid] = job

    def work():
        flags = 0x08000000 if os.name == "nt" else 0
        p = subprocess.Popen([git_bin(), "clone", "--progress", url, dest], stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             env=_env(auth), creationflags=flags)
        buf, tail = b"", []
        while True:
            ch = p.stderr.read(1)
            if not ch:
                break
            if ch in (b"\r", b"\n"):
                line = buf.decode(errors="replace").strip()
                buf = b""
                if line:
                    tail = (tail + [line])[-20:]
                    job["progress"] = line
                    m = re.search(r"(\d+)%", line)
                    if m:
                        stage_w = {"Receiving": 0.8, "Resolving": 0.15, "Counting": 0.0, "Compressing": 0.05}
                        st = next((k for k in stage_w if line.startswith("remote: " + k) or line.startswith(k)), None)
                        base = {"Counting": 0, "Compressing": 0, "Receiving": 5, "Resolving": 85}.get(st or "", 0)
                        job["percent"] = min(99, int(base + int(m.group(1)) * stage_w.get(st or "", 0)))
            else:
                buf += ch
        code = p.wait()
        if code != 0:
            job.update(status="error", error=clean_git_error("\n".join(tail)) or "o clone falhou")
            shutil.rmtree(dest, ignore_errors=True) if os.path.isdir(dest) and not os.listdir(dest) else None
            return
        try:
            repo = add_repo(dest)
            job.update(status="done", percent=100, result=repo)
            log_git("clone", repo, url)
        except Exception as e:  # noqa: BLE001
            job.update(status="error", error=str(e))
    threading.Thread(target=work, daemon=True).start()
    return job


# ---------------------------------------------------------------- limpar branches locais (recomendação pela principal)
# Nunca entram: a atual, a principal, as de longa vida (abaixo) e as abertas em outro worktree. Recomendadas (já
# marcadas): mergeadas em origin/<principal> (merge/fast-forward → `branch -d`), squash/rebase detectados (o conteúdo
# já está na principal → `-D` depois de confirmar) e remoto apagado com todos os commits ainda no servidor. Parada há
# muito tempo ou remoto apagado com commits só aqui: aparecem desmarcadas. Não mergeada e ativa: só informa.
PROTECTED_BRANCHES = {"main", "master", "develop", "development", "dev", "trunk", "staging", "stage", "production", "prod",
                      "release", "qa", "homolog", "homologacao", "hml", "gh-pages"}
STALE_DAYS = 90


def _rc(path, *args, timeout=30):
    """Só o código de saída (merge-base --is-ancestor, rev-parse --verify…)."""
    flags = 0x08000000 if os.name == "nt" else 0
    return subprocess.run([git_bin(), *args], cwd=path, capture_output=True, timeout=timeout, env=_env(), creationflags=flags).returncode


def _main_remote(path):
    rs = run(path, "remote", timeout=10).split()
    return "origin" if "origin" in rs else (rs[0] if rs else None)


def main_branch(path, remote=None):
    """(nome, ref de comparação): a que o <remoto>/HEAD aponta; senão main; senão master. develop é integração, não a
    principal — só vale se não houver main/master. A comparação é com a remota (o que já está no servidor)."""
    remote = remote if remote is not None else _main_remote(path)
    head = None
    if remote:
        try:
            head = run(path, "symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD", timeout=10).strip().split("/", 1)[1]
        except (GitError, IndexError):
            head = None
    order = ([head] if head and head not in ("develop", "development", "dev") else []) + ["main", "master"] + ([head] if head else [])
    for name in dict.fromkeys(order):
        for ref in ([f"{remote}/{name}"] if remote else []) + [name]:
            if _rc(path, "rev-parse", "--verify", "--quiet", ref + "^{commit}") == 0:
                return name, ref
    return None, None


def _patch_ids(path, *log_args, input=None):
    """patch-id estável de cada commit (git log -p) ou de um diff (input); vazio se o Git não souber."""
    try:
        patch = input if input is not None else run(path, "log", "-p", "--no-merges", "--format=commit %H", *log_args, timeout=60, raw=True)
        if not patch.strip():
            return []
        out = run(path, "patch-id", "--stable", input=patch, timeout=60)
        return [ln.split()[0] for ln in out.splitlines() if ln.strip()]
    except (GitError, subprocess.TimeoutExpired):
        return []


def _fresh(path, name):
    """A branch só tem o registro de criação no reflog (nunca recebeu commit, merge nem pull)."""
    try:
        log = run(path, "reflog", "show", "--format=%gs", f"refs/heads/{name}", "--", timeout=10).splitlines()
    except GitError:
        return False
    return len(log) == 1 and log[0].startswith("branch: Created from")


def _ago_label(days):
    return f"{days} dias" if days < 60 else f"{days // 30} meses" if days < 730 else f"{days // 365} anos"


def branch_cleanup_plan(path, do_fetch=True, auth=None, stale_days=STALE_DAYS):
    remote = _main_remote(path)
    fetched, fetch_error, pruned = False, None, []
    if do_fetch and remote:
        before = set(run(path, "for-each-ref", "--format=%(refname:short)", "refs/remotes", timeout=30).split())
        try:
            run(path, "fetch", "--all", "--prune", timeout=300, auth=auth)
            fetched = True
        except (GitError, subprocess.TimeoutExpired) as e:
            fetch_error = str(e) or "não consegui falar com o servidor"
        after = set(run(path, "for-each-ref", "--format=%(refname:short)", "refs/remotes", timeout=30).split())
        pruned = sorted(before - after)
    main, base = main_branch(path, remote)
    try:
        current = run(path, "symbolic-ref", "--short", "-q", "HEAD", timeout=10).strip() or None
    except GitError:
        current = None
    worktrees, wt_path = {}, None
    for ln in run(path, "worktree", "list", "--porcelain", timeout=15).splitlines():
        if ln.startswith("worktree "):
            wt_path = ln[9:]
        elif ln.startswith("branch refs/heads/"):
            worktrees[ln[18:]] = wt_path
    here = os.path.realpath(path)
    merged = set(run(path, "branch", "--format=%(refname:short)", "--merged", base, timeout=30).split()) if base else set()
    remote_merged = set(run(path, "branch", "-r", "--format=%(refname:short)", "--merged", base, timeout=30).split()) if base else set()
    remote_refs = set(run(path, "for-each-ref", "--format=%(refname:short)", "refs/remotes", timeout=30).split())
    fmt = FIELD.join(["%(refname:short)", "%(objectname)", "%(upstream:short)", "%(upstream:track)", "%(committerdate:unix)", "%(subject)"])
    now = time.time()
    items, pending = [], []
    for ln in run(path, "for-each-ref", f"--format={fmt}", "refs/heads", timeout=30).splitlines():
        f = ln.split(FIELD)
        if len(f) < 6:
            continue
        name, sha, up, track, ts, subject = f
        days = int((now - int(ts or now)) // 86400)
        it = {"name": name, "sha": sha, "upstream": up or None, "gone": "gone" in track, "days": days, "subject": subject,
              "kind": "keep", "reason": "", "detail": "", "recommended": False, "selectable": False, "force": False, "remote": None}
        wt = worktrees.get(name)
        if name == current:
            it["reason"] = "branch atual"
        elif name == main:
            it["reason"] = "branch principal"
        elif name.lower() in PROTECTED_BRANCHES:
            it["reason"] = "branch de longa vida"
        elif wt and os.path.realpath(wt) != here:
            it["reason"], it["detail"] = "aberta em outro worktree", home_path(wt)
        elif not base:
            it["reason"] = "sem branch principal para comparar"
        elif name in merged:
            it.update(kind="merged", reason=f"mergeada em {main}", recommended=True, selectable=True)
            if not up and _fresh(path, name):   # recém-criada, ainda sem commits: "mergeada" só no papel
                it.update(recommended=False, reason="sem commits próprios", detail=f"aponta para um commit de {main}")
        else:
            pending.append(it)
        if (it["kind"] == "merged" and up and not it["gone"] and up in remote_refs and up in remote_merged
                and up.split("/", 1)[-1] != main and up.split("/", 1)[-1].lower() not in PROTECTED_BRANCHES):
            it["remote"] = up   # continua no servidor, já mergeada: dá para apagar lá também (opcional)
        items.append(it)

    # o que não é ancestral da principal: squash/rebase (conteúdo já lá), remoto apagado, parada, ativa
    if pending:
        mbs = {}
        for it in pending:
            try:
                mbs[it["name"]] = run(path, "merge-base", base, it["sha"], timeout=15).strip()
            except GitError:
                mbs[it["name"]] = None
        oldest = min((int(run(path, "log", "-1", "--format=%ct", mb, timeout=10).strip() or 0) for mb in mbs.values() if mb), default=None)
        base_ids = set(_patch_ids(path, "--max-count=4000", f"--since={oldest - 86400}", base)) if oldest else set()
        for it in pending:
            mb, sha = mbs.get(it["name"]), it["sha"]
            ahead = int(run(path, "rev-list", "--count", f"{base}..{sha}", timeout=30).strip() or 0)
            local_only = int(run(path, "rev-list", "--count", sha, "--not", "--remotes", timeout=30).strip() or 0)
            how = None
            if mb and base_ids:
                own = _patch_ids(path, f"{mb}..{sha}")
                if own and all(p in base_ids for p in own):
                    how = "rebase"
                elif (whole := _patch_ids(path, input=run(path, "diff", mb, sha, timeout=60, raw=True))) and whole[0] in base_ids:
                    how = "squash"
            if not how and mb:
                # squash com ajuste no merge: os arquivos que a branch mexeu estão iguais na principal
                files = set(run(path, "diff", "--name-only", mb, sha, timeout=60).splitlines())
                if files and not (files & set(run(path, "diff", "--name-only", base, sha, timeout=60).splitlines())):
                    how = "conteúdo"
            only = f"{local_only} commit(s) só nesta máquina" if local_only else ""
            if how:
                it.update(kind="squash", recommended=True, selectable=True, force=True,
                          reason=f"squash-mergeada em {main}" if how == "squash" else f"rebase em {main}" if how == "rebase" else f"conteúdo já está em {main}",
                          detail=f"{ahead} commit(s) com outro SHA na principal")
            elif it["gone"] and not local_only:
                where = next(iter(run(path, "branch", "-r", "--contains", sha, "--format=%(refname:short)", timeout=30).split()), "")
                it.update(kind="gone", recommended=True, selectable=True, force=True, reason="remoto apagado",
                          detail=f"os commits continuam em {where}" if where else "os commits continuam no servidor")
            elif it["gone"]:
                it.update(kind="gone", selectable=True, force=True, reason="remoto apagado", detail=only)
            elif it["days"] >= stale_days:
                it.update(kind="stale", selectable=True, force=True, reason=f"parada há {_ago_label(it['days'])}",
                          detail=only or ("está no servidor" if it["upstream"] else f"{ahead} commit(s) fora de {main}"))
            else:
                it.update(kind="unmerged", reason=f"não mergeada em {main}",
                          detail=f"{ahead} commit(s) à frente" + (f" · {local_only} só nesta máquina" if local_only else ""))
    order = {"merged": 0, "squash": 1, "gone": 2, "stale": 3, "unmerged": 4, "keep": 5}
    items.sort(key=lambda x: (order[x["kind"]], not x["recommended"], x["days"]))
    return {"main": main, "base": base, "remote": remote, "current": current, "fetched": fetched, "fetchError": fetch_error,
            "pruned": pruned, "staleDays": stale_days, "branches": items}


def home_path(p):
    return re.sub(r"^/Users/[^/]+|^C:\\Users\\[^\\]+", "~", p or "", flags=re.I)


def cleanup_plan(repo_id, do_fetch=True):
    r = get_repo(repo_id)
    plan = branch_cleanup_plan(r["path"], do_fetch, auth_for(r))
    _done(repo_id)
    return plan


def cleanup_branches(repo_id, branches, remote_too=False):
    """Apaga o que a tela confirmou. Reanalisa (sem fetch) e só apaga o que continua apagável e no mesmo commit;
    `-D` só para quem o plano marca como forçar (squash/rebase, remoto apagado, parada) e a tela mandou force."""
    r = get_repo(repo_id)
    res = delete_branches(r["path"], branches, remote_too, auth_for(r))
    _done(repo_id)
    if res["deleted"]:
        log_git("branch-cleanup", r, ", ".join(res["deleted"]) + (f" (+{len(res['remoteDeleted'])} no servidor)" if res["remoteDeleted"] else ""))
    return res


def delete_branches(path, branches, remote_too=False, auth=None):
    plan = {b["name"]: b for b in branch_cleanup_plan(path, do_fetch=False)["branches"]}
    deleted, failed, remotes = [], [], []
    for req in branches or []:
        name = _check_branch(req.get("name"))
        it = plan.get(name)
        if not it or not it["selectable"]:
            failed.append({"name": name, "error": it["reason"] if it else "não existe mais"})
            continue
        if req.get("sha") and req["sha"] != it["sha"]:
            failed.append({"name": name, "error": "ganhou commits desde a análise"})
            continue
        if it["force"] and not req.get("force"):
            failed.append({"name": name, "error": "precisa confirmar (não é ancestral da principal)"})
            continue
        try:
            if it["kind"] == "merged":
                try:
                    run(path, "branch", "-d", name)
                except GitError:
                    # -d compara com a upstream/HEAD; a análise já confirmou que está em origin/<principal>
                    run(path, "branch", "-D", name)
            else:
                run(path, "branch", "-D", name)
            deleted.append(name)
            if remote_too and it.get("remote"):
                remotes.append(it["remote"])
        except GitError as e:
            failed.append({"name": name, "error": str(e)})
    remote_deleted = []
    by_remote = {}
    for ref in remotes:
        rem, br = ref.split("/", 1)
        by_remote.setdefault(rem, []).append(_check_branch(br))
    for rem, names in by_remote.items():
        try:
            run(path, "push", _check_ref(rem), "--delete", *names, timeout=180, auth=auth)
            remote_deleted += [f"{rem}/{n}" for n in names]
        except GitError as e:
            failed.append({"name": f"{rem} (servidor)", "error": str(e)})
    return {"deleted": deleted, "remoteDeleted": remote_deleted, "failed": failed}


# ---------------------------------------------------------------- limpar local (Lixeira) com travas
def clean_blockers(repo_id):
    """O que impede apagar a cópia local sem perder trabalho. Vazio = seguro."""
    r = get_repo(repo_id)
    st = status(repo_id)
    out = []
    n = len(st["staged"]) + len(st["unstaged"]) + len(st["untracked"]) + len(st["conflicts"])
    if n:
        out.append(f"{n} alteração(ões) sem commit")
    if st["stashes"]:
        out.append(f"{st['stashes']} stash(es) guardado(s)")
    if st["operation"]:
        out.append(f"{st['operation']} em andamento")
    # commits que não existem em nenhuma branch remota (inclui branches locais sem upstream)
    try:
        unpushed = run(r["path"], "log", "--branches", "--not", "--remotes", "--format=%h", timeout=30).split()
    except GitError:
        unpushed = []
    if unpushed:
        out.append(f"{len(unpushed)} commit(s) que não foram enviados para o servidor")
    if not r.get("remoteUrl"):
        out.append("o repositório não tem remoto — a pasta é a única cópia")
    return out


def clean_local(repo_id):
    r = get_repo(repo_id)
    blockers = clean_blockers(repo_id)
    if blockers:
        raise ValueError("Não dá para limpar: " + "; ".join(blockers))
    move_to_trash(r["path"])
    remove_repo(repo_id)
    log_git("clean", r, r["path"])


def move_to_trash(path):
    path = os.path.abspath(path)
    if sys.platform == "darwin":
        # o caminho vai como argumento (argv), nunca dentro do texto do script: nome com aspas não vira comando
        script = 'on run argv\ntell application "Finder" to delete (POSIX file (item 1 of argv) as alias)\nend run'
        r = subprocess.run(["osascript", "-e", script, path], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            # sem permissão de automação do Finder: move para ~/.Trash direto
            trash = os.path.expanduser("~/.Trash")
            target = os.path.join(trash, os.path.basename(path))
            if os.path.exists(target):
                target += f" {time.strftime('%H.%M.%S')}"
            shutil.move(path, target)
        return
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                        ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                        ("lpszProgressTitle", wintypes.LPCWSTR)]
        op = SHFILEOPSTRUCTW(None, 3, path + "\0", None, 0x0040 | 0x0010 | 0x0004 | 0x0400, False, None, None)  # DELETE + ALLOWUNDO
        if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) != 0:
            raise RuntimeError("Não consegui mandar para a Lixeira")
        return
    raise RuntimeError("Lixeira não suportada neste sistema")


# ---------------------------------------------------------------- abrir no editor / Finder / Explorer / terminal
EDITORS = {
    "vscode": {"name": "VS Code", "cli": ["code"], "mac": "Visual Studio Code",
               "win": [r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd", r"%ProgramFiles%\Microsoft VS Code\bin\code.cmd"]},
    "cursor": {"name": "Cursor", "cli": ["cursor"], "mac": "Cursor", "win": [r"%LOCALAPPDATA%\Programs\cursor\resources\app\bin\cursor.cmd"]},
    "rider": {"name": "Rider", "cli": ["rider"], "mac": "Rider", "win": []},
    "visualstudio": {"name": "Visual Studio", "cli": [], "mac": None, "win": [r"%ProgramFiles%\Microsoft Visual Studio\2022\Community\Common7\IDE\devenv.exe",
                                                                           r"%ProgramFiles%\Microsoft Visual Studio\2022\Professional\Common7\IDE\devenv.exe",
                                                                           r"%ProgramFiles%\Microsoft Visual Studio\2022\Enterprise\Common7\IDE\devenv.exe"]},
}


def available_editors():
    out = []
    for key, e in EDITORS.items():
        if _editor_cmd(key):
            out.append({"id": key, "name": e["name"]})
    return out


def _editor_cmd(key):
    e = EDITORS[key]
    for c in e["cli"]:
        p = shutil.which(c)
        if p:
            return [p]
    if sys.platform == "darwin" and e["mac"]:
        for base in ("/Applications", os.path.expanduser("~/Applications")):
            if os.path.isdir(os.path.join(base, e["mac"] + ".app")):
                return ["open", "-a", e["mac"]]
    if os.name == "nt":
        for c in e["win"]:
            p = os.path.expandvars(c)
            if os.path.exists(p):
                return [p]
    return None


def open_in(path, target, editor="vscode", file=None):
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise ValueError("Pasta não encontrada")
    detached = {"creationflags": 0x00000008 | 0x08000000} if os.name == "nt" else {"start_new_session": True}
    if target == "editor":
        cmd = _editor_cmd(editor) or _editor_cmd("vscode") or _editor_cmd("cursor")
        if not cmd:
            raise ValueError("Nenhum editor encontrado (VS Code, Cursor, Rider…)")
        args = cmd + [path] + ([os.path.join(path, file)] if file else [])
        if cmd[0].endswith(".cmd"):
            args = ["cmd", "/c"] + args
        subprocess.Popen(args, **detached)
    elif target == "files":
        if sys.platform == "darwin":
            subprocess.Popen(["open", path], **detached)
        elif os.name == "nt":
            subprocess.Popen(["explorer", path], **detached)
        else:
            subprocess.Popen(["xdg-open", path], **detached)
    elif target == "terminal":
        if sys.platform == "darwin":
            app = "iTerm" if os.path.isdir("/Applications/iTerm.app") else "Terminal"
            subprocess.Popen(["open", "-a", app, path], **detached)
        elif os.name == "nt":
            wt = shutil.which("wt")
            subprocess.Popen([wt, "-d", path] if wt else ["cmd", "/c", "start", "cmd", "/K", f'cd /d "{path}"'], **detached)
        else:
            subprocess.Popen(["x-terminal-emulator"], cwd=path, **detached)
    else:
        raise ValueError("destino inválido")
