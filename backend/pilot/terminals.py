"""Terminais de verdade (PTY) para a tela: shells e agentes de IA (Claude Code, Codex, cursor-agent…).

macOS/Linux: pty.openpty + processo em sessão própria. Windows: ConPTY (CreatePseudoConsole) via ctypes — a mesma API
do Windows Terminal, disponível do Windows 10 1809 em diante.

Cada terminal guarda as últimas saídas (até MAX_SCROLLBACK bytes) para a tela poder reconectar — trocar de aba ou
recarregar a interface não mata o processo. Quem assina recebe a saída ao vivo (os WebSockets da tela).

O processo NUNCA herda a chave do app (CODECK_*) nem segredos que o app conhece: um agente rodando no terminal
não pode chamar a API local nem ler os PATs.
"""
import os
import shlex
import shutil
import sys
import threading
import time
import uuid


MAX_SCROLLBACK = 1_500_000
_SECRET_ENV = ("CODECK_", "COMMITDECK_", "LFTP_PASSWORD", "AZURE_DEVOPS_EXT_PAT", "VSS_NUGET_EXTERNAL_FEED_ENDPOINTS",
               # marcas de uma sessão de IA de FORA (se o app foi aberto de dentro de um agente): herdadas, fariam o
               # agente novo se achar "sessão filha" (sem histórico) ou usar a conta errada — a conta vem do app
               "CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_CONFIG_DIR", "CLAUDE_AGENT", "CODEX_HOME", "CODEX_SANDBOX", "CODEX_THREAD")
IS_WIN = os.name == "nt"


def clean_env(extra=None):
    from . import userpath
    env = {k: v for k, v in os.environ.items() if not k.startswith(_SECRET_ENV)}
    env["PATH"] = userpath.get()   # o PATH do usuário (com o do .zshrc): o app aberto pelo Finder nasce com PATH mínimo
    if os.name != "nt" and not env.get("USER"):
        import pwd   # sem USER o Claude Code não acha o login dele no Keychain
        env["USER"] = env["LOGNAME"] = pwd.getpwuid(os.getuid()).pw_name
    env.update(TERM="xterm-256color", COLORTERM="truecolor", TERM_PROGRAM="Codeck", LANG=env.get("LANG") or "pt_BR.UTF-8")
    env.update(extra or {})
    return env


def default_shell(override=None):
    if override:
        return shutil.which(override) or override
    if IS_WIN:
        return shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
    return os.environ.get("SHELL") or ("/bin/zsh" if sys.platform == "darwin" else "/bin/bash")


# PowerShell no Windows: saída em UTF-8 (sem isto o 5.1 usa a página OEM 850 e os acentos de git/dotnet/node viram lixo)
PS_UTF8 = "try { [Console]::OutputEncoding = $OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch {}"


def shell_argv(command=None, shell=None, win=None):
    """Shell de login (PATH do usuário, nvm, etc.). Com `command`, roda o comando e, quando ele sai, fica no shell."""
    win = IS_WIN if win is None else win
    sh = default_shell(shell)
    name = os.path.basename(sh.replace("\\", "/")).lower()
    if name.startswith(("pwsh", "powershell")):
        base = [sh, "-NoLogo"]
        if win:
            # o Windows PowerShell 5.1 vem com a política "Restricted": o npm.ps1/claude.ps1/pnpm.ps1 das CLIs instaladas
            # pelo npm não rodavam ("a execução de scripts foi desabilitada"). Só para este processo — não muda a máquina.
            base += ["-ExecutionPolicy", "Bypass"]
            return base + ["-NoExit", "-Command", PS_UTF8 + (f"; {command}" if command else "")]
        return base + (["-NoExit", "-Command", command] if command else [])
    if win and name in ("cmd", "cmd.exe"):
        return [sh] + (["/K", command] if command else [])
    if win:   # bash do Git/WSL etc. escolhido nos ajustes
        return [sh] + (["-l", "-c", f"{command}; exec {shlex.quote(sh)} -l"] if command else ["-l"])
    if not command:
        return [sh, "-l"]
    return [sh, "-l", "-c", f"{command}; exec {shlex.quote(sh)} -l"]


# ---------------------------------------------------------------- PTY por plataforma
def _descendants(pid):
    """Todos os descendentes de um processo (POSIX), pela tabela do `ps` — filhos, netos…"""
    import subprocess
    try:
        out = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    kids = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            kids.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, todo = [], [pid]
    while todo:
        for c in kids.get(todo.pop(), []):
            if c not in found:
                found.append(c)
                todo.append(c)
    return found


def _running(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


class _PosixPty:
    def __init__(self, argv, cwd, env, cols, rows):
        import fcntl
        import pty
        import struct
        import subprocess
        import termios
        self._fcntl, self._termios, self._struct = fcntl, termios, struct
        self.master, slave = pty.openpty()
        self.resize(cols, rows, fd=slave)
        # sessão nova (setsid) + o PTY como terminal de CONTROLE dela. Sem isto o processo não tinha terminal de
        # controle: o sistema nunca entregava o SIGWINCH ao redimensionar, e programas de tela inteira (Claude Code,
        # vim, htop…) continuavam desenhando no tamanho antigo — a tela embaralhava e cortava as linhas.
        # Feito num Python pequeno que depois vira o shell (exec), e não num preexec_fn: código Python entre o fork e
        # o exec, com outras threads rodando, podia travar o filho — e o Popen (o pedido de abrir o agente) junto.
        stub = "import fcntl,os,sys,termios; fcntl.ioctl(0, termios.TIOCSCTTY, 0); os.execvp(sys.argv[1], sys.argv[1:])"
        self.proc = subprocess.Popen([sys.executable, "-I", "-S", "-c", stub, *argv], stdin=slave, stdout=slave, stderr=slave,
                                     cwd=cwd, env=env, start_new_session=True, close_fds=True)
        os.close(slave)

    def read(self):
        try:
            return os.read(self.master, 65536)
        except OSError:
            return b""

    def write(self, data):
        # o os.write pode escrever só uma parte (pedido longo colado no agente): sem o resto, o agente ficava esperando
        # o fim da colagem para sempre
        try:
            while data:
                data = data[os.write(self.master, data):]
        except OSError:
            pass

    def resize(self, cols, rows, fd=None):
        try:
            self._fcntl.ioctl(fd if fd is not None else self.master, self._termios.TIOCSWINSZ,
                              self._struct.pack("HHHH", max(rows, 2), max(cols, 10), 0, 0))
        except OSError:
            pass

    def alive(self):
        return self.proc.poll() is None

    def exit_code(self):
        return self.proc.poll()

    def kill(self):
        import signal
        # os filhos que saíram do grupo (servidores MCP, `node` destacado, o shell de uma ferramenta do agente) não
        # recebem o sinal do grupo e ficavam vivos depois de fechar o terminal: vão pela árvore de processos
        kids = _descendants(self.proc.pid)
        for sig in (signal.SIGHUP, signal.SIGKILL):
            try:
                os.killpg(self.proc.pid, sig)
            except (OSError, ProcessLookupError):
                pass
            for pid in kids:
                try:
                    os.kill(pid, sig)
                except (OSError, ProcessLookupError):
                    pass
            if sig == signal.SIGHUP:
                end = time.time() + 0.5
                while time.time() < end and (self.proc.poll() is None or any(_running(p) for p in kids)):
                    time.sleep(0.05)
        try:
            os.close(self.master)
        except OSError:
            pass


class _WinPty:
    """ConPTY via ctypes: duas pipes (entrada/saída), CreatePseudoConsole e CreateProcessW com o atributo do console."""

    def __init__(self, argv, cwd, env, cols, rows):
        import ctypes
        import subprocess
        from ctypes import wintypes as w
        self.ct, self.w = ctypes, w
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k32 = k32

        class COORD(ctypes.Structure):
            _fields_ = [("X", w.SHORT), ("Y", w.SHORT)]

        class STARTUPINFOW(ctypes.Structure):
            _fields_ = [("cb", w.DWORD), ("lpReserved", w.LPWSTR), ("lpDesktop", w.LPWSTR), ("lpTitle", w.LPWSTR),
                        ("dwX", w.DWORD), ("dwY", w.DWORD), ("dwXSize", w.DWORD), ("dwYSize", w.DWORD),
                        ("dwXCountChars", w.DWORD), ("dwYCountChars", w.DWORD), ("dwFillAttribute", w.DWORD),
                        ("dwFlags", w.DWORD), ("wShowWindow", w.WORD), ("cbReserved2", w.WORD),
                        ("lpReserved2", ctypes.c_void_p), ("hStdInput", w.HANDLE), ("hStdOutput", w.HANDLE),
                        ("hStdError", w.HANDLE)]

        class STARTUPINFOEXW(ctypes.Structure):
            _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [("hProcess", w.HANDLE), ("hThread", w.HANDLE), ("dwProcessId", w.DWORD), ("dwThreadId", w.DWORD)]

        self.COORD = COORD
        HANDLE = w.HANDLE
        for name, args, res in (
            ("CreatePipe", [ctypes.POINTER(HANDLE), ctypes.POINTER(HANDLE), ctypes.c_void_p, w.DWORD], w.BOOL),
            ("CreatePseudoConsole", [COORD, HANDLE, HANDLE, w.DWORD, ctypes.POINTER(ctypes.c_void_p)], ctypes.c_long),
            ("ResizePseudoConsole", [ctypes.c_void_p, COORD], ctypes.c_long),
            ("ClosePseudoConsole", [ctypes.c_void_p], None),
            ("InitializeProcThreadAttributeList", [ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)], w.BOOL),
            ("UpdateProcThreadAttribute", [ctypes.c_void_p, w.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p], w.BOOL),
            ("DeleteProcThreadAttributeList", [ctypes.c_void_p], None),
            ("CreateProcessW", [w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD, ctypes.c_void_p, w.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(PROCESS_INFORMATION)], w.BOOL),
            ("ReadFile", [HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p], w.BOOL),
            ("WriteFile", [HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p], w.BOOL),
            ("CloseHandle", [HANDLE], w.BOOL),
            ("WaitForSingleObject", [HANDLE, w.DWORD], w.DWORD),
            ("GetExitCodeProcess", [HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
            ("TerminateProcess", [HANDLE, ctypes.c_uint], w.BOOL),
        ):
            fn = getattr(k32, name)
            fn.argtypes, fn.restype = args, res

        in_read, self.in_write, self.out_read, out_write = HANDLE(), HANDLE(), HANDLE(), HANDLE()
        if not k32.CreatePipe(ctypes.byref(in_read), ctypes.byref(self.in_write), None, 0) or \
           not k32.CreatePipe(ctypes.byref(self.out_read), ctypes.byref(out_write), None, 0):
            raise OSError(ctypes.get_last_error(), "CreatePipe falhou")
        self.hpc = ctypes.c_void_p()
        hr = k32.CreatePseudoConsole(COORD(max(cols, 10), max(rows, 2)), in_read, out_write, 0, ctypes.byref(self.hpc))
        if hr != 0:
            raise OSError(hr, "CreatePseudoConsole falhou (precisa do Windows 10 1809 ou mais novo)")
        k32.CloseHandle(in_read)
        k32.CloseHandle(out_write)   # a ConPTY ficou com as pontas dela

        size = ctypes.c_size_t()
        k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        self.attrs = ctypes.create_string_buffer(size.value)
        if not k32.InitializeProcThreadAttributeList(self.attrs, 1, 0, ctypes.byref(size)):
            raise OSError(ctypes.get_last_error(), "InitializeProcThreadAttributeList falhou")
        PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
        if not k32.UpdateProcThreadAttribute(self.attrs, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE, self.hpc,
                                             ctypes.sizeof(ctypes.c_void_p), None, None):
            raise OSError(ctypes.get_last_error(), "UpdateProcThreadAttribute falhou")
        si = STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        # Sem isto, se o processo pai tem a saída redirecionada (serviço, CI), o filho herda ESSA saída em vez da
        # ConPTY e nada chega ao terminal. Medido no runner do GitHub Actions: a saída do pwsh ia para o log do CI.
        si.StartupInfo.dwFlags = 0x00000100   # STARTF_USESTDHANDLES, com os três handles nulos
        si.lpAttributeList = ctypes.cast(self.attrs, ctypes.c_void_p)
        pi = PROCESS_INFORMATION()
        env_block = ctypes.create_unicode_buffer("\0".join(f"{k}={v}" for k, v in env.items()) + "\0\0")
        cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        EXTENDED_STARTUPINFO_PRESENT, CREATE_UNICODE_ENVIRONMENT = 0x00080000, 0x00000400
        if not k32.CreateProcessW(None, cmdline, None, None, False, EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT,
                                  env_block, cwd, ctypes.byref(si), ctypes.byref(pi)):
            raise OSError(ctypes.get_last_error(), f"não abriu {argv[0]}")
        self.hproc = pi.hProcess
        self.pid = pi.dwProcessId
        k32.CloseHandle(pi.hThread)
        self._closed = False
        self._out_closed = False
        self._pc_closed = False
        self._lock = threading.Lock()
        k32.WaitForSingleObject.argtypes = [HANDLE, w.DWORD]
        threading.Thread(target=self._wait_exit, daemon=True).start()

    def _wait_exit(self):
        """A ConPTY não fecha a saída quando o processo sai sozinho: fecha aqui, e a leitura recebe o fim."""
        self.k32.WaitForSingleObject(self.hproc, 0xFFFFFFFF)
        self._close_pc()

    def _close_pc(self):
        with self._lock:
            if self._pc_closed:
                return
            self._pc_closed = True
        self.k32.ClosePseudoConsole(self.hpc)

    def read(self):
        buf = self.ct.create_string_buffer(65536)
        n = self.w.DWORD()
        ok = self.k32.ReadFile(self.out_read, buf, 65536, self.ct.byref(n), None)
        if ok and n.value:
            return buf.raw[: n.value]
        # fim da saída (o pseudoconsole fechou): a ponta de leitura fecha aqui, na própria thread que lia
        if not self._out_closed:
            self._out_closed = True
            self.k32.CloseHandle(self.out_read)
        return b""

    def write(self, data):
        n = self.w.DWORD()
        self.k32.WriteFile(self.in_write, data, len(data), self.ct.byref(n), None)

    def resize(self, cols, rows):
        if not self._closed and not self._pc_closed:
            self.k32.ResizePseudoConsole(self.hpc, self.COORD(max(cols, 10), max(rows, 2)))

    def alive(self):
        return not self._closed and self.k32.WaitForSingleObject(self.hproc, 0) == 0x102   # WAIT_TIMEOUT

    def exit_code(self):
        if self._closed:
            return -1
        code = self.w.DWORD()
        self.k32.GetExitCodeProcess(self.hproc, self.ct.byref(code))
        return None if code.value == 259 else code.value   # STILL_ACTIVE

    def kill(self):
        """Ordem da documentação da ConPTY: encerra o processo, fecha o pseudoconsole (a leitura pendente recebe o fim
        e a própria thread de leitura fecha a ponta dela) e só então os demais handles."""
        if self._closed:
            return
        self._closed = True
        # o agente roda DENTRO do PowerShell/cmd do terminal: matar só o shell deixava o claude/node órfão, ainda
        # trabalhando. O taskkill /T leva a árvore inteira.
        import subprocess
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.pid)], capture_output=True, timeout=5,
                           creationflags=0x08000000)   # CREATE_NO_WINDOW
        except (OSError, subprocess.SubprocessError):
            pass
        self.k32.TerminateProcess(self.hproc, 1)
        self._close_pc()
        self.k32.CloseHandle(self.in_write)
        self.k32.CloseHandle(self.hproc)
        self.k32.DeleteProcThreadAttributeList(self.attrs)


# ---------------------------------------------------------------- terminal (processo + histórico + assinantes)
class Terminal:
    def __init__(self, argv, cwd, title, kind="shell", meta=None, env=None, cols=120, rows=32):
        self.id = uuid.uuid4().hex[:12]
        self.title, self.kind, self.cwd, self.meta = title, kind, cwd, dict(meta or {})
        self.argv = argv
        self.created = time.time()
        self.last_output = self.created
        self.scroll = bytearray()
        self.total = 0   # bytes produzidos desde o início: a tela retoma de onde parou ao reconectar
        self.subs = set()
        self.lock = threading.Lock()
        self.exit = None
        self.cols, self.rows = cols, rows
        self.pty = (_WinPty if IS_WIN else _PosixPty)(argv, cwd, clean_env(env), cols, rows)
        threading.Thread(target=self._pump, daemon=True, name=f"pty-{self.id}").start()

    def _pump(self):
        while True:
            data = self.pty.read()
            if not data:
                if not self.pty.alive() or IS_WIN:
                    break
                time.sleep(0.05)
                continue
            with self.lock:
                self.last_output = time.time()
                self.scroll += data
                self.total += len(data)
                if len(self.scroll) > MAX_SCROLLBACK:
                    # corta numa quebra de linha: começar no meio de uma sequência de escape bagunçava a tela ao redesenhar
                    cut = len(self.scroll) - MAX_SCROLLBACK
                    nl = self.scroll.find(b"\n", cut, cut + 65536)
                    del self.scroll[: (nl + 1) if nl >= 0 else cut]
                subs = list(self.subs)
            for fn in subs:
                try:
                    fn(data)
                except Exception:  # noqa: BLE001 — assinante caído sai da lista
                    self.subs.discard(fn)
        for _ in range(20):
            if not self.pty.alive():
                break
            time.sleep(0.1)
        self.exit = self.pty.exit_code()
        for fn in list(self.subs):
            try:
                fn(None)   # None = terminou
            except Exception:  # noqa: BLE001
                pass

    def attach(self, fn, since=None):
        """Assina a saída. Devolve (bytes, início, retomada): com `since` (quantos bytes a tela já tem) e ele ainda no
        histórico, só o que faltou — a tela continua de onde parou; senão, o histórico inteiro para redesenhar do zero."""
        with self.lock:
            self.subs.add(fn)
            base = self.total - len(self.scroll)
            if since is not None and base <= since <= self.total:
                return bytes(self.scroll[since - base:]), since, True
            return bytes(self.scroll), base, False

    def detach(self, fn):
        self.subs.discard(fn)

    def write(self, data):
        if self.exit is None:
            self.pty.write(data)

    def resize(self, cols, rows):
        self.cols, self.rows = max(int(cols), 10), max(int(rows), 2)
        _last_size[:] = [self.cols, self.rows]
        self.pty.resize(self.cols, self.rows)

    def kill(self):
        self.pty.kill()

    @property
    def alive(self):
        return self.exit is None and self.pty.alive()

    def info(self):
        return {"id": self.id, "title": self.title, "kind": self.kind, "cwd": self.cwd, "meta": self.meta,
                "created": self.created, "lastOutput": self.last_output, "alive": self.alive, "exit": self.exit,
                "cols": self.cols, "rows": self.rows}


_terms = {}
_lock = threading.Lock()
# último tamanho que a tela mandou: terminal novo já nasce do tamanho do painel. Antes nascia com 120×32 — o agente
# desenhava a 1ª tela para 120 colunas num painel de ~90, o xterm quebrava as linhas e o redesenho deixava lixo.
_last_size = [120, 32]


def hint_size(cols, rows):
    """A tela diz o tamanho do painel antes de criar um terminal (agente, shell, tarefa, executar)."""
    try:
        c, r = int(cols), int(rows)
    except (TypeError, ValueError):
        return
    if 20 <= c <= 1000 and 5 <= r <= 500:
        _last_size[:] = [c, r]


def create(cwd, title=None, command=None, kind="shell", meta=None, env=None, cols=None, rows=None, shell=None):
    cols, rows = int(cols or _last_size[0]), int(rows or _last_size[1])
    cwd = os.path.abspath(os.path.expanduser(cwd or os.path.expanduser("~")))
    if not os.path.isdir(cwd):
        raise ValueError("Pasta não encontrada")
    t = Terminal(shell_argv(command, shell), cwd, title or os.path.basename(cwd), kind, meta, env, cols, rows)
    with _lock:
        _terms[t.id] = t
    return t


def get(tid):
    t = _terms.get(tid)
    if not t:
        raise LookupError("Terminal não encontrado")
    return t


def list_all(**match):
    with _lock:
        items = list(_terms.values())
    return [t.info() for t in items if all(t.meta.get(k) == v for k, v in match.items())]


def close(tid):
    with _lock:
        t = _terms.pop(tid, None)
    if t:
        t.kill()


def close_all():
    """Ao sair do app: sinal para TODOS os terminais de uma vez, uma espera só, e força quem não saiu — rápido mesmo com
    muitos terminais/agentes (antes era um por vez, ~0,2 s cada)."""
    with _lock:
        items = list(_terms.values())
        _terms.clear()
    kids = []
    if not IS_WIN:
        import signal
        for t in items:
            try:
                kids += _descendants(t.pty.proc.pid)   # antes do sinal: depois os órfãos já não têm o pai na árvore
                os.killpg(t.pty.proc.pid, signal.SIGHUP)
            except (OSError, ProcessLookupError, AttributeError):
                pass
        for pid in kids:
            try:
                os.kill(pid, signal.SIGHUP)
            except (OSError, ProcessLookupError):
                pass
        end = time.time() + 1.0
        while time.time() < end and any(t.pty.alive() for t in items):
            time.sleep(0.05)
        for pid in kids:
            try:
                os.kill(pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
    for t in items:
        t.kill()   # quem sobrou: SIGKILL (POSIX) / taskkill da árvore + TerminateProcess (Windows)


def rename(tid, title):
    get(tid).title = (title or "").strip()[:60] or get(tid).title


