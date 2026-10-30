"""Banco do app Flutter: acha e abre o banco local do app (offline-first) no aparelho onde ele roda.

Detecta pelo projeto: o pubspec.yaml diz o pacote (sqflite, drift, floor, Hive, sembast, shared_preferences…), o
android/ e o ios/ dizem o id do app, e o código diz o nome dos arquivos e — no Hive — o nome dos campos de cada
@HiveType. Não precisa configurar nada.

Onde o arquivo está e como se edita:
  - simulador iOS, macOS e Windows: o arquivo está neste computador e abre direto. Editar grava nele (o SQLite
    controla o acesso junto com o app) e o hot restart mostra o dado novo no app;
  - Android (emulador ou aparelho): `adb … run-as <pacote>` — só build de debug (o próprio Android exige). O Codeck
    trabalha numa cópia; para devolver, fecha o app, guarda um backup do banco do aparelho, troca e reabre o app.
    Trocar com o app aberto não dá: o sqflite segura a conexão nativa mesmo depois do hot restart;
  - iPhone/iPad físico: `xcrun devicectl` (iOS 17+, build de desenvolvimento) — só leitura: o devicectl não apaga o
    -wal do aparelho, e um WAL antigo por cima do banco novo o corromperia.
Hive, sembast e shared_preferences viram um SQLite temporário, só leitura: a mesma bancada (SQL, filtros, cópia,
imagem) serve para todos. Isar, ObjectBox e Realm guardam em formato próprio: aparecem, mas ainda não abrem.

As cópias ficam numa pasta temporária só do seu usuário e somem ao fechar.
"""
import glob
import hashlib
import json
import os
import plistlib
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from . import databases, dbplugins, debug, git
from .dbplugins import PluginError

PACKAGES = {"sqflite": "sqlite", "sqflite_common_ffi": "sqlite", "sqflite_sqlcipher": "sqlite", "drift": "sqlite", "drift_flutter": "sqlite",
            "moor": "sqlite", "moor_flutter": "sqlite", "floor": "sqlite", "sqlite3": "sqlite", "sqlite3_flutter_libs": "sqlite",
            "hive": "hive", "hive_flutter": "hive", "hive_ce": "hive", "hive_ce_flutter": "hive", "sembast": "sembast", "sembast_sqflite": "sembast",
            "shared_preferences": "prefs", "isar": "isar", "isar_flutter_libs": "isar", "isar_community": "isar", "objectbox": "objectbox",
            "objectbox_flutter_libs": "objectbox", "realm": "realm"}
OPENABLE = {"sqlite", "hive", "sembast", "prefs"}
SQLITE_MAGIC = b"SQLite format 3\x00"
SAFE_PATH = re.compile(r"[\w./\-]+")
_lock = threading.Lock()
_apps = {}   # sessão → estado (aparelho, arquivo, cópia, assinatura do remoto, pendências)


def _run(argv, timeout=60, input_bytes=None):
    try:
        return subprocess.run(argv, capture_output=True, timeout=timeout, input=input_bytes,
                              creationflags=0x08000000 if os.name == "nt" else 0)
    except FileNotFoundError:
        raise PluginError("tool-missing", f"Ferramenta não encontrada: {os.path.basename(argv[0])}")
    except subprocess.TimeoutExpired:
        raise PluginError("timeout", f"{os.path.basename(argv[0])} não respondeu a tempo")


# ---------------------------------------------------------------- o projeto

def _read(path, n=2_000_000):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(n)
    except OSError:
        return ""


def _deps(pubspec):
    out, block = set(), None
    for ln in pubspec.splitlines():
        if re.match(r"^(dependencies|dev_dependencies|dependency_overrides):", ln):
            block = True
            continue
        if re.match(r"^\S", ln):
            block = None
        m = re.match(r"^  ([a-z0-9_]+)\s*:", ln)
        if block and m:
            out.add(m.group(1))
    return out


def _hive_types(root):
    """@HiveType(typeId: N) → nome, se é enum e os campos (@HiveField(i) … nome)."""
    types = {}
    for f in glob.glob(os.path.join(root, "lib", "**", "*.dart"), recursive=True)[:3000]:
        src = _read(f)
        if "HiveType" not in src:
            continue
        for m in re.finditer(r"@HiveType\(\s*typeId\s*:\s*(\d+)[^)]*\)\s*(?:@\w+(?:\([^)]*\))?\s*)*(class|enum)\s+(\w+)", src):
            tid, kind, name = int(m.group(1)), m.group(2), m.group(3)
            body_start = src.find("{", m.end())
            depth, i = 0, body_start
            while 0 <= i < len(src):
                depth += {"{": 1, "}": -1}.get(src[i], 0)
                if depth == 0:
                    break
                i += 1
            body = src[body_start:i]
            fields = {}
            if kind == "class":
                for fm in re.finditer(r"@HiveField\(\s*(\d+)[^)]*\)\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:final\s+|late\s+)*[\w<>?,\s]+?\s+(\w+)\s*[;=]", body):
                    fields[int(fm.group(1))] = fm.group(2)
            else:
                vals = [v.strip().split("(")[0] for v in re.sub(r"@\w+(\([^)]*\))?", "", body.strip("{} \n")).split(";")[0].split(",")]
                fields = {i: v for i, v in enumerate(x for x in vals if x)}
            types[tid] = {"name": name, "enum": kind == "enum", "fields": fields}
    return types


def info(repo_id):
    root = git.get_repo(repo_id)["path"]
    pub = _read(os.path.join(root, "pubspec.yaml"))
    if not pub or not re.search(r"^\s+flutter:", pub, re.M) and "sdk: flutter" not in pub:
        return {"flutter": False}
    deps = _deps(pub)
    kinds = sorted({PACKAGES[d] for d in deps if d in PACKAGES})
    ids = {}
    for g in ("android/app/build.gradle", "android/app/build.gradle.kts"):
        m = re.search(r"applicationId\s*=?\s*[\"']([\w.]+)[\"']", _read(os.path.join(root, g)))
        if m:
            ids["android"] = m.group(1)
            break
    bundles = re.findall(r"PRODUCT_BUNDLE_IDENTIFIER = \"?([\w.\-]+)\"?;", _read(os.path.join(root, "ios/Runner.xcodeproj/project.pbxproj")))
    bundles = [b for b in bundles if "Tests" not in b and "$" not in b]
    if bundles:
        ids["ios"] = max(set(bundles), key=bundles.count)
    m = re.search(r"PRODUCT_BUNDLE_IDENTIFIER\s*=\s*([\w.\-]+)", _read(os.path.join(root, "macos/Runner/Configs/AppInfo.xcconfig")))
    if m:
        ids["macos"] = m.group(1)
    rc = _read(os.path.join(root, "windows/runner/Runner.rc"))
    comp, prod = re.search(r'VALUE "CompanyName", "([^"]*)"', rc), re.search(r'VALUE "ProductName", "([^"]*)"', rc)
    if prod:
        ids["windows"] = {"company": comp.group(1) if comp else "", "product": prod.group(1)}
    names = set()
    for f in glob.glob(os.path.join(root, "lib", "**", "*.dart"), recursive=True)[:3000]:
        src = _read(f)
        names.update(re.findall(r"['\"]([\w\-.]+\.(?:db|sqlite3?|hive|sqlite))['\"]", src))
        names.update(n.lower() + ".hive" for n in re.findall(r"openBox(?:<[^>]*>)?\(\s*['\"]([\w\-]+)['\"]", src))
        names.update(n + ".sqlite" for n in re.findall(r"driftDatabase\(\s*name\s*:\s*['\"]([\w\-]+)['\"]", src))
    return {"flutter": True, "kinds": kinds, "openable": [k for k in kinds if k in OPENABLE], "unsupported": [k for k in kinds if k not in OPENABLE],
            "packages": sorted(d for d in deps if d in PACKAGES), "ids": ids, "names": sorted(names)}


# ---------------------------------------------------------------- aparelhos

def devices(repo_id):
    inf = info(repo_id)
    out = []
    for d in debug.devices().get("devices") or []:
        p = (d.get("platform") or "").lower()
        kind = "android" if p.startswith("android") else "ios-sim" if p == "ios" and d.get("emulator") else "ios" if p == "ios" \
            else "macos" if p.startswith("darwin") else "windows" if p.startswith("windows") else None
        if not kind:
            continue
        need = {"android": "android", "ios-sim": "ios", "ios": "ios", "macos": "macos", "windows": "windows"}[kind]
        out.append({"id": d["id"], "name": d.get("name") or d["id"], "kind": kind, "appId": bool(inf.get("ids", {}).get(need)),
                    "editable": kind != "ios", "running": _running_session(repo_id, d["id"]) is not None})
    return {"devices": out, "info": inf}


def _running_session(repo_id, device_id):
    for s in list(debug._sessions.values()):
        if getattr(s, "repo_id", None) == repo_id and getattr(s, "adapter", None) == "dart" and getattr(s, "device", None) == device_id \
                and getattr(s, "status", "") not in ("exited", "terminated", "error"):
            return s
    return None


def _kind_of(path, head=b""):
    low = path.lower()
    if head.startswith(SQLITE_MAGIC) or low.endswith((".db", ".sqlite", ".sqlite3")) and not head:
        return "sqlite"
    if low.endswith(".hive"):
        return "hive"
    if low.endswith(("fluttersharedpreferences.xml", ".plist", "shared_preferences.json")):
        return "prefs"
    if head[:1] == b"{" and b"sembast" in head[:200]:
        return "sembast"
    return None


def _adb():
    a = debug._adb()
    if not a:
        raise PluginError("tool-missing", "adb não encontrado (Android SDK → platform-tools)")
    return a


def _app_id(repo_id, kind):
    ids = info(repo_id).get("ids") or {}
    v = ids.get({"android": "android", "ios-sim": "ios", "ios": "ios", "macos": "macos", "windows": "windows"}[kind])
    if not v:
        raise PluginError("no-app-id", "Não achei o id do app no projeto (applicationId / PRODUCT_BUNDLE_IDENTIFIER)")
    return v


def _sim_container(udid, bundle):
    r = _run(["xcrun", "simctl", "get_app_container", udid, bundle, "data"], timeout=30)
    if r.returncode:
        raise PluginError("app-not-installed", "O app não está instalado neste simulador — rode o projeto nele uma vez")
    return r.stdout.decode().strip()


def _local_roots(repo_id, kind, device):
    if kind == "ios-sim":
        return [_sim_container(device, _app_id(repo_id, kind))]
    home = os.path.expanduser("~")
    if kind == "macos":   # só as pastas do app: o contêiner (sandbox) ou a pasta dele em Application Support
        b = _app_id(repo_id, kind)
        return [p for p in (os.path.join(home, "Library", "Containers", b, "Data", "Documents"),
                            os.path.join(home, "Library", "Containers", b, "Data", "Library"),
                            os.path.join(home, "Library", "Application Support", b)) if os.path.isdir(p)]
    w = _app_id(repo_id, kind)
    appdata = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    return [p for p in (os.path.join(appdata, w["company"], w["product"]), os.path.join(appdata, w["product"])) if os.path.isdir(p)]


def files(repo_id, device_id):
    dev = next((d for d in devices(repo_id)["devices"] if d["id"] == device_id), None)
    if not dev:
        raise PluginError("no-device", "Aparelho não encontrado — está ligado?")
    kind, inf = dev["kind"], info(repo_id)
    names = {n.lower() for n in inf.get("names") or []}
    out = []

    def add(path, rel, size, mtime, head=b"", force=None):
        base = os.path.basename(rel).lower()
        if re.search(r"-(wal|shm|journal)$|\.lock$", base):
            return
        k = force or _kind_of(rel, head)
        if k is None and base not in names:
            return
        if k == "prefs" and kind == "macos" and not base.startswith(_app_id(repo_id, kind).lower()) and base.endswith(".plist"):
            return
        out.append({"path": path, "rel": rel, "kind": k or "sqlite", "size": size, "mtime": mtime})

    if kind == "macos":
        pl = os.path.join(os.path.expanduser("~"), "Library", "Preferences", _app_id(repo_id, kind) + ".plist")
        if os.path.isfile(pl):
            add(pl, os.path.basename(pl), os.path.getsize(pl), os.path.getmtime(pl), force="prefs")
    if kind in ("ios-sim", "macos", "windows"):
        for root in _local_roots(repo_id, kind, device_id):
            for dp, dns, fns in os.walk(root):
                if dp[len(root):].count(os.sep) > 5:
                    dns[:] = []
                    continue
                dns[:] = [d for d in dns if d not in ("Caches", "tmp", "WebKit", "SplashBoard", "Snapshots", "HTTPStorages", "Saved Application State")
                          and not os.path.islink(os.path.join(dp, d))]
                for fn in fns:
                    p = os.path.join(dp, fn)
                    try:
                        st = os.stat(p)
                        with open(p, "rb") as f:
                            head = f.read(200)
                    except OSError:
                        continue
                    add(p, os.path.relpath(p, root), st.st_size, st.st_mtime, head)
    elif kind == "android":
        pkg = _app_id(repo_id, kind)
        r = _run([_adb(), "-s", device_id, "shell", "run-as", pkg, "find", ".", "-maxdepth", "5", "-type", "f"], timeout=30)
        if r.returncode:
            msg = (r.stderr or r.stdout).decode(errors="replace")
            if "not debuggable" in msg:
                raise PluginError("not-debuggable", "O app instalado não é build de debug — o Android só deixa ler o banco de builds de debug")
            raise PluginError("adb", f"Não consegui ler o app no aparelho: {msg.strip()[:200]}")
        for ln in r.stdout.decode(errors="replace").splitlines():
            rel = ln.strip().lstrip("./")
            if rel and SAFE_PATH.fullmatch(rel) and not rel.startswith(("cache/", "code_cache/", "app_webview/", "no_backup/com.google")):
                if rel.startswith("databases/"):   # pasta do sqflite/floor/drift no Android: SQLite, com ou sem extensão
                    add(rel, rel, None, None, force="sqlite")
                elif _kind_of(rel) or os.path.basename(rel).lower() in names:
                    add(rel, rel, None, None)
    elif kind == "ios":
        bundle = _app_id(repo_id, kind)
        tmp = tempfile.mkdtemp(prefix="codeck-ls-")
        try:
            out_json = os.path.join(tmp, "o.json")
            r = _run(["xcrun", "devicectl", "device", "info", "files", "--device", device_id, "--domain-type", "appDataContainer",
                      "--domain-identifier", bundle, "--json-output", out_json], timeout=90)
            if r.returncode:
                raise PluginError("devicectl", "Não consegui listar os arquivos do app no iPhone (precisa de iOS 17+ e build de desenvolvimento)")
            data = json.load(open(out_json))
            for f in (data.get("result") or {}).get("files") or []:
                rel = f.get("relativePath") or f.get("path") or ""
                if rel and SAFE_PATH.fullmatch(rel) and not f.get("isDirectory"):
                    add(rel, rel, f.get("size"), None)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    out.sort(key=lambda x: ({"sqlite": 0, "hive": 1, "sembast": 2, "prefs": 3}.get(x["kind"], 9), x["rel"]))
    return {"files": out, "device": dev}


# ---------------------------------------------------------------- abrir (direto, cópia ou conversão)

def _workdir():
    d = tempfile.mkdtemp(prefix="codeck-app-")
    os.chmod(d, 0o700)
    return d


def _pull(st):
    """Traz o arquivo (com -wal/-shm) do aparelho para a pasta de trabalho. Devolve o caminho local."""
    dest = os.path.join(st["work"], "snap", os.path.basename(st["rel"]))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(dest + suffix):
            os.remove(dest + suffix)
    if st["kind_dev"] == "android":
        for suffix in ("", "-wal", "-shm"):
            r = _run([_adb(), "-s", st["device"], "exec-out", "run-as", st["app"], "cat", st["rel"] + suffix], timeout=180)
            if r.returncode or (not r.stdout and suffix):
                if suffix:
                    continue
                raise PluginError("adb", "Não consegui copiar o banco do aparelho")
            with open(dest + suffix, "wb") as f:
                f.write(r.stdout)
    else:   # iPhone físico
        for suffix in ("", "-wal", "-shm"):
            r = _run(["xcrun", "devicectl", "device", "copy", "from", "--device", st["device"], "--domain-type", "appDataContainer",
                      "--domain-identifier", st["app"], "--source", st["rel"] + suffix, "--destination", dest + suffix], timeout=180)
            if r.returncode and not suffix:
                raise PluginError("devicectl", "Não consegui copiar o banco do iPhone")
    return dest


def _remote_sig(st):
    if st["kind_dev"] == "android":
        r = _run([_adb(), "-s", st["device"], "shell", "run-as", st["app"], "stat", "-c", "%s:%Y", st["rel"], st["rel"] + "-wal"], timeout=20)
        return r.stdout.decode(errors="replace").strip()
    if st["kind_dev"] == "ios":
        return str(int(time.time() // 10))   # sem stat barato no iPhone: relê a cada 10 s no modo ao vivo
    sig = []
    for suffix in ("", "-wal"):
        try:
            s = os.stat(st["src"] + suffix)
            sig.append(f"{s.st_size}:{s.st_mtime_ns}")
        except OSError:
            sig.append("-")
    return "|".join(sig)


def open_app(repo_id, device_id, path):
    dev = next((d for d in devices(repo_id)["devices"] if d["id"] == device_id), None)
    if not dev:
        raise PluginError("no-device", "Aparelho não encontrado — está ligado?")
    listed = next((f for f in files(repo_id, device_id)["files"] if f["path"] == path), None)
    if not listed:
        raise PluginError("no-file", "Esse arquivo não está mais no app")
    kind_dev = dev["kind"]
    st = {"repo": repo_id, "device": device_id, "kind_dev": kind_dev, "rel": listed["rel"], "fmt": listed["kind"], "work": _workdir(),
          "app": _app_id(repo_id, kind_dev), "src": path if kind_dev in ("ios-sim", "macos", "windows") else None, "dirty": False,
          "backup": None, "deviceName": dev["name"]}
    local = st["src"] if st["src"] else _pull(st)
    direct = st["src"] is not None and st["fmt"] == "sqlite"
    if st["fmt"] != "sqlite":
        local = _convert(st, local)
    st["local"] = local
    st["sig"] = _remote_sig(st)
    writable = st["fmt"] == "sqlite" and kind_dev != "ios"
    label = f"{os.path.basename(st['rel'])} · {dev['name']}"
    sess = databases.open_file_session(local, label=label, read_only=not writable, repo_id=repo_id, bank_id="app:" + repo_id,
                                       onwrite=None if direct else (lambda sid: _mark_dirty(sid)))
    sess_id = sess["id"]
    with _lock:
        _apps[sess_id] = st
    databases._sessions[sess_id]["onclose"] = lambda: shutil.rmtree(st["work"], ignore_errors=True)
    return {**sess, "app": _public(st, sess_id)}


def _public(st, sid=None):
    return {"device": st["device"], "deviceName": st["deviceName"], "deviceKind": st["kind_dev"], "rel": st["rel"], "format": st["fmt"],
            "direct": st["src"] is not None and st["fmt"] == "sqlite", "dirty": st["dirty"], "backup": bool(st["backup"]),
            "editable": st["fmt"] == "sqlite" and st["kind_dev"] != "ios",
            "running": _running_session(st["repo"], st["device"]) is not None}


def _mark_dirty(sid):
    st = _apps.get(sid)
    if st:
        st["dirty"] = True


def _state(sid):
    st = _apps.get(sid)
    if not st:
        raise PluginError("no-session", "Conexão fechada — abra de novo")
    return st


def sync(sid):
    """Modo ao vivo: o arquivo mudou no aparelho? Se mudou (e você não tem edição pendente), relê."""
    st = _state(sid)
    sig = _remote_sig(st)
    if sig == st["sig"]:
        return {"changed": False, "app": _public(st, sid)}
    if st["dirty"]:
        return {"changed": False, "conflict": True, "app": _public(st, sid)}
    st["sig"] = sig
    if st["src"] and st["fmt"] == "sqlite":   # aberto direto: a próxima consulta já vê o dado novo
        return {"changed": True, "app": _public(st, sid)}
    local = st["src"] or _pull(st)
    if st["fmt"] != "sqlite":
        local = _convert(st, local)
    databases.reopen_file_session(sid, local)
    st["local"] = local
    return {"changed": True, "app": _public(st, sid)}


def push(sid, relaunch=True):
    """Android: devolve a cópia editada ao aparelho — fecha o app, guarda o banco atual como backup, troca e reabre."""
    st = _state(sid)
    if st["kind_dev"] != "android":
        raise PluginError("not-supported", "Só o Android recebe o banco de volta (no simulador e no desktop a edição já é direta)")
    if not SAFE_PATH.fullmatch(st["rel"]):
        raise PluginError("bad-path", "Caminho inesperado")
    s = databases._get(sid)   # tudo no arquivo principal antes de enviar (direto no plugin: não é comando seu)
    dbplugins.get("sqlite").call("query", {"session": s["plugin"], "sql": "PRAGMA wal_checkpoint(TRUNCATE)"}, timeout=60)
    adb, dev, pkg, rel = _adb(), st["device"], st["app"], st["rel"]
    backup = os.path.join(st["work"], f"backup-{int(time.time())}.db")
    r = _run([adb, "-s", dev, "exec-out", "run-as", pkg, "cat", rel], timeout=180)
    if r.returncode:
        raise PluginError("adb", "Não consegui guardar o backup do banco do aparelho — nada foi trocado")
    with open(backup, "wb") as f:
        f.write(r.stdout)
    _send(st, st["local"], relaunch)
    st["backup"], st["dirty"] = backup, False
    st["sig"] = _remote_sig(st)
    return {"ok": True, "app": _public(st, sid)}


def undo(sid, relaunch=True):
    st = _state(sid)
    if not st.get("backup"):
        raise PluginError("no-backup", "Não há backup para voltar")
    _send(st, st["backup"], relaunch)
    shutil.copyfile(st["backup"], st["local"])
    for suffix in ("-wal", "-shm"):
        if os.path.exists(st["local"] + suffix):
            os.remove(st["local"] + suffix)
    databases.reopen_file_session(sid, st["local"])
    st["backup"], st["dirty"] = None, False
    st["sig"] = _remote_sig(st)
    return {"ok": True, "app": _public(st, sid)}


def _send(st, local, relaunch):
    adb, dev, pkg, rel = _adb(), st["device"], st["app"], st["rel"]
    tmp = f"/data/local/tmp/codeck-{hashlib.sha1(os.urandom(8)).hexdigest()[:10]}.db"
    if _run([adb, "-s", dev, "push", local, tmp], timeout=300).returncode:
        raise PluginError("adb", "Não consegui enviar o banco ao aparelho — nada foi trocado")
    try:
        _run([adb, "-s", dev, "shell", "am", "force-stop", pkg], timeout=30)
        if not re.fullmatch(r"[\w.]+", pkg) or not SAFE_PATH.fullmatch(rel):
            raise PluginError("bad-path", "Caminho inesperado")
        # o adb shell junta os argumentos num texto só: o script vai entre aspas (caminho e pacote já conferidos)
        r = _run([adb, "-s", dev, "shell", f"run-as {pkg} sh -c 'cp {tmp} {rel} && rm -f {rel}-wal {rel}-shm'"], timeout=60)
        if r.returncode:
            raise PluginError("adb", f"O aparelho recusou a troca: {(r.stderr or r.stdout).decode(errors='replace').strip()[:200]}")
    finally:
        _run([adb, "-s", dev, "shell", "rm", "-f", tmp], timeout=30)
    if relaunch:
        _run([adb, "-s", dev, "shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"], timeout=30)


def hot_restart(sid):
    st = _state(sid)
    s = _running_session(st["repo"], st["device"])
    if not s:
        raise PluginError("not-running", "O app não está rodando pelo Codeck neste aparelho")
    return s.control("hotRestart")


# ---------------------------------------------------------------- conversões (Hive, sembast, shared_preferences)

def _convert(st, src):
    out = os.path.join(st["work"], "conv-" + hashlib.sha1(src.encode()).hexdigest()[:8] + f"-{int(time.time() * 1000)}.sqlite")
    con = sqlite3.connect(out)
    try:
        if st["fmt"] == "hive":
            _hive_to_sql(con, src, _hive_types(git.get_repo(st["repo"])["path"]))
        elif st["fmt"] == "sembast":
            _sembast_to_sql(con, src)
        elif st["fmt"] == "prefs":
            _prefs_to_sql(con, src)
        con.commit()
    finally:
        con.close()
    return out


def _table(con, name, rows, extra_cols=()):
    """rows: [{"key":…, "value":…, campos…}] → tabela com key, value (JSON) e uma coluna por campo."""
    q = lambda s: '"' + str(s).replace('"', '""') + '"'
    cols = ["key", "value", *[c for c in extra_cols if c not in ("key", "value")]][:80]
    con.execute(f"CREATE TABLE {q(name)} ({', '.join(q(c) + (' PRIMARY KEY' if c == 'key' else '') for c in cols)})")
    for r in rows:
        vals = [r.get(c) for c in cols]
        vals = [v if v is None or isinstance(v, (int, float, str)) else json.dumps(v, ensure_ascii=False, default=str) for v in vals]
        con.execute(f"INSERT OR REPLACE INTO {q(name)} VALUES ({', '.join('?' * len(cols))})", vals)


def _flatten(rows):
    cols = []
    for r in rows:
        if isinstance(r["value"], dict):
            for k in r["value"]:
                if k not in cols:
                    cols.append(k)
                r.setdefault(k, r["value"][k])
    return cols


class _Hive:
    def __init__(self, data, types):
        self.b, self.i, self.types = data, 0, types

    def u8(self):
        v = self.b[self.i]
        self.i += 1
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.b, self.i)[0]
        self.i += 4
        return v

    def f64(self):
        v = struct.unpack_from("<d", self.b, self.i)[0]
        self.i += 8
        return v

    def int_(self):
        v = self.f64()
        return int(v) if v == v and abs(v) < 2 ** 63 else v

    def text(self, n=None):
        n = self.u32() if n is None else n
        v = self.b[self.i:self.i + n].decode("utf-8", errors="replace")
        self.i += n
        return v

    def value(self):
        t = self.u8()
        if t == 0:
            return None
        if t == 1:
            return self.int_()
        if t == 2:
            return self.f64()
        if t == 3:
            return self.u8() != 0
        if t == 4:
            return self.text()
        if t == 5:
            n = self.u32()
            v = "0x" + self.b[self.i:self.i + n].hex().upper()
            self.i += n
            return v
        if t in (6, 7):
            return [self.int_() if t == 6 else self.f64() for _ in range(self.u32())]
        if t == 8:
            return [self.u8() != 0 for _ in range(self.u32())]
        if t == 9:
            return [self.text() for _ in range(self.u32())]
        if t == 10:
            return [self.value() for _ in range(self.u32())]
        if t == 11:
            n = self.u32()
            out = {}
            for _ in range(n):
                k = self.value()
                out[str(k)] = self.value()
            return out
        if t == 12:   # HiveList: chaves de outra caixa
            n = self.u32()
            box = self.text(self.u8())
            keys = [self.u32() if self.u8() == 0 else self.text(self.u8()) for _ in range(n)]
            return {"$box": box, "keys": keys}
        if t == 16:   # DateTime
            return datetime.fromtimestamp(self.int_() / 1000, tz=timezone.utc).astimezone().isoformat(sep=" ")
        if t == 18:   # DateTime com fuso
            ms, utc = self.int_(), self.u8() != 0
            d = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
            return (d if utc else d.astimezone()).isoformat(sep=" ")
        if t == 17:   # BigInt
            return self.text(self.u8())
        if t >= 32:
            ty = self.types.get(t - 32)
            if ty and ty["enum"]:
                idx = self.u8()
                return ty["fields"].get(idx, idx)
            n = self.u8()
            obj = {}
            for _ in range(n):
                idx = self.u8()
                obj[(ty or {}).get("fields", {}).get(idx, f"campo{idx}")] = self.value()
            if not ty:
                obj["$typeId"] = t - 32
            return obj
        raise ValueError(f"tipo {t} desconhecido")


def _hive_to_sql(con, path, types):
    data = open(path, "rb").read()
    entries, i = {}, 0
    while i + 8 <= len(data):
        ln = struct.unpack_from("<I", data, i)[0]
        if ln < 8 or i + ln > len(data):
            break
        r = _Hive(data[i:i + ln - 4], types)
        r.i = 4
        kt = r.u8()
        key = r.u32() if kt == 0 else r.text(r.u8())
        if r.i >= len(r.b):
            entries.pop(key, None)   # registro apagado
        else:
            try:
                entries[key] = r.value()
            except (ValueError, struct.error, IndexError) as e:
                entries[key] = {"$erro": f"não consegui ler ({e}) — a caixa pode estar criptografada"}
        i += ln
    rows = [{"key": k, "value": v} for k, v in entries.items()]
    cols = _flatten(rows)
    name = os.path.splitext(os.path.basename(path))[0]
    _table(con, name, rows, cols)


def _sembast_to_sql(con, path):
    stores = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, ln in enumerate(f):
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            if n == 0 and "sembast" in rec:
                continue
            store = rec.get("store") or "_main"
            if rec.get("deleted"):
                stores.setdefault(store, {}).pop(json.dumps(rec.get("key")), None)
            else:
                stores.setdefault(store, {})[json.dumps(rec.get("key"))] = {"key": rec.get("key"), "value": rec.get("value")}
    for store, recs in stores.items():
        rows = list(recs.values())
        _table(con, store, rows, _flatten(rows))


def _prefs_to_sql(con, path):
    rows = []
    low = path.lower()
    if low.endswith(".xml"):
        for el in ET.parse(path).getroot():
            name = el.get("name")
            if el.tag == "set":
                val = [x.text for x in el]
            elif el.tag == "string":
                val = el.text or ""
            else:
                val = el.get("value")
            rows.append({"key": name, "value": val, "type": el.tag})
    elif low.endswith(".plist"):
        with open(path, "rb") as f:
            d = plistlib.load(f)
        rows = [{"key": k, "value": v if not isinstance(v, bytes) else "0x" + v.hex(), "type": type(v).__name__} for k, v in d.items()]
    else:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        rows = [{"key": k, "value": v, "type": type(v).__name__} for k, v in d.items()]
    rows.sort(key=lambda r: (not str(r["key"]).startswith("flutter."), str(r["key"])))
    _table(con, "preferences", rows, ["type"])
