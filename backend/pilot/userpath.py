"""PATH de verdade do usuário — o que um terminal aberto por ele enxerga.

O app aberto pelo Finder/Explorer nasce com PATH mínimo. Antes o app perguntava ao shell de LOGIN (`zsh -l`), que não
lê o ~/.zshrc — e é lá que muita gente põe ~/.local/bin (onde o instalador nativo do Claude Code coloca o `claude`),
nvm, pnpm, bun… Resultado: "CLI não instalada" com a CLI instalada. Agora:
  · macOS/Linux: shell de login E interativo (lê .zprofile e .zshrc), com marcadores para ignorar o que o .zshrc imprime;
  · Windows: PATH do usuário e da máquina lidos do registro (o processo do app guarda o PATH de quando abriu);
  · mais as pastas onde os instaladores costumam pôr as CLIs, caso o shell não diga.
"""
import glob
import os
import re
import shutil
import subprocess
import threading
import time

_cache = {"at": 0.0, "path": None}
_lock = threading.Lock()
TTL = 600
MARK = "__CODECK_PATH__"


def _version(path):
    m = re.search(r"v(\d+)\.(\d+)\.(\d+)", path)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def _known_dirs():
    home = os.path.expanduser("~")
    if os.name == "nt":
        env = os.environ
        local, roaming = env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local"), env.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        return [os.path.join(home, ".local", "bin"), os.path.join(roaming, "npm"), os.path.join(home, ".bun", "bin"),
                os.path.join(local, "Microsoft", "WinGet", "Links"), os.path.join(home, "scoop", "shims"),
                os.path.join(local, "pnpm"), os.path.join(home, ".volta", "bin"), os.path.join(home, ".cargo", "bin"),
                os.path.join(local, "Programs", "cursor", "resources", "app", "bin"), os.path.join(home, ".dotnet", "tools"),
                os.path.join(home, "go", "bin")]
    dirs = [os.path.join(home, ".local", "bin"), os.path.join(home, ".claude", "local"), os.path.join(home, ".npm-global", "bin"),
            os.path.join(home, ".bun", "bin"), os.path.join(home, ".volta", "bin"), os.path.join(home, ".cargo", "bin"),
            os.path.join(home, "Library", "pnpm"), os.path.join(home, ".local", "share", "pnpm"), os.path.join(home, ".yarn", "bin"),
            os.path.join(home, ".opencode", "bin"), os.path.join(home, ".dotnet", "tools"), os.path.join(home, "go", "bin"),
            "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    # nvm/fnm: a versão de Node mais nova instalada (onde ficam as CLIs instaladas com npm -g)
    nodes = sorted(glob.glob(os.path.join(home, ".nvm", "versions", "node", "v*", "bin")) +
                   glob.glob(os.path.join(home, ".local", "share", "fnm", "node-versions", "v*", "installation", "bin")), key=_version, reverse=True)
    return dirs + nodes[:1]


def _shell_path():
    sh = os.environ.get("SHELL") or ("/bin/zsh" if os.path.exists("/bin/zsh") else "/bin/bash")
    fish = os.path.basename(sh) == "fish"
    script = f'printf "\\n{MARK}%s{MARK}\\n" "$PATH"' if not fish else f'printf "\\n{MARK}%s{MARK}\\n" (string join : $PATH)'
    env = {**os.environ, "TERM": "dumb"}
    for args in ([sh, "-l", "-i", "-c", script], [sh, "-l", "-c", script]):
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL, env=env).stdout
        except Exception:  # noqa: BLE001 — shell exótico ou travado: tenta o próximo
            continue
        if MARK in out:
            got = out.split(MARK)[1]
            if got.strip():
                return got.strip()
    return ""


def _registry_path():
    try:
        import winreg
    except ImportError:
        return ""
    parts = []
    for root, key in ((winreg.HKEY_CURRENT_USER, r"Environment"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
        try:
            with winreg.OpenKey(root, key) as k:
                parts.append(os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]))
        except OSError:
            continue
    return os.pathsep.join(parts)


def get(force=False):
    """PATH completo do usuário (cache de 10 min). Vencido, devolve o que já tem e relê em segundo plano: reler abre um
    shell interativo (.zshrc com nvm, oh-my-zsh… leva segundos) e isso acontecia DENTRO do pedido de abrir um agente
    ou terminal — o painel ficava parado esperando."""
    if not force and _cache["path"]:
        if time.time() - _cache["at"] >= TTL and not _cache.get("busy"):
            _cache["busy"] = True
            threading.Thread(target=_refresh, daemon=True).start()
        return _cache["path"]
    with _lock:
        if not force and _cache["path"]:
            return _cache["path"]
        return _read()


def _refresh():
    try:
        with _lock:
            _read()
    finally:
        _cache["busy"] = False


def _read():
    """Relê o PATH (chame com o _lock)."""
    base = _registry_path() if os.name == "nt" else _shell_path()
    seen, out = set(), []
    for p in (base.split(os.pathsep) if base else []) + (os.environ.get("PATH") or "").split(os.pathsep) + _known_dirs():
        p = p.strip().strip('"')
        key = os.path.normcase(os.path.normpath(p)) if p else ""
        if p and key not in seen and os.path.isdir(p):
            seen.add(key)
            out.append(p)
    _cache.update(at=time.time(), path=os.pathsep.join(out))
    return _cache["path"]


def which(name, force=False):
    return shutil.which(name, path=get(force))
