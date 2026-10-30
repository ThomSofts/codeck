"""Túnel SSH para bancos que só se alcançam por um servidor intermediário (bastion).

Usa o ssh do próprio sistema (macOS; Windows 10+ traz o OpenSSH) com:
  - BatchMode: nunca pede senha — vale a sua chave (ssh-agent, ~/.ssh ou o arquivo indicado);
  - StrictHostKeyChecking=yes: o servidor tem de estar no seu known_hosts. O Codeck não aceita chave nova sozinho —
    na primeira vez, rode `ssh usuario@servidor` no terminal e confira a impressão digital;
  - a porta local só no 127.0.0.1, escolhida livre na hora. Um túnel por ambiente, compartilhado pelas conexões.
O certificado TLS do banco continua conferido pelo nome do servidor real (tlsHost), não pelo 127.0.0.1.
"""
import os
import re
import shutil
import socket
import subprocess
import threading
import time

from .dbplugins import PluginError

HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*|\[[0-9a-fA-F:]+\]")
USER_RE = re.compile(r"[A-Za-z0-9_][\w.\-]*")
_tunnels = {}   # id do ambiente → {"proc", "port", "refs"}
_lock = threading.Lock()


def _ssh():
    exe = shutil.which("ssh")
    if not exe and os.name == "nt":
        cand = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "OpenSSH", "ssh.exe")
        exe = cand if os.path.isfile(cand) else None
    if not exe:
        raise PluginError("ssh-missing", "ssh não encontrado (no Windows: Configurações → Apps → Recursos opcionais → Cliente OpenSSH)")
    return exe


def clean(raw):
    """Valida o que vem da tela. Devolve None se não há túnel."""
    raw = raw or {}
    host = str(raw.get("host") or "").strip()
    if not host:
        return None
    user = str(raw.get("user") or "").strip()
    key = os.path.expanduser(str(raw.get("key") or "").strip())
    if not HOST_RE.fullmatch(host):
        raise ValueError("Servidor SSH inválido")
    if user and not USER_RE.fullmatch(user):
        raise ValueError("Usuário SSH inválido")
    try:
        port = int(raw.get("port") or 22)
    except (TypeError, ValueError):
        port = 22
    if not 0 < port < 65536:
        raise ValueError("Porta SSH inválida")
    return {"host": host, "port": port, "user": user, "key": key if key else ""}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def acquire(env_id, ssh, db_host, db_port):
    """Abre (ou reaproveita) o túnel e devolve a porta local."""
    if not HOST_RE.fullmatch(db_host or ""):
        raise PluginError("bad-host", "Servidor do banco inválido para o túnel")
    with _lock:
        t = _tunnels.get(env_id)
        if t and t["proc"].poll() is None:
            t["refs"] += 1
            return t["port"]
    if ssh.get("key") and not os.path.isfile(ssh["key"]):
        raise PluginError("ssh-key", f"Arquivo de chave não encontrado: {ssh['key']}")
    lp = _free_port()
    argv = [_ssh(), "-N", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30", "-o", "ConnectTimeout=15", "-p", str(ssh["port"]),
            "-L", f"127.0.0.1:{lp}:{db_host}:{int(db_port)}"]
    if ssh.get("key"):
        argv += ["-i", ssh["key"], "-o", "IdentitiesOnly=yes"]
    if os.environ.get("CODECK_TEST_KNOWN_HOSTS"):   # só a bateria de testes (o app nunca define): outro known_hosts, mesma checagem
        argv += ["-o", "UserKnownHostsFile=" + os.environ["CODECK_TEST_KNOWN_HOSTS"]]
    argv += ["--", f"{ssh['user']}@{ssh['host']}" if ssh.get("user") else ssh["host"]]
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            creationflags=0x08000000 if os.name == "nt" else 0)
    deadline = time.time() + 20
    while time.time() < deadline:
        if proc.poll() is not None:
            err = (proc.stderr.read() or b"").decode(errors="replace")
            if "Host key verification failed" in err or "No ED25519 host key" in err or "host key" in err.lower():
                raise PluginError("ssh-hostkey", f"O servidor SSH {ssh['host']} não está no seu known_hosts (ou a chave dele mudou). "
                                  f"Rode uma vez no terminal: ssh {ssh['user'] + '@' if ssh.get('user') else ''}{ssh['host']} e confira a impressão digital")
            if "Permission denied" in err:
                raise PluginError("ssh-auth", "O servidor SSH recusou a sua chave (o Codeck não usa senha de SSH: use chave ou ssh-agent)")
            raise PluginError("ssh", f"O túnel SSH não abriu: {err.strip()[-300:] or 'ssh saiu sem explicar'}")
        try:
            with socket.create_connection(("127.0.0.1", lp), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        raise PluginError("ssh", "O túnel SSH não respondeu a tempo")
    with _lock:
        _tunnels[env_id] = {"proc": proc, "port": lp, "refs": 1}
    return lp


def release(env_id):
    with _lock:
        t = _tunnels.get(env_id)
        if not t:
            return
        t["refs"] -= 1
        if t["refs"] > 0:
            return
        _tunnels.pop(env_id, None)
    try:
        t["proc"].terminate()
        t["proc"].wait(5)
    except (OSError, subprocess.TimeoutExpired):
        t["proc"].kill()


def close_all():
    for k in list(_tunnels):
        with _lock:
            if k in _tunnels:
                _tunnels[k]["refs"] = 1
        release(k)
