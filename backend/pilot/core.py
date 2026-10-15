"""Núcleo: pastas e arquivos de dados, estado compartilhado, utilidades de tempo/JSON, histórico e notificações.

Quem sobe o backend é o app nativo — macos/Codeck.swift ou windows/Codeck (C#). Ele passa:
  CODECK_TOKEN            chave por execução — sem ela nenhuma rota /api responde
  CODECK_PARENT_PID       o processo encerra junto com o app
  CODECK_NATIVE_NOTIFY=1  notificações saem pelo app (clicáveis)
  CODECK_VERSION / _BUILD / _PLATFORM / _UPDATE_URL  versão instalada e canal de atualização
"""
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCT = "Codeck"   # nome de exibição (a marca mora em ui/src/lib/brand.ts); ids internos não mudam com ela


class OfflineError(RuntimeError):
    """Sem rede (DNS, rota, timeout, conexão recusada). Não é erro da conta: a tela mostra "sem conexão" e mantém o que já leu."""

    def __init__(self, detail=""):
        super().__init__("Sem conexão com a internet")
        self.detail = str(detail)[:200]


def is_network_error(e):
    import socket
    import ssl
    import urllib.error
    if isinstance(e, urllib.error.HTTPError):
        return False
    return isinstance(e, (OfflineError, urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout, socket.gaierror, ssl.SSLEOFError)) \
        or (isinstance(e, OSError) and e.errno in (50, 51, 60, 61, 64, 65, 101, 110, 111, 113, 10051, 10060, 10061, 10065))


def default_data_dir():
    # Um lugar só por usuário: app instalado, debug do editor e terminal enxergam as mesmas contas e regras.
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Codeck")
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Codeck")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "codeck")


LEGACY_NAMES = ("Commitdeck", "PR Pilot")   # nomes anteriores, do mais recente ao mais antigo


def _adopt_legacy_dir(new):
    """O app já se chamou Commitdeck e, antes, PR Pilot: na primeira execução como Codeck, a pasta de dados mais
    recente dos nomes antigos vira a nova (contas, regras, histórico). Os apps nativos já fazem isso antes de subir o
    backend; aqui cobre o dev."""
    lower = os.path.basename(new) == "codeck"
    for name in LEGACY_NAMES:
        old = os.path.join(os.path.dirname(new), name.lower().replace(" ", "-") if lower else name)
        if os.path.exists(new):
            return
        if os.path.isdir(old):
            try:
                os.rename(old, new)
            except OSError:
                pass


if not os.environ.get("CODECK_DATA"):
    _adopt_legacy_dir(default_data_dir())
DATA = os.path.abspath(os.environ.get("CODECK_DATA") or default_data_dir())
os.makedirs(DATA, exist_ok=True)
for _old in (BACKEND_DIR, os.path.join(BACKEND_DIR, "data")):
    # versões antigas guardavam os dados ao lado do código
    for _name in ("config.json", "rules.json", "archive.json", "notified.json", "activity.jsonl"):
        if os.path.exists(os.path.join(_old, _name)) and not os.path.exists(os.path.join(DATA, _name)) and _old != DATA:
            shutil.move(os.path.join(_old, _name), os.path.join(DATA, _name))

CONFIG_FILE = os.path.join(DATA, "config.json")
RULES_FILE = os.path.join(DATA, "rules.json")
ARCHIVE_FILE = os.path.join(DATA, "archive.json")
NOTIFIED_FILE = os.path.join(DATA, "notified.json")
ACTIVITY_FILE = os.path.join(DATA, "activity.jsonl")
REPOS_FILE = os.path.join(DATA, "repos.json")
CATALOGS_FILE = os.path.join(DATA, "catalogs.json")
LIBRARY_FILE = os.path.join(DATA, "library.json")
UPDATES_DIR = os.path.join(DATA, "updates")
STATIC_DIR = os.path.abspath(os.environ.get("CODECK_STATIC") or os.path.join(BACKEND_DIR, "static"))   # CODECK_STATIC: outra build (testes)

DEFAULT_PORT = 47821  # porta incomum de propósito: não briga com APIs/fronts locais
APP_VERSION = os.environ.get("CODECK_VERSION") or "dev"
APP_BUILD = int(os.environ.get("CODECK_BUILD") or 0)
APP_PLATFORM = os.environ.get("CODECK_PLATFORM") or ("macos" if sys.platform == "darwin" else "windows" if os.name == "nt" else "linux")
UPDATE_URL = os.environ.get("CODECK_UPDATE_URL") or ""
TOKEN = os.environ.get("CODECK_TOKEN") or ""
NATIVE_NOTIFY = os.environ.get("CODECK_NATIVE_NOTIFY") == "1"

lock = threading.RLock()
wake = threading.Event()
# Contas carregadas (trocadas inteiras pelo engine.reload_accounts): ctx.orgs = Azure, ctx.gh = GitHub.
ctx = SimpleNamespace(orgs={}, gh={}, config={})
state = {
    "polling": None, "offline": None, "prs": [], "myPrs": [], "builds": [], "buildErrors": {}, "errors": {}, "lastPoll": None, "me": {}, "pollMs": None,
    "deploys": [], "releases": [], "deployErrors": {}, "lastDeployPoll": None, "lastBuildPoll": None,
    "issues": [], "issueErrors": {}, "lastIssuePoll": None, "ghErrors": {},
    # cada fonte lê no próprio ciclo: loading[fonte] = desde quando está lendo (None = parada); updated = última leitura
    "loading": {}, "updated": {},
}
notifications = []    # fila lida pelo app: {"seq", "title", "subtitle", "message", "target"}
_notify = {"seq": 0}


def now():
    return datetime.now(timezone.utc)


def now_iso():
    return now().isoformat(timespec="seconds")


def parse_dt(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, data, private=False):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    if private:
        os.chmod(path, 0o600)


def notify_seq():
    return _notify["seq"]


def notify(title, subtitle, message, target=None):
    """target = "rota/chave" que o app abre quando a notificação é clicada (ex.: "fila/GlorySoft|7604")."""
    if NATIVE_NOTIFY:
        with lock:
            _notify["seq"] += 1
            notifications.append({"seq": _notify["seq"], "title": title, "subtitle": subtitle, "message": message, "target": target})
            del notifications[:-50]
        return
    if sys.platform != "darwin":
        return

    def q(s):
        return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'
    try:
        subprocess.run(["osascript", "-e", f"display notification {q(message)} with title {q(title)} subtitle {q(subtitle)}"],
                       timeout=5, capture_output=True)
    except Exception:  # noqa: BLE001 — notificação nunca derruba o ciclo
        pass


# ---------------------------------------------------------------- cópia dos dados ao trocar de versão
BACKUPS_DIR = os.path.join(DATA, "backups")
BACKUPS_KEEP = 5


def backup_on_upgrade():
    """Primeira execução de uma versão nova: copia os arquivos de dados (contas, quadro, projetos, regras, histórico…)
    para backups/<anterior>-para-<nova>-<data>/ ANTES de qualquer migração. Se uma versão estragar algo, os registros
    voltam dali. Guarda as 5 últimas cópias. Pastas (anexos do quadro, atualizações) não entram: nada migra nelas."""
    if APP_VERSION == "dev":
        return None
    marker = os.path.join(DATA, ".version")
    cur = f"{APP_VERSION}+{APP_BUILD}"
    try:
        with open(marker, encoding="utf-8") as f:
            prev = f.read().strip()
    except FileNotFoundError:
        prev = "anterior"
    if prev == cur:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUPS_DIR, f"{prev}-para-{cur}-{stamp}".replace("+", "_"))
    try:
        os.makedirs(dest, exist_ok=True)
        for name in os.listdir(DATA):
            src = os.path.join(DATA, name)
            if os.path.isfile(src) and not name.endswith(".tmp") and name not in ("codeck.log", ".version"):
                shutil.copy2(src, os.path.join(dest, name))
        old = sorted((os.path.join(BACKUPS_DIR, d) for d in os.listdir(BACKUPS_DIR)), key=os.path.getmtime)
        old = [d for d in old if os.path.isdir(d)]
        for d in old[:-BACKUPS_KEEP]:
            shutil.rmtree(d, ignore_errors=True)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(cur)
        print(f"Dados copiados para {dest} (versão {prev} → {cur})", flush=True)
        return dest
    except OSError as e:   # sem a cópia o app ainda abre; o marcador fica para tentar de novo na próxima
        print(f"Não consegui copiar os dados antes de atualizar: {e}", flush=True)
        return None


# ---------------------------------------------------------------- histórico (activity.jsonl)
def append_activity(entry):
    entry = {"ts": now_iso(), **entry}
    with lock, open(ACTIVITY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[{entry['ts']}] {entry.get('by')} {entry.get('action')} {entry.get('org')} {entry.get('title')}", flush=True)


def pr_summary(pr):
    return {k: pr.get(k) for k in ("key", "provider", "org", "prId", "title", "creatorName", "creatorUnique", "target", "repo", "url", "created")}


def log_activity(by, action, pr, vote=None, detail=None, rule_id=None):
    append_activity({"by": by, "action": action, "vote": vote, "detail": detail, "ruleId": rule_id, **pr_summary(pr)})


def log_deploy(by, action, item, detail=None, rule_id=None):
    append_activity({"by": by, "action": action, "detail": detail, "ruleId": rule_id, "kind": item["kind"],
                     "provider": item.get("provider", "azure"), "org": item["org"], "title": item["title"],
                     "pipeline": item["pipeline"], "stage": item.get("stage"), "branch": item.get("branch"),
                     "version": item.get("version"), "prNumber": item.get("prNumber"), "url": item["url"], "prId": None})


def log_build(by, action, b):
    append_activity({"by": by, "action": f"build-{action}", "kind": "build", "provider": b.get("provider", "azure"),
                     "org": b["org"], "title": f"{b['pipeline']} {b['number']}", "pipeline": b["pipeline"],
                     "branch": b["branch"], "version": b["number"], "prNumber": b.get("prNumber"), "url": b["url"], "prId": None})


def log_git(action, repo, detail=None):
    append_activity({"by": "manual", "action": f"git-{action}", "kind": "git", "provider": "git", "org": repo.get("name"),
                     "title": detail or action, "url": None, "prId": None, "path": repo.get("path")})


def read_activity(limit=None):
    try:
        with open(ACTIVITY_FILE, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []
    if limit:
        lines = lines[-limit:]
    out = []
    for line in reversed(lines):
        if not line.strip():
            continue
        e = json.loads(line)
        e.setdefault("action", "vote")  # entradas antigas só registravam votos
        e.setdefault("provider", "azure")
        if not e.get("key") and e.get("prId"):
            e["key"] = f"{e['org']}|{e['prId']}"
        out.append(e)
    return out


def http_code(e):
    import re
    m = re.match(r"HTTP (\d{3})", str(e))
    return int(m.group(1)) if m else None
