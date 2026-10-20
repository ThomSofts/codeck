"""Depurar como no Visual Studio / VS Code: breakpoints, parar, passo a passo, variáveis, inspeção, pilha de chamadas
e console de depuração — pelo Debug Adapter Protocol (DAP), o mesmo protocolo do VS Code.

Adaptadores (todos de código aberto, achados na máquina ou baixados para a pasta de dados com a sua permissão):
  - .NET (coreclr): **netcoredbg** (Samsung, MIT). O vsdbg da Microsoft só pode ser usado dentro do VS/VS Code.
  - Node, NestJS, Next.js, React no Chrome: **js-debug** (Microsoft, MIT) — o mesmo do VS Code, no modo servidor DAP.
    Cada processo Node (ou aba do Chrome) vira uma sessão filha (`startDebugging`).
  - Flutter/Dart: o adaptador que vem no próprio SDK (`flutter debug_adapter` / `dart debug_adapter`), com hot reload.

Também guarda as execuções SEM depurar (Ctrl+F5): um terminal "▶" por configuração, com o mesmo estado (rodando,
terminou) e o `serverReadyAction` (abrir o navegador quando o servidor diz "Now listening on…").

A tela acompanha por /api/debug/poll (espera longa: responde assim que algo muda).
"""
import collections
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import tarfile
import threading
import time
import urllib.request
import uuid
import zipfile

from . import launch, terminals
from .core import DATA, load_json, save_json

IS_WIN = os.name == "nt"
TOOLS = os.path.join(DATA, "tools")
BP_FILE = os.path.join(DATA, "breakpoints.json")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)")
DONE = "__CODECK_BUILD_DONE__"


# ---------------------------------------------------------------- adaptadores: achar e instalar
def _path():
    from . import userpath
    return userpath.get()


def _which(name):
    return shutil.which(name, path=_path())


def _netcoredbg():
    exe = "netcoredbg.exe" if IS_WIN else "netcoredbg"
    local = os.path.join(TOOLS, "netcoredbg", exe)
    return local if os.path.isfile(local) else _which("netcoredbg")


def _jsdebug():
    f = os.path.join(TOOLS, "js-debug", "src", "dapDebugServer.js")
    return f if os.path.isfile(f) else None


def adapters():
    """O que está instalado (e o que dá para instalar) para cada tipo de depuração."""
    node = _which("node")
    flutter, dart = _which("flutter"), _which("dart")
    return {
        "dotnet": {"ok": bool(_netcoredbg()), "name": "netcoredbg", "installable": True, "path": _netcoredbg(),
                   "note": "Depurador .NET de código aberto (Samsung, MIT) — ~15 MB"},
        "js": {"ok": bool(_jsdebug() and node), "name": "js-debug", "installable": bool(node), "path": _jsdebug(),
               "note": "O depurador JavaScript do VS Code (Microsoft, MIT) — ~20 MB" if node else "Precisa do Node instalado"},
        "dart": {"ok": bool(flutter or dart), "name": "flutter debug_adapter", "installable": False, "path": flutter or dart,
                 "note": "Vem com o SDK do Flutter/Dart" if (flutter or dart) else "Instale o Flutter (flutter.dev) e reabra o app"},
    }


_installing = {}


def _gh_asset(repo, pick):
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases?per_page=8", headers={"User-Agent": "Codeck", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:   # noqa: S310 — URL fixa do GitHub
        rels = json.load(r)
    for rel in rels:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        for a in rel.get("assets") or []:
            if pick(a["name"]):
                return a["browser_download_url"], rel.get("tag_name")
    raise LookupError(f"Não achei um pacote do {repo} para esta máquina")


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Codeck"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:   # noqa: S310
        shutil.copyfileobj(r, f)


def _safe_extract_zip(z, dest):
    for m in z.infolist():
        target = os.path.realpath(os.path.join(dest, m.filename))
        if not target.startswith(os.path.realpath(dest) + os.sep) and target != os.path.realpath(dest):
            raise ValueError("Pacote inválido")
    z.extractall(dest)


def _safe_extract_tar(arch, dest):
    """Sem links nem caminhos para fora (o filter="data" só existe do Python 3.12 em diante; o do macOS é 3.9)."""
    root = os.path.realpath(dest)
    with tarfile.open(arch) as t:
        members = []
        for m in t.getmembers():
            target = os.path.realpath(os.path.join(dest, m.name))
            if not (target == root or target.startswith(root + os.sep)) or m.issym() or m.islnk() or m.isdev():
                continue
            members.append(m)
        t.extractall(dest, members=members)   # noqa: S202 — membros já conferidos acima


def install(kind):
    """Baixa o adaptador para <dados>/tools (só GitHub oficial do projeto). Devolve o novo estado."""
    if kind not in ("dotnet", "js"):
        raise ValueError("Este depurador não se instala pelo app")
    if _installing.get(kind):
        raise ValueError("Já está instalando")
    _installing[kind] = True
    try:
        os.makedirs(TOOLS, exist_ok=True)
        tmp = os.path.join(TOOLS, f".{kind}-{uuid.uuid4().hex[:6]}")
        os.makedirs(tmp)
        try:
            if kind == "dotnet":
                arm = platform.machine().lower() in ("arm64", "aarch64")
                want = ("win64" if IS_WIN else ("osx-arm64" if arm else "osx-amd64") if os.uname().sysname == "Darwin" else
                        ("linux-arm64" if arm else "linux-amd64"))
                url, tag = _gh_asset("Samsung/netcoredbg", lambda n: want in n)
                arch = os.path.join(tmp, "pkg")
                _download(url, arch)
                if url.endswith(".zip"):
                    with zipfile.ZipFile(arch) as z:
                        _safe_extract_zip(z, tmp)
                else:
                    _safe_extract_tar(arch, tmp)
                src = os.path.join(tmp, "netcoredbg")
                if not os.path.isdir(src):
                    raise ValueError("O pacote do netcoredbg veio diferente do esperado")
                dst = os.path.join(TOOLS, "netcoredbg")
            else:
                url, tag = _gh_asset("microsoft/vscode-js-debug", lambda n: n.startswith("js-debug-dap-") and n.endswith(".tar.gz"))
                arch = os.path.join(tmp, "pkg.tar.gz")
                _download(url, arch)
                _safe_extract_tar(arch, tmp)
                src = os.path.join(tmp, "js-debug")
                dst = os.path.join(TOOLS, "js-debug")
            shutil.rmtree(dst, ignore_errors=True)
            os.replace(src, dst)
            if kind == "dotnet" and not IS_WIN:
                os.chmod(os.path.join(dst, "netcoredbg"), 0o755)
                if os.uname().sysname == "Darwin":   # tira a quarentena (se houver) — senão o macOS barra a execução
                    subprocess.run(["xattr", "-dr", "com.apple.quarantine", dst], capture_output=True, check=False)
            with open(os.path.join(dst, ".codeck-version"), "w") as f:
                f.write(str(tag))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        _installing.pop(kind, None)
    return adapters()


# ---------------------------------------------------------------- conexão DAP (stdio ou TCP)
class DapError(Exception):
    pass


class Conn:
    """Uma conexão DAP: mensagens JSON com cabeçalho Content-Length, nos dois sentidos."""

    def __init__(self, name, rfile, wfile, on_event, on_request, on_close, closer=None):
        self.name, self.rfile, self.wfile = name, rfile, wfile
        self.on_event, self.on_request, self.on_close, self.closer = on_event, on_request, on_close, closer
        self.seq = 0
        self.pending = {}
        self.wlock = threading.Lock()
        self.closed = False
        threading.Thread(target=self._read, daemon=True, name=f"dap-{name}").start()

    def _read(self):
        try:
            while True:
                length = 0
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    line = line.strip()
                    if not line:
                        break
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":", 1)[1])
                body = self.rfile.read(length) if length else b""
                if not body:
                    continue
                try:
                    msg = json.loads(body.decode("utf-8", "replace"))
                except ValueError:
                    continue
                t = msg.get("type")
                if t == "response":
                    p = self.pending.pop(msg.get("request_seq"), None)
                    if p:
                        p["msg"] = msg
                        p["ev"].set()
                        if p.get("cb"):
                            threading.Thread(target=p["cb"], args=(msg,), daemon=True).start()
                elif t == "event":
                    try:
                        self.on_event(msg)
                    except Exception:  # noqa: BLE001
                        pass
                elif t == "request":
                    threading.Thread(target=self._reverse, args=(msg,), daemon=True).start()
        except (OSError, ValueError):
            pass
        finally:
            self.closed = True
            for p in list(self.pending.values()):
                p["msg"] = {"success": False, "message": "o depurador encerrou"}
                p["ev"].set()
            self.pending.clear()
            try:
                self.on_close()
            except Exception:  # noqa: BLE001
                pass

    def _reverse(self, msg):
        try:
            body = self.on_request(msg)
            self._send({"type": "response", "request_seq": msg["seq"], "command": msg["command"], "success": True, "body": body or {}})
        except Exception as e:  # noqa: BLE001
            self._send({"type": "response", "request_seq": msg["seq"], "command": msg["command"], "success": False, "message": str(e)})

    def _send(self, msg, pending=None):
        if self.closed:
            raise DapError("O depurador não está mais conectado")
        with self.wlock:
            self.seq += 1
            msg["seq"] = self.seq
            if pending is not None:
                self.pending[self.seq] = pending
            data = json.dumps(msg).encode("utf-8")
            try:
                self.wfile.write(b"Content-Length: %d\r\n\r\n" % len(data) + data)
                self.wfile.flush()
            except (OSError, ValueError) as e:
                raise DapError("O depurador não está mais conectado") from e
            return self.seq

    def send_request(self, command, arguments=None, cb=None):
        p = {"ev": threading.Event(), "msg": None, "cb": cb}
        msg = {"type": "request", "command": command, "arguments": arguments or {}}
        try:
            self._send(msg, p)
        except DapError:
            self.pending.pop(msg.get("seq"), None)
            raise
        return p

    def request(self, command, arguments=None, timeout=30):
        p = self.send_request(command, arguments)
        if not p["ev"].wait(timeout):
            raise DapError(f"O depurador não respondeu ({command})")
        m = p["msg"]
        if not m.get("success"):
            raise DapError(_err_text(m))
        return m.get("body") or {}

    def close(self):
        self.closed = True
        try:
            if self.closer:
                self.closer()
        except Exception:  # noqa: BLE001
            pass


def _err_text(m):
    e = (m.get("body") or {}).get("error") or {}
    if e.get("format"):
        try:
            return re.sub(r"\{(\w+)\}", lambda x: str((e.get("variables") or {}).get(x.group(1), x.group(0))), e["format"])
        except Exception:  # noqa: BLE001
            return e["format"]
    return m.get("message") or "o depurador recusou"


# ---------------------------------------------------------------- estado (sessões, eventos) e espera longa
_lock = threading.RLock()
_cond = threading.Condition(_lock)
_seq = [0]
_sessions = {}           # id → Session/RunSession
_signals = collections.deque(maxlen=200)   # {seq, type: "open"|"focus"|"notice", …}


def _bump(signal=None):
    with _cond:
        _seq[0] += 1
        if signal:
            _signals.append({**signal, "seq": _seq[0]})
        _cond.notify_all()


def poll(after=0, wait=25, repo_id=None):
    """Espera algo mudar depois de `after` (até `wait` s) e devolve o retrato: sessões + sinais novos."""
    end = time.time() + min(max(wait, 0), 30)
    with _cond:
        while _seq[0] <= after and time.time() < end:
            _cond.wait(max(0.05, end - time.time()))
        items = [s.public() for s in _sessions.values() if not repo_id or s.repo_id == repo_id]
        return {"seq": _seq[0], "sessions": items, "signals": [x for x in _signals if x["seq"] > after]}


def _gc():
    """Sessões encerradas ficam um tempo (mostrar "terminou (1)"); depois saem."""
    with _lock:
        ended = sorted((s for s in _sessions.values() if s.status == "ended"), key=lambda s: s.ended or 0)
        for s in ended[:-12]:
            _sessions.pop(s.id, None)
        for s in ended:
            if s.ended and time.time() - s.ended > 1800:
                _sessions.pop(s.id, None)


# ---------------------------------------------------------------- breakpoints (por projeto, caminho relativo)
def _bp_db():
    return load_json(BP_FILE, {})


def breakpoints(repo_id):
    with _lock:
        d = _bp_db().get(repo_id) or {}
    return {"files": d.get("files") or {}, "exceptions": d.get("exceptions") or {}, "functions": d.get("functions") or []}


def set_breakpoints(repo_id, rel, bps):
    """Troca os breakpoints de um arquivo e manda para as sessões abertas do projeto. Devolve o que cada um virou."""
    rel = str(rel or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise ValueError("Arquivo inválido")
    clean = []
    for b in bps or []:
        try:
            line = int(b.get("line"))
        except (TypeError, ValueError):
            continue
        x = {"line": line, "enabled": b.get("enabled") is not False}
        for k in ("condition", "hitCondition", "logMessage"):
            if str(b.get(k) or "").strip():
                x[k] = str(b[k]).strip()[:500]
        clean.append(x)
    clean = sorted({b["line"]: b for b in clean}.values(), key=lambda b: b["line"])[:500]
    with _lock:
        d = _bp_db()
        p = d.setdefault(repo_id, {})
        files = p.setdefault("files", {})
        if clean:
            files[rel] = clean
        else:
            files.pop(rel, None)
        save_json(BP_FILE, d)
        live = [s for s in _sessions.values() if isinstance(s, Session) and s.repo_id == repo_id and s.alive and s.debugging]
    for s in live:
        threading.Thread(target=s.send_file_breakpoints, args=(rel, clean), daemon=True).start()
    _bump()
    return {"files": files}


def clear_breakpoints(repo_id, rel=None):
    with _lock:
        d = _bp_db()
        files = (d.get(repo_id) or {}).get("files") or {}
        targets = [rel] if rel else list(files)
    for r in targets:
        set_breakpoints(repo_id, r, [])
    return breakpoints(repo_id)


def set_exception_filters(repo_id, kind, filters):
    with _lock:
        d = _bp_db()
        p = d.setdefault(repo_id, {})
        p.setdefault("exceptions", {})[kind] = [str(f)[:80] for f in filters or []][:20]
        save_json(BP_FILE, d)
        live = [s for s in _sessions.values() if isinstance(s, Session) and s.repo_id == repo_id and s.alive and s.debugging and s.adapter == kind]
    for s in live:
        threading.Thread(target=s.send_exception_filters, daemon=True).start()
    _bump()
    return breakpoints(repo_id)


# ---------------------------------------------------------------- sessão de execução (sem depurar)
class RunSession:
    """Ctrl+F5: a configuração rodando num terminal. Acompanha se ainda está viva e o serverReadyAction."""
    debugging = False

    def __init__(self, repo_id, task_id, root, config_id, cfg, group=None):
        self.id = uuid.uuid4().hex[:10]
        self.repo_id, self.task_id, self.root, self.config_id, self.cfg = repo_id, task_id, root, config_id, cfg
        self.name = cfg.get("name") or "?"
        self.group = group or self.id
        self.status, self.error, self.exit_code = "running", None, None
        self.started, self.ended = time.time(), None
        self.term_ids = []
        self.parent = None
        self.url = None

    @property
    def alive(self):
        return self.status != "ended"

    def public(self):
        terms = []
        for tid in self.term_ids:
            try:
                t = terminals.get(tid)
                terms.append(t.alive)
                if not t.alive and self.status != "ended":
                    self.exit_code = t.exit
            except LookupError:
                terms.append(False)
        if self.status != "ended" and terms and not any(terms):
            self.status, self.ended = "ended", time.time()
        return {"id": self.id, "kind": "run", "name": self.name, "configId": self.config_id, "repoId": self.repo_id, "taskId": self.task_id,
                "group": self.group, "parent": None, "status": self.status, "error": self.error, "exitCode": self.exit_code, "terms": self.term_ids,
                "started": self.started, "ended": self.ended, "url": self.url, "adapter": None, "threads": [], "stopped": None, "outSeq": 0, "caps": {}}

    def stop(self):
        for tid in self.term_ids:
            terminals.close(tid)
        self.status, self.ended = "ended", time.time()
        _bump()


def _watch_ready(sess, term, action):
    """serverReadyAction: espera o padrão na saída e abre o navegador (ou o Chrome depurando)."""
    if not action or action.get("action") not in ("openExternally", "debugWithChrome", "debugWithEdge", None):
        return
    try:
        pat = re.compile(action.get("pattern") or r"listening on.* (https?://\S+|[0-9]+)", re.I)
    except re.error:
        return
    buf = {"t": "", "done": False}

    def feed(data):
        if buf["done"] or data is None:
            return
        buf["t"] = (buf["t"] + ANSI.sub("", data.decode("utf-8", "replace")))[-4000:]
        m = pat.search(buf["t"])
        if not m:
            return
        buf["done"] = True
        val = m.group(1) if m.groups() else m.group(0)
        if val.isdigit():
            val = f"http://localhost:{val}"
        fmt = action.get("uriFormat") or "%s"
        url = fmt.replace("%s", val, 1) if "%s" in fmt else fmt
        url = re.sub(r"(?<!:)//+", "/", url.replace("://", "\0")).replace("\0", "://")
        sess.url = url
        term.detach(feed)
        if action.get("action") in ("debugWithChrome", "debugWithEdge") and sess.debugging:
            threading.Thread(target=_start_browser_child, args=(sess, url, action), daemon=True).start()
        else:
            _bump({"type": "open", "url": url, "session": sess.id, "repoId": sess.repo_id})
    history, _, _ = term.attach(feed)
    if history:
        feed(history[-8000:])


def _start_browser_child(sess, url, action):
    cfg = {"type": "pwa-msedge" if action.get("action") == "debugWithEdge" else "pwa-chrome", "request": "launch", "url": url,
           "name": f"{sess.name} · navegador", "webRoot": launch.resolve_vars(action.get("webRoot") or "${workspaceFolder}", sess.root)}
    try:
        s = Session(sess.repo_id, sess.task_id, sess.root, sess.config_id, cfg, "js", group=sess.group)
        s.name = cfg["name"]
        with _lock:
            _sessions[s.id] = s
        s.start()
    except Exception as e:  # noqa: BLE001
        _bump({"type": "notice", "level": "error", "text": f"Não abri o navegador depurando: {e}", "repoId": sess.repo_id})


# ---------------------------------------------------------------- sessão de depuração
class Session:
    debugging = True

    def __init__(self, repo_id, task_id, root, config_id, cfg, adapter, group=None, parent=None, no_debug=False, device=None):
        self.id = uuid.uuid4().hex[:10]
        self.repo_id, self.task_id, self.root, self.config_id = repo_id, task_id, root, config_id
        self.cfg, self.adapter, self.parent, self.no_debug, self.device = cfg, adapter, parent, no_debug, device
        self.name = cfg.get("name") or "?"
        self.group = group or self.id
        self.status = "starting"   # building → starting → running ⇄ stopped → ended
        self.error = None
        self.exit_code = None
        self.started, self.ended = time.time(), None
        self.conn = None
        self.proc = None
        self.caps = {}
        self.threads = {}
        self.stopped = None
        self.frames = {}
        self.output = collections.deque(maxlen=4000)
        self.out_seq = 0
        self.term_ids = []
        self.build_term = None
        self.children = []
        self.verified = {}          # rel → [{line, verified, message}]
        self.url = None
        self.hot = adapter == "dart"
        self.boot = None            # ligando o emulador/simulador antes de subir o Flutter
        self.device_pref = None     # o aparelho escolhido/ligado pelo backend, para a tela lembrar
        # Flutter: a URI da VM (o DevTools conecta nela), o isolate da UI e as extensões de serviço (debug paint…)
        self.vm_uri, self.isolate, self.app_mode = None, None, None
        self.exts, self.ext_state, self.ext_user = set(), {}, {}
        self._initialized = threading.Event()
        self._closing = False

    @property
    def alive(self):
        return self.status != "ended"

    def public(self):
        return {"id": self.id, "kind": "debug", "name": self.name, "configId": self.config_id, "repoId": self.repo_id, "taskId": self.task_id,
                "group": self.group, "parent": self.parent.id if self.parent else None, "status": self.status, "error": self.error,
                "exitCode": self.exit_code, "terms": self.term_ids, "buildTerm": self.build_term, "started": self.started, "ended": self.ended,
                "adapter": self.adapter, "noDebug": self.no_debug, "device": self.device, "url": self.url,
                "threads": [{"id": k, "name": v} for k, v in self.threads.items()], "stopped": self.stopped, "outSeq": self.out_seq,
                "verified": self.verified, "hot": self.hot, "boot": self.boot, "devicePref": self.device_pref,
                "flutter": {"vmUri": self.vm_uri, "mode": self.app_mode, "tools": bool(self.isolate and not self.no_debug),
                            "exts": sorted(self.exts & FLUTTER_EXTS), "state": self.ext_state} if self.adapter == "dart" else None,
                "caps": {"exceptionFilters": self.caps.get("exceptionBreakpointFilters") or [], "restart": bool(self.caps.get("supportsRestartRequest")),
                         "setVariable": bool(self.caps.get("supportsSetVariable")), "conditional": bool(self.caps.get("supportsConditionalBreakpoints")),
                         "logPoints": bool(self.caps.get("supportsLogPoints")), "hitConditional": bool(self.caps.get("supportsHitConditionalBreakpoints")),
                         "terminateThreads": bool(self.caps.get("supportsTerminateThreadsRequest"))}}

    # -------------------------------------------------------- saída (console de depuração)
    def out(self, text, cat="console"):
        if not text:
            return
        with _lock:
            self.out_seq += 1
            self.output.append({"seq": self.out_seq, "cat": cat, "text": text[:20000]})
        _bump()

    def read_output(self, after=0):
        with _lock:
            return {"seq": self.out_seq, "items": [x for x in self.output if x["seq"] > after]}

    def _end(self, error=None):
        if self.status == "ended":
            return
        self.status, self.ended = "ended", time.time()
        if error and not self.error:
            self.error = error
        self.stopped = None
        _bump()
        for c in list(self.children):
            c._end()

    # -------------------------------------------------------- iniciar
    def _spawn(self):
        env = terminals.clean_env(launch.run_env(self.cfg) if self.adapter == "dart" else None)
        cwd = self.cfg.get("cwd") or self.root
        if not os.path.isdir(cwd):
            cwd = self.root
        flags = 0x08000000 if IS_WIN else 0
        if self.adapter == "dotnet":
            exe = _netcoredbg()
            if not exe:
                raise LookupError("need-adapter:dotnet")
            argv = [exe, "--interpreter=vscode"]
        elif self.adapter == "dart":
            flutter = (self.cfg.get("codeck") or {}).get("kind") == "flutter" or self.cfg.get("type") == "flutter" or _is_flutter(cwd)
            exe = _which("flutter" if flutter else "dart") or _which("dart")
            if not exe:
                raise LookupError("need-adapter:dart")
            argv = [exe, "debug_adapter"]
            if IS_WIN and exe.lower().endswith((".bat", ".cmd")):
                argv = ["cmd.exe", "/c", exe, "debug_adapter"]
        elif self.adapter == "js":
            host, port = _js_server()
            sock = socket.create_connection((host, port), timeout=10)
            sock.settimeout(None)
            self.conn = Conn(self.name, sock.makefile("rb"), sock.makefile("wb"), self._event, self._reverse, self._closed,
                             closer=lambda: _close_sock(sock))
            return
        else:
            raise ValueError("Tipo de depuração sem adaptador")
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
        threading.Thread(target=self._stderr, daemon=True).start()
        self.conn = Conn(self.name, self.proc.stdout, self.proc.stdin, self._event, self._reverse, self._closed, closer=self._kill)

    def _stderr(self):
        try:
            for line in self.proc.stderr:
                t = line.decode("utf-8", "replace")
                if t.strip():
                    self.out(t, "stderr")
        except (OSError, ValueError):
            pass

    def _kill(self):
        p = self.proc
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=3)
            except Exception:  # noqa: BLE001
                p.kill()

    def start(self, attach_args=None):
        """Sobe o adaptador, initialize → launch/attach → breakpoints → configurationDone. Roda numa thread."""
        try:
            self._spawn()
            adapter_id = {"dotnet": "coreclr", "dart": "dart", "js": self.cfg.get("type") or "pwa-node"}[self.adapter]
            self.caps = self.conn.request("initialize", {
                "clientID": "codeck", "clientName": "Codeck", "adapterID": adapter_id, "pathFormat": "path", "linesStartAt1": True,
                "columnsStartAt1": True, "supportsVariableType": True, "supportsVariablePaging": False, "supportsRunInTerminalRequest": True,
                "supportsStartDebuggingRequest": True, "supportsProgressReporting": False, "supportsInvalidatedEvent": False,
                "supportsMemoryReferences": False, "supportsArgsCanBeInterpretedByShell": True, "locale": "pt-BR"}, timeout=30)
            req = (attach_args or {}).get("request") or self.cfg.get("request") or "launch"
            args = attach_args or self._launch_args()
            pending = self.conn.send_request(req, args)
            # alguns adaptadores só respondem o launch depois do configurationDone; o "initialized" vem antes
            if not self._initialized.wait(45):
                if pending["ev"].is_set() and not pending["msg"].get("success"):
                    raise DapError(_err_text(pending["msg"]))
                raise DapError("O depurador não ficou pronto (initialized)")
            if not self.no_debug:
                self.send_all_breakpoints()
                self.send_exception_filters()
            if self.caps.get("supportsConfigurationDoneRequest", True):
                self.conn.request("configurationDone", {}, timeout=30)
            if not pending["ev"].wait(120):
                raise DapError("O depurador não confirmou o início")
            if not pending["msg"].get("success"):
                raise DapError(_err_text(pending["msg"]))
            if self.status == "starting":
                self.status = "running"
            _bump()
        except LookupError as e:
            self._end(str(e))
            self.conn and self.conn.close()
        except Exception as e:  # noqa: BLE001
            self.out(f"Não consegui iniciar a depuração: {e}\n", "stderr")
            self._end(str(e))
            self.conn and self.conn.close()

    def _launch_args(self):
        c = {k: v for k, v in self.cfg.items() if k not in ("codeck", "preLaunchTask", "postDebugTask", "serverReadyAction", "presentation", "internalConsoleOptions")}
        c["__sessionId"] = self.id
        if self.no_debug:
            c["noDebug"] = True
        if self.adapter == "dotnet":
            c["type"] = "coreclr"
            c.setdefault("cwd", self.root)
            env = {**_launch_settings_env(self.cfg, self.root), **launch.run_env(self.cfg)}
            c["env"] = env
            c.pop("envFile", None)
            c.setdefault("justMyCode", True)
            c.setdefault("stopAtEntry", False)
            c["console"] = "internalConsole"
        elif self.adapter == "js":
            t = c.get("type")
            c["type"] = {"node": "pwa-node", "chrome": "pwa-chrome", "msedge": "pwa-msedge"}.get(t, t)
            if c["type"] == "node-terminal":
                # o node-terminal é do VS Code (abre o terminal pela API dele); no servidor DAP o equivalente é o pwa-node
                # com o comando como runtimeExecutable: o js-debug põe o bootloader no NODE_OPTIONS e todo processo node
                # filho (npm → nest/next/vite) vira uma sessão depurável
                c["type"] = "pwa-node"
                c["runtimeExecutable"], c["runtimeArgs"] = _split_command(c.pop("command", "") or "npm start")
                c.setdefault("autoAttachChildProcesses", True)
            env = launch.run_env(self.cfg)
            if env:
                c["env"] = env
            c.pop("envFile", None)
            c.setdefault("cwd", self.root)
            if c["type"] in ("pwa-node", "node-terminal"):
                c.setdefault("console", "integratedTerminal")
                c.setdefault("skipFiles", ["<node_internals>/**"])
                c.setdefault("resolveSourceMapLocations", ["${workspaceFolder}/**", "!**/node_modules/**"])
                c["resolveSourceMapLocations"] = launch.resolve_vars(c["resolveSourceMapLocations"], self.root)
                c["skipFiles"] = launch.resolve_vars(c["skipFiles"], self.root)
            if c["type"] in ("pwa-chrome", "pwa-msedge"):
                c.setdefault("webRoot", self.root)
                c.setdefault("userDataDir", os.path.join(DATA, "chrome-debug-profile"))
        elif self.adapter == "dart":
            c["type"] = "dart"
            c.pop("deviceId", None)   # do launch.json do VS Code: vira o -d abaixo
            c.setdefault("cwd", self.root)
            tool = list(c.get("toolArgs") or [])
            if self.device and "-d" not in tool:
                tool += ["-d", self.device]
            mode = c.pop("flutterMode", None)
            if mode in ("profile", "release"):
                tool.append("--" + mode)
            if tool:
                c["toolArgs"] = tool
            env = launch.run_env(self.cfg)
            if env:
                c["env"] = env
            c.pop("envFile", None)
            c.setdefault("sendLogsToClient", False)
        return c

    # -------------------------------------------------------- breakpoints
    def _abs(self, rel):
        return os.path.normpath(os.path.join(self.root, rel))

    def _rel(self, path):
        if not path:
            return None, None
        p = os.path.normpath(path)
        try:
            r = os.path.relpath(p, self.root)
        except ValueError:
            return None, p
        if r.startswith(".."):
            return None, p
        return r.replace(os.sep, "/"), p

    def send_file_breakpoints(self, rel, bps):
        if not self.conn or self.conn.closed or self.no_debug or not self.debugging:
            return
        if self.adapter == "js" and not self.parent and self.children:
            pass   # a sessão-mãe do js-debug também aceita (repassa às filhas); manda para todas
        on = [b for b in bps if b.get("enabled", True)]
        args = {"source": {"path": self._abs(rel), "name": os.path.basename(rel)},
                "breakpoints": [{k: v for k, v in b.items() if k in ("line", "condition", "hitCondition", "logMessage")} for b in on],
                "lines": [b["line"] for b in on], "sourceModified": False}
        try:
            r = self.conn.request("setBreakpoints", args, timeout=20)
            res = r.get("breakpoints") or []
            self.verified[rel] = [{"line": (res[i].get("line") if i < len(res) else None) or b["line"], "asked": b["line"],
                                   "id": res[i].get("id") if i < len(res) else None,
                                   "verified": bool(i < len(res) and res[i].get("verified")), "message": (res[i].get("message") if i < len(res) else None)}
                                  for i, b in enumerate(on)]
            _bump()
        except DapError:
            pass
        for c in list(self.children):
            c.send_file_breakpoints(rel, bps)

    def send_all_breakpoints(self):
        files = breakpoints(self.repo_id)["files"]
        for rel, bps in files.items():
            if not os.path.isfile(self._abs(rel)):
                continue
            if not any(b.get("enabled", True) for b in bps):
                continue
            self.send_file_breakpoints(rel, bps)
        fns = breakpoints(self.repo_id).get("functions") or []
        if fns and self.caps.get("supportsFunctionBreakpoints"):
            try:
                self.conn.request("setFunctionBreakpoints", {"breakpoints": [{"name": f} for f in fns]}, timeout=10)
            except DapError:
                pass

    def send_exception_filters(self):
        if not self.conn or self.conn.closed or self.no_debug:
            return
        avail = self.caps.get("exceptionBreakpointFilters") or []
        if not avail:
            return
        saved = breakpoints(self.repo_id)["exceptions"].get(self.adapter)
        filters = saved if saved is not None else [f["filter"] for f in avail if f.get("default")]
        filters = [f for f in filters if any(a["filter"] == f for a in avail)]
        try:
            self.conn.request("setExceptionBreakpoints", {"filters": filters}, timeout=10)
        except DapError:
            pass

    # -------------------------------------------------------- eventos e pedidos do adaptador
    def _event(self, msg):
        ev, body = msg.get("event"), msg.get("body") or {}
        if ev == "initialized":
            self._initialized.set()
        elif ev == "output":
            cat = body.get("category") or "console"
            if cat == "telemetry":
                return
            text = body.get("output") or ""
            if body.get("variablesReference") and not text.strip():
                return
            self.out(text, cat)
            self._ready_check(text)
        elif ev == "stopped":
            tid = body.get("threadId")
            self.status = "stopped"
            self.stopped = {"threadId": tid, "reason": body.get("reason"), "text": body.get("text") or body.get("description"),
                            "description": body.get("description"), "all": body.get("allThreadsStopped", True), "top": None, "at": time.time()}
            threading.Thread(target=self._after_stop, args=(tid,), daemon=True).start()
            _bump()
        elif ev == "continued":
            if body.get("allThreadsContinued", True) or not self.stopped or self.stopped.get("threadId") == body.get("threadId"):
                self.status, self.stopped, self.frames = "running", None, {}
                _bump()
        elif ev == "thread":
            tid = body.get("threadId")
            if body.get("reason") == "exited":
                self.threads.pop(tid, None)
            else:
                self.threads.setdefault(tid, f"Thread #{tid}")
                threading.Thread(target=self._refresh_threads, daemon=True).start()
            _bump()
        elif ev == "exited":
            self.exit_code = body.get("exitCode")
            _bump()
        elif ev == "terminated":
            if body.get("restart") is not None and self.adapter == "js":
                pass
            self._end()
            threading.Thread(target=self._shutdown, daemon=True).start()
        elif ev == "breakpoint":
            bp = body.get("breakpoint") or {}
            if bp.get("id") is not None:   # o adaptador confirmou (ou moveu) um breakpoint depois que o código carregou
                for items in self.verified.values():
                    for x in items:
                        if x.get("id") == bp["id"]:
                            x["verified"] = bool(bp.get("verified"))
                            x["line"] = bp.get("line") or x["line"]
                            x["message"] = bp.get("message")
            _bump()
        elif ev == "process":
            if self.status == "starting":
                self.status = "running"
            _bump()
        elif ev in ("flutter.appStarted", "flutter.appStart"):
            if ev == "flutter.appStart":
                self.app_mode = body.get("mode")
            if self.status == "starting":
                self.status = "running"
            self.hot = True
            _bump()
        elif ev == "dart.serviceExtensionAdded":
            rpc, iso = body.get("extensionRPC"), body.get("isolateId")
            if iso and iso != self.isolate:   # hot restart: isolate novo, as extensões se registram de novo
                self.isolate, self.exts = iso, set()
            self.exts.add(rpc)
            if rpc in FLUTTER_EXTS and rpc not in FLUTTER_DUMPS:
                # o estado atual (sem parâmetro a extensão só responde); o que foi ligado aqui volta depois do hot restart
                threading.Thread(target=self._ext_sync, args=(rpc,), daemon=True).start()
            if self.status == "starting":
                self.status = "running"
            self.hot = True
            _bump()
        elif ev == "flutter.serviceExtensionStateChanged":   # mudou pelo DevTools (ou pelo app)
            if body.get("extension"):
                self.ext_state[body["extension"]] = body.get("value")
                _bump()
        elif ev == "dart.debuggerUris":
            self.vm_uri = body.get("vmServiceUri") or self.vm_uri
            _bump()

    def _reverse(self, msg):
        cmd, args = msg.get("command"), msg.get("arguments") or {}
        if cmd == "runInTerminal":
            return self._run_in_terminal(args)
        if cmd == "startDebugging":
            conf = args.get("configuration") or {}
            child = Session(self.repo_id, self.task_id, self.root, self.config_id, {**conf, "name": conf.get("name") or self.name},
                            "js", group=self.group, parent=self, no_debug=self.no_debug)
            child.name = conf.get("name") or self.name
            with _lock:
                _sessions[child.id] = child
            self.children.append(child)
            threading.Thread(target=child.start, kwargs={"attach_args": {**conf, "request": args.get("request") or "attach"}}, daemon=True).start()
            _bump()
            return {}
        if cmd == "handshake":
            raise DapError("sem suporte")
        raise DapError(f"pedido não suportado: {cmd}")

    def _run_in_terminal(self, args):
        """O programa (o node/npm do js-debug) roda num terminal "▶" do projeto — saída colorida e entrada de teclado."""
        a = [str(x) for x in args.get("args") or []]
        cwd = args.get("cwd") or self.root
        env = {k: v for k, v in (args.get("env") or {}).items() if v is not None}
        if len(a) == 1 or args.get("argsCanBeInterpretedByShell"):
            cmd = " ".join(a)
        else:
            cmd = " ".join(launch._q(x) for x in a)
        root = self.parent or self
        meta = {"project": self.repo_id, "run": self.config_id, "debug": root.id, **({"task": self.task_id} if self.task_id else {})}
        t = terminals.create(cwd, "🐞 " + (root.name or "depurar"), cmd, "run", meta, env or None, shell=launch.scope_settings_shell(self.repo_id))
        root.term_ids.append(t.id)
        sra = (root.cfg or {}).get("serverReadyAction")
        if sra:
            threading.Thread(target=_watch_ready, args=(root, t, sra), daemon=True).start()
        _bump({"type": "focus", "term": t.id, "repoId": self.repo_id, "taskId": self.task_id})
        pid = getattr(getattr(t.pty, "proc", None), "pid", None)
        return {"processId": pid} if pid else {}

    def _ready_check(self, text):
        sra = self.cfg.get("serverReadyAction") if not self.parent else None
        if not sra or self.url:
            return
        try:
            m = re.search(sra.get("pattern") or r"listening on.* (https?://\S+|[0-9]+)", ANSI.sub("", text), re.I)
        except re.error:
            return
        if not m:
            return
        val = m.group(1) if m.groups() else m.group(0)
        if val.isdigit():
            val = f"http://localhost:{val}"
        fmt = sra.get("uriFormat") or "%s"
        url = fmt.replace("%s", val, 1) if "%s" in fmt else fmt
        url = re.sub(r"(?<!:)//+", "/", url.replace("://", "\0")).replace("\0", "://")
        self.url = url
        if sra.get("action") in ("debugWithChrome", "debugWithEdge"):
            threading.Thread(target=_start_browser_child, args=(self, url, sra), daemon=True).start()
        else:
            _bump({"type": "open", "url": url, "session": self.id, "repoId": self.repo_id})

    def _closed(self):
        if self.status != "ended":
            self._end(None if self._closing else ("o depurador encerrou" if self.status == "starting" else None))
        with _lock:
            _gc()

    def _refresh_threads(self):
        try:
            r = self.conn.request("threads", {}, timeout=10)
            self.threads = {t["id"]: t.get("name") or f"Thread #{t['id']}" for t in r.get("threads") or []}
            _bump()
        except DapError:
            pass

    def _after_stop(self, tid):
        self._refresh_threads()
        if tid is None and self.threads:
            tid = next(iter(self.threads))
            if self.stopped:
                self.stopped["threadId"] = tid
        if tid is None:
            return
        try:
            frames = self.stack(tid)
        except DapError:
            frames = []
        top = next((f for f in frames if f.get("path") or f.get("abs")), frames[0] if frames else None)
        if self.stopped and self.stopped.get("threadId") == tid:
            self.stopped["top"] = top
            if (self.stopped.get("reason") == "exception") and self.caps.get("supportsExceptionInfoRequest"):
                try:
                    ex = self.conn.request("exceptionInfo", {"threadId": tid}, timeout=10)
                    self.stopped["exception"] = {"id": ex.get("exceptionId"), "description": ex.get("description"),
                                                 "type": ((ex.get("details") or {}).get("typeName")), "message": ((ex.get("details") or {}).get("message"))}
                except DapError:
                    pass
        _bump({"type": "stopped", "session": self.id, "repoId": self.repo_id, "taskId": self.task_id, "top": top,
               "reason": (self.stopped or {}).get("reason")})

    # -------------------------------------------------------- inspeção
    def stack(self, tid, levels=60):
        r = self.conn.request("stackTrace", {"threadId": tid, "startFrame": 0, "levels": levels}, timeout=15)
        out = []
        for f in r.get("stackFrames") or []:
            src = f.get("source") or {}
            rel, absp = self._rel(src.get("path"))
            out.append({"id": f["id"], "name": f.get("name"), "line": f.get("line") or 0, "col": f.get("column") or 0, "path": rel, "abs": absp,
                        "source": src.get("name"), "ref": src.get("sourceReference") or 0, "hint": f.get("presentationHint") or src.get("presentationHint"),
                        "external": rel is None})
        self.frames[tid] = out
        return out

    def scopes(self, frame_id):
        r = self.conn.request("scopes", {"frameId": frame_id}, timeout=15)
        return [{"name": s.get("name"), "ref": s.get("variablesReference"), "expensive": bool(s.get("expensive")), "hint": s.get("presentationHint")}
                for s in r.get("scopes") or []]

    def variables(self, ref):
        r = self.conn.request("variables", {"variablesReference": ref}, timeout=20)
        return [{"name": v.get("name"), "value": v.get("value"), "type": v.get("type"), "ref": v.get("variablesReference") or 0,
                 "evaluateName": v.get("evaluateName"), "hint": (v.get("presentationHint") or {}).get("kind")} for v in (r.get("variables") or [])[:2000]]

    def evaluate(self, expr, frame_id=None, context="repl"):
        args = {"expression": expr, "context": context}
        if frame_id:
            args["frameId"] = frame_id
        r = self.conn.request("evaluate", args, timeout=20)
        return {"result": r.get("result"), "type": r.get("type"), "ref": r.get("variablesReference") or 0}

    def set_variable(self, ref, name, value):
        r = self.conn.request("setVariable", {"variablesReference": ref, "name": name, "value": value}, timeout=15)
        return {"value": r.get("value"), "type": r.get("type"), "ref": r.get("variablesReference") or 0}

    def source(self, ref, path=None):
        r = self.conn.request("source", {"sourceReference": ref, **({"source": {"path": path, "sourceReference": ref}} if path else {})}, timeout=15)
        return {"content": r.get("content") or "", "mime": r.get("mimeType")}

    # -------------------------------------------------------- Flutter: extensões de serviço (as chaves do DevTools)
    def service(self, method, params=None):
        """Chama uma extensão de serviço do app (ext.flutter.debugPaint…) pelo adaptador (`callService`)."""
        if self.adapter != "dart":
            raise ValueError("Só para apps Flutter/Dart")
        if not re.fullmatch(r"ext\.[\w.]+", str(method or "")):
            raise ValueError("Extensão inválida")
        if self.no_debug or not self.isolate:
            raise ValueError("Precisa do app rodando depurando (F5, modo debug)" if self.no_debug or self.app_mode in ("profile", "release")
                             else "O app ainda não terminou de subir")
        args = {k: str(v) for k, v in (params or {}).items()}
        r = self.conn.request("callService", {"method": method, "params": {"isolateId": self.isolate, **args}}, timeout=30) or {}
        val = r.get("enabled", r.get("value", r.get(method.rsplit(".", 1)[-1])))
        if val is not None and "data" not in r:
            self.ext_state[method] = val
            if args:
                self.ext_user[method] = args
        _bump()
        return {"value": val, "data": r.get("data")}

    def _ext_sync(self, rpc):
        try:
            if rpc in self.ext_user:
                self.service(rpc, self.ext_user[rpc])
            else:
                self.service(rpc)
        except Exception:  # noqa: BLE001
            pass

    # -------------------------------------------------------- controle
    def control(self, action, tid=None):
        tid = tid or (self.stopped or {}).get("threadId") or next(iter(self.threads), None)
        if action in ("continue", "next", "stepIn", "stepOut") and tid is None:
            raise ValueError("Nenhuma thread parada")
        if action == "continue":
            self.conn.request("continue", {"threadId": tid}, timeout=15)
            self.status, self.stopped, self.frames = "running", None, {}
        elif action in ("next", "stepIn", "stepOut"):
            self.conn.request(action, {"threadId": tid}, timeout=15)
            self.status, self.stopped, self.frames = "running", None, {}
        elif action == "pause":
            self.conn.request("pause", {"threadId": tid or 0}, timeout=15)
        elif action in ("hotReload", "hotRestart"):
            if self.adapter != "dart":
                raise ValueError("Hot reload é do Flutter")
            self.conn.request(action, {"reason": "manual"}, timeout=60)
            self.out(("Hot reload" if action == "hotReload" else "Hot restart") + " ✓\n", "console")
        else:
            raise ValueError("Ação inválida")
        _bump()
        return {"ok": True}

    def disconnect(self):
        self._closing = True
        try:
            if self.conn and not self.conn.closed:
                if self.caps.get("supportsTerminateRequest") and not self.parent:
                    try:
                        self.conn.request("terminate", {}, timeout=4)
                    except DapError:
                        pass
                self.conn.request("disconnect", {"terminateDebuggee": True, "restart": False}, timeout=6)
        except DapError:
            pass
        threading.Thread(target=self._shutdown, args=(0.6,), daemon=True).start()

    def _shutdown(self, grace=1.5):
        time.sleep(grace)
        if self.conn:
            self.conn.close()
        for tid in self.term_ids:
            try:
                terminals.close(tid)
            except Exception:  # noqa: BLE001
                pass
        if self.build_term and self.status == "ended":
            pass
        self._end()


def _split_command(cmd):
    """"npm run dev" → ("npm", ["run", "dev"]); com operadores do shell (&&, |, $VAR=…), roda pelo shell."""
    import shlex
    if not re.search(r"[&|;<>`$()]|^\s*\w+=", cmd):
        try:
            parts = shlex.split(cmd, posix=not IS_WIN)
            if parts:
                return parts[0], parts[1:]
        except ValueError:
            pass
    if IS_WIN:
        return "cmd.exe", ["/d", "/s", "/c", cmd]
    return "/bin/sh", ["-c", cmd]


def _close_sock(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    sock.close()


def _wants_device(cfg, root):
    """Precisa escolher o aparelho? As detectadas dizem; as do launch.json/salvas: Flutter sem -d nos toolArgs."""
    c = cfg.get("codeck") or {}
    if "device" in c:
        return bool(c["device"])
    if "-d" in (cfg.get("toolArgs") or []) or "--device-id" in (cfg.get("toolArgs") or []):
        return False
    cwd = cfg.get("cwd") if cfg.get("cwd") and os.path.isdir(cfg.get("cwd")) else root
    return cfg.get("type") == "flutter" or _is_flutter(cwd)


def _is_flutter(d):
    try:
        return bool(re.search(r"^\s+sdk:\s*flutter\s*$", open(os.path.join(d, "pubspec.yaml"), encoding="utf-8").read(), re.M))
    except OSError:
        return False


def _launch_settings_env(cfg, root):
    """O C# do VS Code lê o launchSettings.json (perfil) para o ambiente e a URL; o netcoredbg não — o app lê."""
    prof = cfg.get("launchSettingsProfile") or (cfg.get("codeck") or {}).get("profile")
    proj = (cfg.get("codeck") or {}).get("project")
    pdir = os.path.dirname(os.path.join(root, proj)) if proj else None
    if not pdir:
        prog = str(cfg.get("program") or "").replace("\\", "/")
        if "/bin/" in prog:
            pdir = prog.split("/bin/")[0]
    env = {}
    if pdir:
        lsf = cfg.get("launchSettingsFilePath") or os.path.join(pdir, "Properties", "launchSettings.json")
        if os.path.isfile(lsf):
            try:
                profs = launch._jsonc(open(lsf, encoding="utf-8-sig").read()).get("profiles") or {}
            except Exception:  # noqa: BLE001
                profs = {}
            p = profs.get(prof) if prof else next((v for v in profs.values() if (v or {}).get("commandName") == "Project"), None)
            p = p or {}
            env.update({k: str(v) for k, v in (p.get("environmentVariables") or {}).items()})
            if p.get("applicationUrl"):
                env.setdefault("ASPNETCORE_URLS", p["applicationUrl"])
    if pdir and os.path.isfile(os.path.join(pdir, "appsettings.Development.json")):
        env.setdefault("ASPNETCORE_ENVIRONMENT", "Development")
    return env


# ---------------------------------------------------------------- servidor do js-debug (um só para o app)
_js = {"proc": None, "port": None}
_js_lock = threading.Lock()


def _js_server():
    with _js_lock:
        p = _js["proc"]
        if p and p.poll() is None:
            return "127.0.0.1", _js["port"]
        script, node = _jsdebug(), _which("node")
        if not script or not node:
            raise LookupError("need-adapter:js")
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        env = terminals.clean_env()
        _js["proc"] = subprocess.Popen([node, script, str(port), "127.0.0.1"], cwd=os.path.dirname(os.path.dirname(script)), env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=0x08000000 if IS_WIN else 0)
        _js["port"] = port
        end = time.time() + 15
        while time.time() < end:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                threading.Thread(target=lambda pr=_js["proc"]: [None for _ in pr.stdout], daemon=True).start()   # esvazia a saída
                return "127.0.0.1", port
            except OSError:
                if _js["proc"].poll() is not None:
                    break
                time.sleep(0.15)
        raise DapError("O js-debug não subiu")


# ---------------------------------------------------------------- DevTools do Flutter (um servidor para o app)
# O mesmo do VS Code: `dart devtools --machine` serve a interface; cada página conecta na VM do app pela URI que o
# adaptador manda (dart.debuggerUris). A tela abre numa aba do Codeck (iframe) ou no navegador.
FLUTTER_EXTS = {"ext.flutter.inspector.show", "ext.flutter.debugPaint", "ext.flutter.debugPaintBaselinesEnabled", "ext.flutter.repaintRainbow",
                "ext.flutter.showPerformanceOverlay", "ext.flutter.debugAllowBanner", "ext.flutter.timeDilation", "ext.flutter.invertOversizedImages",
                "ext.flutter.brightnessOverride", "ext.flutter.platformOverride", "ext.flutter.debugDumpApp", "ext.flutter.debugDumpRenderTree",
                "ext.flutter.debugDumpLayerTree", "ext.flutter.debugDumpSemanticsTreeInTraversalOrder", "ext.flutter.debugDumpFocusTree"}
FLUTTER_DUMPS = {"ext.flutter.debugDumpApp", "ext.flutter.debugDumpRenderTree", "ext.flutter.debugDumpLayerTree",
                 "ext.flutter.debugDumpSemanticsTreeInTraversalOrder", "ext.flutter.debugDumpFocusTree"}
DEVTOOLS_PAGES = ("", "inspector", "performance", "cpu-profiler", "memory", "network", "logging", "app-size", "deep-links", "vm-tools")
_dt = {"proc": None, "url": None}
_dt_lock = threading.Lock()


def _devtools_server():
    with _dt_lock:
        p = _dt["proc"]
        if p and p.poll() is None and _dt["url"]:
            return _dt["url"]
        dart = _which("dart")
        if not dart:
            raise LookupError("O DevTools vem com o SDK do Flutter/Dart — instale o Flutter e reabra o app")
        argv = [dart, "devtools", "--machine", "--no-launch-browser", "--host=127.0.0.1", "--port=0"]
        if IS_WIN and dart.lower().endswith((".bat", ".cmd")):
            argv = ["cmd.exe", "/c"] + argv
        proc = subprocess.Popen(argv, env=terminals.clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=0x08000000 if IS_WIN else 0)
        _dt.update(proc=proc, url=None)
        got, ready = {}, threading.Event()

        def read():   # {"event":"server.started","params":{"host":"127.0.0.1","port":9100,…}}; depois só esvazia a saída
            for raw in proc.stdout:
                try:
                    j = json.loads(raw.decode("utf-8", "replace").strip() or "{}")
                except ValueError:
                    continue
                if j.get("event") == "server.started" and (j.get("params") or {}).get("port"):
                    got["url"] = f"http://{j['params'].get('host') or '127.0.0.1'}:{j['params']['port']}"
                    ready.set()
            ready.set()
        threading.Thread(target=read, daemon=True, name="devtools").start()
        if not ready.wait(90) or not got.get("url"):
            _devtools_kill()
            raise DapError("O DevTools não subiu (dart devtools)")
        _dt["url"] = got["url"]
        return _dt["url"]


def _devtools_kill():
    p = _dt.get("proc")
    if p and p.poll() is None:
        try:
            p.kill()
        except OSError:
            pass
    _dt.update(proc=None, url=None)


def devtools(sid, page="", theme="dark", embed=False):
    """A URL do DevTools conectado ao app desta sessão, já na página pedida (inspetor, performance, memória…).
    embed (a aba do Codeck, num iframe): sem isolamento de origem o WebAssembly falha e o DevTools cai para JS
    depois de tentar — pede JS de uma vez."""
    import urllib.parse
    s = _get(sid)
    if not isinstance(s, Session) or s.adapter != "dart":
        raise ValueError("O DevTools é para apps Flutter/Dart")
    if page not in DEVTOOLS_PAGES:
        raise ValueError("Página do DevTools inválida")
    if not s.vm_uri:
        raise ValueError("O app ainda não terminou de subir" if s.alive else "O app não está mais rodando")
    base = _devtools_server()
    qs = urllib.parse.urlencode({"uri": s.vm_uri, "ide": "Codeck", "theme": "light" if theme == "light" else "dark", **({"compiler": "js"} if embed else {})})
    return {"url": f"{base}/{page}?{qs}" if page else f"{base}/?{qs}", "base": base}


def service(sid, method, params=None):
    s = _get_debug(sid)
    try:
        r = s.service(method, params)
    except DapError as e:
        raise ValueError(str(e)) from None
    if r.get("data"):   # os "imprimir árvore…" vão para o console de depuração
        s.out(str(r["data"]).rstrip() + "\n", "stdout")
    return r


def kill_now():
    """Saída rápida do app (SIGTERM, pai morreu): mata adaptadores e os servidores do js-debug e do DevTools sem conversar."""
    _devtools_kill()
    with _lock:
        items = list(_sessions.values())
    for s in items:
        p = getattr(s, "proc", None)
        if p and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass
    p = _js.get("proc")
    if p and p.poll() is None:
        p.kill()


def shutdown():
    with _lock:
        items = list(_sessions.values())
    for s in items:
        try:
            if isinstance(s, Session) and not s.parent and s.alive:
                s.disconnect()
        except Exception:  # noqa: BLE001
            pass
    p = _js.get("proc")
    if p and p.poll() is None:
        p.kill()
    _devtools_kill()


# ---------------------------------------------------------------- iniciar / parar (o que a tela chama)
def _build_then(sess, pre, cwd, then):
    """preLaunchTask num terminal "⚙" (a saída aparece ao vivo; os erros vão para Problemas); se der certo, segue."""
    from . import dotnet
    marker = dotnet._done_marker(pre)
    meta = {"project": sess.repo_id, "dotnet": "build", "debugBuild": sess.id, **({"task": sess.task_id} if sess.task_id else {})}
    for t in terminals.list_all(project=sess.repo_id):
        if t["meta"].get("debugBuild") and t["meta"].get("task") == sess.task_id and not t["alive"]:
            terminals.close(t["id"])
    term = terminals.create(cwd, f"⚙ Compilar · {sess.name}", marker, "run", meta, shell=launch.scope_settings_shell(sess.repo_id))
    sess.build_term = term.id
    sess.status = "building"
    _bump()

    def wait():
        while True:
            time.sleep(0.4)
            if sess.status == "ended":
                return
            try:
                t = terminals.get(term.id)
            except LookupError:
                return sess._end("compilação cancelada")
            text = ANSI.sub("", bytes(t.scroll[-4000:]).decode("utf-8", "replace"))
            m = re.search(DONE + r" (\d+)", text)
            if m:
                break
            if not t.alive:
                return sess._end("compilação interrompida")
        if m.group(1) != "0":
            sess.out("A compilação falhou — veja a aba ⚙ e o painel Problemas.\n", "stderr")
            return sess._end("A compilação falhou")
        sess.status = "starting"
        _bump()
        then()
    threading.Thread(target=wait, daemon=True).start()


def _dotnet_target_path(cfg, root):
    """Onde o .dll ficou de verdade (OutputPath/artifacts/TFM): pergunta ao MSBuild; se não der, usa o do launch.json."""
    proj = (cfg.get("codeck") or {}).get("project")
    if not proj:
        return cfg.get("program")
    full = os.path.join(root, proj)
    try:
        r = subprocess.run([_which("dotnet") or "dotnet", "msbuild", full, "-getProperty:TargetPath", "-p:Configuration=Debug", "-nologo"],
                           capture_output=True, text=True, timeout=60, env=terminals.clean_env(), creationflags=0x08000000 if IS_WIN else 0)
        p = r.stdout.strip().splitlines()[-1].strip() if r.returncode == 0 and r.stdout.strip() else ""
        if p.lower().endswith(".exe"):
            p = p[:-4] + ".dll" if os.path.isfile(p[:-4] + ".dll") else p
        if p and os.path.isfile(p):
            return p
    except Exception:  # noqa: BLE001
        pass
    return cfg.get("program")


def start(repo_id, task_id, config_id, no_debug=False, device=None, _group=None):
    """F5 (depurar) ou Ctrl+F5 (sem depurar). Composta: inicia cada uma (mesmo grupo — parar para todas)."""
    root, cfg, tasks = launch.resolve(repo_id, task_id, config_id)
    group = _group or uuid.uuid4().hex[:10]
    if cfg.get("type") == "compound":
        out = []
        for name in cfg["configurations"]:
            cid = launch.find_by_name(repo_id, task_id, name)
            if cid:
                out += start(repo_id, task_id, cid, no_debug, device, _group=group)["sessions"]
        if not out:
            raise ValueError("Nenhuma configuração da composta existe mais")
        return {"sessions": out, "group": group}
    t = cfg.get("type")
    kind = launch.DEBUG_TYPES.get(t)
    debuggable = kind and (cfg.get("codeck") or {}).get("debug") is not False
    # sem depurar: terminal (Ctrl+F5), menos o Flutter (o adaptador dá hot reload também sem depurar) e o navegador
    if no_debug and t not in ("dart", "flutter", "chrome", "pwa-chrome", "msedge", "pwa-msedge") or not debuggable:
        if not no_debug and not debuggable:
            why = (cfg.get("codeck") or {}).get("why") or "Esta configuração não tem depurador — executando sem depurar"
            _bump({"type": "notice", "level": "info", "text": why, "repoId": repo_id})
        return {"sessions": [_start_run(repo_id, task_id, root, config_id, cfg, tasks, device, group)], "group": group}
    cfg = dict(cfg)
    wants_dev = kind == "dart" and _wants_device(cfg, root)
    if wants_dev and cfg.get("deviceId"):
        device = str(cfg["deviceId"])   # o launch.json fixou o aparelho (como no VS Code)
    s = Session(repo_id, task_id, root, config_id, cfg, kind, group=group, no_debug=no_debug, device=device)
    with _lock:
        _sessions[s.id] = s
        _gc()
    if kind == "js" and not _jsdebug():
        s._end("need-adapter:js")
        return {"sessions": [s.public()], "group": group}
    if kind == "dotnet" and not _netcoredbg():
        s._end("need-adapter:dotnet")
        return {"sessions": [s.public()], "group": group}
    pre = launch.pre_launch(cfg, root, tasks)

    def go():
        if wants_dev:
            try:
                s.device = _ensure_device(s, device)
            except _Cancelled:
                return
            except Exception as e:  # noqa: BLE001
                s.out(f"{e}\n", "stderr")
                return s._end(str(e))
            s.device_pref = device_pref(s.device)
            _bump()
        if kind == "dotnet":
            prog = _dotnet_target_path(cfg, root)
            if prog:
                s.cfg["program"] = prog
            if not s.cfg.get("program") or not os.path.isfile(s.cfg["program"]):
                s.out(f"Não achei o programa compilado: {s.cfg.get('program')}\n", "stderr")
                return s._end("Programa compilado não encontrado — compile o projeto")
        s.start()
    if pre:
        _build_then(s, pre, root, go)
    else:
        threading.Thread(target=go, daemon=True).start()
    _bump()
    return {"sessions": [s.public()], "group": group}


def _start_run(repo_id, task_id, root, config_id, cfg, tasks, device, group):
    t = cfg.get("type")
    rs = RunSession(repo_id, task_id, root, config_id, cfg, group)
    if t in ("chrome", "pwa-chrome", "msedge", "pwa-msedge"):
        rs.url = cfg.get("url")
        rs.status, rs.ended = "ended", time.time()
        if rs.url:
            _bump({"type": "open", "url": rs.url, "session": rs.id, "repoId": repo_id})
        return rs.public()
    if (cfg.get("codeck") or {}).get("device") and not device:
        raise ValueError("Escolha o dispositivo (emulador, simulador, Chrome, macOS…)")
    cmd = launch.run_command(cfg, root, tasks, device=device)
    if not cmd:
        raise ValueError(f"Não sei executar o tipo “{t}” sem depurar")
    cwd = cfg.get("cwd") if cfg.get("cwd") and os.path.isdir(cfg.get("cwd")) else root
    # a configuração anterior com o mesmo id (Ctrl+F5 de novo): reinicia — fecha o terminal antigo
    with _lock:
        prev = [s for s in _sessions.values() if isinstance(s, RunSession) and s.repo_id == repo_id and s.task_id == task_id and s.config_id == config_id and s.alive]
    for p in prev:
        p.stop()
    meta = {"project": repo_id, "run": config_id, **({"task": task_id} if task_id else {})}
    term = terminals.create(cwd, "▶ " + rs.name, cmd, "run", meta, launch.run_env(cfg) or None, shell=launch.scope_settings_shell(repo_id))
    rs.term_ids.append(term.id)
    with _lock:
        _sessions[rs.id] = rs
        _gc()
    if cfg.get("serverReadyAction"):
        threading.Thread(target=_watch_ready, args=(rs, term, cfg["serverReadyAction"]), daemon=True).start()
    _bump({"type": "focus", "term": term.id, "repoId": repo_id, "taskId": task_id})
    return rs.public()


def _get(sid):
    s = _sessions.get(sid)
    if not s:
        raise LookupError("Sessão de depuração não encontrada")
    return s


def _get_debug(sid):
    s = _get(sid)
    if not isinstance(s, Session):
        raise ValueError("Esta execução não está depurando")
    if not s.conn or s.conn.closed:
        raise ValueError("A sessão já terminou")
    return s


def stop(sid=None, group=None, repo_id=None):
    """Shift+F5: para a sessão (e o grupo dela — composta, filhas, navegador)."""
    with _lock:
        if sid:
            group = _get(sid).group
        items = [s for s in _sessions.values() if s.alive and ((group and s.group == group) or (repo_id and not group and s.repo_id == repo_id))]
    for s in items:
        if isinstance(s, RunSession):
            s.stop()
        elif not s.parent:
            if s.status == "booting":
                s._end("cancelada")   # o emulador continua ligando (fica pronto para a próxima)
            elif s.status == "building" and s.build_term:
                terminals.close(s.build_term)
                s._end("cancelada")
            else:
                s.disconnect()
    _bump()
    return {"stopped": len(items)}


def restart(sid):
    s = _get(sid)
    root = s
    while getattr(root, "parent", None):
        root = root.parent
    group = root.group
    with _lock:
        members = [x for x in _sessions.values() if x.group == group and not getattr(x, "parent", None)]
    configs = list(dict.fromkeys((x.config_id, getattr(x, "no_debug", not x.debugging), getattr(x, "device", None)) for x in members))
    repo_id, task_id = root.repo_id, root.task_id
    stop(group=group)
    time.sleep(0.8)
    out = []
    for cid, nd, dev in configs:
        try:
            out += start(repo_id, task_id, cid, nd, dev)["sessions"]
        except Exception as e:  # noqa: BLE001
            _bump({"type": "notice", "level": "error", "text": str(e), "repoId": repo_id})
    return {"sessions": out}


def control(sid, action, thread_id=None):
    return _get_debug(sid).control(action, thread_id)


def stack(sid, thread_id):
    return {"frames": _get_debug(sid).stack(int(thread_id))}


def scopes(sid, frame_id):
    return {"scopes": _get_debug(sid).scopes(int(frame_id))}


def variables(sid, ref):
    return {"variables": _get_debug(sid).variables(int(ref))}


def evaluate(sid, expr, frame_id=None, context="repl"):
    s = _get_debug(sid)
    if context == "repl":
        s.out(f"> {expr}\n", "input")
    try:
        r = s.evaluate(expr, int(frame_id) if frame_id else None, context)
    except DapError as e:
        if context == "repl":
            s.out(f"{e}\n", "stderr")
        raise ValueError(str(e)) from None
    if context == "repl":
        s.out(f"{r['result']}\n", "result")
    return r


def set_variable(sid, ref, name, value):
    try:
        return _get_debug(sid).set_variable(int(ref), name, value)
    except DapError as e:
        raise ValueError(str(e)) from None


def source(sid, ref, path=None):
    return _get_debug(sid).source(int(ref), path)


def output(sid, after=0):
    return _get(sid).read_output(int(after or 0)) if isinstance(_get(sid), Session) else {"seq": 0, "items": []}


def on_saved(repo_id, task_id, rel):
    """Salvou um .dart com o Flutter rodando: hot reload (como o VS Code)."""
    if not str(rel).endswith(".dart"):
        return {"reloaded": 0}
    with _lock:
        items = [s for s in _sessions.values() if isinstance(s, Session) and s.adapter == "dart" and s.repo_id == repo_id and s.task_id == task_id
                 and s.status in ("running", "stopped") and s.conn and not s.conn.closed]
    n = 0
    for s in items:
        try:
            s.control("hotReload")
            n += 1
        except Exception:  # noqa: BLE001
            pass
    return {"reloaded": n}


# ---------------------------------------------------------------- dispositivos do Flutter
# Ligados: o `flutter devices`. Desligados: os emuladores do Android (AVDs, do Android SDK) e os simuladores do iOS
# (xcrun simctl). Executar com um desligado escolhido — ou sem nada ligado — liga o aparelho e espera ele terminar de
# subir antes de chamar o Flutter (como o VS Code). A escolha de um emulador Android fica como "avd:<nome>": o serial
# (emulator-5554) muda a cada vez que ele liga.
_devices = {"at": 0, "list": [], "offline": [], "err": None}
_dev_lock = threading.Lock()
_avd_of = {}        # serial do emulador Android ligado → nome do AVD
_booting = {}       # id do desligado → quando começou a ligar
IS_MAC = platform.system() == "Darwin"


class _Cancelled(Exception):
    pass


def _out(argv, timeout=20):
    """A saída do comando; vazia se não deu para rodar."""
    if IS_WIN and argv[0].lower().endswith((".bat", ".cmd")):
        argv = ["cmd.exe", "/c"] + argv
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=terminals.clean_env(),
                              creationflags=0x08000000 if IS_WIN else 0).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _android_sdk():
    env = terminals.clean_env()
    for d in (env.get("ANDROID_HOME"), env.get("ANDROID_SDK_ROOT")):
        if d and os.path.isdir(d):
            return d
    adb = _which("adb")
    if adb:
        d = os.path.dirname(os.path.dirname(os.path.realpath(adb)))   # <sdk>/platform-tools/adb
        if os.path.isdir(os.path.join(d, "emulator")):
            return d
    home = os.path.expanduser("~")
    for d in (os.path.join(home, "Library", "Android", "sdk"), os.path.join(os.environ.get("LOCALAPPDATA") or home, "Android", "Sdk"),
              os.path.join(home, "Android", "Sdk")):
        if os.path.isdir(d):
            return d
    return None


def _sdk_tool(*rel):
    sdk = _android_sdk()
    f = sdk and os.path.join(sdk, *rel[:-1], rel[-1] + (".exe" if IS_WIN else ""))
    return f if f and os.path.isfile(f) else None


def _adb():
    return _which("adb") or _sdk_tool("platform-tools", "adb")


def _avds():
    # o `emulator` do PATH costuma ser o antigo (<sdk>/tools/emulator); o certo é o de <sdk>/emulator
    exe = _sdk_tool("emulator", "emulator")
    return [x.strip() for x in _out([exe, "-list-avds"]).splitlines() if re.fullmatch(r"[\w.\-]+", x.strip())] if exe else []


def _running_avds():
    """Emuladores Android ligados: serial → {avd, ready} (ready = o adb já fala com ele)."""
    adb = _adb()
    if not adb:
        return {}
    out = {}
    for line in _out([adb, "devices"], 10).splitlines():
        m = re.match(r"(emulator-\d+)\s+(\w+)", line)
        if not m:
            continue
        serial, state = m.groups()
        if not _avd_of.get(serial):
            name = (_out([adb, "-s", serial, "emu", "avd", "name"], 8).strip().splitlines() or [""])[0].strip()
            if re.fullmatch(r"[\w.\-]+", name):
                _avd_of[serial] = name
        out[serial] = {"avd": _avd_of.get(serial), "ready": state == "device"}
    for serial in [x for x in _avd_of if x not in out]:
        _avd_of.pop(serial, None)
    return out


def _sims():
    """Simuladores do iOS desta máquina (macOS), o runtime mais novo primeiro e os iPhones antes dos iPads."""
    if not IS_MAC or not shutil.which("xcrun"):
        return []
    try:
        data = json.loads(_out(["xcrun", "simctl", "list", "devices", "available", "--json"], 20) or "{}")
    except ValueError:
        return []
    out = []
    for rt, items in (data.get("devices") or {}).items():
        m = re.search(r"SimRuntime\.iOS-(\d+)-(\d+)", rt)
        if not m:
            continue
        for d in items:
            if d.get("udid"):
                out.append({"udid": d["udid"], "name": d.get("name") or d["udid"], "runtime": f"iOS {m.group(1)}.{m.group(2)}",
                            "booted": d.get("state") == "Booted", "ver": (int(m.group(1)), int(m.group(2)))})
    return sorted(out, key=lambda x: (tuple(-v for v in x["ver"]), not x["name"].startswith("iPhone"), x["name"]))


def _dev_view():
    off = [{**d, "booting": d["id"] in _booting} for d in _devices["offline"]]
    return {"devices": _devices["list"], "offline": off, "error": _devices["err"]}


def devices(force=False):
    with _dev_lock:
        if not force and _devices["at"] and time.time() - _devices["at"] < 30:
            return _dev_view()
        flutter = _which("flutter")
        if not flutter:
            return {"devices": [], "offline": [], "error": "Flutter não encontrado no PATH"}
        try:
            argv = ["cmd.exe", "/c", flutter, "devices", "--machine"] if IS_WIN and flutter.lower().endswith((".bat", ".cmd")) else [flutter, "devices", "--machine"]
            r = subprocess.run(argv, capture_output=True, text=True, timeout=60, env=terminals.clean_env(), creationflags=0x08000000 if IS_WIN else 0)
            j = r.stdout[r.stdout.find("["):] if "[" in r.stdout else "[]"
            items = json.loads(j)
            avds = _running_avds()
            lst = []
            for d in items:
                if not d.get("id"):
                    continue
                avd = (avds.get(d["id"]) or {}).get("avd")   # o Flutter chama todo emulador de "sdk gphone64…": mostra o AVD
                lst.append({"id": d["id"], "name": avd.replace("_", " ") if avd else d.get("name"), "platform": d.get("targetPlatform") or "",
                            "emulator": bool(d.get("emulator")), "supported": d.get("isSupported", True), "sdk": d.get("sdk"), "avd": avd})
            on = {x["avd"] for x in avds.values()}
            offline = [{"id": "avd:" + n, "name": n.replace("_", " "), "platform": "android", "emulator": True, "supported": True, "offline": True,
                        "sdk": "emulador Android"} for n in _avds() if n not in on]
            sims = _sims()
            newest = sims[0]["ver"] if sims else None
            offline += [{"id": x["udid"], "name": x["name"], "platform": "ios", "emulator": True, "supported": True, "offline": True,
                         "sdk": f"simulador · {x['runtime']}"} for x in sims if not x["booted"] and x["ver"] == newest][:8]
            _devices.update(at=time.time(), list=lst, offline=offline, err=None)
        except Exception as e:  # noqa: BLE001
            _devices.update(at=time.time(), err=f"flutter devices: {e}")
        return _dev_view()


def _detached(argv):
    """Sobe um processo que fica vivo mesmo se o Codeck fechar (o emulador)."""
    kw = {"creationflags": 0x00000008 | 0x00000200} if IS_WIN else {"start_new_session": True}
    return subprocess.Popen(argv, env=terminals.clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


def _boot(dev_id, sess=None, timeout=300):
    """Liga o emulador Android ("avd:<nome>") ou o simulador do iOS (UDID) e espera ficar pronto para instalar o app.
    Devolve o id que o Flutter usa (o Android ganha um serial, emulator-5554). Para se a sessão for parada."""
    def alive():
        if sess is not None and sess.status == "ended":
            raise _Cancelled()
    _booting[dev_id] = time.time()
    _bump({"type": "devices"})
    try:
        end = time.time() + timeout
        if dev_id.startswith("avd:"):
            avd = dev_id[4:]
            exe, adb = _sdk_tool("emulator", "emulator"), _adb()
            if not exe or not adb:
                raise ValueError("Não achei o emulador do Android SDK — instale pelo Android Studio (SDK Manager → Android Emulator)")
            if not any(x["avd"] == avd for x in _running_avds().values()):
                proc = _detached([exe, "-avd", avd])
            else:
                proc = None
            while time.time() < end:
                alive()
                serial = next((s for s, x in _running_avds().items() if x["avd"] == avd and x["ready"]), None)
                if serial and _out([adb, "-s", serial, "shell", "getprop", "sys.boot_completed"], 8).strip() == "1":
                    return serial
                if proc is not None and proc.poll() is not None and not serial:
                    raise ValueError(f"O emulador {avd} fechou ao ligar (código {proc.returncode}) — abra pelo Android Studio para ver o motivo")
                time.sleep(2)
            raise ValueError(f"O emulador {avd} não terminou de ligar em {timeout // 60} min")
        if not IS_MAC:
            raise ValueError("Dispositivo desconhecido")
        _out(["xcrun", "simctl", "boot", dev_id], 60)   # já ligado: só reclama; segue
        subprocess.run(["open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", dev_id], capture_output=True, check=False, timeout=20)
        while time.time() < end:
            alive()
            if any(x["udid"] == dev_id and x["booted"] for x in _sims()):
                _out(["xcrun", "simctl", "bootstatus", dev_id], 120)   # espera o SpringBoard
                return dev_id
            time.sleep(2)
        raise ValueError("O simulador não terminou de ligar")
    finally:
        _booting.pop(dev_id, None)
        _devices["at"] = 0
        _bump({"type": "devices"})


def _platforms(d):
    """As plataformas que o projeto Flutter tem (as pastas android/, ios/, web/…); sem nenhuma, celular."""
    have = {p for p in ("android", "ios", "web", "macos", "windows", "linux") if os.path.isdir(os.path.join(d, p))}
    return have or {"android", "ios"}


def _ensure_device(sess, pref):
    """O dispositivo para o `flutter run -d`: o escolhido (ligando o emulador/simulador se estiver desligado); sem
    escolha (ou o escolhido sumiu), um celular/emulador ligado; senão liga um emulador; senão o que houver (macOS, Chrome…)."""
    def boot(dev_id, name):
        sess.status, sess.boot = "booting", name
        sess.out(f"Ligando {name}…\n", "console")
        _bump()
        dev = _boot(dev_id, sess)
        sess.out(f"{name} pronto.\n", "console")
        sess.status, sess.boot = "starting", None
        _bump()
        return dev
    if pref:
        if pref.startswith("avd:"):
            serial = next((s for s, x in _running_avds().items() if x["avd"] == pref[4:] and x["ready"]), None)
            return serial or boot(pref, pref[4:].replace("_", " "))
        if re.fullmatch(r"emulator-\d+", pref):
            run = _running_avds()
            if pref in run and run[pref]["ready"]:
                return pref
            if _avd_of.get(pref):
                return boot("avd:" + _avd_of[pref], _avd_of[pref].replace("_", " "))
        sim = next((x for x in _sims() if x["udid"] == pref), None)
        if sim:
            return pref if sim["booted"] else boot(pref, sim["name"])
        if any(d["id"] == pref for d in devices()["devices"]) or any(d["id"] == pref for d in devices(True)["devices"]):
            return pref
        sess.out(f"O dispositivo “{pref}” não está conectado — usando outro.\n", "console")
    plats = _platforms(sess.cfg.get("cwd") or sess.root)
    st = devices(True)
    mobile = [d for d in st["devices"] if d["supported"] and any(d["platform"].startswith(p) for p in plats & {"android", "ios"})]
    if mobile:
        return sorted(mobile, key=lambda d: not d["emulator"])[0]["id"]   # emulador antes do aparelho (sem fio é lento)
    off = [d for d in st["offline"] if d["platform"] in plats]
    if off:
        d = next((x for x in off if x["platform"] == "android"), off[0])
        return boot(d["id"], d["name"])
    host = {"macos": "darwin", "windows": "windows", "linux": "linux", "web": "web"}
    other = [d for d in st["devices"] if d["supported"] and any(d["platform"].startswith(host[p]) for p in plats if p in host)]
    if other:
        return other[0]["id"]
    raise ValueError("Nenhum dispositivo para o Flutter — crie um emulador no Android Studio (Device Manager) ou um simulador no Xcode")


def device_pref(dev):
    """Como lembrar a escolha: o emulador Android pelo AVD (o serial muda); o resto pelo id."""
    return "avd:" + _avd_of[dev] if dev in _avd_of else dev


def launch_emulator(eid):
    """Liga um desligado em segundo plano (escolheu no menu de dispositivos) — o próximo F5 já encontra ligado."""
    eid = str(eid or "")
    if not (re.fullmatch(r"avd:[\w.\-]+", eid) or re.fullmatch(r"[0-9A-Fa-f\-]{36}", eid)):
        raise ValueError("Emulador inválido")
    if eid not in _booting:
        def run():
            try:
                _boot(eid)
            except Exception as e:  # noqa: BLE001
                _bump({"type": "notice", "level": "error", "text": str(e)})
        threading.Thread(target=run, daemon=True).start()
    return {"ok": True}
