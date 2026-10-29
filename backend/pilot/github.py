"""GitHub: conta (Entrar com GitHub por código de dispositivo, token colado ou importado do gh CLI), PRs, Actions,
deploys esperando aprovação (environments), issues, repositórios de todas as contas/organizações e criação de PR.

Os itens saem no MESMO formato dos do Azure (provider="github"), então fila, regras, builds e notificações tratam as
duas plataformas igual. Chave de PR: "gh:<dono>/<repo>#<número>"; de run: "gh:<dono>/<repo>#run<id>".
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone

from . import secrets
from .core import CONFIG_FILE, OfflineError, is_network_error, load_json, now_iso, save_json

API_URL = "https://api.github.com"
SCOPES = "repo read:org workflow project"
UA = "Codeck"
# OAuth App com "device flow" habilitado. O client id é público por natureza (vai dentro do app); quem distribuir
# outro build pode trocar por CODECK_GITHUB_CLIENT_ID ou "githubClientId" no config.json.
GITHUB_CLIENT_ID = "Ov23liBS7zajZmsdvkL3"


def client_id():
    return os.environ.get("CODECK_GITHUB_CLIENT_ID") or load_json(CONFIG_FILE, {}).get("githubClientId") or GITHUB_CLIENT_ID


def github_message(e):
    text = str(e)
    m = re.search(r'"message":\s*"(.*?)(?<!\\)"', text)
    code = re.match(r"HTTP (\d{3})", text)
    msg = m.group(1) if m else re.sub(r"https?://\S+", "", text)
    if code and code.group(1) == "401":
        msg = "o GitHub recusou o token (inválido, expirado ou revogado)"
    return (f"HTTP {code.group(1)} — " if code else "") + msg.strip()[:240]


VOTE_FROM_STATE = {"APPROVED": 10, "CHANGES_REQUESTED": -10, "COMMENTED": 0, "DISMISSED": 0, "PENDING": 0}
CHECK_STATUS = {
    "SUCCESS": "approved", "FAILURE": "rejected", "ERROR": "rejected", "TIMED_OUT": "rejected", "STARTUP_FAILURE": "rejected",
    "ACTION_REQUIRED": "rejected", "IN_PROGRESS": "running", "QUEUED": "queued", "PENDING": "running", "WAITING": "running",
    "EXPECTED": "queued", "REQUESTED": "queued", "NEUTRAL": "notApplicable", "SKIPPED": "notApplicable",
    "CANCELLED": "notApplicable", "STALE": "notApplicable",
}

PR_FRAGMENT = """
fragment pr on PullRequest {
  number title body url isDraft createdAt updatedAt closedAt mergeable headRefName baseRefName headRefOid
  autoMergeRequest { enabledAt }
  author { login avatarUrl ... on User { name } }
  repository { name nameWithOwner owner { login } }
  reviewRequests(first: 20) { nodes { requestedReviewer { ... on User { login name } ... on Team { name slug } } } }
  latestReviews(first: 20) { nodes { state author { login ... on User { name } } } }
  commits(last: 1) { nodes { commit { statusCheckRollup { state contexts(first: 40) { nodes {
    ... on CheckRun { name status conclusion }
    ... on StatusContext { context state }
  } } } } } }
}"""

ISSUE_FRAGMENT = """
fragment issue on Issue {
  number title url updatedAt createdAt state comments { totalCount }
  author { login }
  repository { name nameWithOwner owner { login } }
  labels(first: 8) { nodes { name color } }
  assignees(first: 5) { nodes { login avatarUrl } }
}"""


class GitHub:
    provider = "github"

    def __init__(self, cfg):
        self.cfg = cfg
        self.id = cfg.get("id") or "teste"
        self.login = cfg.get("login") or ""
        self.name = self.login
        self._token = cfg.get("token")   # só em teste/conexão, antes de ir para o cofre
        self.me = None
        self.scopes = None
        self.rate = {}
        self.retry_until = 0   # limite secundário/Retry-After: a leitura de fundo pula a conta até essa hora (epoch)
        self._etags = {}
        self._lock = threading.Lock()
        self.auth_error = None   # {"at", "message"} quando o GitHub recusou o token e não deu para renovar sozinho

    # ------------------------------------------------------------ HTTP
    def token(self):
        if not self._token:
            self._token = secrets.get(self.id, self.cfg.get("secret"))
            if not self._token:
                raise RuntimeError("Token do GitHub não configurado")
        # token que expira (App do GitHub com "expire user tokens", ou OAuth com refresh): renova 10 min antes
        exp = self.cfg.get("expiresAt")
        if exp and self.cfg.get("refreshSecret") and time.time() > exp - 600:
            self._renew("expirando")
        return self._token

    def _renew(self, why):
        """Recupera o acesso sem pedir login de novo: troca o refresh token por um novo par, ou relê o token do gh CLI
        (que o próprio gh renova). Devolve True se conseguiu um token diferente do atual."""
        with _renew_lock:
            # outra thread pode ter renovado enquanto esta esperava: relê do config antes de gastar o refresh token
            fresh = next((a for a in load_json(CONFIG_FILE, {}).get("github", []) if a.get("id") == self.id), None)
            if fresh and fresh.get("expiresAt", 0) > (self.cfg.get("expiresAt") or 0):
                self.cfg.update(fresh)
                self._token = None
                self._token = secrets.get(self.id, fresh.get("secret"))
                return True
            old = self._token
            try:
                if self.cfg.get("refreshSecret"):
                    rt = secrets.get(self.id + "-r", self.cfg["refreshSecret"])
                    t = _form_post("https://github.com/login/oauth/access_token", {
                        "client_id": client_id(), "grant_type": "refresh_token", "refresh_token": rt})
                    if not t.get("access_token"):
                        raise RuntimeError(t.get("error_description") or t.get("error") or "o GitHub recusou a renovação")
                    self._token = t["access_token"]
                    _persist_tokens(self.id, t, self.cfg)
                elif self.cfg.get("source") == "gh-cli" and gh_cli_path():
                    tok = gh_cli_token()
                    if tok == old:
                        return False
                    self._token = tok
                    _persist_tokens(self.id, {"access_token": tok}, self.cfg)
                else:
                    return False
                print(f"[{now_iso()}] github: token de @{self.login} renovado ({why})", flush=True)
                return self._token != old
            except Exception as e:  # noqa: BLE001
                print(f"[{now_iso()}] github: não renovei o token de @{self.login} ({why}): {str(e)[:200]}", flush=True)
                return False

    def req(self, method, path, body=None, raw=False, etag=False, accept="application/vnd.github+json", headers_out=None, _retry=True):
        url = path if path.startswith("http") else f"{API_URL}/{path.lstrip('/')}"
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(url, data=data, method=method)
        r.add_unredirected_header("Authorization", f"Bearer {self.token()}")  # o log redireciona para outro host: o token não vai junto
        r.add_header("Accept", accept)
        r.add_header("X-GitHub-Api-Version", "2022-11-28")
        r.add_header("User-Agent", UA)
        if data is not None:
            r.add_header("Content-Type", "application/json")
        cached = self._etags.get(url) if etag and method == "GET" else None
        if cached:
            r.add_header("If-None-Match", cached[0])  # 304 não conta na cota de chamadas
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                self._note_rate(resp.headers)
                self.auth_error = None
                if headers_out is not None:
                    headers_out.update({k.lower(): v for k, v in resp.headers.items()})
                payload = resp.read()
                if raw:
                    return payload.decode(errors="replace")
                out = json.loads(payload) if payload else None
                if etag and resp.headers.get("ETag"):
                    self._etags[url] = (resp.headers["ETag"], out)
                return out
        except urllib.error.HTTPError as e:
            self._note_rate(e.headers)
            if e.code == 304 and cached:
                return cached[1]
            if e.code == 401 and _retry and self.id != "teste":
                # token recusado: renova (refresh token / gh CLI) e tenta UMA vez de novo antes de dar a conta por caída
                print(f"[{now_iso()}] github: 401 para @{self.login} em {method} {path.split('?')[0]}"
                      f" (expira: {e.headers.get('github-authentication-token-expiration') or 'não informado'})", flush=True)
                if self._renew("recusado"):
                    return self.req(method, path, body, raw, etag, accept, headers_out, _retry=False)
            if e.code == 401:
                self.auth_error = {"at": now_iso(), "message": "o GitHub recusou o token (expirado ou revogado)"}
            msg = e.read().decode(errors="replace")[:400]
            raise RuntimeError(f"HTTP {e.code} em {method} {path}: {msg}") from None
        except OSError as e:
            if is_network_error(e):
                raise OfflineError(e) from None
            raise

    def _note_rate(self, h):
        if h and h.get("X-RateLimit-Remaining"):
            self.rate = {"remaining": int(h["X-RateLimit-Remaining"]), "limit": int(h.get("X-RateLimit-Limit") or 0),
                         "reset": int(h.get("X-RateLimit-Reset") or 0)}
        if h and (h.get("Retry-After") or "").isdigit():   # limite secundário (403/429): o GitHub diz quanto esperar
            self.retry_until = time.time() + int(h["Retry-After"])

    def gql(self, query, variables=None):
        res = self.req("POST", "graphql", {"query": query, "variables": variables or {}})
        if res.get("errors") and not res.get("data"):
            raise RuntimeError("GraphQL: " + "; ".join(e.get("message", "") for e in res["errors"])[:300])
        return res["data"]

    def paged(self, path, limit=1000):
        out, page = [], 1
        sep = "&" if "?" in path else "?"
        while len(out) < limit:
            batch = self.req("GET", f"{path}{sep}per_page=100&page={page}")
            items = batch if isinstance(batch, list) else batch.get("repositories") or batch.get("workflow_runs") or []
            out.extend(items)
            if len(items) < 100:
                break
            page += 1
        return out[:limit]

    # ------------------------------------------------------------ conta
    def identity(self):
        if self.me is None:
            h = {}
            u = self.req("GET", "user", headers_out=h)
            self.scopes = [s.strip() for s in h.get("x-oauth-scopes", "").split(",") if s.strip()] if "x-oauth-scopes" in h else None
            self.me = {"id": u["login"], "login": u["login"], "name": u.get("name") or u["login"], "email": u.get("email") or "",
                       "avatar": u.get("avatar_url")}
            self.login = self.name = u["login"]
        return self.me

    def orgs(self):
        return [{"login": o["login"], "avatar": o.get("avatar_url"), "description": o.get("description") or ""}
                for o in self.req("GET", "user/orgs?per_page=100")]

    # ------------------------------------------------------------ repositórios (catálogos)
    def _shape_repo(self, r):
        return {
            "key": f"github:{r['full_name']}", "provider": "github", "account": self.login, "owner": r["owner"]["login"],
            "name": r["name"], "fullName": r["full_name"], "id": r["id"], "project": None,
            "cloneUrl": r.get("clone_url"), "sshUrl": r.get("ssh_url"), "webUrl": r.get("html_url"),
            "defaultBranch": r.get("default_branch"), "private": r.get("private", False), "fork": r.get("fork", False),
            "archived": r.get("archived", False), "description": r.get("description") or "", "size": r.get("size"),
            "updated": r.get("pushed_at") or r.get("updated_at"), "language": r.get("language"),
            "stars": r.get("stargazers_count", 0),
        }

    def list_repos(self, owner=None):
        me = self.identity()
        if not owner:
            raw = self.paged("user/repos?affiliation=owner,collaborator,organization_member&sort=pushed")
        elif owner.lower() == me["login"].lower():
            raw = self.paged("user/repos?affiliation=owner&sort=pushed")
        else:
            try:
                raw = self.paged(f"orgs/{urllib.parse.quote(owner)}/repos?type=all&sort=pushed")
            except RuntimeError as e:
                if "HTTP 404" not in str(e):
                    raise
                raw = self.paged(f"users/{urllib.parse.quote(owner)}/repos?sort=pushed")
        return [self._shape_repo(r) for r in raw]

    # ------------------------------------------------------------ PRs
    def _shape_pr(self, n, viewer):
        repo = n["repository"]
        author = n.get("author") or {}
        reviewers, my_vote, approvals = [], 0, 0
        for rv in (n.get("latestReviews") or {}).get("nodes", []):
            who = rv.get("author") or {}
            vote = VOTE_FROM_STATE.get(rv["state"], 0)
            approvals += vote == 10
            if who.get("login") == viewer:
                my_vote = vote
            reviewers.append({"name": who.get("name") or who.get("login", "?"), "vote": vote, "required": False, "id": who.get("login")})
        requested_me = False
        for rq in (n.get("reviewRequests") or {}).get("nodes", []):
            who = rq.get("requestedReviewer") or {}
            if who.get("login") == viewer:
                requested_me = True
            if not any(r["id"] == (who.get("login") or who.get("slug")) for r in reviewers):
                reviewers.append({"name": who.get("name") or who.get("login") or f"time {who.get('slug')}", "vote": 0,
                                  "required": True, "id": who.get("login") or who.get("slug")})
        rollup = (((n.get("commits") or {}).get("nodes") or [{}])[0].get("commit") or {}).get("statusCheckRollup") or {}
        policies = []
        for c in (rollup.get("contexts") or {}).get("nodes", []):
            if "name" in c:
                st = c.get("conclusion") or c.get("status") or ""
                policies.append({"name": c["name"], "type": "Build", "status": CHECK_STATUS.get(st, "queued"), "blocking": False})
            elif "context" in c:
                policies.append({"name": c["context"], "type": "Build", "status": CHECK_STATUS.get(c.get("state") or "", "queued"), "blocking": False})
        from .azure import build_status
        return {
            "key": f"gh:{repo['nameWithOwner']}#{n['number']}", "provider": "github", "account": self.login,
            "org": repo["owner"]["login"], "project": repo["nameWithOwner"], "projectId": None,
            "repo": repo["name"], "repoId": repo["nameWithOwner"], "prId": n["number"], "title": n["title"],
            "description": (n.get("body") or "")[:1500], "creatorName": author.get("name") or author.get("login", ""),
            "creatorUnique": author.get("login", ""), "creatorId": author.get("login"), "creatorAvatar": author.get("avatarUrl"),
            "source": n["headRefName"], "target": n["baseRefName"], "isDraft": n.get("isDraft", False),
            "created": n.get("createdAt"), "closed": n.get("closedAt"),
            "mergeStatus": {"CONFLICTING": "conflicts", "MERGEABLE": "succeeded"}.get(n.get("mergeable"), "queued"),
            "commit": n.get("headRefOid"), "autoComplete": bool(n.get("autoMergeRequest")), "reviewers": reviewers,
            "url": n["url"], "myVote": my_vote, "approvals": approvals, "policies": policies, "build": build_status(policies),
            "reviewRequested": requested_me,
        }

    def fetch_prs(self, watch_repos=()):
        """PRs que me pedem revisão, que já revisei, as minhas e as abertas nos repositórios acompanhados."""
        me = self.identity()
        base = "is:pr is:open archived:false"
        queries = {"req": f"{base} review-requested:@me", "rev": f"{base} reviewed-by:@me", "mine": f"{base} author:@me"}
        watch = [r for r in watch_repos if re.fullmatch(r"[\w.\-]+/[\w.\-]+", r)][:30]
        if watch:
            queries["watch"] = base + " " + " ".join(f"repo:{r}" for r in watch)
        parts = [f'{k}: search(query: ${k}, type: ISSUE, first: 60) {{ nodes {{ ...pr }} }}' for k in queries]
        q = f"query({', '.join(f'${k}: String!' for k in queries)}) {{ {' '.join(parts)} }}" + PR_FRAGMENT
        data = self.gql(q, queries)
        seen, others, mine = set(), [], []
        for k in queries:
            for n in data[k]["nodes"]:
                if not n or "number" not in n:
                    continue
                pr = self._shape_pr(n, me["login"])
                if pr["key"] in seen:
                    continue
                seen.add(pr["key"])
                if pr["creatorUnique"] == me["login"]:
                    mine.append(pr)
                elif not pr["isDraft"]:
                    others.append(pr)
        return others, mine

    def vote(self, full_name, number, vote, comment=""):
        event = {10: "APPROVE", 5: "APPROVE", -10: "REQUEST_CHANGES", -5: "REQUEST_CHANGES", 0: "COMMENT"}[vote]
        body = comment or {5: "Aprovado com sugestões.", -5: "Aguardando ajustes do autor.", -10: "Mudanças necessárias."}.get(vote, "")
        if event == "COMMENT" and not body:
            raise ValueError("No GitHub não dá para remover a revisão pelo app — abra a PR no navegador")
        self.req("POST", f"repos/{full_name}/pulls/{number}/reviews", {"event": event, "body": body})

    def comment(self, full_name, number, text):
        self.req("POST", f"repos/{full_name}/issues/{number}/comments", {"body": text})

    def review(self, full_name, number, event, body, comments=()):
        """Revisão com comentários presos às linhas (event: APPROVE, REQUEST_CHANGES ou COMMENT). O GitHub recusa (422)
        a revisão inteira se uma linha não está no diff: aí os pontos vão no texto da revisão."""
        path = f"repos/{full_name}/pulls/{int(number)}/reviews"
        cs = [{"path": c["path"], "line": int(c["line"]), "side": "RIGHT", "body": c["body"]} for c in comments if c.get("path") and c.get("line")]
        if cs:
            try:
                return self.req("POST", path, {"event": event, "body": body, "comments": cs})
            except RuntimeError as e:
                if not str(e).startswith("HTTP 422"):
                    raise
            body += "\n\n" + "\n\n".join(f"**{c['path']}:{c['line']}** — {c['body']}" for c in cs)
        return self.req("POST", path, {"event": event, "body": body})

    def open_feedback(self, full_name, number):
        """O que está em aberto na revisão: conversas no código não resolvidas e o texto da última revisão de cada um
        que pediu mudança ou comentou."""
        owner, name = full_name.split("/", 1)
        q = """query($o: String!, $n: String!, $num: Int!) { repository(owner: $o, name: $n) { pullRequest(number: $num) {
          reviewThreads(first: 100) { nodes { isResolved isOutdated path line originalLine comments(first: 30) { nodes { author { login } body } } } }
          reviews(last: 40) { nodes { state body author { login } } } } } }"""
        pr = self.gql(q, {"o": owner, "n": name, "num": int(number)})["repository"]["pullRequest"]
        out = []
        for t in pr["reviewThreads"]["nodes"]:
            cs = [{"author": (c.get("author") or {}).get("login") or "?", "text": c["body"].strip()}
                  for c in t["comments"]["nodes"] if (c.get("body") or "").strip()]
            if not t.get("isResolved") and cs:
                out.append({"id": None, "file": t.get("path"), "line": t.get("line") or t.get("originalLine"),
                            "outdated": bool(t.get("isOutdated")), "comments": cs})
        last = {}
        for rv in pr["reviews"]["nodes"]:   # do mais antigo ao mais novo: fica a última de cada pessoa
            last[(rv.get("author") or {}).get("login") or "?"] = rv
        for who, rv in last.items():
            if rv.get("state") in ("CHANGES_REQUESTED", "COMMENTED") and (rv.get("body") or "").strip():
                out.append({"id": None, "file": None, "line": None, "comments": [{"author": who, "text": rv["body"].strip()}]})
        return out

    def pr_approved_by_me(self, full_name, number):
        me = self.identity()["login"]
        last = None
        for rv in self.req("GET", f"repos/{full_name}/pulls/{number}/reviews?per_page=100"):
            if (rv.get("user") or {}).get("login") == me and rv.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
                last = rv["state"]
        return last == "APPROVED"

    def create_pr(self, full_name, source, target, title, description="", draft=False):
        pr = self.req("POST", f"repos/{full_name}/pulls",
                      {"head": source, "base": target, "title": title, "body": description, "draft": bool(draft)})
        return {"id": pr["number"], "url": pr["html_url"]}

    # ------------------------------------------------------------ Actions
    def _shape_run(self, full, r):
        status = {"completed": "completed", "in_progress": "inProgress"}.get(r["status"], "notStarted")
        result = {"success": "succeeded", "failure": "failed", "cancelled": "canceled", "timed_out": "failed",
                  "startup_failure": "failed", "action_required": "partiallySucceeded", "skipped": "succeeded",
                  "neutral": "succeeded", "stale": "canceled"}.get(r.get("conclusion") or "", None)
        prs = r.get("pull_requests") or []
        head = r.get("head_commit") or {}
        actor = r.get("triggering_actor") or r.get("actor") or {}
        owner, name = full.split("/", 1)
        return {
            "key": f"gh:{full}#run{r['id']}", "provider": "github", "account": self.login, "org": owner, "project": full,
            "id": r["id"], "number": f"#{r.get('run_number')}", "pipeline": r.get("name") or "workflow",
            "pipelineId": r.get("workflow_id"), "folder": name, "sourceBranch": r.get("head_branch") or "",
            "branch": r.get("head_branch") or "", "sourceVersion": r.get("head_sha"), "status": status, "result": result,
            "waiting": r["status"] == "waiting",
            "reason": {"push": "individualCI", "pull_request": "pullRequest", "pull_request_target": "pullRequest",
                       "workflow_dispatch": "manual", "schedule": "schedule"}.get(r.get("event"), r.get("event")),
            "requestedFor": actor.get("login", ""), "requestedForId": actor.get("login"), "requestedForAvatar": actor.get("avatar_url"),
            "queued": r.get("created_at"), "started": r.get("run_started_at"),
            "finished": r.get("updated_at") if status == "completed" else None,
            "message": (head.get("message") or r.get("display_title") or "").split("\n")[0][:200],
            "prNumber": prs[0]["number"] if prs else None, "repo": name, "attempt": r.get("run_attempt", 1),
            "url": r.get("html_url"),
        }

    def fetch_runs(self, repos, per_repo=15):
        out, errors = [], {}
        for full in list(repos)[:40]:
            try:
                data = self.req("GET", f"repos/{full}/actions/runs?per_page={per_repo}", etag=True)
                out.extend(self._shape_run(full, r) for r in data.get("workflow_runs", []))
            except Exception as e:  # noqa: BLE001 — repo sem Actions/sem acesso não derruba os outros
                if "HTTP 404" not in str(e):
                    errors[full] = github_message(e)
        return out, errors

    def run_detail(self, full, run_id):
        jobs = self.req("GET", f"repos/{full}/actions/runs/{run_id}/jobs?per_page=50").get("jobs", [])
        stages, failed = [], []
        for j in jobs:
            res = {"success": "succeeded", "failure": "failed", "cancelled": "canceled", "skipped": "skipped"}.get(j.get("conclusion") or "")
            stages.append({"name": j["name"], "state": {"completed": "completed", "in_progress": "inProgress"}.get(j["status"], "pending"),
                           "result": res, "order": len(stages)})
            if j.get("conclusion") not in ("failure", "timed_out", "cancelled"):
                continue
            steps = [s for s in j.get("steps", []) if s.get("conclusion") in ("failure", "timed_out", "cancelled")]
            issues = []
            try:
                cr = (j.get("check_run_url") or "").rsplit("/", 1)[-1]
                for a in self.req("GET", f"repos/{full}/check-runs/{cr}/annotations")[:6]:
                    issues.append({"type": "error" if a.get("annotation_level") == "failure" else "warning",
                                   "message": (a.get("message") or "")[:600]})
            except Exception:  # noqa: BLE001
                pass
            item = {"name": f"{j['name']} › {steps[0]['name']}" if steps else j["name"], "type": "Job",
                    "result": "failed" if j.get("conclusion") != "cancelled" else "canceled", "issues": issues, "logTail": None}
            if len(failed) < 3:
                try:
                    text = self.req("GET", f"repos/{full}/actions/jobs/{j['id']}/logs", raw=True)
                    lines = [re.sub(r"^\S+Z ", "", ln) for ln in text.splitlines()]
                    # o fim do log é limpeza do runner: mostra o trecho em volta do último erro
                    errs = [i for i, ln in enumerate(lines) if "##[error]" in ln]
                    end = errs[-1] + 3 if errs else len(lines)
                    item["logTail"] = "\n".join(lines[max(0, end - 40):end])
                except Exception:  # noqa: BLE001
                    pass
            failed.append(item)
        return {"stages": stages, "failed": failed[:8]}

    def run_phase(self, full, run_id):
        """O que um run "em andamento" está fazendo de verdade: falhando (um job já falhou), esperando runner, ou o
        job/passo atual."""
        jobs = self.req("GET", f"repos/{full}/actions/runs/{run_id}/jobs?per_page=50", etag=True).get("jobs", [])
        last = max((j.get("completed_at") or j.get("started_at") or "" for j in jobs), default="") or None
        bad = [j for j in jobs if j.get("conclusion") in ("failure", "timed_out", "startup_failure")]
        if bad:
            step = next((s["name"] for s in bad[0].get("steps", []) if s.get("conclusion") in ("failure", "timed_out")), None)
            return {"state": "failing", "label": f"falhou em {bad[0]['name']}" + (f" › {step}" if step else ""), "stage": None,
                    "job": bad[0]["name"], "since": last}
        cur = next((j for j in jobs if j.get("status") == "in_progress"), None)
        if not cur:
            queued = [j for j in jobs if j.get("status") in ("queued", "waiting", "pending", "requested")]
            if queued:
                return {"state": "agent", "label": "esperando runner", "stage": None, "job": queued[0]["name"], "since": last}
            return {"state": "running", "label": "rodando", "stage": None, "job": None, "since": last}
        step = next((s["name"] for s in cur.get("steps", []) if s.get("status") == "in_progress"), None)
        return {"state": "running", "label": cur["name"] + (f" › {step}" if step else ""), "stage": None, "job": cur["name"], "since": last}

    def run_action(self, b, action):
        full, run_id = b["project"], b["id"]
        path = {"retry": "rerun-failed-jobs", "rerun": "rerun", "cancel": "cancel"}.get(action)
        if not path:
            raise ValueError("ação inválida")
        self.req("POST", f"repos/{full}/actions/runs/{run_id}/{path}", {})

    def fetch_pending_deploys(self, runs):
        """Runs parados esperando aprovação de environment — viram itens da fila, como as releases do Azure."""
        items = []
        for b in runs:
            if not b.get("waiting"):
                continue
            try:
                pend = self.req("GET", f"repos/{b['project']}/actions/runs/{b['id']}/pending_deployments")
            except Exception:  # noqa: BLE001
                continue
            for p in pend:
                env = p.get("environment") or {}
                reviewers = [(rv.get("reviewer") or {}).get("login") or (rv.get("reviewer") or {}).get("name", "")
                             for rv in p.get("reviewers", [])]
                items.append({
                    "kind": "release", "provider": "github", "account": self.login,
                    "key": f"gh:{b['project']}#run{b['id']}:env{env.get('id')}", "org": b["org"], "project": b["project"],
                    "repo": b["repo"], "title": b["pipeline"], "pipeline": b["pipeline"], "stage": env.get("name", ""),
                    "envId": env.get("id"), "runId": b["id"], "branch": b["branch"], "version": b["number"],
                    "buildId": b["id"], "message": b["message"], "prNumber": b.get("prNumber"), "requestedFor": b["requestedFor"],
                    "approver": ", ".join(r for r in reviewers if r), "mine": bool(p.get("current_user_can_approve")),
                    "created": p.get("wait_timer_started_at") or b["queued"], "resources": [], "url": b["url"],
                    "prUrl": f"https://github.com/{b['project']}/pull/{b['prNumber']}" if b.get("prNumber") else None,
                })
        return items

    def decide_deploy(self, item, approve, comment=""):
        self.req("POST", f"repos/{item['project']}/actions/runs/{item['runId']}/pending_deployments", {
            "environment_ids": [item["envId"]], "state": "approved" if approve else "rejected",
            "comment": comment or ("Aprovado pelo Codeck" if approve else "Rejeitado pelo Codeck")})

    # ------------------------------------------------------------ issues
    def fetch_issues(self, scopes=("assigned", "created", "mentioned"), state="open", limit=500):
        """Issues por escopo — atribuídas a mim, criadas por mim, que me mencionam ou todas (dos meus repositórios e
        das minhas organizações) — e estado (open, closed, all). Todas as páginas da busca (100 por página; a busca
        do GitHub para em 1000 por consulta). Cada issue diz por que veio (`reasons`)."""
        base = "is:issue archived:false" + {"open": " is:open", "closed": " is:closed"}.get(state, "")
        queries = []
        for scope in list(dict.fromkeys(list(scopes) + (["assigned", "created", "mentioned"] if "all" in scopes else []))):
            if scope == "all":
                owners = [self.identity()["login"]] + [o["login"] for o in self.paged("user/orgs", limit=100)]
                queries += [("all", f"{base} {'user' if k == 0 else 'org'}:{o}") for k, o in enumerate(owners) if o]
            else:
                queries.append((scope, f"{base} " + {"assigned": "assignee:@me", "created": "author:@me", "mentioned": "mentions:@me"}[scope]))
        out, by = [], {}
        for reason, q in queries:
            after, got = None, 0
            while got < limit:
                data = self.gql("query($q: String!, $after: String) { search(query: $q, type: ISSUE, first: 100, after: $after) "
                                "{ pageInfo { hasNextPage endCursor } nodes { ...issue } } }" + ISSUE_FRAGMENT, {"q": q, "after": after})["search"]
                for n in data["nodes"]:
                    got += 1
                    if not n or "number" not in n:
                        continue
                    key = f"gh:{n['repository']['nameWithOwner']}#i{n['number']}"
                    if key in by:
                        if reason != "all" and reason not in by[key]["reasons"]:
                            by[key]["reasons"].append(reason)
                            by[key]["reason"] = by[key]["reasons"][0]
                        continue
                    by[key] = {
                        "key": key, "provider": "github", "org": n["repository"]["owner"]["login"],
                        "repo": n["repository"]["nameWithOwner"], "number": n["number"], "title": n["title"], "state": n["state"],
                        "type": "Issue", "updated": n["updatedAt"], "created": n["createdAt"], "author": (n.get("author") or {}).get("login", ""),
                        "labels": [{"name": l["name"], "color": f"#{l['color']}"} for l in n["labels"]["nodes"]],
                        "assignees": [{"login": a["login"], "avatar": a["avatarUrl"]} for a in n["assignees"]["nodes"]],
                        "comments": n["comments"]["totalCount"], "reason": reason if reason != "all" else "other",
                        "reasons": [reason] if reason != "all" else [], "url": n["url"],
                    }
                    out.append(by[key])
                if not data["pageInfo"]["hasNextPage"]:
                    break
                after = data["pageInfo"]["endCursor"]
        return out

    def issue(self, repo, number):
        """Uma issue inteira, para ler no app: corpo (Markdown), etiquetas, responsáveis e os comentários."""
        i = self.req("GET", f"repos/{repo}/issues/{int(number)}")
        comments = self.paged(f"repos/{repo}/issues/{int(number)}/comments", limit=300) if i.get("comments") else []
        return {"provider": "github", "number": i["number"], "title": i["title"], "state": i["state"], "type": "Issue", "project": repo,
                "author": (i.get("user") or {}).get("login", ""), "assignee": ", ".join(a["login"] for a in i.get("assignees") or []),
                "created": i.get("created_at"), "updated": i.get("updated_at"), "milestone": (i.get("milestone") or {}).get("title"),
                "labels": [l["name"] for l in i.get("labels") or []], "markdown": i.get("body") or "",
                "comments": [{"author": (c.get("user") or {}).get("login", ""), "created": c.get("created_at"), "markdown": c.get("body") or ""} for c in comments],
                "relations": [], "url": i["html_url"]}

    # ------------------------------------------------------------ Projects (v2): quadro pelo campo Status
    # Ler pede o escopo read:project (escrever, project): logins antigos não têm — a tela pede para entrar de novo.
    def _gql_projects(self, query, variables=None):
        res = self.req("POST", "graphql", {"query": query, "variables": variables or {}})
        errs = res.get("errors") or []
        if any(e.get("type") == "INSUFFICIENT_SCOPES" for e in errs):
            raise PermissionError("O login do GitHub não tem acesso aos Projects — entre de novo com o GitHub em Contas e ajustes "
                                  "(o login novo pede o escopo project)")
        if errs and not res.get("data"):
            raise RuntimeError("GraphQL: " + "; ".join(e.get("message", "") for e in errs)[:300])
        return res.get("data") or {}

    def projects_v2(self):
        frag = "fragment p on ProjectV2 { id number title url closed updatedAt owner { ... on User { login } ... on Organization { login } } }"
        q = ("query { viewer { projectsV2(first: 40, orderBy: {field: UPDATED_AT, direction: DESC}) { nodes { ...p } } "
             "organizations(first: 40) { nodes { login projectsV2(first: 40, orderBy: {field: UPDATED_AT, direction: DESC}) { nodes { ...p } } } } } } " + frag)
        v = self._gql_projects(q)["viewer"]
        nodes = list((v.get("projectsV2") or {}).get("nodes") or [])
        for o in ((v.get("organizations") or {}).get("nodes") or []):
            nodes += ((o or {}).get("projectsV2") or {}).get("nodes") or []   # org com SSO/política que barra o app: vem null
        seen, out = set(), []
        for n in nodes:
            if not n or n["id"] in seen or n.get("closed"):
                continue
            seen.add(n["id"])
            owner = (n.get("owner") or {}).get("login") or ""
            out.append({"id": f"gh|{self.login}|{n['id']}", "provider": "github", "org": owner, "account": self.login, "project": owner,
                        "title": n["title"], "number": n["number"], "url": n["url"], "updated": n.get("updatedAt")})
        return out

    def project_board(self, pid, sprint_id=None):
        """O Project em colunas: as opções do campo Status (ou o 1º campo de seleção única); sprint = o campo de iteração."""
        fq = """query($id: ID!) { node(id: $id) { ... on ProjectV2 { title url
          repositories(first: 30) { nodes { id nameWithOwner } }
          fields(first: 40) { nodes {
            ... on ProjectV2SingleSelectField { id name options { id name color } }
            ... on ProjectV2IterationField { id name configuration { iterations { id title startDate duration } completedIterations { id title startDate duration } } } } } } } }"""
        pj = self._gql_projects(fq, {"id": pid})["node"]
        if not pj:
            raise LookupError("Project não encontrado (ou sem acesso)")
        fields = [f for f in pj["fields"]["nodes"] if f]
        sel = [f for f in fields if "options" in f]
        status = next((f for f in sel if f["name"].lower() == "status"), None) or (sel[0] if sel else None)
        itf = next((f for f in fields if "configuration" in f), None)
        today = datetime.now(timezone.utc).date()
        sprints, cur = [], None
        if itf:
            conf = itf["configuration"]
            for it, done in [(x, True) for x in (conf.get("completedIterations") or [])[:4]] + [(x, False) for x in conf.get("iterations") or []]:
                start = date.fromisoformat(it["startDate"])
                fin = start + timedelta(days=int(it["duration"]))
                tf = "past" if done or fin <= today else "current" if start <= today else "future"
                sprints.append({"id": it["id"], "name": it["title"], "start": it["startDate"], "finish": fin.isoformat(), "timeFrame": tf})
            sprints.sort(key=lambda x: x["start"])
            cur = next((x for x in sprints if x["id"] == sprint_id), None) or next((x for x in sprints if x["timeFrame"] == "current"), None)
        iq = """query($id: ID!, $after: String) { node(id: $id) { ... on ProjectV2 { items(first: 100, after: $after) {
          pageInfo { hasNextPage endCursor }
          nodes { id type isArchived
            fieldValues(first: 30) { nodes {
              ... on ProjectV2ItemFieldSingleSelectValue { optionId field { ... on ProjectV2SingleSelectField { id } } }
              ... on ProjectV2ItemFieldIterationValue { iterationId field { ... on ProjectV2IterationField { id } } } } }
            content {
              ... on DraftIssue { title body }
              ... on Issue { number title url state updatedAt createdAt author { login } repository { nameWithOwner owner { login } }
                assignees(first: 5) { nodes { login avatarUrl } } labels(first: 8) { nodes { name color } } comments { totalCount } }
              ... on PullRequest { number title url state updatedAt createdAt author { login } repository { nameWithOwner owner { login } }
                assignees(first: 5) { nodes { login avatarUrl } } labels(first: 8) { nodes { name color } } comments { totalCount } } } } } } } }"""
        items, after = [], None
        while len(items) < 1000:
            page = self._gql_projects(iq, {"id": pid, "after": after})["node"]["items"]
            for n in page["nodes"]:
                if not n or n.get("isArchived"):
                    continue
                vals = [v for v in n["fieldValues"]["nodes"] if v]
                opt = next((v["optionId"] for v in vals if status and (v.get("field") or {}).get("id") == status["id"] and "optionId" in v), "")
                iteration = next((v["iterationId"] for v in vals if itf and (v.get("field") or {}).get("id") == itf["id"] and "iterationId" in v), None)
                if cur and iteration != cur["id"]:
                    continue
                c = n.get("content") or {}
                base = {"itemId": n["id"], "column": opt or "", "provider": "github", "account": self.login, "order": len(items)}
                if n["type"] == "DRAFT_ISSUE":
                    items.append({**base, "key": f"gh-draft:{n['id']}", "kind": "draft", "type": "Rascunho", "title": c.get("title") or "(sem título)",
                                  "body": c.get("body") or "", "number": None, "labels": [], "assignees": [], "state": "OPEN", "repo": None, "url": pj["url"]})
                    continue
                if "number" not in c:
                    continue   # item sem acesso (repositório privado de outra conta): o GitHub devolve vazio
                repo = c["repository"]["nameWithOwner"]
                pr = n["type"] == "PULL_REQUEST"
                items.append({**base, "key": f"gh:{repo}#{'' if pr else 'i'}{c['number']}", "kind": "pr" if pr else "issue", "type": "PR" if pr else "Issue",
                              "org": c["repository"]["owner"]["login"], "repo": repo, "number": c["number"], "title": c["title"], "state": c["state"],
                              "updated": c.get("updatedAt"), "created": c.get("createdAt"), "author": (c.get("author") or {}).get("login", ""),
                              "labels": [{"name": l["name"], "color": f"#{l['color']}"} for l in c["labels"]["nodes"]],
                              "assignees": [{"login": a["login"], "avatar": a["avatarUrl"]} for a in c["assignees"]["nodes"]],
                              "comments": c["comments"]["totalCount"], "url": c["url"], "reason": "other", "reasons": []})
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
        colors = {"GRAY": "#8b949e", "BLUE": "#4493f8", "GREEN": "#3fb950", "YELLOW": "#d29922", "ORANGE": "#db6d28", "RED": "#f85149",
                  "PINK": "#db61a2", "PURPLE": "#a371f7"}
        cols = ([{"id": "", "name": "Sem status"}] if any(not i["column"] for i in items) or not status else []) + \
               [{"id": o["id"], "name": o["name"], "color": colors.get(o.get("color"))} for o in (status or {}).get("options") or []]
        return {"title": pj["title"], "url": pj["url"], "statusField": (status or {}).get("id"), "sprint": cur, "sprints": sprints,
                "sprintLabel": (itf or {}).get("name"), "columns": cols, "items": items,
                "repos": [r["nameWithOwner"] for r in pj["repositories"]["nodes"] if r]}

    def project_move(self, pid, item_id, field_id, option_id):
        if option_id:
            m = """mutation($p: ID!, $i: ID!, $f: ID!, $o: String!) { updateProjectV2ItemFieldValue(input: {projectId: $p, itemId: $i, fieldId: $f,
                   value: {singleSelectOptionId: $o}}) { projectV2Item { id } } }"""
            self._gql_projects(m, {"p": pid, "i": item_id, "f": field_id, "o": option_id})
        else:
            m = "mutation($p: ID!, $i: ID!, $f: ID!) { clearProjectV2ItemFieldValue(input: {projectId: $p, itemId: $i, fieldId: $f}) { projectV2Item { id } } }"
            self._gql_projects(m, {"p": pid, "i": item_id, "f": field_id})

    def project_draft_to_issue(self, item_id, repo):
        """Rascunho do Project vira issue de verdade no repositório (o cartão continua no mesmo lugar do quadro)."""
        owner, name = repo.split("/", 1)
        rid = self.gql("query($o: String!, $n: String!) { repository(owner: $o, name: $n) { id } }", {"o": owner, "n": name})["repository"]["id"]
        m = """mutation($i: ID!, $r: ID!) { convertProjectV2DraftIssueItemToIssue(input: {itemId: $i, repositoryId: $r}) {
               item { content { ... on Issue { number url } } } } }"""
        c = self._gql_projects(m, {"i": item_id, "r": rid})["convertProjectV2DraftIssueItemToIssue"]["item"]["content"]
        return {"number": c["number"], "url": c["url"], "repo": repo}

    def comment_issue(self, repo, number, text):
        self.req("POST", f"repos/{repo}/issues/{int(number)}/comments", {"body": text})

    def edit_issue(self, repo, number, changes):
        """Edita a issue pelo app: título, corpo, estado (open/closed), responsáveis e etiquetas. Só manda o que mudou;
        devolve a issue inteira de novo (como `issue`), para a tela trocar o otimista pelo que o GitHub gravou."""
        body = {}
        for k in ("title", "body", "assignees", "labels"):
            if k in changes:
                body[k] = changes[k]
        if changes.get("state") in ("open", "closed"):
            body["state"] = changes["state"]
            if changes["state"] == "closed":
                body["state_reason"] = "not_planned" if changes.get("stateReason") == "not_planned" else "completed"
        if body.get("title") is not None and not str(body["title"]).strip():
            raise ValueError("O título não pode ficar vazio")
        if body:
            self.req("PATCH", f"repos/{repo}/issues/{int(number)}", body)
        return self.issue(repo, number)

    def issue_options(self, repo):
        """O que dá para escolher ao editar uma issue do repositório: as etiquetas (com cor) e quem pode ser responsável."""
        labels = self.paged(f"repos/{repo}/labels", limit=300)
        people = self.paged(f"repos/{repo}/assignees", limit=300)
        return {"states": [{"name": "open", "label": "Aberta", "category": "Proposed"}, {"name": "closed", "label": "Fechada", "category": "Completed"}],
                "labels": [{"name": l["name"], "color": f"#{l.get('color') or '888888'}"} for l in labels],
                "people": [{"id": u["login"], "name": u["login"], "avatar": u.get("avatar_url")} for u in people]}

    # ------------------------------------------------------------ arquivos da PR
    def pr_files(self, full, number):
        """Arquivos modificados da PR: caminho, status e +/- (100 por página; o GitHub para em 3000). A base do diff é a
        base do merge (como na aba "Files changed"), não a ponta atual da branch de destino."""
        pr = self.req("GET", f"repos/{full}/pulls/{int(number)}")
        head, base = pr["head"]["sha"], pr["base"]["sha"]
        try:
            base = (self.req("GET", f"repos/{full}/compare/{base}...{head}?per_page=1").get("merge_base_commit") or {}).get("sha") or base
        except Exception:  # noqa: BLE001 — sem compare (fork apagado, histórico enorme): compara com a ponta do destino
            pass
        st = {"added": "A", "removed": "D", "modified": "M", "renamed": "R", "copied": "C", "changed": "M", "unchanged": "M"}
        files = [{"path": f["filename"], "oldPath": f.get("previous_filename"), "status": st.get(f.get("status"), "M"),
                  "add": f.get("additions", 0), "del": f.get("deletions", 0), "binary": "patch" not in f and f.get("changes", 0) == 0 and f.get("status") != "renamed"}
                 for f in self.paged(f"repos/{full}/pulls/{int(number)}/files", limit=3000)]
        return {"files": files, "base": base, "head": head, "total": pr.get("changed_files", len(files)),
                "additions": pr.get("additions"), "deletions": pr.get("deletions")}

    def file_at(self, full, path, sha):
        """O texto do arquivo num commit (None se ele não existe lá)."""
        try:
            return self.req("GET", f"repos/{full}/contents/{urllib.parse.quote(path)}?ref={urllib.parse.quote(sha)}", raw=True,
                            accept="application/vnd.github.raw+json")
        except RuntimeError as e:
            if str(e).startswith("HTTP 404"):
                return None
            raise

# ---------------------------------------------------------------- login: código de dispositivo e gh CLI
device_flows = {}   # id -> {status, userCode, verificationUri, expires, interval, error, account}
_renew_lock = threading.Lock()


def _persist_tokens(aid, t, cfg):
    """Grava o token novo (e o refresh token e as validades, quando o GitHub manda) no cofre e no config.json."""
    entry_upd = {"secret": secrets.put(aid, t["access_token"], secrets.GITHUB)}
    if t.get("refresh_token"):
        entry_upd["refreshSecret"] = secrets.put(aid + "-r", t["refresh_token"], secrets.GITHUB)
    entry_upd["expiresAt"] = int(time.time() + int(t["expires_in"])) if t.get("expires_in") else None
    entry_upd["refreshExpiresAt"] = int(time.time() + int(t["refresh_token_expires_in"])) if t.get("refresh_token_expires_in") \
        else cfg.get("refreshExpiresAt")
    entry_upd["renewedAt"] = now_iso()
    full = load_json(CONFIG_FILE, {})
    for a in full.get("github", []):
        if a.get("id") == aid:
            a.update(entry_upd)
    save_json(CONFIG_FILE, full, private=True)
    cfg.update(entry_upd)


def _form_post(url, fields):
    r = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST",
                               headers={"Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read())


def device_start(on_token):
    cid = client_id()
    if not cid:
        raise ValueError("O login pelo navegador ainda não está habilitado neste build (falta o client id do OAuth App). Use um token.")
    d = _form_post("https://github.com/login/device/code", {"client_id": cid, "scope": SCOPES})
    if "device_code" not in d:
        raise RuntimeError(d.get("error_description") or "O GitHub recusou o início do login")
    fid = uuid.uuid4().hex[:12]
    flow = {"id": fid, "status": "pending", "userCode": d["user_code"], "verificationUri": d["verification_uri"],
            "expires": time.time() + int(d.get("expires_in", 900)), "error": None, "account": None}
    device_flows[fid] = flow

    def poll():
        interval = int(d.get("interval", 5))
        while time.time() < flow["expires"] and flow["status"] == "pending":
            time.sleep(interval)
            try:
                t = _form_post("https://github.com/login/oauth/access_token", {
                    "client_id": cid, "device_code": d["device_code"], "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
            except Exception as e:  # noqa: BLE001
                flow.update(status="error", error=str(e)[:200])
                return
            if t.get("access_token"):
                try:
                    flow["account"] = on_token(t["access_token"], t)
                    flow["status"] = "done"
                except Exception as e:  # noqa: BLE001
                    flow.update(status="error", error=str(e)[:200])
                return
            err = t.get("error")
            if err == "slow_down":
                interval += 5
            elif err != "authorization_pending":
                flow.update(status="error", error={"access_denied": "Login cancelado no GitHub",
                                                   "expired_token": "O código expirou — comece de novo"}.get(err, err))
                return
        if flow["status"] == "pending":
            flow.update(status="error", error="O código expirou — comece de novo")
    threading.Thread(target=poll, daemon=True).start()
    return {k: flow[k] for k in ("id", "userCode", "verificationUri", "status")}


def gh_cli_path():
    for c in (shutil.which("gh"), "/opt/homebrew/bin/gh", "/usr/local/bin/gh", r"C:\Program Files\GitHub CLI\gh.exe"):
        if c and os.path.exists(c):
            return c
    return None


def gh_cli_token():
    gh = gh_cli_path()
    if not gh:
        raise ValueError("GitHub CLI (gh) não encontrado nesta máquina")
    r = subprocess.run([gh, "auth", "token", "--hostname", "github.com"], capture_output=True, text=True, timeout=20)
    tok = r.stdout.strip()
    if r.returncode != 0 or not tok:
        raise ValueError("O gh CLI não está logado (rode: gh auth login)")
    return tok


# ---------------------------------------------------------------- teste da conta
NEEDED = {"repo": "PRs, revisões, repositórios privados, Actions e deploys", "read:org": "listar organizações e times",
          "workflow": "repetir/cancelar Actions que mexem em workflows"}


def test_account(gh):
    checks = []

    def add(group, label, status, detail, fix=None):
        checks.append({"group": group, "label": label, "status": status, "detail": detail, "fix": fix})

    t0 = time.monotonic()
    try:
        me = gh.identity()
        add("Conta", "Conectar com o token", "ok", f"{me['name']} (@{me['login']})")
    except Exception as e:  # noqa: BLE001
        add("Conta", "Conectar com o token", "fail", github_message(e), "Gere um token novo ou entre com o GitHub de novo")
        return {"ok": False, "verdict": "Não conecta", "checks": checks, "ms": int((time.monotonic() - t0) * 1000)}
    if gh.scopes is None:
        add("Conta", "Tipo de token", "warn", "token de granularidade fina — as permissões valem por repositório",
            "Confira se ele inclui Pull requests, Actions, Contents e Issues (leitura e escrita)")
    else:
        for sc, why in NEEDED.items():
            have = sc in gh.scopes or (sc == "read:org" and "admin:org" in gh.scopes)
            add("Permissões", f"Escopo {sc}", "ok" if have else "fail", why, None if have else f"Inclua o escopo {sc} no token")
        # opcional: só a tela Sprints e projetos usa
        have = "project" in gh.scopes or "read:project" in gh.scopes
        add("Permissões", "Escopo project", "ok" if have else "warn", "ler e mover os cartões dos Projects (Sprints e projetos)",
            None if have else "Entre de novo com o GitHub (o login novo já pede) ou inclua o escopo project no token")
    try:
        orgs = gh.orgs()
        add("Conta", "Organizações", "ok", ", ".join(o["login"] for o in orgs[:6]) or "nenhuma (só a conta pessoal)")
    except Exception as e:  # noqa: BLE001
        add("Conta", "Organizações", "warn", github_message(e))
    try:
        repos = gh.req("GET", "user/repos?per_page=5&sort=pushed&affiliation=owner,collaborator,organization_member")
        add("Repositórios", "Ler repositórios", "ok", ", ".join(r["full_name"] for r in repos[:3]) or "nenhum")
        if repos:
            gh.req("GET", f"repos/{repos[0]['full_name']}/actions/runs?per_page=1")
            add("Actions", "Ler Actions", "ok", f"testado em {repos[0]['full_name']}")
    except Exception as e:  # noqa: BLE001
        add("Repositórios", "Ler repositórios / Actions", "fail", github_message(e), "Inclua o escopo repo no token")
    rate = gh.rate
    if rate:
        add("Conta", "Cota de chamadas", "ok" if rate["remaining"] > 500 else "warn", f"{rate['remaining']} de {rate['limit']} restantes nesta hora")
    fails = [c for c in checks if c["status"] == "fail"]
    verdict = "Pronto para tudo" if not fails and all(c["status"] == "ok" for c in checks) else \
        "Funciona com limitações" if checks[0]["status"] == "ok" else "Não conecta"
    return {"ok": not fails, "verdict": verdict, "checks": checks, "ms": int((time.monotonic() - t0) * 1000)}


def account_entry(gh):
    me = gh.identity()
    return {"id": gh.id, "login": me["login"], "name": me["name"], "avatar": me["avatar"], "scopes": gh.scopes,
            "connectedAt": now_iso()}
