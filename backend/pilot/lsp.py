"""Servidores de linguagem (LSP) para o editor: autocompletar, erros, ir para a definição, documentação no hover.

O app não traz servidor nenhum: usa o que estiver instalado na máquina (PATH do shell de login). Cada aba de editor
conectada abre um WebSocket (/ws/lsp/<linguagem>?repoId=…&taskId=…); o backend sobe o servidor na pasta do projeto e
repassa as mensagens JSON-RPC entre o WebSocket (uma mensagem = um JSON) e o stdio do servidor (Content-Length).
"""
import json
import os
import subprocess
import threading
import time

from . import terminals

SERVERS = {
    # linguagem do Monaco -> candidatos (o 1º instalado vence)
    "typescript": [["typescript-language-server", "--stdio"]],
    "javascript": [["typescript-language-server", "--stdio"]],
    "python": [["pyright-langserver", "--stdio"], ["basedpyright-langserver", "--stdio"], ["pylsp"]],
    "csharp": [["csharp-ls"], ["OmniSharp", "-lsp"], ["omnisharp", "-lsp"]],
    "go": [["gopls"]],
    "rust": [["rust-analyzer"]],
    "java": [["jdtls"]],
    "php": [["intelephense", "--stdio"]],
    "html": [["vscode-html-language-server", "--stdio"]],
    "css": [["vscode-css-language-server", "--stdio"]],
    "json": [["vscode-json-language-server", "--stdio"]],
    # Dart/Flutter: o analysis server do próprio SDK (no PATH, ou o `dart` que vem dentro do Flutter)
    "dart": [["dart", "language-server", "--protocol=lsp", "--client-id=codeck"]],
}
# servidores que executam código do projeto ao abrir um arquivo (MSBuild, build.rs/proc-macros): só em projeto confiável
RUNS_PROJECT_CODE = {"csharp", "rust"}
_found = {"at": 0, "map": {}}


def _login_path():
    from . import userpath
    return userpath.get()


def available():
    """Qual servidor está instalado para cada linguagem (cache de 5 min)."""
    if time.time() - _found["at"] < 300:
        return _found["map"]
    home = os.path.expanduser("~")
    extra = [os.path.join(home, d) for d in (".dotnet/tools", "go/bin", ".cargo/bin", ".local/bin", ".npm-global/bin")]
    extra += [p for p in (os.environ.get("CODECK_LSP_PATH") or "").split(os.pathsep) if p]   # testes/dev
    path = os.pathsep.join([_login_path()] + extra)
    import shutil
    out = {}
    for lang, cands in SERVERS.items():
        for c in cands:
            exe = shutil.which(c[0], path=path)
            if exe:
                out[lang] = {"cmd": [exe] + c[1:], "name": c[0]}
                break
    if "dart" not in out:   # só o Flutter no PATH: o Dart vem dentro dele (flutter/bin/cache/dart-sdk)
        fl = shutil.which("flutter", path=path)
        exe = fl and _sdk_dart(os.path.dirname(os.path.dirname(os.path.realpath(fl))))
        if exe:
            out["dart"] = {"cmd": [exe] + SERVERS["dart"][0][1:], "name": "dart"}
    _found.update(at=time.time(), map=out, path=path)
    return out


def _sdk_dart(sdk):
    """O executável `dart` de um SDK do Flutter (o binário de verdade em bin/cache/dart-sdk; senão o wrapper de bin/)."""
    win = os.name == "nt"
    for p in (os.path.join(sdk, "bin", "cache", "dart-sdk", "bin", "dart.exe" if win else "dart"), os.path.join(sdk, "bin", "dart.bat" if win else "dart")):
        if os.path.isfile(p):
            return p
    return None


def _inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _project_dart(root, trusted=False):
    """Flutter fixado pelo projeto (FVM, dart.flutterSdkPath): o servidor de Dart tem de ser o desse SDK — o do PATH
    pode ser de outra versão e acusar erros falsos. O app pode estar numa subpasta (monorepo): procura o pubspec."""
    from . import launch
    dirs = [root]
    try:
        dirs += [os.path.join(root, d) for d in sorted(os.listdir(root)) if os.path.isfile(os.path.join(root, d, "pubspec.yaml"))][:5]
    except OSError:
        pass
    for d in dirs:
        try:
            sdk, _ = launch.flutter_sdk(d, root)
        except Exception:  # noqa: BLE001
            sdk = None
        if sdk and not trusted and _inside(sdk, root):
            sdk = None   # SDK versionado dentro do repositório = binário escolhido pelo repo: só em projeto confiável
        exe = sdk and _sdk_dart(sdk)
        if exe:
            return [exe] + SERVERS["dart"][0][1:]
    return None


class Bridge:
    """Um servidor de linguagem ligado a um WebSocket."""

    def __init__(self, lang, root, sock, trusted=False):
        if lang in RUNS_PROJECT_CODE and not trusted:
            raise LookupError("Este servidor de linguagem executa código do projeto ao abrir os arquivos — confie no projeto "
                              "(Ajustes do projeto → Projeto confiável) e reabra o arquivo")
        spec = available().get(lang)
        if lang == "dart":
            cmd = _project_dart(root, trusted)
            spec = {"cmd": cmd, "name": "dart"} if cmd else spec
        if not spec:
            raise LookupError(f"Nenhum servidor de linguagem instalado para {lang}")
        env = terminals.clean_env({"PATH": _found.get("path") or os.environ.get("PATH", "")})
        self.proc = subprocess.Popen(spec["cmd"], cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, creationflags=0x08000000 if os.name == "nt" else 0)
        self.sock = sock
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        out = self.proc.stdout
        try:
            while True:
                length = 0
                while True:   # cabeçalhos até a linha vazia
                    line = out.readline()
                    if not line:
                        return
                    line = line.strip()
                    if not line:
                        break
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":", 1)[1])
                body = out.read(length)
                self.sock.send_text(body.decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001 — conexão caiu ou servidor saiu
            pass

    def send(self, text):
        data = text.encode("utf-8")
        try:
            self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(data) + data)
            self.proc.stdin.flush()
        except OSError:
            pass

    def close(self):
        try:
            self.send(json.dumps({"jsonrpc": "2.0", "method": "exit"}))
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            self.proc.kill()

