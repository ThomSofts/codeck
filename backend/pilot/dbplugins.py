"""Plugins de banco de dados: um executável por banco (db/ no repositório, em Go), falando uma linha JSON por mensagem
no stdin/stdout — sem porta, sem arquivo de log. O backend inicia o plugin na primeira conexão daquele banco e o
mantém aberto; se ele cair, a próxima chamada inicia outro (as conexões abertas se perdem e a tela reabre).

Onde o Codeck procura o executável, nesta ordem:
  - CODECK_DB_PLUGINS (pasta): desenvolvimento e testes;
  - db-plugins/ junto do app: o build local (scripts/build-macos.sh) embute os plugins — vêm com o próprio app;
  - <dados>/plugins/db/: plugins instalados pela tela. O SHA-256 de cada um vem no latest.json assinado pela ThomSoft
    (dbPlugins), é conferido no download e anotado no plugins.json — e conferido de novo antes de cada execução;
  - db/bin do repositório, só quando o app roda direto do código (versão "dev").
"""
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse

from . import update
from .core import APP_PLATFORM, APP_VERSION, BACKEND_DIR, DATA, load_json, save_json

# engine (como o cadastro guarda) → nome do executável
ENGINES = {
    "sqlserver": {"bin": "mssql", "label": "SQL Server", "port": 1433},
    "postgres": {"bin": "postgres", "label": "PostgreSQL", "port": 5432},
    "mysql": {"bin": "mysql", "label": "MySQL / MariaDB", "port": 3306},
    "sqlite": {"bin": "sqlite", "label": "SQLite", "port": None},
    "mongodb": {"bin": "mongodb", "label": "MongoDB", "port": 27017, "documents": True},
    "firebase": {"bin": "firebase", "label": "Firebase (Firestore / Realtime DB)", "port": None, "documents": True},
    "libsql": {"bin": "libsql", "label": "libSQL / Turso", "port": None},
    "redis": {"bin": "redis", "label": "Redis / Valkey", "port": 6379, "documents": True},
}
DOCUMENTS = {e for e, s in ENGINES.items() if s.get("documents")}   # sem transação: produção não tem Confirmar/Desfazer
BUNDLED_DIR = os.path.join(os.path.dirname(BACKEND_DIR), "db-plugins")
PLUGINS_DIR = os.path.join(DATA, "plugins", "db")
MANIFEST = os.path.join(PLUGINS_DIR, "plugins.json")
EXE = ".exe" if os.name == "nt" else ""


class PluginError(Exception):
    """Erro vindo do plugin (ou de iniciá-lo). code é estável: a tela decide o que mostrar por ele."""

    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code, self.data = code, data


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def locate(engine):
    """(caminho, origem) do executável do plugin, ou (None, motivo)."""
    spec = ENGINES.get(engine)
    if not spec:
        return None, "Banco não suportado"
    name = f"codeck-db-{spec['bin']}{EXE}"
    dev = os.environ.get("CODECK_DB_PLUGINS")
    if dev and os.path.isfile(os.path.join(dev, name)):
        return os.path.join(dev, name), "dev"
    if os.path.isfile(os.path.join(BUNDLED_DIR, name)):
        return os.path.join(BUNDLED_DIR, name), "bundled"
    installed = os.path.join(PLUGINS_DIR, name)
    if os.path.isfile(installed):
        want = (load_json(MANIFEST, {}).get("plugins") or {}).get(engine, {}).get("sha256")
        if not want or _sha256(installed) != want:
            return None, "O plugin instalado não confere com a assinatura — reinstale em Ajustes → Dados → Plugins"
        return installed, "installed"
    repo = os.path.join(os.path.dirname(BACKEND_DIR), "db", "bin", name)
    if APP_VERSION == "dev" and os.path.isfile(repo):
        return repo, "repo"
    return None, f"Plugin de {spec['label']} não instalado — instale em Ajustes → Dados → Plugins"


def status():
    man = (load_json(MANIFEST, {}).get("plugins") or {})
    out = []
    for engine, spec in ENGINES.items():
        path, origin = locate(engine)
        out.append({"engine": engine, "label": spec["label"], "installed": bool(path), "origin": origin if path else None,
                    "problem": None if path else origin, "version": (man.get(engine) or {}).get("version") if origin == "installed" else None})
    return out


# ---------------------------------------------------------------- instalar pela tela (baixa e confere o hash assinado)

def _retry(fn, *args):
    """No Windows, o .exe de um processo que acabou de sair fica travado por um instante: tenta por até ~5 s."""
    for i in range(25):
        try:
            return fn(*args)
        except PermissionError:
            if os.name != "nt" or i == 24:
                raise
            time.sleep(0.2)

installing = {}   # engine → {"done", "total"}: a tela mostra o progresso


def published():
    """O que a ThomSoft publicou para este sistema (do latest.json assinado)."""
    info = update.signed_manifest()
    plat = ((info.get("dbPlugins") or {}).get(APP_PLATFORM)) or {}
    man = (load_json(MANIFEST, {}).get("plugins") or {})
    out = {}
    for engine, a in (plat.get("engines") or {}).items():
        if engine in ENGINES:
            mine = man.get(engine) or {}
            out[engine] = {"version": plat.get("version"), "size": a.get("size"),
                           "update": bool(mine) and mine.get("sha256") != str(a.get("sha256", "")).lower()}
    return {"version": plat.get("version"), "engines": out}


def install(engine):
    spec = ENGINES.get(engine)
    if not spec:
        raise PluginError("bad-engine", "Banco não suportado")
    info = update.signed_manifest()   # sem a assinatura da ThomSoft, nada é baixado
    plat = ((info.get("dbPlugins") or {}).get(APP_PLATFORM)) or {}
    a = (plat.get("engines") or {}).get(engine)
    if not a or not re.fullmatch(r"[0-9a-f]{64}", str(a.get("sha256", "")).lower()):
        raise PluginError("plugin-unavailable", f"O plugin de {spec['label']} ainda não foi publicado para este sistema")
    sha = a["sha256"].lower()
    urls = [u for u in [a.get("url"), *(a.get("mirrors") or [])] if str(u or "").startswith(update.DOWNLOAD_PREFIXES)]
    want = re.compile(rf"codeck-db-{spec['bin']}-[\w.\-]+")
    urls = [u for u in urls if want.fullmatch(os.path.basename(urllib.parse.urlparse(u).path))]
    if not urls:
        raise PluginError("plugin-unavailable", "O endereço publicado do plugin não é da ThomSoft — nada foi baixado")
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    name = f"codeck-db-{spec['bin']}{EXE}"
    final = os.path.join(PLUGINS_DIR, name)
    part = final + ".part"
    installing[engine] = {"done": 0, "total": int(a.get("size") or 0)}
    try:
        err = None
        for url in urls:
            try:
                update._fetch(url, part, int(a.get("size") or 0), installing[engine])
            except Exception as e:  # noqa: BLE001 — tenta o espelho
                err = e
                continue
            if _sha256(part) == sha:
                break
            err = ValueError("O plugin baixado não confere com o publicado")
        else:
            raise PluginError("plugin-download", f"Não consegui instalar o plugin: {err}")
        os.chmod(part, 0o755)
        stop(engine)   # o plugin antigo (se houver) sai antes da troca
        _retry(os.replace, part, final)
        man = load_json(MANIFEST, {})
        man.setdefault("plugins", {})[engine] = {"sha256": sha, "version": plat.get("version"), "build": plat.get("build")}
        save_json(MANIFEST, man, private=True)
    finally:
        installing.pop(engine, None)
        if os.path.exists(part):
            os.remove(part)
    return status()


def uninstall(engine):
    stop(engine)
    name = f"codeck-db-{ENGINES[engine]['bin']}{EXE}" if engine in ENGINES else None
    if name and os.path.isfile(os.path.join(PLUGINS_DIR, name)):
        _retry(os.remove, os.path.join(PLUGINS_DIR, name))
    man = load_json(MANIFEST, {})
    (man.get("plugins") or {}).pop(engine, None)
    if os.path.isdir(PLUGINS_DIR):
        save_json(MANIFEST, man, private=True)
    return status()


class Plugin:
    def __init__(self, engine):
        path, why = locate(engine)
        if not path:
            raise PluginError("plugin-missing", why)
        # ambiente mínimo: o plugin não herda variáveis do app (tokens, PATH de ferramentas do projeto)
        env = {k: v for k, v in os.environ.items() if k in ("HOME", "USERPROFILE", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "LANG", "TZ",
                                                             "CODECK_FIREBASE_EMULATOR")}   # o último: só a bateria de testes define
        self.engine = engine
        self.proc = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
                                     creationflags=0x08000000 if os.name == "nt" else 0)
        self.lock = threading.Lock()
        self.seq = 0
        self.waiting = {}
        threading.Thread(target=self._read, name=f"db-plugin-{engine}", daemon=True).start()
        hello = self.call("hello", timeout=15)
        if hello.get("protocol") != 1:
            self.stop()
            raise PluginError("plugin-version", "O plugin instalado é de outra versão do Codeck — atualize os plugins")

    def _read(self):
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            slot = self.waiting.pop(msg.get("id"), None)
            if slot:
                slot[1] = msg
                slot[0].set()
        for slot in list(self.waiting.values()):   # o plugin morreu: ninguém fica esperando para sempre
            slot[1] = {"error": {"code": "plugin-died", "message": "O plugin do banco parou — a conexão foi perdida"}}
            slot[0].set()
        self.waiting.clear()

    def alive(self):
        return self.proc.poll() is None

    def call(self, method, params=None, timeout=None):
        slot = [threading.Event(), None]
        with self.lock:
            self.seq += 1
            mid = self.seq
            self.waiting[mid] = slot
            try:
                self.proc.stdin.write((json.dumps({"id": mid, "method": method, "params": params or {}}) + "\n").encode())
                self.proc.stdin.flush()
            except (OSError, ValueError):
                self.waiting.pop(mid, None)
                raise PluginError("plugin-died", "O plugin do banco parou — a conexão foi perdida")
        if not slot[0].wait(timeout):
            self.waiting.pop(mid, None)
            raise PluginError("timeout", "O plugin não respondeu a tempo")
        msg = slot[1]
        if msg.get("error"):
            e = msg["error"]
            raise PluginError(e.get("code") or "db", e.get("message") or "Erro no banco", e.get("data"))
        return msg.get("result")

    def stop(self):
        try:
            self.proc.stdin.close()   # o plugin sai sozinho quando o stdin fecha
            self.proc.wait(3)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()


_plugins = {}
_lock = threading.Lock()


def get(engine):
    with _lock:
        p = _plugins.get(engine)
        if p is None or not p.alive():
            p = _plugins[engine] = Plugin(engine)
        return p


def stop(engine):
    with _lock:
        p = _plugins.pop(engine, None)
    if p:
        p.stop()


def stop_all():
    with _lock:
        for p in _plugins.values():
            p.stop()
        _plugins.clear()
