"""Cofre de credenciais: Keychain no macOS, DPAPI no Windows. O config.json guarda só a referência.

Serviços: dev.prpilot.pat (PAT do Azure DevOps) e dev.prpilot.github (token do GitHub). A gravação no Keychain usa
`security -i` com o comando no stdin, para o segredo não aparecer na lista de processos (ps).
"""
import base64
import ctypes
import os
import re
import subprocess
import sys
import time

# IDs herdados do nome antigo (PR Pilot): o serviço do Keychain e a entropia do DPAPI fazem parte da credencial
# já gravada — trocar aqui deixaria de ler os PATs e tokens de quem atualizou. São internos; o usuário não os vê.
AZURE = "dev.prpilot.pat"
GITHUB = "dev.prpilot.github"
_DPAPI_ENTROPY = {AZURE: b"PR Pilot / Azure DevOps PAT", GITHUB: b"PR Pilot / GitHub token"}


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data, protect, entropy):
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    src = ctypes.create_string_buffer(data, len(data))
    ent = ctypes.create_string_buffer(entropy, len(entropy))
    blob_in = _Blob(len(data), ctypes.cast(src, ctypes.POINTER(ctypes.c_char)))
    blob_ent = _Blob(len(entropy), ctypes.cast(ent, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    args = (ctypes.byref(blob_in), "Codeck" if protect else None, ctypes.byref(blob_ent), None, None, 0x1, ctypes.byref(blob_out))
    if not fn(*args):  # 0x1 = CRYPTPROTECT_UI_FORBIDDEN
        raise RuntimeError("DPAPI recusou a operação")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def put(account, value, service=AZURE):
    """Guarda o segredo cifrado e devolve a referência que vai para o config.json."""
    if not re.fullmatch(r"[\w\-]{1,64}", account) or not re.fullmatch(r"[\w\-.]{8,400}", value):
        raise ValueError("Credencial com formato inesperado")
    if sys.platform == "darwin":
        cmd = f'add-generic-password -U -s {service} -a {account} -l "Codeck — credencial" -w "{value}"\n'
        r = subprocess.run(["/usr/bin/security", "-i"], input=cmd, text=True, capture_output=True, timeout=20)
        if r.returncode != 0 or "error" in (r.stderr or "").lower():
            raise RuntimeError("Não consegui gravar no Keychain")
        return {"store": "keychain", "service": service}
    if os.name == "nt":
        return {"store": "dpapi", "blob": base64.b64encode(_dpapi(value.encode(), True, _DPAPI_ENTROPY[service])).decode(),
                "service": service}
    raise RuntimeError("Sistema sem cofre suportado (use macOS ou Windows)")


def get(account, ref):
    if not ref:
        return None
    service = ref.get("service") or AZURE
    if ref.get("store") == "keychain":
        # o Keychain às vezes falha por um instante (Mac acordando, chaveiro ainda travado): tenta de novo antes de
        # dizer que a credencial sumiu — antes isso parecia "a conta desconectou sozinha"
        for attempt in range(3):
            try:
                r = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
                                   capture_output=True, text=True, timeout=20)
            except subprocess.TimeoutExpired:
                r = None
            if r is not None and r.returncode == 0:
                return r.stdout.strip()
            if r is not None and r.returncode == 44:   # errSecItemNotFound: não existe mesmo
                break
            time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("Credencial não encontrada no Keychain — conecte a conta de novo")
    if ref.get("store") == "dpapi":
        return _dpapi(base64.b64decode(ref["blob"]), False, _DPAPI_ENTROPY[service]).decode()
    return None


def delete(account, ref):
    if (ref or {}).get("store") == "keychain":
        subprocess.run(["/usr/bin/security", "delete-generic-password", "-s", ref.get("service") or AZURE, "-a", account],
                       capture_output=True, timeout=20)
