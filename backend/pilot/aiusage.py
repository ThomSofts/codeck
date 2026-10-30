"""Consumo das IAs no dia a dia — Claude Code, Codex e Cursor —, lido dos registros que cada CLI grava no disco
(inclusive o uso fora do Codeck): modelo, effort e tokens de cada resposta, somados por dia, conta, modelo, effort e
projeto. A leitura é incremental (só o que foi acrescentado desde a última vez) e a base é do Codeck: as CLIs apagam os
próprios registros (o Claude Code, as conversas com mais de 30 dias), a soma fica — e cresce com o uso.

Fontes:
  · Claude Code: <pasta da conta>/projects/…/*.jsonl — cada resposta traz `message.model`, `message.usage` (entrada,
    saída, escrita e leitura do cache) e `effort`. Uma resposta vem em várias linhas (uma por bloco) com o mesmo id, e
    uma conversa retomada pode copiar respostas para outro arquivo: conta-se cada id uma vez só.
  · Codex: <pasta da conta>/sessions/AAAA/MM/DD/rollout-*.jsonl — `turn_context` (modelo, effort) e `token_count`
    (tokens acumulados da sessão; a diferença entre dois é o passo).
  · Cursor: ~/.cursor/ai-tracking/ai-code-tracking.db — o modelo de cada trecho de código gerado e, por commit, as
    linhas da IA × as suas. O Cursor não guarda consumo de tokens no disco.
Custo: o equivalente em preço de API (US$) dos modelos do Claude, pela tabela oficial da Anthropic — para comparar
modelo e effort mesmo no plano de assinatura. Modelo sem preço conhecido (os do Codex) fica só em tokens.
"""
import glob
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from . import agents, git
from .core import DATA, load_json, save_json

FILE = os.path.join(DATA, "ai-ledger.json")
IDS_FILE = os.path.join(DATA, "ai-ledger-ids.json")
EVERY = 600          # relê a cada 10 min
KEEP_IDS_DAYS = 90   # ids de resposta guardados para não contar de novo uma conversa retomada
HOME = os.path.expanduser("~")

# US$ por milhão de tokens: entrada, saída, leitura do cache. Escrita no cache: 1,25× a entrada (5 min) e 2× (1 h).
# Tabela oficial da Anthropic (o prefixo mais longo primeiro: "opus-5-5" antes de "opus-5").
PRICES = (
    ("claude-fable-5-1", 10, 50, 0.25), ("claude-mythos-5-1", 10, 50, 0.25), ("claude-fable-5", 10, 50, 1.0),
    ("claude-mythos-5", 10, 50, 1.0), ("claude-opus-5-5", 4, 20, 0.20), ("claude-opus-5", 5, 25, 0.5),
    ("claude-opus-4-8", 5, 25, 0.5), ("claude-opus-4-7", 5, 25, 0.5), ("claude-opus-4-6", 5, 25, 0.5),
    ("claude-sonnet-5-5", 2, 10, 0.2), ("claude-sonnet-5", 2, 10, 0.2), ("claude-sonnet-4-6", 3, 15, 0.3),
    ("claude-haiku-5-5", 0.10, 0.50, 0.01), ("claude-haiku-4-5", 1, 5, 0.1),
)
FAST = {"claude-opus-5-5": 2, "claude-opus-5": 2}   # modo rápido: o dobro (só onde a tabela diz)

_lock = threading.Lock()        # uma leitura por vez
_state = {"scanning": False, "at": None, "error": None, "files": 0}
_started = {"on": False}


def price_of(model):
    m = (model or "").lower()
    return next((p for p in PRICES if m.startswith(p[0])), None)


def cost_of(model, inp, out, cread, cw5, cw1h, speed=None):
    p = price_of(model)
    if not p:
        return None
    _, pi, po, pr = p
    c = (inp * pi + out * po + cread * pr + cw5 * pi * 1.25 + cw1h * pi * 2) / 1e6
    if speed == "fast":
        c *= FAST.get(p[0], 1)
    return c


def _day(ts):
    """Dia local de um carimbo ISO (UTC com Z) ou de milissegundos."""
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------- base
def _blank():
    return {"v": 1, "files": {}, "rows": {}, "sessions": {}, "last": {}, "cursor": {"models": {}, "commits": {}}}


def _load():
    d = load_json(FILE, None) or _blank()
    for k, v in _blank().items():
        d.setdefault(k, v)
    return d


_projects_cache = {"at": 0, "list": []}


def _project_of(cwd):
    """Nome do projeto de uma pasta de trabalho: o repositório registrado que a contém (o worktree de uma tarefa vale
    pelo repositório dela), senão o nome da pasta."""
    if not cwd:
        return "—"
    if time.time() - _projects_cache["at"] > 300:
        try:
            reps = [(os.path.normcase(os.path.normpath(r["path"])), r["name"]) for r in git._repos()]
        except Exception:  # noqa: BLE001
            reps = []
        _projects_cache.update(at=time.time(), list=sorted(reps, key=lambda x: -len(x[0])))
    c = os.path.normcase(os.path.normpath(cwd))
    m = re.search(r"^(.*?)[\\/]\.worktrees[\\/]", c)
    if m:
        c = m.group(1)
    for path, name in _projects_cache["list"]:
        if c == path or c.startswith(path + os.sep):
            return name
    return os.path.basename(c.rstrip("\\/")) or "—"


def _sources():
    """(provedor, id da conta, nome, pasta) de cada conta: as configuradas e as encontradas no disco."""
    seen, out = set(), []
    try:
        accs = agents._load()["accounts"]
    except Exception:  # noqa: BLE001
        accs = []
    for a in accs:
        if a.get("provider") in ("claude", "codex") and os.path.isdir(a.get("dir") or ""):
            key = os.path.normcase(os.path.normpath(a["dir"]))
            if key not in seen:
                seen.add(key)
                out.append((a["provider"], a["id"], a.get("name") or a["provider"], a["dir"]))
    try:
        found = agents.detect()
    except Exception:  # noqa: BLE001
        found = []
    for x in found:
        key = os.path.normcase(os.path.normpath(x["dir"]))
        if x["provider"] in ("claude", "codex") and key not in seen:
            seen.add(key)
            out.append((x["provider"], "dir:" + os.path.basename(x["dir"]), x.get("name") or os.path.basename(x["dir"]), x["dir"]))
    return out


def _add(d, prov, acc, day, model, effort, project, sid, ts, inp=0, out=0, cread=0, cw5=0, cw1h=0, reasoning=0, cost=None):
    key = f"{day}|{prov}|{acc}|{model}|{effort or '—'}|{project}"
    r = d["rows"].setdefault(key, {"n": 0, "i": 0, "o": 0, "cr": 0, "cw": 0, "r": 0, "c": 0.0, "ck": False})
    r["n"] += 1
    r["i"] += inp
    r["o"] += out
    r["cr"] += cread
    r["cw"] += cw5 + cw1h
    r["r"] += reasoning
    if cost is not None:
        r["c"] += cost
        r["ck"] = True
    tok = inp + out + cread + cw5 + cw1h
    if sid:
        s = d["sessions"].setdefault(sid, {"p": prov, "a": acc, "pr": project, "d0": day, "d1": day, "n": 0, "t": 0, "c": 0.0, "mf": {}})
        s["d1"] = max(s["d1"], day)
        s["d0"] = min(s["d0"], day)
        s["n"] += 1
        s["t"] += tok
        s["c"] += cost or 0
        mk = f"{model}|{effort or '—'}"
        s["mf"][mk] = s["mf"].get(mk, 0) + tok
    last = d["last"].get(acc)
    if ts and (not last or str(ts) >= last["ts"]):
        d["last"][acc] = {"ts": str(ts), "model": model, "effort": effort or "—", "prov": prov}


def _read_lines(path, st):
    """As linhas completas novas do arquivo (a partir do deslocamento guardado)."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    off = st.get("off", 0)
    if size < off:   # o arquivo encolheu (reescrito): não dá para saber o que já foi contado — fica como estava
        st["off"] = size
        return
    if size == off:
        return
    with open(path, "rb") as f:
        f.seek(off)
        for line in f:
            if not line.endswith(b"\n"):
                break   # a CLI ainda está escrevendo esta linha: fica para a próxima leitura
            off += len(line)
            yield line
    st["off"] = off


def _scan_claude(d, ids, acc, root):
    proj_root = os.path.join(root, "projects")
    if not os.path.isdir(proj_root):
        return 0
    n = 0
    for dp, _dn, fns in os.walk(proj_root):
        for fn in fns:
            if not fn.endswith(".jsonl"):
                continue
            path = os.path.join(dp, fn)
            st = d["files"].setdefault(path, {"off": 0})
            n += 1
            for line in _read_lines(path, st):
                if b'"assistant"' not in line or b'"usage"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get("type") != "assistant":
                    continue
                m = o.get("message") or {}
                model, u = m.get("model"), m.get("usage") or {}
                if not model or model.startswith("<") or not u:
                    continue
                mid = m.get("id") or o.get("uuid")
                if mid:
                    if mid in ids:
                        continue
                    ids[mid] = _day(o.get("timestamp"))
                inp, out = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
                cread, cw = int(u.get("cache_read_input_tokens") or 0), int(u.get("cache_creation_input_tokens") or 0)
                cw1h = int((u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0)
                cw5 = max(0, cw - cw1h)
                effort = o.get("effort") or o.get("perTurnEffort")
                _add(d, "claude", acc, _day(o.get("timestamp")), model, effort, _project_of(o.get("cwd")), o.get("sessionId"),
                     o.get("timestamp"), inp, out, cread, cw5, cw1h, 0, cost_of(model, inp, out, cread, cw5, cw1h, u.get("speed")))
    return n


def _scan_codex(d, ids, acc, root):
    n = 0
    for sub in ("sessions", "archived_sessions"):
        base = os.path.join(root, sub)
        if not os.path.isdir(base):
            continue
        for path in glob.glob(os.path.join(base, "**", "rollout-*.jsonl"), recursive=True):
            st = d["files"].setdefault(path, {"off": 0})
            n += 1
            for line in _read_lines(path, st):
                if b"token_count" not in line and b"turn_context" not in line and b"session_meta" not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                typ, p = o.get("type"), o.get("payload") or {}
                if typ == "session_meta":
                    st["sid"] = p.get("id") or st.get("sid") or os.path.basename(path)
                    st["cwd"] = p.get("cwd") or st.get("cwd")
                elif typ == "turn_context":
                    st["model"] = p.get("model") or st.get("model")
                    st["effort"] = p.get("effort") or p.get("reasoning_effort") or st.get("effort")
                    st["cwd"] = p.get("cwd") or st.get("cwd")
                elif typ == "event_msg" and p.get("type") == "token_count" and p.get("info"):
                    tot = p["info"].get("total_token_usage") or {}
                    prev = st.get("prev") or {}
                    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
                    delta = {k: int(tot.get(k) or 0) - int(prev.get(k) or 0) for k in keys}
                    if any(v < 0 for v in delta.values()):   # recomeçou a contagem: vale o último passo
                        lt = p["info"].get("last_token_usage") or {}
                        delta = {k: int(lt.get(k) or 0) for k in keys}
                    st["prev"] = {k: int(tot.get(k) or 0) for k in keys}
                    if not any(delta.values()):
                        continue
                    cached = min(delta["cached_input_tokens"], delta["input_tokens"])
                    model = st.get("model") or "codex"
                    _add(d, "codex", acc, _day(o.get("timestamp")), model, st.get("effort"), _project_of(st.get("cwd")),
                         st.get("sid") or os.path.basename(path), o.get("timestamp"), delta["input_tokens"] - cached,
                         delta["output_tokens"], cached, 0, 0, delta["reasoning_output_tokens"], None)
    return n


def _scan_cursor(d):
    db = os.path.join(HOME, ".cursor", "ai-tracking", "ai-code-tracking.db")
    if not os.path.isfile(db):
        return
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            models = {}
            for model, day, chunks, convs in con.execute(
                    "SELECT COALESCE(model,'?'), date(createdAt/1000,'unixepoch','localtime'), count(*), count(DISTINCT conversationId) "
                    "FROM ai_code_hashes GROUP BY 1, 2"):
                models[f"{day}|{model}"] = [chunks, convs]
            commits = {}
            for day, ai, human, n in con.execute(
                    "SELECT date(scoredAt/1000,'unixepoch','localtime'), sum(COALESCE(composerLinesAdded,0)+COALESCE(tabLinesAdded,0)), "
                    "sum(COALESCE(humanLinesAdded,0)), count(*) FROM scored_commits GROUP BY 1"):
                commits[day] = [ai or 0, human or 0, n]
        finally:
            con.close()
    except sqlite3.Error as e:
        _state["error"] = f"Cursor: {e}"
        return
    # o banco do Cursor também apaga o que é velho: soma o que já se viu (o máximo de cada dia)
    for k, v in models.items():
        cur = d["cursor"]["models"].get(k) or [0, 0]
        d["cursor"]["models"][k] = [max(cur[0], v[0]), max(cur[1], v[1])]
    for k, v in commits.items():
        cur = d["cursor"]["commits"].get(k) or [0, 0, 0]
        d["cursor"]["commits"][k] = [max(cur[0], v[0]), max(cur[1], v[1]), max(cur[2], v[2])]


def scan():
    """Lê o que é novo em todas as fontes e grava a base. Devolve quantos arquivos olhou."""
    if not _lock.acquire(blocking=False):
        return None
    _state["scanning"] = True
    try:
        d = _load()
        ids = load_json(IDS_FILE, {}) or {}
        n = 0
        for prov, acc, _name, root in _sources():
            try:
                n += _scan_claude(d, ids, acc, root) if prov == "claude" else _scan_codex(d, ids, acc, root)
            except Exception as e:  # noqa: BLE001 — uma conta com problema não para as outras
                _state["error"] = f"{prov} {root}: {e}"[:300]
        _scan_cursor(d)
        cut = (datetime.now() - timedelta(days=KEEP_IDS_DAYS)).strftime("%Y-%m-%d")
        ids = {k: v for k, v in ids.items() if v >= cut}
        d["files"] = {k: v for k, v in d["files"].items() if os.path.exists(k) or v.get("off")}
        save_json(FILE, d)
        save_json(IDS_FILE, ids)
        _state.update(at=time.time(), files=n)
        return n
    finally:
        _state["scanning"] = False
        _lock.release()


def loop():
    time.sleep(20)   # depois da abertura do app
    while True:
        try:
            scan()
        except Exception as e:  # noqa: BLE001
            _state["error"] = str(e)[:300]
        time.sleep(EVERY)


def start():
    if not _started["on"]:
        _started["on"] = True
        threading.Thread(target=loop, daemon=True, name="ai-ledger").start()


# ---------------------------------------------------------------- o que está configurado em cada conta
def _configured(prov, root):
    """Modelo e effort padrão da conta (o que a CLI usa sem pedir outro)."""
    try:
        if prov == "claude":
            s = load_json(os.path.join(root, "settings.json"), {}) or {}
            return {"model": s.get("model"), "effort": s.get("effortLevel")}
        if prov == "codex":
            text = open(os.path.join(root, "config.toml"), encoding="utf-8").read()
            top = text.split("\n[", 1)[0]
            g = lambda k: (re.search(rf'^\s*{k}\s*=\s*"([^"]+)"', top, re.M) or [None, None])[1]
            return {"model": g("model"), "effort": g("model_reasoning_effort")}
    except (OSError, ValueError):
        pass
    return {"model": None, "effort": None}


# ---------------------------------------------------------------- relatório
def _g():
    return {"n": 0, "i": 0, "o": 0, "cr": 0, "cw": 0, "r": 0, "c": 0.0, "ck": False, "sessions": 0}


def _acc(g, r):
    for k in ("n", "i", "o", "cr", "cw", "r"):
        g[k] += r[k]
    g["c"] += r["c"]
    g["ck"] = g["ck"] or r["ck"]


def _fin(g):
    t = g["i"] + g["o"] + g["cr"] + g["cw"]
    ctx = g["i"] + g["cr"] + g["cw"]
    return {**g, "tokens": t, "perCall": round(t / g["n"]) if g["n"] else 0, "outPerCall": round(g["o"] / g["n"]) if g["n"] else 0,
            "cacheHit": round(g["cr"] / ctx * 100, 1) if ctx else None, "cost": round(g["c"], 4) if g["ck"] else None,
            "costPerCall": round(g["c"] / g["n"], 4) if g["ck"] and g["n"] else None,
            "costPerSession": round(g["c"] / g["sessions"], 3) if g["ck"] and g["sessions"] else None}


def report(days=30):
    days = max(1, min(int(days), 3650))
    since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    week = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    d = _load()
    try:
        accs = {a["id"]: a for a in agents._load()["accounts"]}
    except Exception:  # noqa: BLE001
        accs = {}
    names = {acc: (accs.get(acc) or {}).get("name") or name for _p, acc, name, _r in _sources()}
    roots = {acc: (prov, root) for prov, acc, _n, root in _sources()}

    groups = {k: {} for k in ("provider", "model", "effort", "account", "project")}
    by_day = {}
    week_acc = {}
    for key, r in d["rows"].items():
        day, prov, acc, model, effort, project = key.split("|", 5)
        if day >= week:
            _acc(week_acc.setdefault(acc, _g()), r)
            mk = f"{model}|{effort}"
            wm = week_acc[acc].setdefault("models", {})
            wm[mk] = wm.get(mk, 0) + r["i"] + r["o"] + r["cr"] + r["cw"]
        if day < since:
            continue
        for gk, k in (("provider", prov), ("model", f"{prov}|{model}"), ("effort", f"{prov}|{model}|{effort}"),
                      ("account", acc), ("project", project)):
            _acc(groups[gk].setdefault(k, _g()), r)
        _acc(by_day.setdefault(day, {}).setdefault(prov, _g()), r)
    # sessões: cada uma conta para o provedor, a conta, o projeto e cada modelo/effort que usou
    for sid, s in d["sessions"].items():
        if s["d1"] < since:
            continue
        for gk, k in (("provider", s["p"]), ("account", s["a"]), ("project", s["pr"])):
            if k in groups[gk]:
                groups[gk][k]["sessions"] += 1
        for mk in s["mf"]:
            model, effort = mk.split("|", 1)
            for gk, k in (("model", f"{s['p']}|{model}"), ("effort", f"{s['p']}|{model}|{effort}")):
                if k in groups[gk]:
                    groups[gk][k]["sessions"] += 1

    out = {k: {kk: _fin(v) for kk, v in g.items()} for k, g in groups.items()}
    total = _g()
    for v in groups["provider"].values():
        _acc(total, v)
        total["sessions"] += v["sessions"]
    series = []
    for i in range(days):
        day = (datetime.now() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        series.append({"day": day, **{p: _fin(g) for p, g in by_day.get(day, {}).items()}})

    # o que cada conta está usando: o padrão configurado, o último usado e o mais usado na semana
    accounts = {}
    for acc in set(list(roots) + list(d["last"])):
        prov, root = roots.get(acc, (d["last"].get(acc, {}).get("prov"), None))
        w = week_acc.get(acc)
        top = max((w or {}).get("models", {}).items(), key=lambda kv: kv[1], default=(None, 0))[0]
        accounts[acc] = {"name": names.get(acc, acc), "provider": prov, "configured": _configured(prov, root) if root else {},
                         "last": d["last"].get(acc), "week": _fin({k: v for k, v in w.items() if k != "models"}) if w else None,
                         "weekTop": {"model": top.split("|")[0], "effort": top.split("|")[1]} if top else None}

    # linhas alteradas e limite gasto por modelo/effort — só as sessões abertas pelo Codeck sabem disso (a linha de
    # status); a conversa da CLI liga a sessão às respostas (o histórico guarda o id; antes dele, o registro de retomar)
    lines = {}
    try:
        hist = agents._history()
        resume = agents._resume_db()
    except Exception:  # noqa: BLE001
        hist, resume = {}, {}
    for codeck_sid, h in hist.items():
        cli = h.get("cliSession") or (resume.get(codeck_sid) or {}).get("cliSession")
        s = d["sessions"].get(cli) if cli else None
        if not s or s["d1"] < since or not s["mf"]:
            continue
        mk = max(s["mf"].items(), key=lambda kv: kv[1])[0]
        model, effort = mk.split("|", 1)
        g = lines.setdefault(f"{s['p']}|{model}|{effort}", {"sessions": 0, "lines": 0, "tokens": 0, "cost": 0.0, "weekPct": 0.0, "fiveHPct": 0.0})
        ln = h.get("lines") or [0, 0]
        g["sessions"] += 1
        g["lines"] += (ln[0] or 0) + (ln[1] or 0)
        g["tokens"] += s["t"]
        g["cost"] += s["c"]
        for wk, v in (h.get("limitUsed") or {}).items():
            if wk.startswith("semanal|"):
                g["weekPct"] += v
            elif wk.startswith("5 h|"):
                g["fiveHPct"] += v

    cursor_models, cursor_commits = {}, {"ai": 0, "human": 0, "commits": 0}
    for k, (chunks, convs) in d["cursor"]["models"].items():
        day, model = k.split("|", 1)
        if day >= since:
            c = cursor_models.setdefault(model, {"chunks": 0, "conversations": 0})
            c["chunks"] += chunks
            c["conversations"] += convs
    for day, (ai, human, n) in d["cursor"]["commits"].items():
        if day >= since:
            cursor_commits["ai"] += ai
            cursor_commits["human"] += human
            cursor_commits["commits"] += n

    res = {"days": days, "since": since, "total": _fin({**total}), **out, "series": series, "accounts": accounts,
           "lines": lines, "cursor": {"models": cursor_models, "commits": cursor_commits},
           "scan": {"scanning": _state["scanning"], "at": _state["at"], "error": _state["error"], "files": _state["files"],
                    "oldest": min((k.split("|", 1)[0] for k in d["rows"]), default=None)}}
    res["insights"] = insights(res)
    return res


# ---------------------------------------------------------------- leituras prontas (o que fazer com os números)
def _mlabel(model):
    m = re.match(r"claude-(opus|sonnet|haiku|fable|mythos)-(\d+)(?:-(\d+))?", model or "")
    if m:
        return f"{m.group(1).capitalize()} {m.group(2)}{'.' + m.group(3) if m.group(3) and len(m.group(3)) < 3 else ''}"
    return model or "?"


def _pct(a, b):
    return round(a / b * 100) if b else 0


def _usd(n):
    s = f"{n:,.2f}" if n < 100 else f"{round(n):,}"
    return "US$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def _tok(n):
    n = float(n or 0)
    return f"{n / 1e9:.1f} bi".replace(".", ",") if n >= 1e9 else f"{n / 1e6:.1f} M".replace(".", ",") if n >= 1e6 \
        else f"{round(n / 1e3)} mil" if n >= 1e3 else str(round(n))


def insights(r):
    out = []
    tot = r["total"]["tokens"] or 0
    if not tot:
        return out
    eff = sorted(r["effort"].items(), key=lambda kv: -kv[1]["tokens"])
    # 1. quem mais consome
    k, g = eff[0]
    prov, model, effort = k.split("|")
    out.append({"tone": "info", "title": f"{_mlabel(model)} · {effort} é {_pct(g['tokens'], tot)}% dos tokens",
                "text": f"{g['n']:,} respostas em {g['sessions']} sessões".replace(",", ".") +
                        (f", {_usd(g['cost'])} em preço de API" if g.get("cost") else "") + "."})
    # 2. o mesmo modelo em efforts diferentes: quanto cada um gasta por resposta
    by_model = {}
    for k, g in r["effort"].items():
        prov, model, effort = k.split("|")
        if effort != "—" and g["n"] >= 30:
            by_model.setdefault(f"{prov}|{model}", []).append((effort, g))
    order = {"low": 0, "minimal": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4}
    for mk, lst in by_model.items():
        if len(lst) < 2:
            continue
        lst.sort(key=lambda x: order.get(x[0], 9))
        lo, hi = lst[0], lst[-1]
        if lo[1]["outPerCall"] and hi[1]["outPerCall"]:
            ratio = hi[1]["outPerCall"] / lo[1]["outPerCall"]
            if ratio >= 1.3:
                out.append({"tone": "warn", "title": f"{_mlabel(mk.split('|')[1])}: {hi[0]} escreve {ratio:.1f}× mais por resposta que {lo[0]}",
                            "text": f"{hi[1]['outPerCall']:,} × {lo[1]['outPerCall']:,} tokens de saída por resposta. ".replace(",", ".") +
                                    f"Tarefas simples em {lo[0]} poupam o limite; deixe {hi[0]} para o que é difícil."})
    # 3. cache: o projeto que menos reaproveita
    projs = [(k, g) for k, g in r["project"].items() if g["n"] >= 50 and g["cacheHit"] is not None]
    if projs:
        k, g = min(projs, key=lambda kv: kv[1]["cacheHit"])
        if g["cacheHit"] < 70:
            out.append({"tone": "warn", "title": f"{k} reaproveita só {g['cacheHit']:.0f}% do contexto em cache",
                        "text": "Sessões curtas e recomeçadas pagam o contexto inteiro de novo; continuar a mesma sessão (ou /compact) sai mais barato."})
    # 4. Claude × Codex
    pc = r["provider"]
    if "claude" in pc and "codex" in pc and pc["claude"]["sessions"] >= 5 and pc["codex"]["sessions"] >= 5:
        a, b = pc["claude"], pc["codex"]
        ta, tb = a["tokens"] / a["sessions"], b["tokens"] / b["sessions"]
        big, small, rr = ("Codex", "Claude", tb / ta) if tb > ta else ("Claude", "Codex", ta / tb)
        out.append({"tone": "info", "title": f"{big} usa {rr:.1f}× mais tokens por sessão que o {small}",
                    "text": f"Claude: {_tok(ta)} por sessão · Codex: {_tok(tb)} por sessão (com o cache; no período)."})
    # 5. linhas por US$ (só as sessões do Codeck sabem as linhas)
    lines = [(k, g) for k, g in r["lines"].items() if g["sessions"] >= 3 and g["cost"] > 0 and g["lines"] > 0]
    if len(lines) >= 2:
        lines.sort(key=lambda kv: -kv[1]["lines"] / kv[1]["cost"])
        (kb, gb), (kw, gw) = lines[0], lines[-1]
        out.append({"tone": "good", "title": f"Mais linhas por US$: {_mlabel(kb.split('|')[1])} · {kb.split('|')[2]}",
                    "text": f"{gb['lines']/gb['cost']:.0f} linhas por US$ × {gw['lines']/gw['cost']:.0f} em {_mlabel(kw.split('|')[1])} · {kw.split('|')[2]} "
                            f"(sessões abertas pelo Codeck)."})
    # 5b. quanto do limite semanal cada modelo/effort gasta por sessão (o que pesa no plano de assinatura)
    wk = [(k, g) for k, g in r["lines"].items() if g["sessions"] >= 3 and g["weekPct"] > 0]
    if len(wk) >= 2:
        wk.sort(key=lambda kv: kv[1]["weekPct"] / kv[1]["sessions"])
        (kl, gl), (kh, gh) = wk[0], wk[-1]
        pl, ph = gl["weekPct"] / gl["sessions"], gh["weekPct"] / gh["sessions"]
        if ph >= pl * 1.1:
            p1 = lambda x: f"{x:.1f}".replace(".", ",")
            out.append({"tone": "warn", "title": f"{_mlabel(kh.split('|')[1])} · {kh.split('|')[2]} gasta {p1(ph)}% da semana por sessão",
                        "text": f"× {p1(pl)}% em {_mlabel(kl.split('|')[1])} · {kl.split('|')[2]} — média das sessões abertas pelo Codeck."})
    # 6. Cursor: quanto do código commitado veio da IA
    cc = r["cursor"]["commits"]
    if cc["commits"]:
        out.append({"tone": "info", "title": f"Cursor: {_pct(cc['ai'], cc['ai'] + cc['human'])}% das linhas commitadas vieram da IA",
                    "text": f"{cc['commits']} commits no período; modelo mais usado: " +
                            (max(r["cursor"]["models"].items(), key=lambda kv: kv[1]["chunks"])[0] if r["cursor"]["models"] else "—") + "."})
    # 7. conta apertada no limite gastando o modelo mais caro
    for acc, a in r["accounts"].items():
        u = (agents._usage.get(acc) or {}).get("rateLimits") or []
        week_used = next((w.get("used") for w in u if w.get("window") == "semanal"), None)
        top = a.get("weekTop")
        if week_used and week_used >= 75 and top and top["effort"] in ("high", "xhigh", "max"):
            lower = {"max": "xhigh", "xhigh": "high", "high": "medium"}[top["effort"]]
            prov = a.get("provider") or "claude"
            here, there = r["lines"].get(f"{prov}|{top['model']}|{top['effort']}"), r["lines"].get(f"{prov}|{top['model']}|{lower}")
            proof = ""
            if here and there and here["sessions"] >= 3 and there["sessions"] >= 3 and here["weekPct"] and there["weekPct"]:
                p1 = lambda x: f"{x:.1f}".replace(".", ",")
                proof = (f" Nas suas sessões, {lower} gasta {p1(there['weekPct'] / there['sessions'])}% da semana por sessão × "
                         f"{p1(here['weekPct'] / here['sessions'])}% em {top['effort']}.")
            out.append({"tone": "bad", "title": f"{a['name']} está em {week_used:.0f}% da semana, quase tudo em {_mlabel(top['model'])} · {top['effort']}",
                        "text": f"Passar as tarefas simples para {lower} (ou para outro modelo) estica o que sobra até o reset." + proof})
    return out
