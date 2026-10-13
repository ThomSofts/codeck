"""Quadro (kanban) editável: colunas e cartões seus, que a IA pode planejar e implementar.

kanban.json: {"columns": [{id, name, color, role}], "cards": [{id, title, description, column, order, priority, labels,
              groupId, projects: [repoId], primary: repoId, refs: [repoId], workItem, due, tasks: [{repoId, taskId, flow, at}],
              createdAt, updatedAt}], "autoMove": bool}
  · role da coluna: backlog | todo | doing | review | done (ou nenhum). Com autoMove, o cartão vai sozinho para a coluna
    "doing" quando a IA começa e para a "review" quando o agente termina.
  · projects: os projetos (repositórios locais) da tarefa; primary é onde a IA roda (os outros ganham um worktree na
    mesma branch); refs são projetos só de consulta (o agente enxerga, mas não mexe). groupId dá o contexto do grupo.
"""
import os
import threading
import uuid

from . import agents, git, terminals
from .core import DATA, load_json, now_iso, save_json

FILE = os.path.join(DATA, "kanban.json")
_lock = threading.Lock()
DEFAULT_COLUMNS = [
    {"id": "backlog", "name": "Backlog", "color": "#9AA4B2", "role": "backlog"},
    {"id": "todo", "name": "A fazer", "color": "#6F8CFF", "role": "todo"},
    {"id": "doing", "name": "Em andamento", "color": "#F5B84F", "role": "doing"},
    {"id": "review", "name": "Revisão", "color": "#B07CFF", "role": "review"},
    {"id": "done", "name": "Concluído", "color": "#3CCF91", "role": "done"},
]
PRIORITIES = ("low", "normal", "high", "urgent")


def _load():
    d = load_json(FILE, {})
    if not d.get("columns"):
        d["columns"] = [dict(c) for c in DEFAULT_COLUMNS]
    d.setdefault("cards", [])
    d.setdefault("autoMove", True)
    return d


def _save(d):
    save_json(FILE, d)


def _col(d, role):
    return next((c["id"] for c in d["columns"] if c.get("role") == role), None)


def _live(card, ws_tasks):
    """Estado ao vivo do cartão: a tarefa ligada mais recente e os agentes dela."""
    for link in reversed(card.get("tasks") or []):
        t = ws_tasks.get((link.get("repoId"), link.get("taskId")))
        if not t:
            continue
        terms = terminals.list_all(task=t["id"])
        states = [((agents.session_info(x["meta"].get("sid")) or {}).get("status")) for x in terms if x["kind"] == "agent"]
        status = "needs-you" if "needs-you" in states else "working" if any(s in ("working", "compacting", "starting") for s in states) \
            else "done" if "done" in states else ("idle" if states else "stopped")
        return {"repoId": link["repoId"], "taskId": t["id"], "title": t["title"], "branch": t["branch"], "status": status,
                "flow": link.get("flow"), "exists": os.path.isdir(t["path"]), "pr": t.get("pr"), "agents": len(states)}
    return None


def view():
    from . import workspace
    with _lock:
        d = _load()
        wsd = workspace._load()
        ws_tasks = {(rid, t["id"]): t for rid, p in wsd["projects"].items() for t in p.get("tasks", [])}
        changed = False
        doing, review = _col(d, "doing"), _col(d, "review")
        out = []
        for c in d["cards"]:
            live = _live(c, ws_tasks)
            # o agente terminou ou pede você: o cartão sai de "Em andamento" e vai para "Revisão"
            if d.get("autoMove") and live and doing and review and c["column"] == doing and live["status"] == "done" and not c.get("_held"):
                c["column"] = review
                c["updatedAt"] = now_iso()
                changed = True
            out.append({**{k: v for k, v in c.items() if not k.startswith("_")}, "live": live})
        if changed:
            _save(d)
        return {"columns": d["columns"], "cards": out, "autoMove": d.get("autoMove", True)}


def _clean_ids(xs):
    return [str(x) for x in (xs or []) if str(x).strip()][:30]


def save_card(body):
    with _lock:
        d = _load()
        cid = body.get("id") or uuid.uuid4().hex[:10]
        c = next((x for x in d["cards"] if x["id"] == cid), None)
        if not c:
            title = (body.get("title") or "").strip()
            if not title:
                raise ValueError("Dê um título ao cartão")
            col = body.get("column") if any(x["id"] == body.get("column") for x in d["columns"]) else (_col(d, "todo") or d["columns"][0]["id"])
            c = {"id": cid, "title": title, "description": "", "column": col, "order": max([x.get("order", 0) for x in d["cards"] if x["column"] == col] + [0]) + 1,
                 "priority": "normal", "labels": [], "groupId": None, "projects": [], "primary": None, "refs": [], "workItem": None,
                 "due": None, "tasks": [], "createdAt": now_iso()}
            d["cards"].append(c)
        if "title" in body and (body.get("title") or "").strip():
            c["title"] = body["title"].strip()[:200]
        if "description" in body:
            c["description"] = str(body.get("description") or "")[:20000]
        if "column" in body and any(x["id"] == body["column"] for x in d["columns"]):
            c["column"] = body["column"]
        if body.get("priority") in PRIORITIES:
            c["priority"] = body["priority"]
        if isinstance(body.get("labels"), list):
            c["labels"] = [str(x).strip()[:30] for x in body["labels"] if str(x).strip()][:12]
        if "groupId" in body:
            c["groupId"] = body.get("groupId") or None
        if isinstance(body.get("projects"), list):
            c["projects"] = list(dict.fromkeys(_clean_ids(body["projects"])))
        if isinstance(body.get("refs"), list):
            c["refs"] = [x for x in dict.fromkeys(_clean_ids(body["refs"])) if x not in c["projects"]]
        if "primary" in body:
            c["primary"] = body.get("primary") or None
        if c.get("primary") not in c["projects"]:
            c["primary"] = c["projects"][0] if c["projects"] else None
        if "workItem" in body:
            c["workItem"] = body.get("workItem") or None
        if "due" in body:
            c["due"] = body.get("due") or None
        c["updatedAt"] = now_iso()
        _save(d)
        return c


def delete_card(cid):
    with _lock:
        d = _load()
        d["cards"] = [c for c in d["cards"] if c["id"] != cid]
        _save(d)


def move(cid, column, index=None):
    """Move o cartão para a coluna (na posição `index`) e renumera a ordem da coluna."""
    with _lock:
        d = _load()
        c = next((x for x in d["cards"] if x["id"] == cid), None)
        if not c:
            raise LookupError("Cartão não encontrado")
        if not any(x["id"] == column for x in d["columns"]):
            raise ValueError("Coluna não existe")
        c["column"] = column
        if column == _col(d, "doing") and c.get("tasks"):
            c["_held"] = True   # posto à mão em "Em andamento": não volta sozinho para "Revisão" até a IA começar de novo
        else:
            c.pop("_held", None)
        others = sorted([x for x in d["cards"] if x["column"] == column and x["id"] != cid], key=lambda x: x.get("order", 0))
        idx = len(others) if index is None else max(0, min(int(index), len(others)))
        others.insert(idx, c)
        for i, x in enumerate(others):
            x["order"] = i + 1
        c["updatedAt"] = now_iso()
        _save(d)
        return c


def save_columns(body):
    with _lock:
        d = _load()
        cols = []
        for x in body.get("columns") or []:
            name = (x.get("name") or "").strip()
            if not name:
                continue
            cols.append({"id": x.get("id") or uuid.uuid4().hex[:8], "name": name[:40], "color": (x.get("color") or "#9AA4B2")[:20],
                         "role": x.get("role") if x.get("role") in ("backlog", "todo", "doing", "review", "done") else None})
        if not cols:
            raise ValueError("O quadro precisa de pelo menos uma coluna")
        ids = {c["id"] for c in cols}
        for c in d["cards"]:   # coluna apagada: os cartões dela vão para a primeira
            if c["column"] not in ids:
                c["column"] = cols[0]["id"]
        d["columns"] = cols
        if "autoMove" in body:
            d["autoMove"] = bool(body["autoMove"])
        _save(d)
        return {"columns": cols, "autoMove": d["autoMove"]}


def link_task(cid, repo_id, task_id, flow=None):
    """A IA começou o cartão: liga a tarefa (worktree + agente) e leva o cartão para "Em andamento"."""
    with _lock:
        d = _load()
        c = next((x for x in d["cards"] if x["id"] == cid), None)
        if not c:
            raise LookupError("Cartão não encontrado")
        c.setdefault("tasks", []).append({"repoId": repo_id, "taskId": task_id, "flow": flow, "at": now_iso()})
        doing = _col(d, "doing")
        if d.get("autoMove") and doing:
            c["column"] = doing
            c.pop("_held", None)
        c["updatedAt"] = now_iso()
        _save(d)
        return c


def context(cid):
    """Texto de contexto que acompanha o pedido à IA: o cartão, o grupo e os projetos (onde roda, quais mudam e quais
    são só de consulta), com as pastas — o agente sabe a que conjunto a tarefa pertence."""
    from . import workspace
    d = _load()
    c = next((x for x in d["cards"] if x["id"] == cid), None)
    if not c:
        raise LookupError("Cartão não encontrado")
    repos = {r["id"]: r for r in git.list_repos(with_status=False)}
    g = next((x for x in workspace._load()["groups"] if x["id"] == c.get("groupId")), None)
    lines = [f"Cartão do quadro: {c['title']}"]
    if c.get("labels"):
        lines.append("Etiquetas: " + ", ".join(c["labels"]))
    if c.get("priority") and c["priority"] != "normal":
        lines.append("Prioridade: " + {"low": "baixa", "high": "alta", "urgent": "urgente"}[c["priority"]])
    if c.get("workItem"):
        w = c["workItem"]
        lines.append(f"Item ligado: #{w.get('number')} {w.get('title') or ''} {w.get('url') or ''}".strip())
    if g:
        lines.append(f"\nGrupo de projetos: {g['name']}" + (f" — {g['description']}" if g.get("description") else ""))
        members = [repos[x] for x in g.get("repoIds") or [] if x in repos]
        if members:
            lines.append("Projetos do grupo: " + "; ".join(f"{r['name']} ({r['path']})" for r in members))
    if c.get("projects"):
        lines.append("\nProjetos desta tarefa:")
        for rid in c["projects"]:
            r = repos.get(rid)
            if r:
                lines.append(f"- {r['name']}: {r['path']}" + (" ← a IA roda aqui" if rid == c.get("primary") else " (também muda — worktree na mesma branch)"))
    refs = [repos[x] for x in c.get("refs") or [] if x in repos]
    if refs:
        lines.append("Projetos só para consulta (leia, não altere): " + "; ".join(f"{r['name']} ({r['path']})" for r in refs))
    return "\n".join(lines)
