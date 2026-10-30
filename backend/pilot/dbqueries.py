"""Consultas salvas. Duas origens, mostradas juntas na bancada:
  - do banco: valem em todos os projetos que usam aquele banco — ficam só neste computador (db-queries.json);
  - do projeto: onde o ajuste mandar — neste computador, ou no repositório em .codeck-db/queries/<banco>/<nome>.sql
    (versionadas, o time vê — fora do .codeck/, que o Git ignora). O padrão é global (Ajustes de dados) e cada projeto pode trocar.
"""
import os
import re
import threading
import uuid

from . import databases, git
from .core import DATA, load_json, now_iso, save_json

FILE = os.path.join(DATA, "db-queries.json")
_lock = threading.Lock()


def _slug(s, n=60):
    s = re.sub(r"[^\w\- ]+", "", (s or "").strip(), flags=re.UNICODE).strip().replace(" ", "-")
    return s[:n] or "consulta"


def where(repo_id):
    """"local" ou "repo" para as consultas deste projeto."""
    prefs = databases._load()["prefs"]
    return (prefs.get("queriesByRepo") or {}).get(repo_id) or prefs.get("queries") or "local"


def _repo_dir(repo_id, bank):
    root = os.path.realpath(git.get_repo(repo_id)["path"])
    d = os.path.realpath(os.path.join(root, ".codeck-db", "queries", _slug(bank["name"])))
    if not d.startswith(root + os.sep):
        raise ValueError("Pasta de consultas inválida")
    return d


def list_for(bank_id, repo_id=None):
    bank = databases._bank(databases._load(), bank_id)
    data = load_json(FILE, {})
    out = [{**q, "scope": "bank"} for q in data.get("b:" + bank_id, [])]
    if repo_id:
        out += [{**q, "scope": "project", "store": "local"} for q in data.get(f"p:{repo_id}:{bank_id}", [])]
        try:
            d = _repo_dir(repo_id, bank)
            for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                if f.endswith(".sql") and os.path.isfile(os.path.join(d, f)):
                    with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                        sql = fh.read(1_000_000)
                    out.append({"id": "f:" + f, "name": f[:-4].replace("-", " "), "sql": sql, "scope": "project", "store": "repo",
                                "updated": now_iso()})
        except (ValueError, OSError):
            pass
    return {"items": out, "where": where(repo_id) if repo_id else "local"}


def save(bank_id, name, sql, scope="bank", repo_id=None, qid=None):
    bank = databases._bank(databases._load(), bank_id)
    name = (name or "").strip()[:80] or "Consulta"
    if len(sql or "") > 1_000_000:
        raise ValueError("Consulta grande demais para salvar")
    if scope == "project" and repo_id and (where(repo_id) == "repo" or (qid or "").startswith("f:")):
        d = _repo_dir(repo_id, bank)
        os.makedirs(d, exist_ok=True)
        fname = _slug(name) + ".sql"
        if qid and qid.startswith("f:") and qid[2:] != fname:   # renomeou: o arquivo antigo sai
            old = os.path.join(d, os.path.basename(qid[2:]))
            if os.path.isfile(old):
                os.remove(old)
        with open(os.path.join(d, fname), "w", encoding="utf-8") as f:
            f.write(sql.rstrip() + "\n")
        return {"id": "f:" + fname, **list_for(bank_id, repo_id)}
    key = "b:" + bank_id if scope == "bank" or not repo_id else f"p:{repo_id}:{bank_id}"
    with _lock:
        data = load_json(FILE, {})
        items = data.setdefault(key, [])
        q = next((x for x in items if x["id"] == qid), None)
        if not q:
            q = {"id": "q_" + uuid.uuid4().hex[:10]}
            items.append(q)
        q.update(name=name, sql=sql, updated=now_iso())
        save_json(FILE, data, private=True)
    return {"id": q["id"], **list_for(bank_id, repo_id)}


def delete(bank_id, qid, repo_id=None):
    bank = databases._bank(databases._load(), bank_id)
    if qid.startswith("f:") and repo_id:
        p = os.path.join(_repo_dir(repo_id, bank), os.path.basename(qid[2:]))
        if os.path.isfile(p):
            os.remove(p)
    else:
        with _lock:
            data = load_json(FILE, {})
            for k in ("b:" + bank_id, f"p:{repo_id}:{bank_id}"):
                if k in data:
                    data[k] = [x for x in data[k] if x["id"] != qid]
            save_json(FILE, data, private=True)
    return list_for(bank_id, repo_id)


def set_where(repo_id, value):
    """Onde ficam as consultas do projeto: "local", "repo" ou None (segue o padrão)."""
    git.get_repo(repo_id)
    with databases.lock:
        d = databases._load()
        by = d["prefs"].setdefault("queriesByRepo", {})
        if value in ("local", "repo"):
            by[repo_id] = value
        else:
            by.pop(repo_id, None)
        databases._save(d)
    return {"where": where(repo_id)}
