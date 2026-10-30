"""Confiança por projeto (como o "Workspace Trust" do VS Code).

O que vem do repositório só roda depois que você confia no projeto: launch.json/tasks.json/scripts do package.json,
depuração, compilação .NET (o MSBuild roda os alvos do projeto), o comando de preparação das tarefas e os servidores de
linguagem que executam código do projeto ao abrir um arquivo (C#, Rust, SDK do Dart dentro do repositório). Um clone
novo ou a PR de um fork não executam nada sozinhos. Terminais e agentes não passam por aqui: o comando é seu.

Guardado em config.json: {"trust": {"all": false, "repos": [id…]}}. "all" = não perguntar mais (confiar em todos).
Tarefas (worktrees) seguem a confiança do projeto.
"""
from . import git
from .core import CONFIG_FILE, load_json, lock, save_json


class TrustRequired(Exception):
    """O pedido executaria código do repositório e o projeto ainda não é confiável: a tela pergunta e repete."""

    def __init__(self, repo_id, what):
        self.repo_id, self.what = repo_id, what
        try:
            self.repo_name = git.get_repo(repo_id)["name"]
        except Exception:  # noqa: BLE001
            self.repo_name = repo_id or "projeto"
        super().__init__(f"O projeto {self.repo_name} ainda não é confiável — confie nele para executar {what}")

    def payload(self):
        return {"repoId": self.repo_id, "repoName": self.repo_name, "what": self.what}


def _get():
    t = load_json(CONFIG_FILE, {}).get("trust") or {}
    return {"all": bool(t.get("all")), "repos": [r for r in (t.get("repos") or []) if isinstance(r, str)]}


def _save(t):
    with lock:
        cfg = load_json(CONFIG_FILE, {})
        cfg["trust"] = t
        save_json(CONFIG_FILE, cfg, private=True)


def is_trusted(repo_id):
    t = _get()
    return t["all"] or (bool(repo_id) and repo_id in t["repos"])


def require(repo_id, what):
    if not is_trusted(repo_id):
        raise TrustRequired(repo_id, what)


def trust(repo_id):
    git.get_repo(repo_id)   # só projeto que existe
    t = _get()
    if repo_id not in t["repos"]:
        t["repos"].append(repo_id)
        _save(t)
    return public()


def untrust(repo_id):
    t = _get()
    t["repos"] = [r for r in t["repos"] if r != repo_id]
    _save(t)
    return public()


def set_all(value):
    t = _get()
    t["all"] = bool(value)
    _save(t)
    return public()


def public():
    t = _get()
    names = {r["id"]: r["name"] for r in git._repos()}
    return {"all": t["all"], "repos": [{"id": r, "name": names.get(r, r)} for r in t["repos"] if r in names]}
