"""Atualização do app: lê o latest.json do canal (site da ThomSoft), confere a assinatura dele (latest.json.sig, ECDSA
P-256 da ThomSoft) e baixa o instalador do GitHub Releases da ThomSoft (o site de espelho), retomando quando a conexão
cai e conferindo o SHA-256 assinado.

Sem assinatura válida não há atualização: quem conseguisse trocar o latest.json no servidor (ou no caminho) não
consegue apontar para outro instalador."""
import base64
import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import signature
from .core import APP_BUILD, APP_PLATFORM, UPDATE_URL, UPDATES_DIR, now_iso

# Chave pública da ThomSoft para o canal (a privada: Keychain "codeck-update-signing" e segredo CODECK_SIGNING_KEY do CI)
UPDATE_PUBKEY = ("04b41dd5fbc877cbd1ad626bf74de27d5c9f70ac3bb20cfdaaff2a7f1f91e2f830973987cb50d6f49870a83392611b89"
                 "3449687ba31e49a88dc261f5e8a097585f")


update_state = {"available": False, "checkedAt": None, "error": None, "downloading": False}


def check_update():
    """Fail-open quanto ao uso (falha de rede/JSON só deixa "sem atualização"); fail-closed quanto à confiança: sem a
    assinatura da ThomSoft, nada é oferecido."""
    if not UPDATE_URL:
        update_state.update(available=False, checkedAt=now_iso(), error=None, disabled=True)
        return update_state
    if not UPDATE_URL.startswith("https://"):
        update_state.update(available=False, checkedAt=now_iso(), error="canal de atualização sem https", disabled=True)
        return update_state
    try:
        r = urllib.request.Request(f"{UPDATE_URL}?t={int(time.time())}", headers={"Cache-Control": "no-cache", "User-Agent": "Codeck"})
        with _https_only.open(r, timeout=15) as resp:
            raw = resp.read(200_000)
        rs = urllib.request.Request(f"{UPDATE_URL}.sig?t={int(time.time())}", headers={"Cache-Control": "no-cache", "User-Agent": "Codeck"})
        with _https_only.open(rs, timeout=15) as resp:
            sig = base64.b64decode(resp.read(4_000).strip(), validate=True)
        if not signature.verify(UPDATE_PUBKEY, raw, sig):
            raise ValueError("latest.json sem a assinatura da ThomSoft — atualização ignorada")
        info = json.loads(raw)
        asset = info.get(APP_PLATFORM) or {}
        build = int(asset.get("build") or 0)
        required = int(info.get("required") or 0)
        update_state.update(
            available=bool(asset.get("url")) and build > APP_BUILD, checkedAt=now_iso(), error=None, disabled=False,
            version=asset.get("version"), build=build, notes=info.get("notes"), publishedAt=info.get("publishedAt"),
            required=APP_BUILD < required <= build, url=asset.get("url"), sha256=(asset.get("sha256") or "").lower(),
            size=asset.get("size"), mirrors=asset.get("mirrors") or [])
    except Exception as e:  # noqa: BLE001
        update_state.update(available=False, checkedAt=now_iso(), error=str(e)[:200])
    return update_state


# De onde um instalador pode vir (o latest.json só aponta; o resto é recusado) e o tamanho máximo
DOWNLOAD_PREFIXES = ("https://github.com/ThomSofts/codeck/releases/download/", "https://thomsoft.com.br/downloads/codeck/")
MAX_INSTALLER = 1 << 30


class _HttpsRedirects(urllib.request.HTTPRedirectHandler):
    """Redirecionamento (o GitHub manda para o CDN dele) só para https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise urllib.error.HTTPError(newurl, code, "redirecionamento sem https recusado", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_https_only = urllib.request.build_opener(_HttpsRedirects)


def _fetch(url, part, size):
    """Baixa `url` em `part`, retomando com Range quando a conexão cai no meio (o site da ThomSoft corta downloads
    rápidos por volta de 4 MB). Desiste depois de várias quedas seguidas sem avançar."""
    done, stalls = 0, 0
    open(part, "wb").close()
    while True:
        headers = {"User-Agent": "Codeck"}
        if done:
            headers["Range"] = f"bytes={done}-"
        before = done
        try:
            with _https_only.open(urllib.request.Request(url, headers=headers), timeout=60) as resp:
                if done and resp.status != 206:   # o servidor ignorou o Range: recomeça do zero
                    done = 0
                    open(part, "wb").close()
                if not size:
                    size = int(resp.headers.get("Content-Length") or 0) + done
                    update_state["progress"]["total"] = size
                with open(part, "ab") as f:
                    while chunk := resp.read(1 << 16):
                        f.write(chunk)
                        done += len(chunk)
                        if done > MAX_INSTALLER:
                            raise ValueError("Instalador maior que o esperado")
                        update_state["progress"]["done"] = done   # a tela mostra a barra de download
            if done >= size:
                return
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise
        except (OSError, http.client.HTTPException):
            pass
        if done > before:   # avançou: retoma logo (uma pausa curta — o site corta de novo se a reconexão for imediata)
            stalls = 0
            time.sleep(0.5)
            continue
        stalls += 1
        if stalls >= 6:
            raise ValueError("A conexão caiu várias vezes durante o download")
        time.sleep(min(stalls * 2, 10))


def download_update():
    u = check_update()
    if not u.get("available"):
        raise ValueError("Não há versão nova para baixar")
    if not u.get("sha256") or not str(u.get("url", "")).startswith("https://"):
        raise ValueError("A versão publicada não traz a assinatura do instalador — nada foi baixado")
    os.makedirs(UPDATES_DIR, exist_ok=True)
    # o endereço principal (GitHub Releases) e o espelho (site da ThomSoft): o mesmo arquivo, o mesmo SHA-256 (assinado)
    urls = [x for x in [u["url"], *(u.get("mirrors") or [])] if str(x).startswith(DOWNLOAD_PREFIXES)]
    if not urls:
        raise ValueError("O latest.json aponta para um endereço que não é da ThomSoft — nada foi baixado")
    name = os.path.basename(urllib.parse.urlparse(u["url"]).path)
    if not re.fullmatch(r"Codeck-[\w.\-]+\.(dmg|exe)", name) or any(os.path.basename(urllib.parse.urlparse(x).path) != name for x in urls):
        raise ValueError("Nome de instalador inesperado no latest.json")
    path = os.path.join(UPDATES_DIR, name)
    size = int(u.get("size") or 0)
    update_state["downloading"] = True
    try:
        err = None
        for url in urls:
            update_state["progress"] = {"done": 0, "total": size}
            try:
                _fetch(url, path + ".part", size)
            except Exception as e:  # noqa: BLE001 — tenta o próximo espelho
                err = e
                continue
            digest = hashlib.sha256()
            with open(path + ".part", "rb") as f:
                while chunk := f.read(1 << 20):
                    digest.update(chunk)
            if digest.hexdigest() == u["sha256"] and (not size or os.path.getsize(path + ".part") == size):
                os.replace(path + ".part", path)
                return {"path": path, "version": u["version"], "build": u["build"]}
            err = ValueError("O instalador baixado não confere com o publicado. Nada foi instalado; tente de novo.")
        if os.path.exists(path + ".part"):
            os.remove(path + ".part")
        raise err if isinstance(err, ValueError) else ValueError(f"Não consegui baixar o instalador: {err}")
    finally:
        update_state["downloading"] = False


def update_loop():
    while True:
        check_update()
        time.sleep(3600)


