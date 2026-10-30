"""Importar conexões de outras ferramentas: DBeaver, Tabularis e Beekeeper Studio.

Só lê os arquivos delas (nunca altera). Cada conexão vira um banco com um ambiente; a pasta/grupo vira a pasta do
Codeck. Senhas, só quando você pede, e cada uma vai direto para o cofre do Codeck:
  - DBeaver: credentials-config.json, cifrado com a chave fixa e pública do próprio DBeaver (AES-128-CBC);
  - Tabularis: no Keychain (serviço "tabularis") — o macOS pergunta se o Codeck pode ler cada uma;
  - Beekeeper: a senha é cifrada com uma chave da instalação dele; não é importada (você digita depois).
Bancos ainda sem plugin ficam de fora (aparecem na lista como "ainda não suportado").
"""
import json
import os
import sqlite3
import subprocess
import sys

from . import databases

HOME = os.path.expanduser("~")
if sys.platform == "darwin":
    _APP = os.path.join(HOME, "Library", "Application Support")
    DBEAVER = os.path.join(HOME, "Library", "DBeaverData", "workspace6", "General", ".dbeaver")
else:
    _APP = os.environ.get("APPDATA") or os.path.join(HOME, "AppData", "Roaming")
    DBEAVER = os.path.join(_APP, "DBeaverData", "workspace6", "General", ".dbeaver")
TABULARIS = os.path.join(_APP, "tabularis", "connections.json")
BEEKEEPER = os.path.join(_APP, "beekeeper-studio", "app.db")

ENGINE = {"mssql": "sqlserver", "sqlserver": "sqlserver", "jtds": "sqlserver", "postgresql": "postgres", "postgres": "postgres",
          "mysql": "mysql", "mariadb": "mysql", "sqlite": "sqlite", "cockroach": "postgres", "redshift": "postgres", "mongo": "mongodb", "redis": "redis", "valkey": "redis", "libsql": "libsql", "turso": "libsql"}


def _engine(*names):
    for n in names:
        n = (n or "").lower()
        for k, v in ENGINE.items():
            if k in n:
                return v
    return None


# ---------------------------------------------------------------- AES-128-CBC (só decifrar), para o arquivo do DBeaver
_SBOX = [0] * 256
_INV = [0] * 256


def _init_sbox():
    p = q = 1
    while True:   # gera a S-box pelo inverso multiplicativo em GF(2^8) e a transformação afim
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1 | q >> 7) & 0xFF) ^ ((q << 2 | q >> 6) & 0xFF) ^ ((q << 3 | q >> 5) & 0xFF) ^ ((q << 4 | q >> 4) & 0xFF)
        _SBOX[p] = x ^ 0x63
        if p == 1:
            break
    _SBOX[0] = 0x63
    for i, v in enumerate(_SBOX):
        _INV[v] = i


_init_sbox()


def _xt(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


def _expand(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = [_SBOX[b] for b in t[1:] + t[:1]]
            t[0] ^= rcon
            rcon = _xt(rcon)
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(11)]


def _decrypt_block(blk, rk):
    s = [b ^ k for b, k in zip(blk, rk[10])]
    for rnd in range(9, -1, -1):
        s = [s[(i - 4 * (i % 4)) % 16] for i in range(16)]       # InvShiftRows (estado em colunas)
        s = [_INV[b] for b in s]
        s = [b ^ k for b, k in zip(s, rk[rnd])]
        if rnd:
            out = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                out += [_mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9),
                        _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13),
                        _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11),
                        _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)]
            s = out
    return bytes(s)


def aes128_cbc_decrypt(key, iv, data):
    rk = _expand(key)
    out, prev = b"", iv
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        out += bytes(a ^ b for a, b in zip(_decrypt_block(blk, rk), prev))
        prev = blk
    pad = out[-1] if out else 0
    return out[:-pad] if 0 < pad <= 16 else out


DBEAVER_KEY = bytes.fromhex("babb4a9f774ab853c96c2d653dfe544a")   # a chave pública e fixa do DBeaver (documentada por eles)


def _dbeaver_credentials():
    try:
        with open(os.path.join(DBEAVER, "credentials-config.json"), "rb") as f:
            raw = f.read()
        return json.loads(aes128_cbc_decrypt(DBEAVER_KEY, raw[:16], raw[16:]).decode("utf-8"))
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- leitura das fontes

def _dbeaver(with_secrets):
    try:
        with open(os.path.join(DBEAVER, "data-sources.json"), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    creds = _dbeaver_credentials() if with_secrets else {}
    out = []
    for cid, c in (d.get("connections") or {}).items():
        cfg = c.get("configuration") or {}
        eng = _engine(c.get("provider"), c.get("driver"))
        legacy = "jtds" in (c.get("driver") or "").lower()
        item = {"source": "dbeaver", "id": cid, "name": c.get("name") or cid, "engine": eng, "folder": c.get("folder") or "",
                "kind": {"prod": "prod", "test": "hml"}.get(cfg.get("type"), "dev"), "host": cfg.get("host") or "",
                "port": int(cfg["port"]) if str(cfg.get("port") or "").isdigit() else None, "database": cfg.get("database") or "",
                "file": cfg.get("database") if eng == "sqlite" else "", "user": "", "hasPassword": False,
                "tls": {"mode": "pin" if legacy or eng == "sqlserver" else "verify", "legacy": legacy}}
        cr = (creds.get(cid) or {}).get("#connection") or {}
        item["user"] = cr.get("user") or cfg.get("user") or ""
        item["hasPassword"] = bool(cr.get("password")) if with_secrets else True
        if with_secrets:
            item["password"] = cr.get("password") or ""
        out.append(item)
    return out


def _tabularis(with_secrets):
    try:
        with open(TABULARIS, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    groups = {g["id"]: g.get("name") or "" for g in d.get("groups") or []}
    out = []
    for c in d.get("connections") or []:
        p = c.get("params") or {}
        eng = _engine(p.get("driver"))
        item = {"source": "tabularis", "id": c["id"], "name": c.get("name") or c["id"], "engine": eng, "folder": groups.get(c.get("group_id"), ""),
                "kind": "dev", "host": p.get("host") or "", "port": p.get("port"), "database": p.get("database") or "", "file": "",
                "user": p.get("username") or "", "hasPassword": bool(p.get("password") or p.get("save_in_keychain")), "driver": p.get("driver"),
                "tls": {"mode": "off" if (p.get("ssl_mode") or "").lower() in ("disable", "disabled") else ("pin" if eng == "sqlserver" else "verify"), "legacy": False}}
        if eng == "sqlite":
            item["file"] = p.get("database") or ""
        if with_secrets:
            item["password"] = p.get("password") or (_keychain("tabularis", f"{c['id']}:db") if p.get("save_in_keychain") else "")
        out.append(item)
    return out


def _keychain(service, account):
    if sys.platform != "darwin":
        return ""
    try:   # o macOS pergunta se o Codeck pode ler este item da outra ferramenta
        r = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"], capture_output=True, text=True, timeout=120)
        return r.stdout.rstrip("\n") if r.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        return ""


def _beekeeper(_with_secrets):
    if not os.path.exists(BEEKEEPER):
        return []
    try:
        con = sqlite3.connect(f"file:{BEEKEEPER}?mode=ro", uri=True)
        rows = con.execute("SELECT id, name, connectionType, host, port, username, defaultDatabase, path, ssl FROM saved_connection").fetchall()
        con.close()
    except sqlite3.Error:
        return []
    out = []
    for rid, name, ctype, host, port, user, dbname, path, ssl in rows:
        eng = _engine(ctype)
        out.append({"source": "beekeeper", "id": str(rid), "name": name, "engine": eng, "folder": "", "kind": "dev", "host": host or "", "port": port,
                    "database": dbname or "", "file": path or "", "user": user or "", "hasPassword": False,
                    "tls": {"mode": "verify" if ssl else "off", "legacy": False}})
    return out


SOURCES = {"dbeaver": _dbeaver, "tabularis": _tabularis, "beekeeper": _beekeeper}
LOOPBACK = ("localhost", "127.0.0.1", "::1", "0.0.0.0")


def _tidy(it):
    """Ambiente pelo nome quando a ferramenta não diz ("GlorySoft PROD", "DEV - Legado"); local sem TLS já aceito."""
    n = it["name"].lower()
    if it["kind"] == "dev":
        if any(w in n for w in ("prod", "produção", "producao", "prd")):
            it["kind"] = "prod"
        elif any(w in n for w in ("hml", "homolog", "staging", "stage", "qa")):
            it["kind"] = "hml"
    if (it["host"] or "").lower() in LOOPBACK and it["engine"] != "sqlite":
        it["tls"] = {"mode": "off", "legacy": False, "offAck": True}
    return it


def scan():
    """O que dá para importar (sem senhas). already: já existe um banco com o mesmo servidor/banco/usuário."""
    have = {(e.get("host"), str(e.get("port") or ""), e.get("database"), e.get("user")) for b in databases._load()["banks"] for e in b["envs"]}
    out = []
    for name, fn in SOURCES.items():
        for it in map(_tidy, fn(False)):
            it.pop("password", None)
            it["supported"] = bool(it["engine"])
            it["already"] = (it["host"], str(it["port"] or ""), it["database"], it["user"]) in have
            out.append(it)
    return {"items": out, "found": {k: os.path.exists(p) for k, p in (("dbeaver", os.path.join(DBEAVER, "data-sources.json")),
                                                                         ("tabularis", TABULARIS), ("beekeeper", BEEKEEPER))}}


def run(picks, with_passwords=False):
    """Importa as conexões escolhidas ([{source, id}]). Devolve quantas entraram e quais ficaram sem senha."""
    want = {(p.get("source"), str(p.get("id"))) for p in picks or []}
    created, no_pw = [], []
    for name, fn in SOURCES.items():
        if not any(s == name for s, _ in want):
            continue
        for it in map(_tidy, fn(with_passwords)):
            if (name, str(it["id"])) not in want or not it["engine"]:
                continue
            env = {"kind": it["kind"], "host": it["host"], "port": it["port"], "database": it["database"], "user": it["user"], "file": it["file"],
                   "tls": it["tls"], "password": it.get("password") or None}
            r = databases.save_bank({"name": it["name"], "engine": it["engine"], "folder": it["folder"], "notes": f"Importado do {name.capitalize()}", "envs": [env]})
            created.append(r["bank"]["id"])
            if not env["password"] and it["engine"] != "sqlite":
                no_pw.append(it["name"])
    return {"created": len(created), "noPassword": no_pw, **databases.public()}
