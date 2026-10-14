"""Atualização do app: lê o latest.json do canal (site da ThomSoft) e baixa o instalador conferindo o SHA-256."""
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request

from .core import APP_BUILD, APP_PLATFORM, UPDATE_URL, UPDATES_DIR, now_iso


update_state = {"available": False, "checkedAt": None, "error": None, "downloading": False}


def check_update():
    """Fail-open: qualquer falha de rede/JSON só deixa "sem atualização"."""
    if not UPDATE_URL:
        update_state.update(available=False, checkedAt=now_iso(), error=None, disabled=True)
        return update_state
    try:
        r = urllib.request.Request(f"{UPDATE_URL}?t={int(time.time())}", headers={"Cache-Control": "no-cache", "User-Agent": "Codeck"})
        with urllib.request.urlopen(r, timeout=15) as resp:
            info = json.loads(resp.read(200_000))
        asset = info.get(APP_PLATFORM) or {}
        build = int(asset.get("build") or 0)
        required = int(info.get("required") or 0)
        update_state.update(
            available=bool(asset.get("url")) and build > APP_BUILD, checkedAt=now_iso(), error=None, disabled=False,
            version=asset.get("version"), build=build, notes=info.get("notes"), publishedAt=info.get("publishedAt"),
            required=APP_BUILD < required <= build, url=asset.get("url"), sha256=(asset.get("sha256") or "").lower(),
            size=asset.get("size"))
    except Exception as e:  # noqa: BLE001
        update_state.update(available=False, checkedAt=now_iso(), error=str(e)[:200])
    return update_state


def download_update():
    u = check_update()
    if not u.get("available"):
        raise ValueError("Não há versão nova para baixar")
    if not u.get("sha256") or not str(u.get("url", "")).startswith("https://"):
        raise ValueError("A versão publicada não traz a assinatura do instalador — nada foi baixado")
    os.makedirs(UPDATES_DIR, exist_ok=True)
    name = os.path.basename(urllib.parse.urlparse(u["url"]).path)
    if not re.fullmatch(r"Codeck-[\w.\-]+\.(dmg|exe)", name):
        raise ValueError("Nome de instalador inesperado no latest.json")
    path = os.path.join(UPDATES_DIR, name)
    update_state["downloading"] = True
    update_state["progress"] = {"done": 0, "total": int(u.get("size") or 0)}
    try:
        digest = hashlib.sha256()
        req = urllib.request.Request(u["url"], headers={"User-Agent": "Codeck"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(path + ".part", "wb") as f:
            if not update_state["progress"]["total"]:
                update_state["progress"]["total"] = int(resp.headers.get("Content-Length") or 0)
            while chunk := resp.read(1 << 16):
                digest.update(chunk)
                f.write(chunk)
                update_state["progress"]["done"] += len(chunk)   # a tela mostra a barra de download
        if digest.hexdigest() != u["sha256"] or (u.get("size") and os.path.getsize(path + ".part") != int(u["size"])):
            os.remove(path + ".part")
            raise ValueError("O instalador baixado não confere com o publicado. Nada foi instalado; tente de novo.")
        os.replace(path + ".part", path)
    finally:
        update_state["downloading"] = False
    return {"path": path, "version": u["version"], "build": u["build"]}


def update_loop():
    while True:
        check_update()
        time.sleep(3600)


