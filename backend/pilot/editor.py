"""Editor do projeto (estilo VS Code): conteúdo do arquivo no HEAD/índice (diff e marcações de alteração na margem)
e as operações do explorador — novo arquivo/pasta, renomear, mover (arrastar, recortar e colar), copiar/duplicar,
excluir (vai para a Lixeira) e receber o que se arrasta do Finder/Explorer.

Tudo dentro da pasta do projeto ou da tarefa (worktree): caminhos fora dela são recusados."""
import base64
import os
import re
import shutil
import subprocess
import sys
import time

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


def _entry(root, rel):
    """Caminho de uma entrada do explorador: a pasta-mãe é resolvida (realpath, tem de ficar no projeto) e o último nome
    não — renomear/excluir/mover um link simbólico age no link, nunca no alvo (que pode estar fora do projeto)."""
    rel = _check_name(rel)
    parent = _safe(root, os.path.dirname(rel))
    full = os.path.join(parent, os.path.basename(rel))
    rel = os.path.relpath(full, root).replace(os.sep, "/")
    if rel.split("/")[0] == ".git":
        raise ValueError("Nome inválido")
    return full, rel


def _dir(root, rel):
    """Pasta de destino ("" = raiz do projeto)."""
    if not (rel or "").strip("/\\"):
        return root
    full = _safe(root, _check_name(rel))
    if not os.path.isdir(full):
        raise LookupError(f"Não é uma pasta: {rel}")
    if os.path.relpath(full, root).replace(os.sep, "/").split("/")[0] == ".git":
        raise ValueError("Nome inválido")
    return full


def _rel(root, full):
    return os.path.relpath(full, root).replace(os.sep, "/")


def _inside(a, b):
    """b é a própria `a` ou está dentro dela (mover/copiar pasta para dentro de si mesma). Sem diferenciar maiúsculas,
    como o disco do macOS/Windows."""
    a, b = os.path.normcase(a), os.path.normcase(b)
    if sys.platform == "darwin":   # no Windows o normcase já baixa; no Linux o disco diferencia
        a, b = a.lower(), b.lower()
    return b == a or b.startswith(a.rstrip(os.sep) + os.sep)


def _same_entry(a, b):
    """a e b são a MESMA entrada (troca só de maiúsculas no macOS/Windows), sem seguir link simbólico."""
    try:
        x, y = os.lstat(a), os.lstat(b)
    except OSError:
        return False
    return (x.st_dev, x.st_ino) == (y.st_dev, y.st_ino)


def _free(folder, name):
    """Nome livre na pasta, como o VS Code: "nome copy.ext", "nome copy 2.ext"…"""
    if not os.path.lexists(os.path.join(folder, name)):
        return name
    stem, ext = os.path.splitext(name)
    if not stem or (name.startswith(".") and stem == name):   # ".env": sem extensão
        stem, ext = name, ""
    m = re.match(r"^(.*) copy(?: (\d+))?$", stem)
    base, n = (m.group(1), int(m.group(2) or 1)) if m else (stem, 0)
    while True:
        n += 1
        cand = f"{base} copy{ext}" if n == 1 else f"{base} copy {n}{ext}"
        if not os.path.lexists(os.path.join(folder, cand)):
            return cand


def _tracked(root, rel):
    return bool(git.run(root, "ls-files", "--", f":(literal){rel}", timeout=15, check=False).strip())


def _move(root, a, b):
    """Move a → b. Versionado vai com `git mv` (o Git entende como renomeação, não apagar + criar); se o Git recusar
    (destino ignorado, índice travado…), move no disco mesmo."""
    os.makedirs(os.path.dirname(b), exist_ok=True)
    same = os.path.lexists(b) and _same_entry(a, b)   # só muda maiúscula/minúscula (macOS/Windows não diferenciam)
    if _tracked(root, _rel(root, a)):
        try:
            git.run(root, "mv", "--", _rel(root, a), _rel(root, b), timeout=30)
            return
        except git.GitError:
            if os.path.lexists(b) and not same:
                raise
    if same:
        os.rename(a, b)
    else:
        shutil.move(a, b)


# Lixeira do macOS pelo NSFileManager (JavaScript for Automation): sem pedir automação do Finder, sem o Finder largar
# .DS_Store na pasta do projeto, e o caminho vai como argumento (nunca dentro do código do script)
_JXA_TRASH = ('function run(argv) { ObjC.import("Foundation"); if (!$.NSFileManager.defaultManager'
              '.trashItemAtURLResultingItemURLError($.NSURL.fileURLWithPath(argv[0]), null, null)) throw new Error("trash"); }')


def _trash(full):
    """Lixeira. Link simbólico só é desfeito (mandar para a Lixeira pelo Finder levaria o ALVO, que pode estar fora do
    projeto)."""
    if os.path.islink(full):
        os.unlink(full)
        return
    if sys.platform == "darwin":
        r = subprocess.run(["osascript", "-l", "JavaScript", "-e", _JXA_TRASH, full], capture_output=True, timeout=60)
        if r.returncode == 0:
            return
    git.move_to_trash(full)


def create(repo_id, rel, task_id=None, folder=False):
    root = _root(repo_id, task_id)
    full, rel = _entry(root, rel)
    if os.path.lexists(full):
        raise ValueError(f"Já existe: {rel}")
    if folder:
        os.makedirs(full)
    else:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "x", encoding="utf-8").close()
    return {"path": rel, "folder": folder}


def rename(repo_id, src, dst, task_id=None):
    """Renomeia/move uma entrada para o caminho `dst` (pode trocar de pasta)."""
    root = _root(repo_id, task_id)
    a, src = _entry(root, src)
    b, dst = _entry(root, dst)
    if not os.path.lexists(a):
        raise LookupError(f"Não existe: {src}")
    if os.path.lexists(b) and not _same_entry(a, b):
        raise ValueError(f"Já existe: {dst}")
    if os.path.isdir(a) and not os.path.islink(a) and _inside(a, b) and not _same_entry(a, b):
        raise ValueError("Não dá para mover uma pasta para dentro dela mesma")
    _move(root, a, b)
    return {"path": dst}


def move(repo_id, paths, dest, task_id=None, overwrite=False):
    """Arrastar/recortar e colar: move as entradas para a pasta `dest`. Nome que já existe lá: sem `overwrite` devolve
    {"conflicts": [...]} sem mexer em nada (a tela pergunta); com ele, o que estava no destino vai para a Lixeira."""
    root = _root(repo_id, task_id)
    folder = _dir(root, dest)
    plan, conflicts = [], []
    for p in paths or []:
        a, rel = _entry(root, p)
        if not os.path.lexists(a):
            raise LookupError(f"Não existe: {rel}")
        if os.path.isdir(a) and not os.path.islink(a) and _inside(a, folder):
            raise ValueError(f"Não dá para mover {os.path.basename(a)} para dentro dela mesma")
        b = os.path.join(folder, os.path.basename(a))
        if os.path.normcase(os.path.dirname(a)) == os.path.normcase(folder):
            continue   # já está nesta pasta
        if any(os.path.normcase(b) == os.path.normcase(x[1]) for x in plan):
            raise ValueError(f"Dois itens com o mesmo nome: {os.path.basename(a)}")
        if os.path.lexists(b):
            conflicts.append(_rel(root, b))
        plan.append((a, b))
    if conflicts and not overwrite:
        return {"conflicts": conflicts, "moved": []}
    moved = []
    for a, b in plan:
        if os.path.lexists(b):
            if _inside(b, a):
                raise ValueError(f"Não dá para substituir {_rel(root, b)} por algo que está dentro dela")
            _trash(b)
        src = _rel(root, a)
        _move(root, a, b)
        moved.append({"from": src, "to": _rel(root, b)})
    return {"moved": moved, "conflicts": []}


def copy(repo_id, paths, dest, task_id=None):
    """Copiar e colar / duplicar: copia (pastas inteiras) para `dest`. Nunca sobrescreve: nome repetido vira
    "nome copy.ext", como no VS Code. Links simbólicos são copiados como links."""
    root = _root(repo_id, task_id)
    folder = _dir(root, dest)
    out = []
    for p in paths or []:
        a, rel = _entry(root, p)
        if not os.path.lexists(a):
            raise LookupError(f"Não existe: {rel}")
        if os.path.isdir(a) and not os.path.islink(a) and _inside(a, folder):
            raise ValueError(f"Não dá para copiar {os.path.basename(a)} para dentro dela mesma")
        b = os.path.join(folder, _free(folder, os.path.basename(a)))
        if os.path.isdir(a) and not os.path.islink(a):
            shutil.copytree(a, b, symlinks=True)
        else:
            shutil.copy2(a, b, follow_symlinks=False)
        out.append({"from": rel, "to": _rel(root, b)})
    return {"copied": out}


def delete(repo_id, rel=None, task_id=None, paths=None):
    """Exclui (vai para a Lixeira). Uma entrada (`rel`) ou várias (`paths`)."""
    root = _root(repo_id, task_id)
    out = []
    for p in (paths or [rel]):
        full, p = _entry(root, p)
        if not os.path.lexists(full):
            raise LookupError(f"Não existe: {p}")
        _trash(full)
        out.append(p)
    return {"path": out[0] if out else None, "paths": out}


# ---------------------------------------------------------------- arrastar do Finder/Explorer para a árvore
MAX_UPLOAD_CHUNK = 8_000_000


def free_name(repo_id, dest, name, task_id=None):
    """Nome livre em `dest` para o que vai chegar de fora (a cópia nunca sobrescreve o que está no projeto)."""
    root = _root(repo_id, task_id)
    folder = _dir(root, dest)
    name = _check_name(name)
    if "/" in name:
        raise ValueError("Nome inválido")
    return {"path": _rel(root, os.path.join(folder, _free(folder, name)))}


def upload(repo_id, rel, data="", offset=0, task_id=None, folder=False):
    """Recebe um arquivo arrastado de fora em pedaços (base64): offset 0 cria (nunca sobrescreve), os seguintes
    continuam de onde parou. `folder` cria a pasta (inclusive vazia)."""
    root = _root(repo_id, task_id)
    full, rel = _entry(root, rel)
    if folder:
        os.makedirs(full, exist_ok=True)
        return {"path": rel}
    raw = base64.b64decode(data or "", validate=True)
    if len(raw) > MAX_UPLOAD_CHUNK:
        raise ValueError("Pedaço grande demais")
    offset = int(offset or 0)
    if offset == 0:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        try:
            with open(full, "xb") as f:
                f.write(raw)
        except FileExistsError:
            raise ValueError(f"Já existe: {rel}") from None
    else:
        if os.path.islink(full) or not os.path.isfile(full) or os.path.getsize(full) != offset:
            raise ValueError(f"Envio interrompido: {rel}")
        with open(full, "r+b") as f:
            f.seek(offset)
            f.write(raw)
    return {"path": rel, "size": offset + len(raw)}


def empty_dirs(repo_id, task_id=None, known=()):
    """Pastas sem nenhum arquivo (o `git ls-files` não lista pasta vazia): a "Nova pasta" aparece na árvore na hora."""
    root = _root(repo_id, task_id)
    out = git.run(root, "ls-files", "-o", "--directory", "--exclude-standard", "-z", timeout=30, check=False)
    prefixes = set()
    for f in known:
        i = f.find("/")
        while i > 0:
            prefixes.add(f[:i + 1])
            i = f.find("/", i + 1)
    found = []

    def walk(full, rel, depth):
        # só desce enquanto a pasta tem apenas subpastas; com arquivo dentro (ignorado, já que o git não listou) para ali
        found.append(rel)
        if depth > 12 or len(found) > 500:
            return
        try:
            entries = list(os.scandir(full))
        except OSError:
            return
        if any(not e.is_dir(follow_symlinks=False) for e in entries):
            return
        for e in entries:
            walk(e.path, rel + e.name + "/", depth + 1)

    for d in out.split("\0"):
        if d.endswith("/") and d not in prefixes and len(found) <= 500:
            full = os.path.join(root, d)
            if os.path.isdir(full) and not os.path.islink(full):
                walk(full, d, 0)
    return found
