"""Bateria de testes dos bancos de dados do Codeck — a mesma no macOS e no Windows (só a biblioteca padrão do Python).

Sobe o backend de verdade (server.py) numa pasta de dados temporária e testa pela API, como a tela faz: cofre de
senhas, plugins, políticas de produção, edições, consultas salvas, histórico, imagem, importação, instalação de
plugin, MCP dos agentes (com um cliente MCP de verdade), banco do app Flutter e túnel SSH. Com --targets, testa também
cada banco real (containers, emuladores, aparelho Android).

    python run_tests.py --plugins <pasta dos codeck-db-*> [--targets alvos.json] [--report relatorio.txt] [--no-clipboard]

No fim, apaga tudo o que criou — inclusive as senhas de teste no Keychain/DPAPI. Nada vai para a internet.
"""
import argparse
import base64
import json
import os
import plistlib
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import zlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # ✓ e acentos no console do Windows (o -I ignora PYTHONIOENCODING)
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("CODECK_ROOT") or os.path.dirname(os.path.dirname(HERE))
BACKEND = os.path.join(ROOT, "backend")
FIX = os.path.join(HERE, "fixtures")
WIN = os.name == "nt"

ap = argparse.ArgumentParser()
ap.add_argument("--plugins", required=True)
ap.add_argument("--targets")
ap.add_argument("--report")
ap.add_argument("--no-clipboard", action="store_true")
ap.add_argument("--only", help="só os testes cujo nome contém este texto")
ARGS = ap.parse_args()
PLUGINS = os.path.abspath(ARGS.plugins)
TARGETS = json.load(open(ARGS.targets, encoding="utf-8-sig")) if ARGS.targets else {}   # o PowerShell 5.1 grava UTF-8 com BOM

DATA = tempfile.mkdtemp(prefix="codeck-testes-")
WORK = tempfile.mkdtemp(prefix="codeck-testes-work-")
os.environ["CODECK_DATA"] = DATA   # o backend e os testes "por dentro" usam a mesma pasta
os.environ["CODECK_DB_PLUGINS"] = PLUGINS   # idem para os plugins (no pacote do Windows não há db/bin para achar)
sys.path.insert(0, BACKEND)

out_lines = []


def say(s=""):
    print(s, flush=True)
    out_lines.append(s)


class Skip(Exception):
    pass


def ok(cond, what):
    if not cond:
        raise AssertionError(what)


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# ---------------------------------------------------------------- backend

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = free_port()
TOKEN = base64.urlsafe_b64encode(os.urandom(24)).decode()
BASE = f"http://127.0.0.1:{PORT}"
env = {**os.environ, "CODECK_PORT": str(PORT), "CODECK_TOKEN": TOKEN, "CODECK_DATA": DATA, "CODECK_DB_PLUGINS": PLUGINS,
       "PYTHONIOENCODING": "utf-8"}
for _t in TARGETS.values():   # o túnel de teste usa o known_hosts dele (o app nunca define esta variável)
    if _t.get("kind") == "ssh" and _t.get("known_hosts"):
        env["CODECK_TEST_KNOWN_HOSTS"] = _t["known_hosts"]
backend_log = open(os.path.join(WORK, "backend.log"), "w", encoding="utf-8", errors="replace")
BACKEND_PROC = subprocess.Popen([sys.executable, "-I", "-B", os.path.join(BACKEND, "server.py")], env=env, stdout=backend_log,
                                stderr=subprocess.STDOUT, creationflags=0x08000000 if WIN else 0)


class ApiError(Exception):
    def __init__(self, status, data):
        super().__init__(f"{status}: {data.get('code')} {data.get('error')}")
        self.status, self.data, self.code = status, data, data.get("code")


def api(path, body=None, headers=None, raw=False):
    h = {"X-Codeck-Token": TOKEN}
    if body is not None:
        h.update({"X-Codeck": "1", "Content-Type": "application/json"})
    h.update(headers or {})
    req = urllib.request.Request(BASE + "/api/" + path, data=None if body is None else json.dumps(body).encode(), headers=h,
                                 method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        data = json.loads(e.read() or b"{}")
        raise ApiError(e.code, data)


def expect_error(code, fn):
    try:
        fn()
    except ApiError as e:
        ok(e.code == code, f"esperava erro {code}, veio {e.code}: {e.data.get('error')}")
        return e
    raise AssertionError(f"esperava erro {code}, mas deu certo")


for _ in range(100):
    try:
        api("db")
        break
    except Exception:  # noqa: BLE001
        time.sleep(0.2)
else:
    print(open(os.path.join(WORK, "backend.log"), encoding="utf-8", errors="replace").read())
    sys.exit("o backend não subiu")

from pilot import agents, databases, dbimport, dbmcp, dbplugins, dbtunnel, flutterdb, secrets as sec, update  # noqa: E402
from pilot.core import ctx  # noqa: E402
ctx.port = PORT

REPO = None   # um repositório git temporário, registrado no backend (consultas salvas, MCP, vínculos)


def repo():
    global REPO
    if REPO:
        return REPO
    if not shutil.which("git"):
        raise Skip("sem git")
    d = os.path.join(WORK, "projeto-teste")
    os.makedirs(d, exist_ok=True)
    subprocess.run(["git", "init", "-q", d], check=True, creationflags=0x08000000 if WIN else 0)
    api("repos/add", {"path": d})
    REPO = next(r["id"] for r in api("repos")["repos"] if os.path.normcase(os.path.realpath(r["path"])) == os.path.normcase(os.path.realpath(d)))
    return REPO


def new_sqlite(name="teste.db"):
    f = os.path.join(WORK, name)
    if os.path.exists(f):
        os.remove(f)
    con = sqlite3.connect(f)
    con.executescript("CREATE TABLE clientes (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, saldo REAL);"
                      "INSERT INTO clientes VALUES (1, 'Ana', 10.5), (2, 'Bruno', NULL), (3, 'Carla', 3);")
    con.commit()
    con.close()
    return f


def bank(name, engine, envs, **kw):
    return api("db/bank", {"name": name, "engine": engine, "envs": envs, **kw})["bank"]


def rows(r, i=-1):
    return r["results"][i].get("rows")


def q(session, sql, **kw):
    return api("db/query", {"session": session, "sql": sql, **kw})


# ---------------------------------------------------------------- testes gerais

@test
def seguranca_http():
    def raw(path, method="GET", headers=None, data=None):
        req = urllib.request.Request(BASE + path, data=data, headers=headers or {}, method=method)
        try:
            urllib.request.urlopen(req, timeout=10)
            return 200
        except urllib.error.HTTPError as e:
            return e.code
    ok(raw("/api/db") in (401, 403), "API sem a chave da execução respondeu")
    ok(raw("/api/db", headers={"X-Codeck-Token": "chave-errada"}) in (401, 403), "API com chave errada respondeu")
    ok(raw("/api/db/bank", "POST", {"X-Codeck-Token": TOKEN, "Content-Type": "application/json"}, b"{}") == 403, "POST sem X-Codeck aceito")
    ok(raw("/api/db", headers={"X-Codeck-Token": TOKEN, "Origin": "https://evil.example"}) == 403, "Origin de site aceita")
    ok(raw("/dbmcp/token-falso", "POST", {"Content-Type": "application/json"}, b'{"tool":"list_databases"}') == 403, "MCP com token falso aceito")


@test
def cofre_de_senhas():
    pw = "Sênha 'com' \"aspas\" ;&|<>%$` çãõ \\ fim"
    ref = sec.put_text("codeck-teste-1", pw)
    try:
        ok(sec.get_text("codeck-teste-1", ref) == pw, "senha voltou diferente")
    finally:
        sec.delete("codeck-teste-1", ref)
    sa = json.dumps({"type": "service_account", "private_key": "-----BEGIN PRIVATE KEY-----\n" + "A" * 1700 + "\n-----END PRIVATE KEY-----\n",
                     "client_email": "x@y.iam.gserviceaccount.com", "project_id": "p"})
    ref = sec.put_text("codeck-teste-2", sa)
    try:
        ok(sec.get_text("codeck-teste-2", ref) == sa, f"JSON de conta de serviço ({len(sa)} caracteres) voltou diferente")
    finally:
        sec.delete("codeck-teste-2", ref)
    b = bank("Cofre", "sqlite", [{"kind": "dev", "file": new_sqlite("cofre.db"), "password": "nao-deveria-aparecer"}])
    ok("nao-deveria-aparecer" not in open(os.path.join(DATA, "databases.json"), encoding="utf-8").read(), "senha em texto no databases.json")
    ok(not any("password" in e or "secret" in e for e in b["envs"]), "a tela recebeu a senha ou a referência")
    api("db/bank/delete", {"id": b["id"]})


@test
def plugins_respondem():
    found = sorted(f for f in os.listdir(PLUGINS) if f.startswith("codeck-db-"))
    ok(found, f"nenhum plugin em {PLUGINS}")
    for f in found:
        p = subprocess.Popen([os.path.join(PLUGINS, f)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, creationflags=0x08000000 if WIN else 0)
        out, _ = p.communicate(b'{"id":1,"method":"hello"}\n', timeout=20)
        r = json.loads(out.decode().splitlines()[0])["result"]
        ok(r["protocol"] == 1, f"{f}: protocolo {r.get('protocol')}")
        say(f"     {f}: {r['engine']} {r['version']}")


@test
def sqlite_fluxo_completo():
    f = new_sqlite()
    b = bank("Loja", "sqlite", [{"kind": "dev", "file": f}, {"kind": "prod", "file": f}])
    dev, prod = b["envs"][0]["id"], b["envs"][1]["id"]
    s = api("db/open", {"bank": b["id"], "env": dev})["id"]
    r = q(s, "SELECT * FROM clientes ORDER BY id; SELECT count(*) AS n FROM clientes")
    ok(rows(r, 0) == [[1, "Ana", 10.5], [2, "Bruno", None], [3, "Carla", 3]], f"linhas: {rows(r, 0)}")
    ok(rows(r, 1) == [[3]], "segundo resultado")
    r = q(s, "SELECT * FROM clientes", maxRows=2)
    ok(r["results"][0]["truncated"] and r["results"][0]["total"] == 3, "truncado com total")
    objs = api("db/catalog", {"session": s, "what": "objects"})
    ok(any(o["name"] == "clientes" for o in objs), "catálogo sem a tabela")
    t = api("db/catalog", {"session": s, "what": "table", "schema": "main", "name": "clientes"})
    ok([c["name"] for c in t["columns"] if c["pk"]] == ["id"], "chave primária")
    ch = [{"op": "update", "schema": "main", "table": "clientes", "key": {"id": 1}, "values": {"nome": "Ana O'Neil"}},
          {"op": "insert", "schema": "main", "table": "clientes", "values": {"id": 9, "nome": "Novo"}},
          {"op": "delete", "schema": "main", "table": "clientes", "key": {"id": 2}}]
    pv = api("db/apply", {"session": s, "changes": ch, "dryRun": True})["sql"]
    ok("'Ana O''Neil'" in pv[0], f"prévia: {pv}")
    ok(api("db/apply", {"session": s, "changes": ch})["affected"] == 3, "apply")
    expect_error("row-mismatch", lambda: api("db/apply", {"session": s, "changes": [
        {"op": "update", "schema": "main", "table": "clientes", "key": {"id": 3}, "values": {"nome": "X"}},
        {"op": "update", "schema": "main", "table": "clientes", "key": {"id": 777}, "values": {"nome": "Y"}}]}))
    ok(rows(q(s, "SELECT nome FROM clientes WHERE id = 3")) == [["Carla"]], "edição desfeita quando outra falhou")
    expect_error("confirm", lambda: q(s, "UPDATE clientes SET saldo = 0"))
    expect_error("confirm", lambda: q(s, "DROP TABLE clientes"))
    ok(q(s, "UPDATE clientes SET saldo = 1 WHERE id = 3")["results"][0]["affected"] == 1, "update com where em dev")
    # produção
    p = api("db/open", {"bank": b["id"], "env": prod})
    ok(p["readOnly"] and not p["unlocked"], "produção não abriu travada")
    p = p["id"]
    expect_error("read-only", lambda: q(p, "UPDATE clientes SET nome = 'X' WHERE id = 1"))
    expect_error("tx-control", lambda: q(p, "SELECT 1; COMMIT; SELECT 2"))
    expect_error("read-only", lambda: api("db/apply", {"session": p, "changes": [ch[0]]}))
    api("db/unlock", {"session": p})
    expect_error("confirm", lambda: q(p, "UPDATE clientes SET nome = 'X' WHERE id = 1"))
    r = q(p, "UPDATE clientes SET nome = 'X' WHERE id = 1", confirm=True)
    ok(r.get("pendingTx"), "produção sem transação pendente")
    api("db/tx", {"session": p, "txId": r["pendingTx"]["id"], "commit": False})
    ok(rows(q(p, "SELECT nome FROM clientes WHERE id = 1")) == [["Ana O'Neil"]], "Desfazer não desfez")
    r = q(p, "UPDATE clientes SET nome = 'Ana' WHERE id = 1", confirm=True)
    api("db/tx", {"session": p, "txId": r["pendingTx"]["id"], "commit": True})
    ok(rows(q(p, "SELECT nome FROM clientes WHERE id = 1")) == [["Ana"]], "Confirmar não gravou")
    expect_error("confirm", lambda: api("db/apply", {"session": p, "changes": [ch[0]]}))
    h = api("db/history")["items"]
    ok(h and all(x["env"] == dev for x in h), "histórico: produção não deveria entrar por padrão")
    api("db/close", {"session": s})
    api("db/close", {"session": p})
    api("db/bank/delete", {"id": b["id"]})


@test
def cancelar_e_tempo_limite():
    b = bank("Lenta", "sqlite", [{"kind": "dev", "file": new_sqlite("lenta.db")}])
    s = api("db/open", {"bank": b["id"], "env": b["envs"][0]["id"]})["id"]
    slow = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT count(*) FROM c"
    res = {}

    def run():
        try:
            q(s, slow, queryId="lenta-1")
        except ApiError as e:
            res["code"] = e.code
    th = threading.Thread(target=run)
    th.start()
    time.sleep(1.5)
    api("db/cancel", {"session": s, "queryId": "lenta-1"})
    th.join(30)
    ok(res.get("code") == "canceled", f"cancelar: {res}")
    api("db/prefs", {"timeoutSec": 1})
    try:
        expect_error("timeout", lambda: q(s, slow))
    finally:
        api("db/prefs", {"timeoutSec": 0})
    ok(rows(q(s, "SELECT 1")) == [[1]], "a conexão ficou ruim depois do cancelamento")
    api("db/bank/delete", {"id": b["id"]})


@test
def vinculos_e_consultas_salvas():
    rid = repo()
    b1 = bank("Cifal · Atual", "sqlite", [{"kind": "dev", "file": new_sqlite("a.db")}, {"kind": "prod", "file": new_sqlite("a2.db")}], folder="Cifal")
    b2 = bank("Cifal · Legado", "sqlite", [{"kind": "dev", "file": new_sqlite("b.db")}], folder="Cifal")
    api("db/links", {"bank": b1["id"], "add": [rid, "nao-existe"]})
    api("db/project-banks", {"repoId": rid, "banks": [b1["id"], b2["id"]]})
    pb = api("db/project?repoId=" + rid)["banks"]
    ok(sorted(x["name"] for x in pb) == ["Cifal · Atual", "Cifal · Legado"], "o projeto deveria ter os dois bancos")
    ok(next(x for x in pb if x["id"] == b1["id"])["link"]["env"] == b1["envs"][0]["id"], "ambiente padrão deveria ser o não-prod")
    ok(not any(p["repo"] == "nao-existe" for p in api("db")["banks"][0]["projects"]), "vinculou projeto inexistente")
    api("db/link", {"bank": b1["id"], "repoId": rid, "alias": "ERP"})
    r = api("db/queries/save", {"bank": b1["id"], "name": "Vendas", "sql": "SELECT 1", "scope": "bank"})
    r = api("db/queries/save", {"bank": b1["id"], "repoId": rid, "name": "Do projeto local", "sql": "SELECT 2", "scope": "project"})
    api("db/queries/where", {"repoId": rid, "where": "repo"})
    r = api("db/queries/save", {"bank": b1["id"], "repoId": rid, "name": "../../fora", "sql": "SELECT 3", "scope": "project"})
    folder = os.path.join(next(x["path"] for x in api("repos")["repos"] if x["id"] == rid), ".codeck-db", "queries")
    files = [os.path.join(dp, f) for dp, _, fs in os.walk(folder) for f in fs]
    ok(len(files) == 1 and os.path.realpath(files[0]).startswith(os.path.realpath(folder)), f"arquivo da consulta: {files}")
    lst = api(f"db/queries?bank={b1['id']}&repoId={rid}")["items"]
    ok(sorted((x["scope"], x.get("store")) for x in lst) == [("bank", None), ("project", "local"), ("project", "repo")], f"consultas: {lst}")
    for x in lst:
        api("db/queries/delete", {"bank": b1["id"], "id": x["id"], "repoId": rid})
    ok(not api(f"db/queries?bank={b1['id']}&repoId={rid}")["items"], "consultas não apagaram")
    api("db/queries/where", {"repoId": rid, "where": None})
    api("db/project-banks", {"repoId": rid, "banks": []})
    ok(not api("db/project?repoId=" + rid)["banks"], "desvincular pelo projeto")
    api("db/bank/delete", {"id": b1["id"]})
    api("db/bank/delete", {"id": b2["id"]})


@test
def imagem_png():
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\x6f\x8c\xff")) + chunk(b"IEND", b"")
    pasta = os.path.join(WORK, "imagens")
    api("db/prefs", {"png": {"dest": "file", "dir": pasta}})
    r = api("db/png", {"png": base64.b64encode(png).decode(), "name": "Loja · teste"})
    ok(r["path"] and open(r["path"], "rb").read() == png, "imagem salva diferente")
    try:
        api("db/png", {"png": base64.b64encode(b"nao e png").decode()})
        raise AssertionError("aceitou um arquivo que não é PNG")
    except ApiError as e:
        ok(e.status == 400, "PNG inválido")
    if ARGS.no_clipboard:
        say("     (área de transferência pulada)")
    else:
        api("db/png", {"png": base64.b64encode(png).decode(), "copy": True, "save": False})
    api("db/prefs", {"png": {"dest": "clipboard", "dir": ""}})


@test
def importar_conexoes():
    r = api("db/import")
    ok(isinstance(r["items"], list) and set(r["found"]) == {"dbeaver", "tabularis", "beekeeper"}, "formato da leitura")
    ok(not any("password" in x for x in r["items"]), "a leitura devolveu senha")
    say(f"     encontrou {len(r['items'])} conexões ({', '.join(k for k, v in r['found'].items() if v) or 'nenhuma ferramenta instalada'})")
    key = bytes.fromhex("babb4a9f774ab853c96c2d653dfe544a")
    plain = json.dumps({"x": {"#connection": {"user": "sa", "password": "Ç!@#\"' longa para vários blocos"}}}).encode()
    ok(dbimport.aes128_cbc_decrypt(key, b"\x00" * 16, _aes_encrypt(key, b"\x00" * 16, plain)) == plain, "AES do DBeaver")


def _aes_encrypt(key, iv, data):
    """AES-128-CBC só para o teste (cifra com a S-box do próprio módulo, para conferir a decifração ida e volta)."""
    S, xt = dbimport._SBOX, dbimport._xt
    rk = dbimport._expand(key)
    pad = 16 - len(data) % 16
    data += bytes([pad]) * pad

    def enc(b):
        s = [x ^ k for x, k in zip(b, rk[0])]
        for rnd in range(1, 11):
            s = [S[x] for x in s]
            s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]
            if rnd < 10:
                o = []
                for c in range(4):
                    a = s[c * 4:c * 4 + 4]
                    o += [xt(a[0]) ^ xt(a[1]) ^ a[1] ^ a[2] ^ a[3], a[0] ^ xt(a[1]) ^ xt(a[2]) ^ a[2] ^ a[3],
                          a[0] ^ a[1] ^ xt(a[2]) ^ xt(a[3]) ^ a[3], xt(a[0]) ^ a[0] ^ a[1] ^ a[2] ^ xt(a[3])]
                s = o
            s = [x ^ k for x, k in zip(s, rk[rnd])]
        return bytes(s)
    out, prev = b"", iv
    for i in range(0, len(data), 16):
        prev = enc(bytes(a ^ b for a, b in zip(data[i:i + 16], prev)))
        out += prev
    return out


@test
def instalacao_de_plugin():
    src = os.path.join(PLUGINS, "codeck-db-sqlite" + (".exe" if WIN else ""))
    if not os.path.isfile(src):
        raise Skip("sem o plugin do SQLite")
    import hashlib
    sha = hashlib.sha256(open(src, "rb").read()).hexdigest()
    plat = "windows" if WIN else "macos"
    url = f"https://github.com/ThomSofts/codeck/releases/download/v9.9.9-1/codeck-db-sqlite-{plat}-9.9.9-1" + (".exe" if WIN else "")
    man = lambda h, u=url: {"dbPlugins": {plat: {"version": "9.9.9", "build": 1, "engines": {"sqlite": {"url": u, "sha256": h, "size": os.path.getsize(src)}}}}}
    orig_m, orig_f = update.signed_manifest, update._fetch
    update._fetch = lambda u, part, size, progress=None: shutil.copyfile(src, part)
    dev = os.environ.pop("CODECK_DB_PLUGINS", None)
    try:
        update.signed_manifest = lambda: man("0" * 64)
        try:
            dbplugins.install("sqlite")
            raise AssertionError("instalou com o hash errado")
        except dbplugins.PluginError:
            pass
        update.signed_manifest = lambda: man(sha, "https://evil.example.com/codeck-db-sqlite-x")
        try:
            dbplugins.install("sqlite")
            raise AssertionError("baixou de endereço que não é da ThomSoft")
        except dbplugins.PluginError:
            pass
        update.signed_manifest = lambda: man(sha)
        dbplugins.install("sqlite")
        path, origin = dbplugins.locate("sqlite")
        ok(origin == "installed", f"origem {origin}")
        ok(dbplugins.get("sqlite").call("hello")["protocol"] == 1, "plugin instalado não respondeu")
        dbplugins.stop_all()   # no Windows o .exe em execução fica travado: fecha antes de mexer no arquivo
        update.signed_manifest = lambda: man(sha)
        dbplugins.install("sqlite")   # reinstalar por cima (a atualização) com o plugin acabado de fechar
        ok(dbplugins.get("sqlite").call("hello")["protocol"] == 1, "plugin reinstalado não respondeu")
        dbplugins.stop_all()
        with open(path, "ab") as fh:
            fh.write(b"x")
        ok(dbplugins.locate("sqlite")[0] is None, "binário alterado depois de instalado continuou aceito")
        dbplugins.uninstall("sqlite")
    finally:
        update.signed_manifest, update._fetch = orig_m, orig_f
        if dev:
            os.environ["CODECK_DB_PLUGINS"] = dev


@test
def mcp_dos_agentes():
    rid = repo()
    f = new_sqlite("mcp.db")
    b = bank("Estoque", "sqlite", [{"kind": "dev", "file": f}, {"kind": "prod", "file": f}])
    api("db/links", {"bank": b["id"], "add": [rid]})
    con = sqlite3.connect(f)
    con.execute("UPDATE clientes SET nome = 'Ana Conceição' WHERE id = 3")
    con.commit()
    con.close()
    ok(dbmcp.agent_launch(rid, "claude", "t0") == [], "MCP oferecido sem liberar o banco")
    api("db/link", {"bank": b["id"], "repoId": rid, "flags": {"agents": True}})
    args = dbmcp.agent_launch(rid, "claude", "t1")
    ok(args[0] == "--mcp-config" and os.path.isfile(args[1]), f"argumentos do Claude: {args}")
    argv = agents.agent_argv("claude", "claude", "faça x", settings={"a": 1}, extra=args)
    ok(argv.index("--mcp-config") < argv.index("--") and argv[-1] == "faça x", f"ordem no Claude: {argv}")
    cx = dbmcp.agent_launch(rid, "codex", "t2")
    ok(cx[0] == "-c" and "mcp_servers.codeck-db.command=" in cx[1], f"Codex: {cx}")
    ok(agents.agent_argv("codex", "codex", "x", resume="abc", extra=cx)[1:3] == cx[:2], "Codex: -c antes do subcomando")
    cfg = json.load(open(args[1], encoding="utf-8"))["mcpServers"]["codeck-db"]
    p = subprocess.Popen([cfg["command"], *cfg["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                         env={**os.environ, **cfg["env"]}, creationflags=0x08000000 if WIN else 0)
    n = [0]

    def rpc(method, params=None):
        n[0] += 1
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n[0], "method": method, "params": params or {}}) + "\n")
        p.stdin.flush()
        return json.loads(p.stdout.readline())

    def call(name, args_):
        r = rpc("tools/call", {"name": name, "arguments": args_})["result"]
        return r["isError"], r["content"][0]["text"]

    def answer(allow, remember=False, seen=None):
        def go():
            for _ in range(150):
                items = api("db/agent/pending")["items"]
                if items:
                    if seen is not None:
                        seen.append(items[0])
                    api("db/agent/answer", {"id": items[0]["id"], "allow": allow, "remember": remember})
                    return
                time.sleep(0.1)
        threading.Thread(target=go, daemon=True).start()
    try:
        ok(rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]["serverInfo"]["name"] == "codeck-db", "initialize")
        ok([t["name"] for t in rpc("tools/list")["result"]["tools"]] == ["list_databases", "list_tables", "describe_table", "query"], "ferramentas")
        err, txt = call("list_databases", {})
        ok(not err and json.loads(txt)[0]["database"] == "Estoque", f"list_databases: {txt}")
        err, txt = call("query", {"database": "Estoque", "sql": "SELECT nome FROM clientes ORDER BY id"})
        ok(not err and json.loads(txt)[0]["rows"][0] == ["Ana"], f"leitura: {txt}")
        ok(json.loads(txt)[0]["rows"][2] == ["Ana Conceição"], f"acentos pelo MCP: {txt}")
        seen = []
        answer(True, seen=seen)
        err, txt = call("query", {"database": "Estoque", "sql": "UPDATE clientes SET saldo = 99 WHERE id = 1"})
        ok(not err and json.loads(txt)[0]["affected"] == 1, f"escrita aprovada: {txt}")
        ok(seen and seen[0]["why"] == "Alteração de dados" and seen[0]["remember"] == "agentsWrite", f"pedido: {seen}")
        answer(False)
        err, txt = call("query", {"database": "Estoque", "sql": "DELETE FROM clientes"})
        ok(err and "negou" in txt, f"escrita negada: {txt}")
        ok(sqlite3.connect(f).execute("select count(*) from clientes").fetchone()[0] == 3, "a escrita negada apagou")
        err, txt = call("query", {"database": "Estoque", "sql": "SELECT 1; COMMIT"})
        ok(err, "COMMIT escondido numa leitura passou")
        err, txt = call("query", {"database": "Outro", "sql": "SELECT 1"})
        ok(err, "banco não liberado")
        prod = next(e["id"] for e in b["envs"] if e["kind"] == "prod")
        api("db/link", {"bank": b["id"], "repoId": rid, "env": prod})
        seen = []
        answer(True, remember=True, seen=seen)
        err, txt = call("query", {"database": "Estoque", "sql": "SELECT count(*) FROM clientes"})
        ok(not err and seen and seen[0]["why"] == "Leitura em produção", f"leitura em produção: {txt} {seen}")
        err, txt = call("query", {"database": "Estoque", "sql": "SELECT 1"})
        ok(not err and not api("db/agent/pending")["items"], "'não perguntar de novo' não valeu")
        seen = []
        answer(True, remember=True, seen=seen)
        err, txt = call("query", {"database": "Estoque", "sql": "UPDATE clientes SET saldo = 1 WHERE id = 1"})
        ok(seen and seen[0]["remember"] is None, "alteração em produção ofereceu 'não perguntar de novo'")
        answer(True)
        call("query", {"database": "Estoque", "sql": "UPDATE clientes SET saldo = 2 WHERE id = 1"})
        api("db/link", {"bank": b["id"], "repoId": rid, "flags": {"agents": False}})
        err, txt = call("list_databases", {})
        ok(json.loads(txt) == [], "desligar não tirou o banco")
    finally:
        p.stdin.close()
        p.wait(10)
        api("db/bank/delete", {"id": b["id"]})


@test
def flutter_formatos():
    types = flutterdb._hive_types(os.path.join(FIX, "hiveproj"))
    ok(types[1]["fields"] == {0: "nome", 1: "saldo", 2: "status", 3: "criado"} and types[2]["enum"], f"tipos do Hive: {types}")
    con = sqlite3.connect(":memory:")
    flutterdb._hive_to_sql(con, os.path.join(FIX, "clientes.hive"), types)
    r = con.execute("SELECT key, nome, saldo, status FROM clientes ORDER BY key").fetchall()
    ok(("ana", "Ana Souza", 1600.0, "ativo") in r and ("bruno", "Bruno Lima", -20.0, "bloqueado") in r and len(r) == 3, f"Hive: {r}")
    con = sqlite3.connect(":memory:")
    flutterdb._sembast_to_sql(con, os.path.join(FIX, "sembast.db"))
    ok(con.execute("SELECT cliente, total FROM pedidos").fetchall() == [("ana", 99.9)], "sembast (apagado não pode aparecer)")
    con = sqlite3.connect(":memory:")
    flutterdb._prefs_to_sql(con, os.path.join(FIX, "FlutterSharedPreferences.xml"))
    ok(dict(con.execute("SELECT key, value FROM preferences").fetchall())["flutter.usuario"] == "ana", "prefs do Android")
    pl = os.path.join(WORK, "com.x.plist")
    plistlib.dump({"flutter.n": 3, "flutter.u": "ana"}, open(pl, "wb"))
    con = sqlite3.connect(":memory:")
    flutterdb._prefs_to_sql(con, pl)
    ok(dict(con.execute("SELECT key, value FROM preferences").fetchall()) == {"flutter.n": 3, "flutter.u": "ana"}, "prefs do iOS/macOS")


@test
def flutter_deteccao_do_projeto():
    d = os.path.join(WORK, "app_flutter")
    for sub in ("android/app", "ios/Runner.xcodeproj", "lib/dados", "macos/Runner/Configs", "windows/runner"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    open(os.path.join(d, "pubspec.yaml"), "w").write("name: x\ndependencies:\n  flutter:\n    sdk: flutter\n  sqflite: ^2.0.0\n  hive: ^2.2.3\n  isar: ^3.0.0\n")
    open(os.path.join(d, "android/app/build.gradle.kts"), "w").write('android {\n  defaultConfig {\n    applicationId = "br.com.teste.app"\n  }\n}\n')
    open(os.path.join(d, "ios/Runner.xcodeproj/project.pbxproj"), "w").write(
        "PRODUCT_BUNDLE_IDENTIFIER = br.com.teste.app;\nPRODUCT_BUNDLE_IDENTIFIER = br.com.teste.app;\nPRODUCT_BUNDLE_IDENTIFIER = br.com.teste.app.RunnerTests;\n")
    open(os.path.join(d, "macos/Runner/Configs/AppInfo.xcconfig"), "w").write("PRODUCT_BUNDLE_IDENTIFIER = br.com.teste.mac\n")
    open(os.path.join(d, "windows/runner/Runner.rc"), "w").write('VALUE "CompanyName", "br.com.teste"\nVALUE "ProductName", "app"\n')
    open(os.path.join(d, "lib/dados/db.dart"), "w").write("final db = await openDatabase(join(p, 'vendas.db'));\nawait Hive.openBox<Cliente>('Clientes');\n")
    subprocess.run(["git", "init", "-q", d], creationflags=0x08000000 if WIN else 0)
    api("repos/add", {"path": d})
    rid = next(r["id"] for r in api("repos")["repos"] if os.path.normcase(os.path.realpath(r["path"])) == os.path.normcase(os.path.realpath(d)))
    i = api("db/flutter/info?repoId=" + rid)
    ok(i["flutter"] and i["openable"] == ["hive", "sqlite"] and i["unsupported"] == ["isar"], f"tipos: {i}")
    ok(i["ids"]["android"] == "br.com.teste.app" and i["ids"]["ios"] == "br.com.teste.app" and i["ids"]["macos"] == "br.com.teste.mac"
       and i["ids"]["windows"] == {"company": "br.com.teste", "product": "app"}, f"ids: {i['ids']}")
    ok(set(i["names"]) == {"vendas.db", "clientes.hive"}, f"arquivos: {i['names']}")


@test
def ssh_validacao():
    for raw in ({"host": "-oProxyCommand=x"}, {"host": "ok.com", "user": "a;b"}, {"host": "ok.com", "port": 99999}):
        try:
            dbtunnel.clean(raw)
            raise AssertionError(f"aceitou {raw}")
        except ValueError:
            pass
    try:
        say(f"     ssh: {dbtunnel._ssh()}")
    except Exception as e:  # noqa: BLE001
        say(f"     ssh indisponível ({e}) — o túnel não vai funcionar neste computador")


@test
def janelas_de_console_windows():
    """Os plugins abrem pelo gerenciador (como no app) — e, no Windows, sem janela de console."""
    calls = []
    orig = subprocess.Popen

    class Spy(orig):
        def __init__(self, a, *x, **k):
            calls.append((str(a)[:100], k.get("creationflags", 0)))
            super().__init__(a, *x, **k)
    subprocess.Popen = Spy
    try:
        dbplugins.stop_all()
        dbplugins.get("sqlite").call("hello")
        dbplugins.stop_all()
    finally:
        subprocess.Popen = orig
    ok(calls, "o plugin não foi aberto")
    if WIN:
        ok(all(f & 0x08000000 for _, f in calls), f"processo sem esconder a janela: {calls}")


# ---------------------------------------------------------------- bancos reais (--targets)

SQL_ENGINES = {"postgres", "mysql", "sqlserver", "libsql"}


def engine_sql(name, t):
    eng = t["engine"]
    b = bank(f"Teste {name}", eng, [{**t["env"], "kind": "dev"}, {**t["env"], "kind": "prod"}])
    dev, prod = b["envs"][0]["id"], b["envs"][1]["id"]
    try:
        r = api("db/test", {"engine": eng, "bank": b["id"], "envId": dev, "env": {**t["env"]}})
        if t["env"].get("tls", {}).get("mode") == "pin" and not t["env"]["tls"].get("pin"):
            raise AssertionError("esperava pedir para fixar o certificado")
        say(f"     {r['server']}{' · ' + r['tls']['version'] if r.get('tls') else ''}")
    except ApiError as e:
        ok(e.code == "cert-unknown", f"teste de conexão: {e}")
        sha = e.data["data"]["sha256"]
        api("db/pin", {"bank": b["id"], "env": dev, "sha256": sha})
        api("db/pin", {"bank": b["id"], "env": prod, "sha256": sha})
        say(f"     certificado fixado ({e.data['data']['version']})")
    s = api("db/open", {"bank": b["id"], "env": dev})["id"]
    tb = "codeck_teste"
    decl = {"sqlserver": "IF OBJECT_ID('codeck_teste') IS NOT NULL DROP TABLE codeck_teste;\nCREATE TABLE codeck_teste (id int PRIMARY KEY, nome nvarchar(80) NOT NULL, saldo decimal(10,2))",
            "mysql": "DROP TABLE IF EXISTS codeck_teste; CREATE TABLE codeck_teste (id int PRIMARY KEY, nome varchar(80) NOT NULL, saldo decimal(10,2))"}.get(
        eng, "DROP TABLE IF EXISTS codeck_teste; CREATE TABLE codeck_teste (id int PRIMARY KEY, nome varchar(80) NOT NULL, saldo decimal(10,2))")
    q(s, decl, confirm=True)
    q(s, f"INSERT INTO {tb} (id, nome, saldo) VALUES (1, 'Ana', 10.5), (2, 'Bruno', NULL), (3, 'Carla; ç', 3)")
    r = q(s, f"SELECT id, nome FROM {tb} ORDER BY id")
    ok(rows(r) == [[1, "Ana"], [2, "Bruno"], [3, "Carla; ç"]], f"select: {rows(r)}")
    schema = {"sqlserver": "dbo", "postgres": "public", "libsql": "main"}.get(eng) or t["env"].get("database")
    info = api("db/catalog", {"session": s, "what": "table", "schema": schema, "name": tb})
    ok([c["name"] for c in info["columns"] if c["pk"]] == ["id"], f"chave primária: {info['columns']}")
    ok(any(o["name"] == tb for o in api("db/catalog", {"session": s, "what": "objects"})), "catálogo")
    api("db/apply", {"session": s, "changes": [{"op": "update", "schema": schema, "table": tb, "key": {"id": 1}, "values": {"nome": "Ana O'Neil"}},
                                                {"op": "delete", "schema": schema, "table": tb, "key": {"id": 2}}]})
    ok(rows(q(s, f"SELECT nome FROM {tb} ORDER BY id")) == [["Ana O'Neil"], ["Carla; ç"]], "edições")
    p = api("db/open", {"bank": b["id"], "env": prod})["id"]
    expect_error("read-only", lambda: q(p, f"UPDATE {tb} SET nome = 'X' WHERE id = 1"))
    if eng != "libsql":   # o libSQL pela HTTP não segura transação entre pedidos
        api("db/unlock", {"session": p})
        r = q(p, f"UPDATE {tb} SET nome = 'X' WHERE id = 1", confirm=True)
        api("db/tx", {"session": p, "txId": r["pendingTx"]["id"], "commit": False})
        ok(rows(q(p, f"SELECT nome FROM {tb} WHERE id = 1")) == [["Ana O'Neil"]], "Desfazer em produção")
    q(s, f"DROP TABLE {tb}", confirm=True)
    api("db/close", {"session": s})
    api("db/close", {"session": p})
    api("db/bank/delete", {"id": b["id"]})


def engine_doc(name, t):
    eng = t["engine"]
    b = bank(f"Teste {name}", eng, [{**t["env"], "kind": "dev"}, {**t["env"], "kind": "prod"}])
    dev, prod = b["envs"][0]["id"], b["envs"][1]["id"]
    s = api("db/open", {"bank": b["id"], "env": dev})
    say(f"     {s['server']}")
    s = s["id"]
    p = api("db/open", {"bank": b["id"], "env": prod})["id"]
    if eng == "mongodb":
        q(s, "db.codeck_teste.drop()", confirm=True)
        q(s, 'db.codeck_teste.insertMany([{nome: "Ana", saldo: 10.5, tags: ["a"]}, {_id: "fixo", nome: "Bia", saldo: NumberLong(2)}])')
        r = q(s, 'db.codeck_teste.find({}, {nome: 1, saldo: 1}).sort({nome: 1})')
        ok([x[1] for x in rows(r)] == ["Ana", "Bia"], f"find: {rows(r)}")
        api("db/apply", {"session": s, "changes": [{"op": "update", "schema": t["env"].get("database"), "table": "codeck_teste", "key": {"_id": "fixo"}, "values": {"saldo": "7"}}]})
        ok(rows(q(s, 'db.codeck_teste.findOne({_id: "fixo"})'))[0][2] == 7, "edição pela grade (número continua número)")
        expect_error("row-mismatch", lambda: api("db/apply", {"session": s, "changes": [
            {"op": "update", "table": "codeck_teste", "key": {"_id": "fixo"}, "values": {"nome": "Y"}},
            {"op": "delete", "table": "codeck_teste", "key": {"_id": "nao-existe"}}]}))
        ok(rows(q(s, 'db.codeck_teste.findOne({_id: "fixo"})'))[0][1] == "Bia", "edição parcial aplicada")
        expect_error("confirm", lambda: q(s, "db.codeck_teste.deleteMany({})"))
        expect_error("read-only", lambda: q(p, 'db.codeck_teste.deleteOne({_id: "fixo"})'))
        q(s, "db.codeck_teste.drop()", confirm=True)
    elif eng == "redis":
        q(s, 'SET codeck:teste:1 "Ana Souza"\nHSET codeck:teste:h a 1 b 2')
        ok(rows(q(s, "GET codeck:teste:1")) == [["Ana Souza"]], "GET")
        ok(len(rows(q(s, "KEYS codeck:teste:*"))) == 2, "KEYS → SCAN")
        expect_error("row-mismatch", lambda: api("db/apply", {"session": s, "changes": [
            {"op": "update", "table": "codeck:*", "key": {"key": "codeck:teste:1"}, "values": {"value": "X"}},
            {"op": "update", "table": "codeck:*", "key": {"key": "codeck:teste:h"}, "values": {"value": "Y"}}]}))
        ok(rows(q(s, "GET codeck:teste:1")) == [["Ana Souza"]], "edição parcial no Redis")
        expect_error("read-only", lambda: q(p, "DEL codeck:teste:1"))
        expect_error("confirm", lambda: q(s, "FLUSHDB"))
        q(s, "DEL codeck:teste:1 codeck:teste:h")
    elif eng == "firebase":
        fs = t["env"]["host"].startswith("https://")
        if not fs:
            q(s, "collection('codeck_teste').add({nome: 'Ana', saldo: 10.5, tags: ['a'], quando: ISODate('2025-01-02')})")
            q(s, "doc('codeck_teste/fixo').set({nome: 'Bia', saldo: 2})")
            r = q(s, "collection('codeck_teste').where('saldo', '>', 1).orderBy('saldo')")
            ok([x[1] for x in rows(r)] == ["Bia", "Ana"] or sorted(str(v) for x in rows(r) for v in x if v in ("Ana", "Bia")) == ["Ana", "Bia"], f"query: {r['results'][0]}")
            api("db/apply", {"session": s, "changes": [{"op": "update", "table": "codeck_teste", "key": {"__name__": "fixo"}, "values": {"saldo": "7"}}]})
            r = q(s, "doc('codeck_teste/fixo')")
            ok(dict(zip([c["name"] for c in r["results"][0]["columns"]], rows(r)[0]))["saldo"] == 7, "edição no Firestore")
            ok(any(o["name"] == "codeck_teste" for o in api("db/catalog", {"session": s, "what": "objects"})), "coleções")
            expect_error("read-only", lambda: q(p, "doc('codeck_teste/fixo').delete()"))
            q(s, "doc('codeck_teste/fixo').delete()", confirm=True)
        else:
            q(s, "ref('codeck_teste/a').set({nome: 'Ana', saldo: 10})")
            q(s, "ref('codeck_teste/b').set({nome: 'Bia', saldo: 2})")
            r = q(s, "ref('codeck_teste').orderByKey().limitToFirst(10)")
            ok(sorted(x[0] for x in rows(r)) == ["a", "b"], f"RTDB: {rows(r)}")
            api("db/apply", {"session": s, "changes": [{"op": "update", "table": "codeck_teste", "key": {"__key__": "b"}, "values": {"saldo": "5"}}]})
            r = q(s, "ref('codeck_teste/b')")
            ok(["saldo", 5] in rows(r), f"edição no RTDB (número continua número): {rows(r)}")
            expect_error("read-only", lambda: q(p, "ref('codeck_teste').remove()"))
            q(s, "ref('codeck_teste').remove()", confirm=True)
    api("db/close", {"session": s})
    api("db/close", {"session": p})
    api("db/bank/delete", {"id": b["id"]})


def project(path):
    """Registra uma pasta como projeto (o Codeck só registra repositórios git)."""
    if not os.path.isdir(os.path.join(path, ".git")):
        subprocess.run(["git", "init", "-q", path], check=True, creationflags=0x08000000 if WIN else 0)
    api("repos/add", {"path": path})
    return next(r["id"] for r in api("repos")["repos"] if os.path.normcase(os.path.realpath(r["path"])) == os.path.normcase(os.path.realpath(path)))


def engine_android(name, t):
    """Banco do app num Android (emulador): achar, abrir, editar, enviar (fecha/reabre o app), conferir, desfazer."""
    rid = project(t["project"])
    devs = api("db/flutter/devices?repoId=" + rid)["devices"]
    ok(any(d["id"] == t["device"] for d in devs), f"aparelho {t['device']} não apareceu: {devs}")
    fl = api(f"db/flutter/files?repoId={rid}&device={t['device']}")["files"]
    kinds = {f["rel"]: f["kind"] for f in fl}
    say(f"     arquivos: {kinds}")
    db_file = next(f["path"] for f in fl if f["rel"].endswith("codeck_teste.db"))
    s = api("db/flutter/open", {"repoId": rid, "device": t["device"], "path": db_file})
    ok(s["app"]["editable"] and not s["app"]["direct"], f"estado: {s['app']}")
    sid = s["id"]
    ok(rows(q(sid, "SELECT nome FROM clientes ORDER BY id")) == [["Ana"], ["Bruno"]], "dados do app")
    api("db/apply", {"session": sid, "changes": [{"op": "update", "schema": "main", "table": "clientes", "key": {"id": 1}, "values": {"nome": "Ana pelo Codeck"}}]})
    r = api("db/flutter/push", {"session": sid})
    ok(r["app"]["backup"] and not r["app"]["dirty"], f"envio: {r['app']}")
    time.sleep(5)   # o app reabre e lê o banco
    s2 = api("db/flutter/open", {"repoId": rid, "device": t["device"], "path": db_file})["id"]
    ok(rows(q(s2, "SELECT nome FROM clientes WHERE id = 1")) == [["Ana pelo Codeck"]], "o aparelho não ficou com a edição")
    api("db/close", {"session": s2})
    api("db/flutter/undo", {"session": sid})
    time.sleep(5)
    s3 = api("db/flutter/open", {"repoId": rid, "device": t["device"], "path": db_file})["id"]
    ok(rows(q(s3, "SELECT nome FROM clientes WHERE id = 1")) == [["Ana"]], "Desfazer não devolveu o banco anterior")
    api("db/close", {"session": s3})
    api("db/close", {"session": sid})
    hive = next((f["path"] for f in fl if f["kind"] == "hive"), None)
    prefs = next((f["path"] for f in fl if f["kind"] == "prefs"), None)
    if hive:
        h = api("db/flutter/open", {"repoId": rid, "device": t["device"], "path": hive})["id"]
        ok(dict(rows(q(h, "SELECT key, value FROM config")))["tema"] == "escuro", "Hive do app")
        expect_error("read-only-format", lambda: q(h, "DELETE FROM config"))
        api("db/close", {"session": h})
    if prefs:
        pr = api("db/flutter/open", {"repoId": rid, "device": t["device"], "path": prefs})["id"]
        vals = dict(rows(q(pr, "SELECT key, value FROM preferences")))
        ok(vals.get("flutter.usuario") == "ana", f"preferências: {vals}")
        api("db/close", {"session": pr})


def engine_desktop(name, t):
    """Banco do app de desktop (macOS/Windows): direto no arquivo — editar grava nele; o modo ao vivo vê o app gravando."""
    rid = project(t["project"])
    fl = api(f"db/flutter/files?repoId={rid}&device={t['device']}")["files"]
    say(f"     arquivos: {[(f['rel'], f['kind']) for f in fl]}")
    bundle = api("db/flutter/info?repoId=" + rid)["ids"].get("macos") if t["device"] == "macos" else None
    ok(not bundle or all(bundle in f["path"] for f in fl), f"listou arquivo de fora do app: {[f['path'] for f in fl if bundle not in f['path']]}")
    db_file = next(f["path"] for f in fl if f["rel"].endswith("codeck_teste.db"))
    s = api("db/flutter/open", {"repoId": rid, "device": t["device"], "path": db_file})
    ok(s["app"]["direct"] and s["app"]["editable"], f"estado: {s['app']}")
    sid = s["id"]
    q(sid, "UPDATE clientes SET saldo = 42 WHERE id = 2")
    ok(sqlite3.connect(db_file).execute("SELECT saldo FROM clientes WHERE id = 2").fetchone()[0] == 42, "a edição não chegou ao arquivo do app")
    api("db/flutter/sync", {"session": sid})
    con = sqlite3.connect(db_file)
    con.execute("UPDATE clientes SET nome = 'Bruno (pelo app)' WHERE id = 2")
    con.commit()
    con.close()
    time.sleep(0.2)
    ok(api("db/flutter/sync", {"session": sid})["changed"], "o modo ao vivo não viu o app gravando")
    ok(rows(q(sid, "SELECT nome FROM clientes WHERE id = 2")) == [["Bruno (pelo app)"]], "a releitura não trouxe o dado novo")
    q(sid, "UPDATE clientes SET nome = 'Bruno', saldo = 3 WHERE id = 2")
    for f in fl:
        if f["kind"] in ("hive", "prefs"):
            h = api("db/flutter/open", {"repoId": rid, "device": t["device"], "path": f["path"]})
            ok(h["app"]["format"] == f["kind"] and not h["app"]["editable"], f"{f['rel']}: {h['app']}")
            ok(api("db/catalog", {"session": h["id"], "what": "objects"}), f"{f['rel']}: sem tabelas")
            api("db/close", {"session": h["id"]})
    api("db/close", {"session": sid})


def engine_ssh(name, t):
    b = bank("Teste túnel", t["engine"], [{**t["env"], "kind": "dev", "ssh": t["ssh"]}])
    r = api("db/test", {"engine": t["engine"], "bank": b["id"], "envId": b["envs"][0]["id"], "env": {**t["env"], "ssh": t["ssh"]}})
    ok(r.get("ssh"), "o teste não passou pelo túnel")
    s = api("db/open", {"bank": b["id"], "env": b["envs"][0]["id"]})["id"]
    ok(rows(q(s, "SELECT 1"))[0][0] == 1, "consulta pelo túnel")
    api("db/close", {"session": s})
    bad = bank("Túnel recusado", t["engine"], [{**t["env"], "kind": "dev", "ssh": {**t["ssh"], "host": "localhost"}}])
    expect_error("ssh-hostkey", lambda: api("db/open", {"bank": bad["id"], "env": bad["envs"][0]["id"]}))
    api("db/bank/delete", {"id": bad["id"]})
    api("db/bank/delete", {"id": b["id"]})


def target_tests():
    for name, t in TARGETS.items():
        kind = t.get("kind") or ("sql" if t.get("engine") in SQL_ENGINES else "doc")
        fn = {"sql": engine_sql, "doc": engine_doc, "android": engine_android, "desktop": engine_desktop, "ssh": engine_ssh}[kind]

        def run(name=name, t=t, fn=fn):
            fn(name, t)
        run.__name__ = f"banco_{name}"
        TESTS.append(run)


target_tests()


# ---------------------------------------------------------------- execução e limpeza

def main():
    results = []
    say(f"Codeck — testes de bancos de dados · {sys.platform} · Python {sys.version.split()[0]} · plugins em {PLUGINS}")
    for fn in TESTS:
        if ARGS.only and ARGS.only not in fn.__name__:
            continue
        t0 = time.time()
        try:
            fn()
            status, detail = "ok", ""
        except Skip as e:
            status, detail = "pulado", str(e)
        except Exception as e:  # noqa: BLE001
            status = "FALHOU"
            detail = f"{e}\n" + "".join(traceback.format_exc().splitlines(True)[-8:])
        results.append((fn.__name__, status))
        mark = {"ok": "✓", "pulado": "–", "FALHOU": "✗"}[status]
        say(f"  {mark} {fn.__name__.replace('_', ' ')} ({time.time() - t0:.1f}s){' — ' + detail if detail else ''}")
    falhas = [n for n, s in results if s == "FALHOU"]
    say("")
    say(f"RESULTADO: {sum(s == 'ok' for _, s in results)} ok, {sum(s == 'pulado' for _, s in results)} pulados, {len(falhas)} falharam"
        + (f" — {', '.join(falhas)}" if falhas else ""))
    return 1 if falhas else 0


def cleanup():
    try:   # bancos que sobraram (teste que falhou no meio): as senhas saem do cofre
        for b in api("db")["banks"]:
            api("db/bank/delete", {"id": b["id"]})
    except Exception:  # noqa: BLE001
        pass
    try:
        for b in json.load(open(os.path.join(DATA, "databases.json"), encoding="utf-8")).get("banks", []):
            for e in b.get("envs", []):
                if e.get("secret"):
                    sec.delete(e["id"], e["secret"])
    except Exception:  # noqa: BLE001
        pass
    dbplugins.stop_all()
    dbtunnel.close_all()
    BACKEND_PROC.terminate()
    try:
        BACKEND_PROC.wait(10)
    except subprocess.TimeoutExpired:
        BACKEND_PROC.kill()
    backend_log.close()
    for d in (DATA, WORK):
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        cleanup()
        if ARGS.report:
            with open(ARGS.report, "w", encoding="utf-8") as f:
                f.write("\n".join(out_lines) + "\n")
    sys.exit(code)
