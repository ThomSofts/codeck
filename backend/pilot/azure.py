"""Azure DevOps: PRs, builds, releases clássicas, aprovações de ambiente YAML, permissões de pipeline,
repositórios (para os catálogos), criação de PR e itens de trabalho. Uma instância de Org por organização."""
import base64
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from . import secrets
from .core import CONFIG_FILE, OfflineError, http_code, is_network_error, load_json, now, parse_dt

API = "api-version=7.0"
API_PREVIEW = "api-version=7.1-preview.1"
build_cache = {}      # (org, buildId) -> dado imutável do build (mensagem, branch, PR de origem…)


def phase_from_records(records):
    """{"state": failing|approval|check|agent|running, "label", "stage", "job", "since"} a partir da timeline do Azure."""
    by_type = lambda *t: [r for r in records if r.get("type") in t]
    stages = sorted(by_type("Stage"), key=lambda r: r.get("order") or 0)
    running = lambda rs: [r for r in rs if r.get("state") == "inProgress"]
    last = max((r.get("lastModified") or r.get("startTime") or "" for r in records), default="") or None
    cur_stage = (running(stages) or [None])[0]
    cur_job = (running(by_type("Job", "Phase")) or [None])[0]
    stage_name = cur_stage["name"] if cur_stage else None
    failed = [r for r in by_type("Stage", "Job", "Task") if r.get("result") in ("failed", "abandoned")]
    if failed:
        f = next((r for r in failed if r["type"] == "Task"), failed[0])
        return {"state": "failing", "label": f"falhou em {f['name']}", "stage": stage_name, "job": f["name"], "since": last}
    appr = [r for r in by_type("Checkpoint.Approval") if r.get("state") == "inProgress"]
    if appr:
        ids = {r.get("id"): r for r in records}
        chk = ids.get(appr[0].get("parentId")) or {}   # aprovação → checkpoint → stage
        parent = (ids.get(chk.get("parentId")) or {}).get("name") or stage_name
        return {"state": "approval", "label": "aguardando aprovação" + (f" · {parent}" if parent else ""), "stage": parent, "job": None, "since": last}
    checks = [r for r in by_type("Checkpoint") if r.get("state") == "inProgress"]
    if checks and not cur_job:
        return {"state": "check", "label": "aguardando verificação" + (f" · {stage_name}" if stage_name else ""), "stage": stage_name, "job": None, "since": last}
    pending_jobs = [r for r in by_type("Job") if r.get("state") == "pending"]
    if pending_jobs and not cur_job:
        return {"state": "agent", "label": "esperando agente", "stage": stage_name, "job": pending_jobs[0]["name"], "since": last}
    task = (running(by_type("Task")) or [None])[0]
    label = " › ".join(x for x in (stage_name, cur_job["name"] if cur_job else None, task["name"] if task else None) if x)
    return {"state": "running", "label": label or "rodando", "stage": stage_name, "job": cur_job["name"] if cur_job else None, "since": last}


class Org:
    def __init__(self, cfg):
        self.name = cfg["name"]
        self.url = cfg["url"].rstrip("/")
        self.cfg = cfg
        self._pat = None
        self.me = None
        self.vsrm = self.url.replace("://dev.azure.com", "://vsrm.dev.azure.com")

    def pat(self):
        if self._pat is None:
            if self.cfg.get("secret"):
                self._pat = secrets.get(self.cfg["id"], self.cfg["secret"])
            elif self.cfg.get("pat"):  # só em teste de conexão, antes de salvar
                self._pat = self.cfg["pat"]
            elif self.cfg.get("patCommand"):
                self._pat = subprocess.run(self.cfg["patCommand"], shell=True, capture_output=True,
                                           text=True, check=True).stdout.strip()
            if not self._pat:
                raise RuntimeError("PAT não configurado (config.json)")
        return self._pat

    def req(self, method, path, body=None, raw=False):
        url = path if path.startswith("http") else f"{self.url}/{path.lstrip('/')}"
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(url, data=data, method=method)
        r.add_header("Authorization", "Basic " + base64.b64encode(f":{self.pat()}".encode()).decode())
        r.add_header("Accept", "application/json")
        if data is not None:
            r.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                # PAT inválido/expirado: o Azure responde 203 com a página HTML de login, não 401.
                if resp.status == 203 or (not raw and "json" not in resp.headers.get("Content-Type", "")):
                    raise RuntimeError("PAT inválido ou expirado (Azure devolveu página de login)")
                data = resp.read(2_000_000) if raw else resp.read()  # limite só para texto (logs); JSON vem inteiro
                if raw:
                    return data.decode(errors="replace")
                return json.loads(data) if data else None
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:300]
            raise RuntimeError(f"HTTP {e.code} em {method} {url}: {msg}") from None
        except OSError as e:
            if is_network_error(e):
                raise OfflineError(e) from None
            raise

    def identity(self):
        if self.me is None:
            u = self.req("GET", "_apis/connectionData")["authenticatedUser"]
            self.me = {"id": u["id"], "name": u.get("providerDisplayName", ""),
                       "email": (u.get("properties", {}).get("Account") or {}).get("$value", "")}
        return self.me

    def projects(self):
        return self.req("GET", f"_apis/projects?$top=500&{API}")["value"]

    def _shape(self, p, pr):
        creator = pr.get("createdBy", {})
        repo = pr["repository"]
        proj = urllib.parse.quote(p["name"])
        reviewers = [{"name": rv.get("displayName", ""), "vote": rv.get("vote", 0),
                      "required": rv.get("isRequired", False), "id": rv.get("id")}
                     for rv in pr.get("reviewers", [])]
        return {
            "key": f"{self.name}|{pr['pullRequestId']}",
            "provider": "azure",
            "org": self.name,
            "project": p["name"],
            "projectId": p["id"],
            "repo": repo["name"],
            "repoId": repo["id"],
            "prId": pr["pullRequestId"],
            "title": pr["title"],
            "description": (pr.get("description") or "")[:1500],
            "creatorName": creator.get("displayName", ""),
            "creatorUnique": creator.get("uniqueName", ""),
            "creatorId": creator.get("id"),
            "source": pr["sourceRefName"].removeprefix("refs/heads/"),
            "target": pr["targetRefName"].removeprefix("refs/heads/"),
            "isDraft": pr.get("isDraft", False),
            "created": pr.get("creationDate"),
            "closed": pr.get("closedDate"),
            "mergeStatus": pr.get("mergeStatus"),
            "commit": (pr.get("lastMergeSourceCommit") or {}).get("commitId"),
            "autoComplete": bool(pr.get("autoCompleteSetBy")),
            "reviewers": reviewers,
            "url": f"{self.url}/{proj}/_git/{urllib.parse.quote(repo['name'])}/pullrequest/{pr['pullRequestId']}",
        }

    def fetch_prs(self):
        me = self.identity()
        prs, mine = [], []
        for p in self.projects():
            proj = urllib.parse.quote(p["name"])
            data = self.req("GET", f"{proj}/_apis/git/pullrequests?searchCriteria.status=active&$top=500&{API}")
            for raw in data["value"]:
                pr = self._shape(p, raw)
                pr["myVote"] = next((rv["vote"] for rv in pr["reviewers"] if rv["id"] == me["id"]), 0)
                pr["approvals"] = sum(1 for rv in pr["reviewers"] if rv["vote"] >= 5)
                if pr["creatorId"] == me["id"]:
                    mine.append(pr)  # as minhas vão para "Minhas PRs", inclusive rascunhos
                elif not pr["isDraft"]:
                    prs.append(pr)
        with ThreadPoolExecutor(8) as ex:
            for pr, pol in zip(prs + mine, ex.map(self.policies, prs + mine)):
                pr["policies"] = pol
                pr["build"] = build_status(pol)
        for pr in mine:
            pr["blockers"] = my_pr_blockers(pr)
        return prs, mine

    def policies(self, pr):
        artifact = urllib.parse.quote(f"vstfs:///CodeReview/CodeReviewId/{pr['projectId']}/{pr['prId']}", safe="")
        try:
            data = self.req("GET", f"{urllib.parse.quote(pr['project'])}/_apis/policy/evaluations"
                                   f"?artifactId={artifact}&api-version=7.0-preview.1")
        except Exception:  # noqa: BLE001 — sem permissão de policy, só não mostra
            return []
        out, seen = [], set()
        for ev in data.get("value", []):
            cfg = ev.get("configuration", {})
            if not cfg.get("isEnabled", True):
                continue
            name = (cfg.get("settings") or {}).get("displayName") or cfg.get("type", {}).get("displayName", "?")
            if (name, ev.get("status")) in seen:
                continue  # mesma policy configurada em mais de um escopo
            seen.add((name, ev.get("status")))
            out.append({
                "name": name,
                "type": cfg.get("type", {}).get("displayName", ""),
                "status": ev.get("status"),
                "blocking": cfg.get("isBlocking", False),
            })
        return out

    def fetch_completed(self, days):
        since = now() - timedelta(days=days)
        out = []
        for p in self.projects():
            proj = urllib.parse.quote(p["name"])
            # o Azure devolve no máximo 1000 por página: pagina até sair da janela pedida (mais novas primeiro)
            for page in range(20):
                batch = self.req("GET", f"{proj}/_apis/git/pullrequests?searchCriteria.status=completed"
                                        f"&$top=500&$skip={page * 500}&{API}")["value"]
                recent = [raw for raw in batch if (parse_dt(raw.get("closedDate")) or since) >= since]
                out.extend(self._shape(p, raw) for raw in recent)
                if len(batch) < 500 or not recent:
                    break
        return out

    # ------------------------------------------------------------ releases / pipelines
    # ------------------------------------------------------------ builds
    def fetch_builds(self):
        out = []
        for p in self.projects():
            proj = urllib.parse.quote(p["name"])
            for b in self.req("GET", f"{proj}/_apis/build/builds?$top=80&queryOrder=queueTimeDescending&{API}")["value"]:
                ti = b.get("triggerInfo") or {}
                branch = b.get("sourceBranch") or ""
                msg = ti.get("ci.message") or ti.get("pr.title") or ""
                pr_ref = re.match(r"refs/pull/(\d+)/", branch)
                merged = re.search(r"Merge pull request (\d+)", msg)
                pr_number = ti.get("pr.number") or (pr_ref and pr_ref.group(1)) or (merged and merged.group(1))
                out.append({
                    "key": f"{self.name}|{b['id']}", "provider": "azure", "org": self.name, "project": p["name"], "id": b["id"],
                    "number": b.get("buildNumber"), "pipeline": b["definition"]["name"], "pipelineId": b["definition"]["id"],
                    "folder": (b["definition"].get("path") or "\\").strip("\\"), "sourceBranch": branch,
                    "branch": branch.removeprefix("refs/heads/"), "sourceVersion": b.get("sourceVersion"),
                    "status": b.get("status"), "result": b.get("result"), "reason": b.get("reason"),
                    "requestedFor": (b.get("requestedFor") or {}).get("displayName", ""),
                    "requestedForId": (b.get("requestedFor") or {}).get("id"),
                    "queued": b.get("queueTime"), "started": b.get("startTime"), "finished": b.get("finishTime"),
                    "message": msg.split("\n")[0][:200], "prNumber": int(pr_number) if pr_number else None,
                    "repo": (b.get("repository") or {}).get("name"),
                    "url": f"{self.url}/{proj}/_build/results?buildId={b['id']}",
                })
        return out

    def build_detail(self, project, build_id):
        proj = urllib.parse.quote(project)
        records = (self.req("GET", f"{proj}/_apis/build/builds/{build_id}/timeline?{API}") or {}).get("records") or []
        stages = sorted(({"name": r["name"], "state": r.get("state"), "result": r.get("result"), "order": r.get("order") or 0}
                         for r in records if r["type"] == "Stage"), key=lambda x: x["order"])
        failed = []
        for r in records:
            if r["type"] not in ("Task", "Job", "Checkpoint") or r.get("result") not in ("failed", "canceled", "abandoned"):
                continue
            issues = [{"type": i.get("type"), "message": (i.get("message") or "")[:600]} for i in (r.get("issues") or [])][:6]
            item = {"name": r["name"], "type": r["type"], "result": r["result"], "issues": issues, "logTail": None}
            if r["type"] == "Task" and r["result"] == "failed" and (r.get("log") or {}).get("url") and len(failed) < 3:
                try:
                    log = self.req("GET", r["log"]["url"])  # vem como {"count", "value": [linhas]}
                    lines = log.get("value", []) if isinstance(log, dict) else str(log).splitlines()
                    item["logTail"] = "\n".join(re.sub(r"^\S+Z ", "", ln) for ln in lines[-40:])
                except Exception:  # noqa: BLE001 — sem log, fica só a mensagem
                    pass
            failed.append(item)
        failed.sort(key=lambda f: f["type"] != "Task")
        return {"stages": stages, "failed": failed[:8]}

    def build_phase(self, project, build_id):
        """O que um build "em andamento" está fazendo de verdade, pela timeline: falhando (uma etapa já falhou e o resto
        ainda roda ou vai ser pulado), esperando aprovação/verificação, esperando agente, ou a etapa/job atual."""
        proj = urllib.parse.quote(project)
        records = (self.req("GET", f"{proj}/_apis/build/builds/{build_id}/timeline?{API}") or {}).get("records") or []
        return phase_from_records(records)

    def build_action(self, b, action):
        proj = urllib.parse.quote(b["project"])
        if action == "retry":      # reexecuta só os jobs que falharam, no mesmo run
            self.req("PATCH", f"{proj}/_apis/build/builds/{b['id']}?retry=true&{API}", {})
        elif action == "rerun":    # run novo do mesmo commit
            self.req("POST", f"{proj}/_apis/build/builds?{API}",
                     {"definition": {"id": b["pipelineId"]}, "sourceBranch": b["sourceBranch"], "sourceVersion": b["sourceVersion"]})
        elif action == "cancel":
            self.req("PATCH", f"{proj}/_apis/build/builds/{b['id']}?{API}", {"status": "cancelling"})
        else:
            raise ValueError("ação inválida")

    def build_info(self, project, build_id):
        ck = (self.name, int(build_id))
        if ck not in build_cache:
            b = self.req("GET", f"{urllib.parse.quote(project)}/_apis/build/builds/{build_id}?{API}")
            msg = (b.get("triggerInfo") or {}).get("ci.message")
            if not msg and b.get("sourceVersion") and (b.get("repository") or {}).get("type") == "TfsGit":
                try:
                    msg = self.req("GET", f"{urllib.parse.quote(project)}/_apis/git/repositories/{b['repository']['id']}"
                                          f"/commits/{b['sourceVersion']}?{API}").get("comment")
                except Exception:  # noqa: BLE001 — mensagem é só contexto
                    msg = None
            m = re.search(r"Merge pull request (\d+)", msg or "")
            build_cache[ck] = {
                "buildId": b["id"], "buildNumber": b.get("buildNumber"), "pipeline": b["definition"]["name"],
                "pipelineId": b["definition"]["id"], "branch": (b.get("sourceBranch") or "").removeprefix("refs/heads/"),
                "message": (msg or "").split("\n")[0][:200], "prNumber": int(m.group(1)) if m else None,
                "requestedFor": (b.get("requestedFor") or {}).get("displayName", ""), "queued": b.get("queueTime"),
                "repo": (b.get("repository") or {}).get("name"),
                "url": f"{self.url}/{urllib.parse.quote(project)}/_build/results?buildId={b['id']}",
            }
        return build_cache[ck]

    def fetch_deploys(self):
        me = self.identity()
        items, releases = [], []
        for p in self.projects():
            proj = urllib.parse.quote(p["name"])
            # 1) Release clássica esperando aprovação (pre/post deploy). Junta as minhas (inclui grupos) com as demais.
            mine = self.req("GET", f"{self.vsrm}/{proj}/_apis/release/approvals?statusFilter=pending&includeMyGroupApprovals=true"
                                   f"&assignedToFilter={urllib.parse.quote(me['email'] or me['id'])}&{API}")["value"]
            mine_ids = {a["id"] for a in mine}
            pending = {a["id"]: a for a in self.req("GET", f"{self.vsrm}/{proj}/_apis/release/approvals?statusFilter=pending&{API}")["value"]}
            pending.update({a["id"]: a for a in mine})
            rel_cache = {}
            for a in pending.values():
                rid = a["release"]["id"]
                if rid not in rel_cache:
                    rel_cache[rid] = self.req("GET", f"{self.vsrm}/{proj}/_apis/release/releases/{rid}?{API}")
                rel = rel_cache[rid]
                art = next((x for x in rel.get("artifacts", []) if x.get("isPrimary")), (rel.get("artifacts") or [{}])[0])
                ref = art.get("definitionReference", {})
                build = {}
                if ref.get("version", {}).get("id") and art.get("type") == "Build":
                    try:
                        build = self.build_info(p["name"], ref["version"]["id"])
                    except Exception:  # noqa: BLE001
                        build = {}
                env = a["releaseEnvironment"]
                items.append({
                    "kind": "release", "provider": "azure", "key": f"{self.name}|rel:{a['id']}", "org": self.name, "project": p["name"],
                    "approvalId": a["id"], "approvalType": a.get("approvalType"), "releaseId": rid, "releaseName": rel.get("name"),
                    "envId": env["id"],
                    "title": a["releaseDefinition"]["name"], "pipeline": a["releaseDefinition"]["name"], "stage": env["name"],
                    "branch": (ref.get("branch", {}).get("name") or build.get("branch") or "").removeprefix("refs/heads/"),
                    "version": ref.get("version", {}).get("name"), "buildId": build.get("buildId"),
                    "message": build.get("message"), "prNumber": build.get("prNumber"), "repo": build.get("repo"),
                    "requestedFor": build.get("requestedFor") or (rel.get("createdBy") or {}).get("displayName", ""),
                    "approver": (a.get("approver") or {}).get("displayName", ""), "mine": a["id"] in mine_ids,
                    "created": a.get("createdOn"), "resources": [],
                    "url": f"{self.url}/{proj}/_releaseProgress?_a=release-environment-logs&releaseId={rid}&environmentId={env['id']}",
                })
            # Um estágio com vários aprovadores gera uma aprovação por pessoa: fica uma linha, a minha quando houver.
            by_env = {}
            for it in [x for x in items if x["kind"] == "release" and x["project"] == p["name"]]:
                k = (it["releaseId"], it["envId"], it["approvalType"])
                if k not in by_env or (it["mine"] and not by_env[k]["mine"]):
                    by_env[k] = it
            others = [x["approver"] for x in items if x["kind"] == "release" and x["project"] == p["name"]]
            items = [x for x in items if x["kind"] != "release" or x["project"] != p["name"]] + list(by_env.values())
            for it in by_env.values():
                it["otherApprovers"] = sorted({a for a in others if a and a != it["approver"]})
            # 2) Aprovações de ambiente em pipeline YAML.
            try:
                yaml_appr = self.req("GET", f"{proj}/_apis/pipelines/approvals?state=pending&$expand=steps&{API_PREVIEW}")["value"]
            except Exception:  # noqa: BLE001 — recurso ausente em orgs antigas
                yaml_appr = []
            for a in yaml_appr:
                owner = (a.get("pipeline") or {}).get("owner") or {}
                build = self.build_info(p["name"], owner["id"]) if owner.get("id") else {}
                mine_step = any((st.get("assignedApprover") or {}).get("id") == me["id"] for st in a.get("steps", []))
                items.append({
                    "kind": "approval", "provider": "azure", "key": f"{self.name}|appr:{a['id']}", "org": self.name, "project": p["name"],
                    "approvalId": a["id"], "title": build.get("pipeline") or (a.get("pipeline") or {}).get("name", "?"),
                    "pipeline": build.get("pipeline") or (a.get("pipeline") or {}).get("name", "?"),
                    "stage": a.get("instructions") or "", "branch": build.get("branch"), "version": build.get("buildNumber"),
                    "buildId": build.get("buildId"), "pipelineId": build.get("pipelineId"), "message": build.get("message"),
                    "prNumber": build.get("prNumber"), "repo": build.get("repo"), "requestedFor": build.get("requestedFor"),
                    "mine": mine_step, "created": a.get("createdOn"), "resources": [], "url": build.get("url", self.url),
                })
            # 3) Runs travados pedindo permissão para usar recurso (grupo de variáveis, service connection, ambiente…).
            since = (now() - timedelta(days=30)).isoformat()
            runs = self.req("GET", f"{proj}/_apis/build/builds?statusFilter=notStarted,inProgress&$top=100&{API}")["value"]
            for b in (x for x in runs if (x.get("queueTime") or "") >= since[:19]):
                try:
                    timeline = self.req("GET", f"{proj}/_apis/build/builds/{b['id']}/timeline?{API}") or {}
                except Exception:  # noqa: BLE001
                    continue
                records = timeline.get("records") or []
                for cp in (r for r in records if r["type"] == "Checkpoint" and r["state"] == "inProgress"):
                    try:
                        suite = self.req("GET", f"{proj}/_apis/pipelines/checks/runs/{cp['id']}?$expand=1&{API_PREVIEW}")
                    except Exception:  # noqa: BLE001
                        continue
                    res = [c["checkConfigurationRef"]["resource"] for c in suite.get("checkRuns", [])
                           if c.get("status") == "running" and c["checkConfigurationRef"]["type"]["name"] == "Authorization"]
                    if not res:
                        continue
                    node = ((suite.get("context") or {}).get("GraphNode") or {}).get("Name")
                    stage = next((r["name"] for r in records if r["type"] == "Stage" and r.get("identifier") == node), node or "")
                    build = self.build_info(p["name"], b["id"])
                    items.append({
                        "kind": "permission", "provider": "azure", "key": f"{self.name}|perm:{b['id']}:{cp['id'][:8]}", "org": self.name,
                        "project": p["name"], "title": build["pipeline"], "pipeline": build["pipeline"],
                        "pipelineId": build["pipelineId"], "stage": stage, "branch": build["branch"],
                        "version": build["buildNumber"], "buildId": b["id"], "message": build["message"],
                        "prNumber": build["prNumber"], "repo": build["repo"], "requestedFor": build["requestedFor"],
                        "mine": True, "created": cp.get("startTime") or b.get("queueTime"),
                        "resources": [{"type": r["type"], "id": str(r["id"]), "name": r.get("name") or str(r["id"])} for r in res],
                        "url": build["url"],
                    })
            # Releases recentes, para acompanhar o que subiu.
            for r in self.req("GET", f"{self.vsrm}/{proj}/_apis/release/releases?$top=40&$expand=environments,artifacts&{API}")["value"]:
                art = next((x for x in r.get("artifacts", []) if x.get("isPrimary")), (r.get("artifacts") or [{}])[0])
                ref = art.get("definitionReference", {})
                releases.append({
                    "provider": "azure", "org": self.name, "id": r["id"], "name": r["name"], "pipeline": r["releaseDefinition"]["name"],
                    "created": r.get("createdOn"), "createdBy": (r.get("createdBy") or {}).get("displayName", ""),
                    "branch": (ref.get("branch", {}).get("name") or "").removeprefix("refs/heads/"),
                    "version": ref.get("version", {}).get("name"),
                    "envs": [{"name": e["name"], "status": e["status"]} for e in r.get("environments", [])],
                    "url": f"{self.url}/{proj}/_releaseProgress?_a=release-pipeline-progress&releaseId={r['id']}",
                })
        for it in items:
            if it.get("prNumber") and it.get("repo"):
                it["prUrl"] = f"{self.url}/{urllib.parse.quote(it['project'])}/_git/{urllib.parse.quote(it['repo'])}/pullrequest/{it['prNumber']}"
        return items, releases

    def decide_deploy(self, item, approve, comment=""):
        proj = urllib.parse.quote(item["project"])
        if item["kind"] == "release":
            self.req("PATCH", f"{self.vsrm}/{proj}/_apis/release/approvals/{item['approvalId']}?{API}",
                     {"status": "approved" if approve else "rejected", "comments": comment})
        elif item["kind"] == "approval":
            self.req("PATCH", f"{proj}/_apis/pipelines/approvals?{API_PREVIEW}",
                     [{"approvalId": item["approvalId"], "status": "approved" if approve else "rejected", "comment": comment}])
        elif item["kind"] == "permission":
            if approve:
                for r in item["resources"]:
                    self.req("PATCH", f"{proj}/_apis/pipelines/pipelinePermissions/{r['type']}/{urllib.parse.quote(r['id'], safe='')}?{API_PREVIEW}",
                             {"pipelines": [{"id": item["pipelineId"], "authorized": True}]})
            else:
                self.req("PATCH", f"{proj}/_apis/build/builds/{item['buildId']}?{API}", {"status": "cancelling"})

    def pr_approved_by_me(self, pr_id):
        pr = self.req("GET", f"_apis/git/pullrequests/{pr_id}?{API}")
        me = self.identity()
        return any(rv.get("id") == me["id"] and rv.get("vote", 0) >= 5 for rv in pr.get("reviewers", []))

    # ------------------------------------------------------------ repositórios (catálogos), PR nova, work items
    def list_repos(self, project=None):
        out = []
        for p in self.projects():
            if project and p["name"].lower() != project.lower():
                continue
            proj = urllib.parse.quote(p["name"])
            for r in self.req("GET", f"{proj}/_apis/git/repositories?{API}")["value"]:
                if r.get("isDisabled"):
                    continue
                out.append({
                    "key": f"azure:{self.name}/{p['name']}/{r['name']}", "provider": "azure", "account": self.name,
                    "owner": f"{self.name}/{p['name']}", "name": r["name"], "fullName": f"{p['name']}/{r['name']}",
                    "id": r["id"], "project": p["name"], "cloneUrl": r.get("remoteUrl"), "sshUrl": r.get("sshUrl"),
                    "webUrl": r.get("webUrl"), "defaultBranch": (r.get("defaultBranch") or "").removeprefix("refs/heads/"),
                    "private": True, "description": "", "size": r.get("size"), "updated": None,
                })
        return out

    def find_repo(self, project, name):
        return self.req("GET", f"{urllib.parse.quote(project)}/_apis/git/repositories/{urllib.parse.quote(name)}?{API}")

    def create_pr(self, project, repo_name, source, target, title, description="", draft=False):
        repo = self.find_repo(project, repo_name)
        pr = self.req("POST", f"{urllib.parse.quote(project)}/_apis/git/repositories/{repo['id']}/pullrequests?{API}", {
            "sourceRefName": f"refs/heads/{source}", "targetRefName": f"refs/heads/{target}",
            "title": title, "description": description, "isDraft": bool(draft)})
        return {"id": pr["pullRequestId"],
                "url": f"{self.url}/{urllib.parse.quote(project)}/_git/{urllib.parse.quote(repo_name)}/pullrequest/{pr['pullRequestId']}"}

    def _done_states(self, proj):
        """Estados que encerram o item (categoria Completed/Removed) de cada tipo do projeto — processos personalizados
        têm nomes próprios ("Code Review (Done)", "Concluído"…), então a lista fixa deixava itens fechados ou abertos errados."""
        try:
            types = self.req("GET", f"{proj}/_apis/wit/workitemtypes?{API}").get("value") or []
        except Exception:  # noqa: BLE001 — sem a lista: os nomes padrão
            return {"Closed", "Done", "Removed"}
        out = {s["name"] for t in types for s in (t.get("states") or []) if s.get("category") in ("Completed", "Removed")}
        return out or {"Closed", "Done", "Removed"}

    def _wiql_ids(self, proj, where, top=1000):
        q = {"query": "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project" + (f" AND {where}" if where else "")
                      + " ORDER BY [System.ChangedDate] DESC"}
        return [w["id"] for w in self.req("POST", f"{proj}/_apis/wit/wiql?$top={int(top)}&{API}", q).get("workItems", [])]

    # escopos da lista: os meus (a leitura de fundo) e "all" — todos os itens dos projetos (sob demanda, na tela)
    WI_SCOPES = {"assigned": "[System.AssignedTo] = @Me", "created": "[System.CreatedBy] = @Me",
                 "mentioned": "[System.Id] IN (@RecentMentions)", "all": ""}

    def fetch_work_items(self, scopes=("assigned", "created", "mentioned"), state="open", limit=1000):
        """Itens de trabalho (Boards) por escopo — atribuídos a mim, criados por mim, que me mencionam ou todos os dos
        projetos — e estado (open, closed, all). Cada item diz por que veio (`reasons`: os meus escopos que ele
        cumpre). Sem o escopo Work Items, só não aparece nada. O workitems aceita no máximo 200 ids por chamada."""
        out, seen = [], set()
        fields = "System.Id,System.Title,System.State,System.WorkItemType,System.ChangedDate,System.CreatedDate,System.CreatedBy," \
                 "System.AssignedTo,System.Tags,System.TeamProject,System.CommentCount"
        # com "todos", os meus escopos também são lidos (só ids, barato): o item mostra se é seu e o filtro funciona
        wanted = list(dict.fromkeys(list(scopes) + (["assigned", "created", "mentioned"] if "all" in scopes else [])))
        for p in self.projects():
            proj = urllib.parse.quote(p["name"])
            cond = ""
            if state in ("open", "closed"):
                done = "(" + ", ".join("'" + x.replace("'", "''") + "'" for x in sorted(self._done_states(proj))) + ")"
                cond = f"[System.State] {'NOT IN' if state == 'open' else 'IN'} {done}"
            reasons = {}
            for scope in wanted:
                where = " AND ".join(x for x in (self.WI_SCOPES[scope], cond) if x)
                try:
                    ids = self._wiql_ids(proj, where, limit)
                except RuntimeError:
                    if scope == "mentioned":   # @RecentMentions não existe no Azure DevOps Server antigo
                        continue
                    raise
                for i in ids:
                    r = reasons.setdefault(i, [])
                    if scope != "all":
                        r.append(scope)
            ids = list(reasons)
            for k in range(0, len(ids), 200):
                chunk = ids[k:k + 200]
                items = self.req("GET", f"_apis/wit/workitems?ids={','.join(map(str, chunk))}&fields={fields}&errorPolicy=omit&{API}")["value"]
                for w in items:
                    if not w or w["id"] in seen:
                        continue
                    seen.add(w["id"])
                    f = w.get("fields") or {}
                    team = f.get("System.TeamProject") or p["name"]
                    rs = reasons.get(w["id"]) or []
                    out.append({
                        "key": f"{self.name}|wi:{w['id']}", "provider": "azure", "org": self.name, "repo": team,
                        "number": w["id"], "title": f.get("System.Title"), "state": f.get("System.State"),
                        "type": f.get("System.WorkItemType"), "updated": f.get("System.ChangedDate"), "created": f.get("System.CreatedDate"),
                        "author": (f.get("System.CreatedBy") or {}).get("displayName", ""),
                        "assignees": [{"login": (f.get("System.AssignedTo") or {}).get("displayName", ""), "avatar": None,
                                       "email": (f.get("System.AssignedTo") or {}).get("uniqueName", "")}] if f.get("System.AssignedTo") else [],
                        "labels": [{"name": t.strip(), "color": None} for t in (f.get("System.Tags") or "").split(";") if t.strip()],
                        "reason": rs[0] if rs else "other", "reasons": rs, "comments": f.get("System.CommentCount"),
                        "url": f"{self.url}/{urllib.parse.quote(team)}/_workitems/edit/{w['id']}",
                    })
        return out

    def work_item(self, wid):
        """Um work item inteiro, para ler no app: campos, descrição/critérios (HTML), comentários e o que está ligado."""
        w = self.req("GET", f"_apis/wit/workitems/{int(wid)}?$expand=relations&{API}")
        f = w.get("fields") or {}
        proj = f.get("System.TeamProject") or ""
        comments = []
        try:
            r = self.req("GET", f"{urllib.parse.quote(proj)}/_apis/wit/workItems/{int(wid)}/comments?$top=200&order=asc&api-version=7.0-preview.3")
            comments = [{"author": (c.get("createdBy") or {}).get("displayName", ""), "created": c.get("createdDate"), "html": c.get("text") or ""}
                        for c in r.get("comments") or []]
        except Exception:  # noqa: BLE001 — sem comentários (permissão/servidor antigo): mostra o resto
            pass
        person = lambda v: (v or {}).get("displayName", "") if isinstance(v, dict) else (v or "")   # noqa: E731
        html = [(label, f.get(k)) for label, k in (("Descrição", "System.Description"), ("Passos para reproduzir", "Microsoft.VSTS.TCM.ReproSteps"),
                                                    ("Critérios de aceite", "Microsoft.VSTS.Common.AcceptanceCriteria"),
                                                    ("Informações do sistema", "Microsoft.VSTS.TCM.SystemInfo")) if f.get(k)]
        rels = []
        for r in w.get("relations") or []:
            name = (r.get("attributes") or {}).get("name") or r.get("rel")
            if r.get("rel") == "AttachedFile":
                rels.append({"kind": "file", "name": (r.get("attributes") or {}).get("name") or "anexo", "url": r.get("url")})
            elif "workitems/" in (r.get("url") or "").lower():
                rels.append({"kind": "item", "name": name, "id": int(r["url"].rstrip("/").rsplit("/", 1)[-1])})
            elif str(r.get("url") or "").startswith("http"):   # vstfs:/// (PR, commit) não abre no navegador
                rels.append({"kind": "link", "name": name, "url": r.get("url")})
        return {"provider": "azure", "number": w["id"], "title": f.get("System.Title"), "state": f.get("System.State"),
                "type": f.get("System.WorkItemType"), "project": proj, "author": person(f.get("System.CreatedBy")),
                "assignee": person(f.get("System.AssignedTo")), "created": f.get("System.CreatedDate"), "updated": f.get("System.ChangedDate"),
                "iteration": f.get("System.IterationPath"), "area": f.get("System.AreaPath"), "priority": f.get("Microsoft.VSTS.Common.Priority"),
                "effort": f.get("Microsoft.VSTS.Scheduling.StoryPoints") or f.get("Microsoft.VSTS.Scheduling.Effort") or f.get("Microsoft.VSTS.Scheduling.RemainingWork"),
                "labels": [t.strip() for t in (f.get("System.Tags") or "").split(";") if t.strip()],
                "sections": [{"label": label, "html": v} for label, v in html], "comments": comments, "relations": rels,
                "url": f"{self.url}/{urllib.parse.quote(proj)}/_workitems/edit/{w['id']}"}

    def comment_work_item(self, wid, text):
        w = self.req("GET", f"_apis/wit/workitems/{int(wid)}?fields=System.TeamProject&{API}")
        proj = urllib.parse.quote((w.get("fields") or {}).get("System.TeamProject") or "")
        self.req("POST", f"{proj}/_apis/wit/workItems/{int(wid)}/comments?api-version=7.0-preview.3", {"text": text})

    def comment(self, project, repo_id, pr_id, text):
        """Comentário geral na PR (thread nova, status ativo)."""
        proj = urllib.parse.quote(project)
        self.req("POST", f"{proj}/_apis/git/repositories/{repo_id}/pullRequests/{pr_id}/threads?{API}",
                 {"comments": [{"parentCommentId": 0, "content": text, "commentType": 1}], "status": 1})

    def vote(self, project, repo_id, pr_id, vote):
        me = self.identity()
        proj = urllib.parse.quote(project)
        self.req("PUT", f"{proj}/_apis/git/repositories/{repo_id}/pullrequests/{pr_id}/reviewers/{me['id']}?{API}",
                 {"vote": vote})


def my_pr_blockers(pr):
    """O que trava a MINHA PR — cada item vira um aviso (uma vez por commit)."""
    out = []
    if pr.get("mergeStatus") == "conflicts":
        out.append(("conflict", "conflito de merge"))
    if pr.get("build") == "failed":
        out.append(("build", "build falhou"))
    for rv in pr["reviewers"]:
        if rv["vote"] == -10:
            out.append(("rejected", f"recusada por {rv['name']}"))
        elif rv["vote"] == -5:
            out.append(("waiting", f"{rv['name']} aguarda você"))
    return [{"code": c, "label": l} for c, l in out]


def build_status(policies):
    builds = [p["status"] for p in policies if p["type"] == "Build"]
    if not builds:
        return "none"
    if "rejected" in builds or "broken" in builds:
        return "failed"
    if any(s in ("running", "queued") for s in builds):
        return "running"
    if all(s in ("approved", "notApplicable") for s in builds):
        return "ok"
    return "pending"


def normalize_org_url(url):
    url = (url or "").strip().rstrip("/")
    if url and "://" not in url:
        url = "https://dev.azure.com/" + url  # aceita só o nome da organização
    return url


# Cada teste de ESCRITA manda um pedido inválido de propósito para um recurso que não existe (ou uma lista vazia):
# com o escopo certo o Azure autoriza e recusa o pedido (400/404) — nada é alterado; sem o escopo, responde 401/403.
# Medido em 2026-10-10 nas duas organizações: POST pullrequests {} → 400, PATCH builds/0 → 404,
# PATCH approvals/0 → 400 (VS402960) e PATCH pipelinePermissions com "pipelines": [] → 200 sem alterar nada
# (GET antes e depois iguais). Não medido: o texto exato do Azure para PAT sem o escopo — a tela mostra o que vier.
SCOPE_HINT = {
    "code-read": "Code → Read", "code-write": "Code → Read & write", "build-read": "Build → Read",
    "build-exec": "Build → Read & execute", "release-read": "Release → Read",
    "release-manage": "Release → Read, write, execute & manage", "vg": "Variable Groups → Read, create & manage",
}


def test_org(body):
    """Testa uma organização (nova ou salva) sem gravar nada no Azure nem no app. PAT vazio = usa o já salvo."""
    url = normalize_org_url(body.get("url"))
    cfg = {"id": "teste", "name": body.get("name") or "teste", "url": url, "pat": (body.get("pat") or "").strip()}
    if not cfg["pat"]:
        saved = next((o for o in load_json(CONFIG_FILE, {}).get("orgs", []) if o["name"] == body.get("originalName")), None)
        if not saved:
            raise ValueError("Informe o PAT")
        cfg = {**saved, "url": url, "name": cfg["name"]}
    org = Org(cfg)
    checks, ctx = [], {}

    def add(group, label, status, detail, scope=None):
        checks.append({"group": group, "label": label, "status": status, "detail": detail,
                       "fix": f"Inclua o escopo {SCOPE_HINT[scope]} no PAT" if status == "fail" and scope else None})

    def read(group, label, scope, fn):
        try:
            add(group, label, "ok", fn())
            return True
        except Exception as e:  # noqa: BLE001
            add(group, label, "fail", azure_message(e), scope)
            return False

    def write(group, label, scope, method, path, payload, ok_codes=(200, 400, 404, 409)):
        try:
            org.req(method, path, payload)
            add(group, label, "ok", "autorizado (teste sem efeito)")
        except Exception as e:  # noqa: BLE001
            code = http_code(e)
            if code in ok_codes:
                add(group, label, "ok", "autorizado (teste sem efeito)")
            elif code in (401, 403):
                add(group, label, "fail", azure_message(e), scope)
            else:
                add(group, label, "warn", azure_message(e))

    t0 = time.monotonic()
    if not read("Conta", "Conectar com o PAT", None, lambda: (lambda m: f"{m['name']}" + (f" · {m['email']}" if m["email"] and m["email"] != m["name"] else ""))(org.identity())):
        checks[-1]["fix"] = "Confira a organização/URL e se o PAT não expirou ou foi revogado"
        return {"ok": False, "verdict": "Não conecta", "checks": checks, "ms": int((time.monotonic() - t0) * 1000)}
    projects = []
    read("Conta", "Listar projetos", None, lambda: (projects.extend(org.projects()), f"{len(projects)}: " + ", ".join(p["name"] for p in projects[:4]))[1])
    if projects:
        proj = urllib.parse.quote(projects[0]["name"])
        if read("Pull requests", "Ler PRs", "code-read",
                lambda: f"{len(org.req('GET', f'{proj}/_apis/git/pullrequests?$top=100&{API}')['value'])} abertas em {projects[0]['name']}"):
            try:
                ctx["repo"] = org.req("GET", f"{proj}/_apis/git/repositories?{API}")["value"][0]["id"]
            except Exception:  # noqa: BLE001
                pass
        if ctx.get("repo"):
            write("Pull requests", "Votar (aprovar/recusar)", "code-write", "POST",
                  f"{proj}/_apis/git/repositories/{ctx['repo']}/pullrequests?{API}", {})
        read("Builds", "Ler builds", "build-read", lambda: f"{len(org.req('GET', f'{proj}/_apis/build/builds?$top=20&{API}')['value'])} recentes")
        write("Builds", "Tentar de novo / rodar / cancelar", "build-exec", "PATCH", f"{proj}/_apis/build/builds/0?{API}", {})
        read("Releases", "Ler releases e aprovações", "release-read",
             lambda: f"{len(org.req('GET', f'{org.vsrm}/{proj}/_apis/release/definitions?$top=200&{API}')['value'])} pipelines de release")
        write("Releases", "Aprovar / rejeitar release", "release-manage", "PATCH", f"{org.vsrm}/{proj}/_apis/release/approvals/0?{API}", {})
        try:
            vgs = org.req("GET", f"{proj}/_apis/distributedtask/variablegroups?$top=1&{API}")["value"]
        except Exception as e:  # noqa: BLE001
            vgs = None
            add("Permissões de pipeline", "Liberar recurso para pipeline", "fail" if http_code(e) in (401, 403) else "warn",
                azure_message(e), "vg")
        if vgs == []:
            add("Permissões de pipeline", "Liberar recurso para pipeline", "warn", "nenhum grupo de variáveis visível para testar")
        elif vgs:
            write("Permissões de pipeline", "Liberar recurso para pipeline", "vg", "PATCH",
                  f"{proj}/_apis/pipelines/pipelinePermissions/variablegroup/{vgs[0]['id']}?{API_PREVIEW}", {"pipelines": []},
                  ok_codes=(200,))
    fails = [c for c in checks if c["status"] == "fail"]
    verdict = "Pronto para tudo" if not fails and all(c["status"] == "ok" for c in checks) else \
        "Funciona com limitações" if not any(c["group"] == "Conta" for c in fails) else "Não conecta"
    return {"ok": not fails, "verdict": verdict, "checks": checks, "ms": int((time.monotonic() - t0) * 1000)}


def azure_message(e):
    """Só a mensagem do Azure, sem URL nem JSON — é o que aparece na tela."""
    text, code = str(e), http_code(e)
    m = re.search(r'"message":"(.*?)(?<!\\)"', text)
    if m:
        msg = m.group(1).encode().decode("unicode_escape", "ignore").replace("\r\n", " ")
    elif code == 401 or "PAT inválido" in text:
        msg = "o Azure recusou o PAT (inválido, expirado, revogado ou criado para outra organização)"
    elif code == 404:
        msg = "organização ou recurso não encontrado — confira a URL"
    elif "urlopen error" in text or "timed out" in text:
        msg = "sem resposta do Azure — confira a internet/VPN e a URL"
    else:
        msg = re.sub(r"https?://\S+", "", text)
    return (f"HTTP {code} — " if code else "") + msg.strip()[:220]


