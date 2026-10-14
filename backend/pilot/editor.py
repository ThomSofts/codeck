"""Editor do projeto (estilo VS Code): conteúdo do arquivo no HEAD/índice (diff e marcações de alteração na margem)
e as operações do explorador — novo arquivo/pasta, renomear/mover e excluir (vai para a Lixeira).

Tudo dentro da pasta do projeto ou da tarefa (worktree): caminhos fora dela são recusados."""
import os
import shutil

from . import git
from .workspace import _root, _safe

MAX_SHOW = 3_000_000


def base_text(repo_id, rel, task_id=None, ref="HEAD"):
    """O arquivo como está no último commit (HEAD) ou no que já foi preparado (INDEX). Arquivo novo: exists=False."""
    root = _root(repo_id, task_id)
    full = _safe(root, rel)
    rel = os.path.relpath(full, root).replace(os.sep, "/")
    spec = f":{rel}" if ref == "INDEX" else f"HEAD:{rel}"
    try:
        size = int(git.run(root, "cat-file", "-s", spec, timeout=15).strip() or 0)
    except git.GitError:
        return {"path": rel, "text": "", "exists": False}
    if size > MAX_SHOW:
        return {"path": rel, "text": "", "exists": True, "tooLarge": True}
    raw = git.run(root, "show", spec, timeout=30, raw=True)
    if b"\0" in raw[:8000]:
        return {"path": rel, "text": "", "exists": True, "binary": True}
    return {"path": rel, "text": raw.decode("utf-8", errors="replace"), "exists": True}


def _check_name(rel):
    name = (rel or "").replace("\\", "/").strip("/")
    if not name or any(p in ("", ".", "..") for p in name.split("/")) or name.split("/")[0] == ".git":
        raise ValueError("Nome inválido")
    return name


def create(repo_id, rel, task_id=None, folder=False):
    root = _root(repo_id, task_id)
    rel = _check_name(rel)
    full = _safe(root, rel)
    if os.path.exists(full):
        raise ValueError(f"Já existe: {rel}")
    if folder:
        os.makedirs(full)
    else:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "x", encoding="utf-8").close()
    return {"path": rel, "folder": folder}


def rename(repo_id, src, dst, task_id=None):
    """Renomeia/move. Arquivo versionado vai com `git mv` (o Git entende como renomeação, não apagar + criar)."""
    root = _root(repo_id, task_id)
    src, dst = _check_name(src), _check_name(dst)
    a, b = _safe(root, src), _safe(root, dst)
    if not os.path.exists(a):
        raise LookupError(f"Não existe: {src}")
    if os.path.exists(b) and os.path.normcase(a) != os.path.normcase(b):
        raise ValueError(f"Já existe: {dst}")
    os.makedirs(os.path.dirname(b), exist_ok=True)
    tracked = bool(git.run(root, "ls-files", "--", src, timeout=15, check=False).strip())
    if tracked:
        git.run(root, "mv", "--", src, dst, timeout=30)
    else:
        shutil.move(a, b)
    return {"path": dst}


def delete(repo_id, rel, task_id=None):
    root = _root(repo_id, task_id)
    rel = _check_name(rel)
    full = _safe(root, rel)
    if not os.path.exists(full):
        raise LookupError(f"Não existe: {rel}")
    git.move_to_trash(full)
    return {"path": rel}
