"""Quadro (kanban) editável: colunas e cartões seus. A IA é uma automação opcional — planeja/implementa um cartão e,
com autoMove, move o cartão sozinha (sempre registrando o movimento no histórico do cartão).

kanban.json: {"columns": [{id, name, color, role}], "cards": [{id, title, description, column, order, priority, labels,
              groupId, projects: [repoId], primary: repoId, refs: [repoId], workItem, due, tasks: [{repoId, taskId, flow, at}],
              files: [{id, name, size, type, at}], history: [{at, from, to, by: "ia"|"você", why}], createdAt, updatedAt}],
              "autoMove": bool}
  · role da coluna: backlog | todo | doing | review | done (ou nenhum). Com autoMove, o cartão vai para "doing" quando a
    IA começa, para "review" quando o agente termina ou pede você, e volta para "doing" se o agente retoma (só se foi a
    IA que o levou para "review"). Os movimentos automáticos reagem à MUDANÇA de estado do agente (`_seen` guarda o
    último visto): pôr o cartão à mão em outra coluna não o faz pular de volta no próximo ciclo.
  · projects: os projetos (repositórios locais) da tarefa; primary é onde a IA roda (os outros ganham um worktree na
    mesma branch); refs são projetos só de consulta (o agente enxerga, mas não mexe). groupId dá o contexto do grupo.
  · anexos em <DATA>/kanban-files/<cardId>/<fileId>-<nome> — vão como caminho no contexto do pedido à IA.
"""
import base64
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid

from . import agents, git, terminals
from .core import DATA, load_json, now_iso, save_json

FILE = os.path.join(DATA, "kanban.json")
FILES_DIR = os.path.join(DATA, "kanban-files")
MAX_FILE = 25 * 1024 * 1024
MAX_FILES = 60
_lock = threading.Lock()
DEFAULT_COLUMNS = [
    {"id": "backlog", "name": "Backlog", "color": "#9AA4B2", "role": "backlog"},
    {"id": "todo", "name": "A fazer", "color": "#6F8CFF", "role": "todo"},
    {"id": "doing", "name": "Em andamento", "color": "#F5B84F", "role": "doing"},
    {"id": "review", "name": "Revisão", "color": "#B07CFF", "role": "review"},
    {"id": "done", "name": "Concluído", "color": "#3CCF91", "role": "done"},
]
PRIORITIES = ("low", "normal", "high", "urgent")
WORKING = ("working", "compacting", "starting")


def _load():
    d = load_json(FILE, {})
    if not d.get("columns"):
        d["columns"] = [dict(c) for c in DEFAULT_COLUMNS]
    d.setdefault("cards", [])
    d.setdefault("autoMove", True)
    for c in d["cards"]:
        c.pop("_held", None)   # versão antiga: trava escondida, trocada pelo histórico + mudança de estado
        c.setdefault("files", [])
        c.setdefault("history", [])
        c.setdefault("tasks", [])
    return d


def _save(d):
    save_json(FILE, d)


def _col(d, role):
    return next((c["id"] for c in d["columns"] if c.get("role") == role), None)


def _card(d, cid):
    c = next((x for x in d["cards"] if x["id"] == cid), None)
    if not c:
        raise LookupError("Cartão não encontrado")
    return c


def _record(c, frm, to, by, why=None):
    """Histórico de colunas do cartão: quem moveu (você ou a IA), de onde, para onde e por quê."""
    if frm == to:
        return
    c["history"] = (c.get("history") or [])[-39:] + [{"at": now_iso(), "from": frm, "to": to, "by": by, **({"why": why} if why else {})}]


def _put(d, c, column, index=None):
    """Põe o cartão na coluna (na posição `index`; None = no fim) e renumera a ordem dela."""
    c["column"] = column
    others = sorted([x for x in d["cards"] if x["column"] == column and x["id"] != c["id"]], key=lambda x: x.get("order", 0))
    idx = len(others) if index is None else max(0, min(int(index), len(others)))
    others.insert(idx, c)
    for i, x in enumerate(others):
        x["order"] = i + 1


def _live(card, ws_tasks):
    """Estado ao vivo do cartão pela tarefa ligada MAIS RECENTE e pelos agentes VIVOS dela. Terminal de agente que já
    saiu não conta como "trabalhando" (a sessão guarda o último status, que fica velho quando o processo morre)."""
    links = card.get("tasks") or []
    if not links:
        return None
    link = links[-1]
    t = ws_tasks.get((link.get("repoId"), link.get("taskId")))
    if not t:   # a tarefa foi removida no projeto: o cartão mostra e oferece desvincular
        return {"repoId": link.get("repoId"), "taskId": link.get("taskId"), "title": "", "branch": "", "status": "missing",
                "flow": link.get("flow"), "exists": False, "pr": None, "agents": 0, "since": None}
    exists = os.path.isdir(t["path"])
    terms = [x for x in terminals.list_all(task=t["id"]) if x["kind"] == "agent"]
    alive = [x for x in terms if x["alive"]]
    infos = [agents.session_info(x["meta"].get("sid")) or {} for x in alive]
    states = [i.get("status") for i in infos]
    if not exists:
        status = "gone"
    elif "needs-you" in states:
        status = "needs-you"
    elif any(s in WORKING for s in states):
        status = "working"
    elif "done" in states:
        status = "done"
    elif alive:
        status = "idle"
    else:
        status = "stopped"   # nenhum agente aberto (fechou, saiu, o app reiniciou)
    since = max([i.get("statusAt") or i.get("started") or 0 for i in infos] or [0]) or None
    return {"repoId": link["repoId"], "taskId": t["id"], "title": t["title"], "branch": t["branch"], "status": status,
            "flow": link.get("flow"), "exists": exists, "pr": t.get("pr"), "agents": len(alive), "since": since}


def _automate(d, c, live):
    """Movimento automático por MUDANÇA de estado do agente (não pelo estado em si). Devolve True se algo mudou."""
    cur = live["status"] if live else None
    prev = c.get("_seen")
    if cur == prev:
        return False
    c["_seen"] = cur
    if not d.get("autoMove") or prev is None or not live:
        return True   # 1ª leitura (cartão antigo): só anota o estado, não move nada de surpresa
    doing, review = _col(d, "doing"), _col(d, "review")
    if not doing or not review:
        return True
    if cur in ("done", "needs-you") and c["column"] == doing:
        _record(c, doing, review, "ia", "o agente terminou" if cur == "done" else "o agente precisa de você")
        _put(d, c, review, 0)
        c["updatedAt"] = now_iso()
    elif cur == "working" and c["column"] == review:
        last = (c.get("history") or [None])[-1]
        if last and last.get("by") == "ia" and last.get("to") == review:   # só desfaz o que a própria IA fez
            _record(c, review, doing, "ia", "o agente voltou a trabalhar")
            _put(d, c, doing, 0)
            c["updatedAt"] = now_iso()
    return True


def _public(c, live):
    return {**{k: v for k, v in c.items() if not k.startswith("_")}, "live": live}


def _tick():
    """Lê o estado dos agentes de cada cartão e aplica o movimento automático. Chame com _lock."""
    from . import workspace
    d = _load()
    wsd = workspace._load()
    ws_tasks = {(rid, t["id"]): t for rid, p in wsd["projects"].items() for t in p.get("tasks", [])}
    changed = False
    lives = {}
    for c in d["cards"]:
        lives[c["id"]] = live = _live(c, ws_tasks)
        changed = _automate(d, c, live) or changed
    if changed:
        _save(d)
    return d, lives


def automate():
    """O movimento automático sem a tela aberta (power.kanban_loop): o quadro anda mesmo com a janela escondida."""
    with _lock:
        _tick()


def view():
    with _lock:
        d, lives = _tick()
        return {"columns": d["columns"], "cards": [_public(c, lives[c["id"]]) for c in d["cards"]], "autoMove": d.get("autoMove", True)}


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
                 "due": None, "tasks": [], "files": [], "history": [], "createdAt": now_iso()}
            d["cards"].append(c)
        if "title" in body and (body.get("title") or "").strip():
            c["title"] = body["title"].strip()[:200]
        if "description" in body:
            c["description"] = str(body.get("description") or "")[:20000]
        if "column" in body and any(x["id"] == body["column"] for x in d["columns"]) and body["column"] != c["column"]:
            _record(c, c["column"], body["column"], "você")
            _put(d, c, body["column"])
        if body.get("priority") in PRIORITIES:
            c["priority"] = body["priority"]
        if isinstance(body.get("labels"), list):
            c["labels"] = list(dict.fromkeys(str(x).strip()[:30] for x in body["labels"] if str(x).strip()))[:12]
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
        return _public(c, None)


def delete_card(cid):
    with _lock:
        d = _load()
        d["cards"] = [c for c in d["cards"] if c["id"] != cid]
        _save(d)
    if cid and re.fullmatch(r"[A-Za-z0-9_-]+", str(cid)):
        shutil.rmtree(os.path.join(FILES_DIR, str(cid)), ignore_errors=True)


def move(cid, column, index=None):
    """Você moveu o cartão (arrastar, menu): vai para a coluna na posição `index` e fica no histórico."""
    with _lock:
        d = _load()
        c = _card(d, cid)
        if not any(x["id"] == column for x in d["columns"]):
            raise ValueError("Coluna não existe")
        _record(c, c["column"], column, "você")
        _put(d, c, column, index)
        c["updatedAt"] = now_iso()
        _save(d)
        return _public(c, None)


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
    """A IA começou o cartão: liga a tarefa (worktree + agente) e, com autoMove, leva o cartão para "Em andamento"."""
    with _lock:
        d = _load()
        c = _card(d, cid)
        c["tasks"] = [x for x in c.get("tasks") or [] if x.get("taskId") != task_id] + [{"repoId": repo_id, "taskId": task_id, "flow": flow, "at": now_iso()}]
        c["_seen"] = "linked"   # a próxima mudança de estado do agente desta tarefa já pode mover o cartão
        doing = _col(d, "doing")
        if d.get("autoMove") and doing and c["column"] != doing:
            _record(c, c["column"], doing, "ia", "a IA começou")
            _put(d, c, doing, 0)
        c["updatedAt"] = now_iso()
        _save(d)
        return _public(c, None)


def unlink_task(cid, task_id=None):
    """Desliga a tarefa do cartão (sem task_id: a mais recente). A tarefa e o worktree continuam no projeto."""
    with _lock:
        d = _load()
        c = _card(d, cid)
        links = c.get("tasks") or []
        tid = task_id or (links[-1]["taskId"] if links else None)
        c["tasks"] = [x for x in links if x.get("taskId") != tid]
        c.pop("_seen", None)
        c["updatedAt"] = now_iso()
        _save(d)
        return _public(c, None)


# ---------------------------------------------------------------- anexos (imagens e arquivos do cartão)
def _safe_name(name):
    name = os.path.basename(str(name or "").replace("\\", "/")).strip()
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", name).strip(". ") or "arquivo"
    stem, ext = os.path.splitext(name)
    return stem[:100] + ext[:20]


def _file(c, fid):
    f = next((x for x in c.get("files") or [] if x["id"] == fid), None)
    if not f:
        raise LookupError("Anexo não encontrado")
    return f


def _path(cid, f):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(cid)):
        raise ValueError("cartão inválido")
    return os.path.join(FILES_DIR, cid, f"{f['id']}-{f['name']}")


def add_file(cid, name, data_b64, ctype=None):
    """Anexa um arquivo (conteúdo em base64 — a API só fala JSON). Até 25 MB por arquivo."""
    try:
        raw = base64.b64decode(data_b64 or "", validate=False)
    except ValueError:
        raise ValueError("Arquivo inválido") from None
    if not raw:
        raise ValueError("Arquivo vazio")
    if len(raw) > MAX_FILE:
        raise ValueError(f"{name or 'Arquivo'} passa de {MAX_FILE // (1024 * 1024)} MB")
    name = _safe_name(name)
    with _lock:
        d = _load()
        c = _card(d, cid)
        if len(c["files"]) >= MAX_FILES:
            raise ValueError(f"O cartão já tem {MAX_FILES} anexos")
        f = {"id": uuid.uuid4().hex[:10], "name": name, "size": len(raw),
             "type": (ctype or mimetypes.guess_type(name)[0] or "application/octet-stream")[:100], "at": now_iso()}
        p = _path(cid, f)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(raw)
        c["files"].append(f)
        c["updatedAt"] = now_iso()
        _save(d)
        return f


def get_file(cid, fid):
    from .extensions import RawFile
    d = _load()
    f = _file(_card(d, cid), fid)
    try:
        with open(_path(cid, f), "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        raise LookupError("O arquivo do anexo sumiu do disco") from None
    ctype = f.get("type") or "application/octet-stream"
    if not re.fullmatch(r"[\w.+-]+/[\w.+-]+", ctype):
        ctype = "application/octet-stream"
    return RawFile(data, ctype)


def remove_file(cid, fid):
    with _lock:
        d = _load()
        c = _card(d, cid)
        f = _file(c, fid)
        try:
            os.remove(_path(cid, f))
        except FileNotFoundError:
            pass
        c["files"] = [x for x in c["files"] if x["id"] != fid]
        c["updatedAt"] = now_iso()
        _save(d)
        return {"ok": True}


def open_file(cid, fid, reveal=False):
    """Abre o anexo no app padrão do sistema (ou mostra na pasta)."""
    d = _load()
    p = _path(cid, _file(_card(d, cid), fid))
    if not os.path.isfile(p):
        raise LookupError("O arquivo do anexo sumiu do disco")
    detached = {"creationflags": 0x00000008 | 0x08000000} if os.name == "nt" else {"start_new_session": True}
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", p] if reveal else ["open", p], **detached)
    elif os.name == "nt":
        if reveal:
            subprocess.Popen(["explorer", "/select,", p], **detached)
        else:
            os.startfile(p)  # noqa: S606 — o app padrão do Windows para o tipo do arquivo
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(p) if reveal else p], **detached)
    return {"ok": True}


def context(cid):
    """Texto de contexto que acompanha o pedido à IA: o cartão, o grupo, os projetos (onde roda, quais mudam e quais
    são só de consulta) e os anexos, com as pastas — o agente sabe a que conjunto a tarefa pertence."""
    from . import workspace
    d = _load()
    c = _card(d, cid)
    repos = {r["id"]: r for r in git.list_repos(with_status=False)}
    g = next((x for x in workspace._load()["groups"] if x["id"] == c.get("groupId")), None)
    lines = [f"Cartão do quadro: {c['title']}"]
    if c.get("labels"):
        lines.append("Etiquetas: " + ", ".join(c["labels"]))
    if c.get("priority") and c["priority"] != "normal":
        lines.append("Prioridade: " + {"low": "baixa", "high": "alta", "urgent": "urgente"}[c["priority"]])
    if c.get("due"):
        lines.append("Prazo: " + c["due"])
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
    files = [(f, _path(cid, f)) for f in c.get("files") or []]
    files = [(f, p) for f, p in files if os.path.isfile(p)]
    if files:
        lines.append("\nAnexos do cartão (imagens e arquivos — leia o que for útil):")
        lines += [f"- {f['name']}: {p}" for f, p in files]
    return "\n".join(lines)
