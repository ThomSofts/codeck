"""Skills e MCPs das IAs: o que existe no projeto e em cada conta, de quem é cada um e levar de um lado para o outro.

Onde cada coisa mora:
  · Claude — skills em <conta>/skills/<nome>/SKILL.md e <projeto>/.claude/skills; MCPs em .claude.json da conta
    (mcpServers = da conta toda; projects[<pasta>].mcpServers = da conta só neste projeto) e <projeto>/.mcp.json
    (do projeto, vai para o Git). A conta padrão guarda o .claude.json em ~ e não dentro de ~/.claude.
  · Codex — skills em CODEX_HOME/skills e <projeto>/.agents/skills; MCPs em [mcp_servers.<nome>] do config.toml.
  · Cursor — MCPs em ~/.cursor/mcp.json e <projeto>/.cursor/mcp.json.  · Gemini — mcpServers do settings.json.

Cada lugar vira um "local" (p:<provedor> = projeto, a:<conta> = conta, l:<conta> = conta só neste projeto) e cada
skill/MCP uma lista de onde aparece, com um hash do conteúdo para dizer "igual" ou "diferente" entre os lados.
Segredos (env/headers/tokens) nunca saem daqui: a tela recebe só os nomes, com o valor mascarado.
Remover não apaga: a skill vai para DATA/ai-trash e o MCP removido fica salvo em JSON ao lado.
"""
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import time

from . import agents, git
from .core import DATA, load_json, now_iso, save_json

HOME = os.path.expanduser("~")
TRASH = os.path.join(DATA, "ai-trash")
SKILL_CAP = {"claude", "codex"}
MCP_CAP = {"claude", "codex", "cursor", "gemini"}
SECRET_KEY = re.compile(r"(token|secret|passw|pwd|api[-_]?key|apikey|auth|bearer|credential|private|session|cookie|access[-_]?key|client[-_]?id)", re.I)
SECRET_VAL = re.compile(r"^(sk-|ghp_|gho_|github_pat_|xox[abp]-|AIza|ya29\.|eyJ|glpat-|npm_|pat_|AKIA)|^[A-Za-z0-9_\-+/=]{32,}$")


# ---------------------------------------------------------------- TOML mínimo (o Python do macOS é 3.9, sem tomllib)
def _toml_value(s):
    s = s.strip()
    if not s:
        return ""
    if s[0] in "\"'":
        q = s[0]
        if s.startswith(q * 3):
            return s[3:s.rfind(q * 3)]
        out, i = [], 1
        while i < len(s) and s[i] != q:
            if q == '"' and s[i] == "\\" and i + 1 < len(s):
                out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(s[i + 1], s[i + 1]))
                i += 2
                continue
            out.append(s[i])
            i += 1
        return "".join(out)
    if s[0] == "[":
        return [_toml_value(x) for x in _split_top(s[1:s.rfind("]")]) if x.strip()]
    if s[0] == "{":
        d = {}
        for part in _split_top(s[1:s.rfind("}")]):
            if "=" in part:
                k, v = part.split("=", 1)
                d[k.strip().strip("\"'")] = _toml_value(v)
        return d
    if s in ("true", "false"):
        return s == "true"
    try:
        return int(s) if re.fullmatch(r"[-+]?\d+", s) else float(s)
    except ValueError:
        return s


def _split_top(s):
    """Separa por vírgula fora de aspas/colchetes/chaves."""
    out, buf, depth, q = [], [], 0, None
    for ch in s:
        if q:
            buf.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "\"'":
            q = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if "".join(buf).strip():
        out.append("".join(buf))
    return out


def _header_path(h):
    """'mcp_servers."a b".env' → ['mcp_servers', 'a b', 'env']."""
    return [m.group(1) if m.group(1) is not None else m.group(2) for m in re.finditer(r'"([^"]*)"|([^.\s"]+)', h)]


def _codex_mcps(path):
    """{nome: {command, args, env, url, http_headers…, _span: (início, fim)}} lendo só as seções [mcp_servers.*]."""
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return {}
    out, cur, sub = {}, None, None
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        m = re.match(r"^\[([^\[\]]+)\]\s*(#.*)?$", line)
        if m:
            p = _header_path(m.group(1))
            if len(p) >= 2 and p[0] == "mcp_servers":
                cur, sub = p[1], (p[2] if len(p) > 2 else None)
                e = out.setdefault(cur, {"_span": [i, i]})
                e["_span"][1] = i
            else:
                cur = sub = None
            i += 1
            continue
        if cur and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            # valor que continua nas linhas seguintes (array/tabela/string longa)
            while (v.count("[") > v.count("]") or v.count("{") > v.count("}") or v.count('"""') == 1) and i + 1 < len(lines):
                i += 1
                v += "\n" + lines[i]
            key = k.strip().strip("\"'")
            val = _toml_value(re.sub(r"\s+#[^\"']*$", "", v.strip()) if not v.strip().startswith(("\"", "'")) else v.strip())
            tgt = out[cur] if not sub else out[cur].setdefault(sub, {})
            if isinstance(tgt, dict):
                tgt[key] = val
        if cur:
            out[cur]["_span"][1] = i
        i += 1
    return out


def _toml_str(s):
    return json.dumps(str(s), ensure_ascii=False)


def _toml_key(k):
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else _toml_str(k)


def _toml_inline(d):
    return "{ " + ", ".join(f"{_toml_key(k)} = {_toml_str(v)}" for k, v in d.items()) + " }"


# ---------------------------------------------------------------- MCP: um formato só por dentro
def _norm(spec, fam):
    """O MCP de qualquer CLI vira {transport, command, args, env, cwd, url, headers}."""
    spec = spec or {}
    if fam == "codex":
        url = spec.get("url")
        hdr = dict(spec.get("http_headers") or {})
        if spec.get("bearer_token_env_var"):
            hdr["Authorization"] = "Bearer ${" + spec["bearer_token_env_var"] + "}"
        return {"transport": "http" if url else "stdio", "command": spec.get("command"), "args": list(spec.get("args") or []),
                "env": dict(spec.get("env") or {}), "cwd": spec.get("cwd"), "url": url, "headers": hdr,
                "disabled": spec.get("enabled") is False}
    if fam == "gemini":
        url = spec.get("httpUrl") or spec.get("url")
        return {"transport": "http" if spec.get("httpUrl") else ("sse" if url else "stdio"), "command": spec.get("command"),
                "args": list(spec.get("args") or []), "env": dict(spec.get("env") or {}), "cwd": spec.get("cwd"), "url": url,
                "headers": dict(spec.get("headers") or {}), "disabled": False}
    t = spec.get("type") or ("http" if spec.get("url") else "stdio")
    return {"transport": "sse" if t == "sse" else ("http" if t in ("http", "streamable-http") else "stdio"), "command": spec.get("command"),
            "args": list(spec.get("args") or []), "env": dict(spec.get("env") or {}), "cwd": spec.get("cwd"), "url": spec.get("url"),
            "headers": dict(spec.get("headers") or {}), "disabled": bool(spec.get("disabled"))}


def _denorm(n, fam):
    """O formato interno de volta para o da CLI de destino."""
    if fam == "codex":
        return n  # escrito à parte, em TOML
    if n["transport"] == "stdio":
        d = {"command": n["command"], "args": n["args"]}
        if n.get("env"):
            d["env"] = n["env"]
        if n.get("cwd"):
            d["cwd"] = n["cwd"]
        if fam == "claude":
            d = {"type": "stdio", **d}
        return d
    if fam == "gemini":
        d = {("httpUrl" if n["transport"] == "http" else "url"): n["url"]}
    elif fam == "cursor":
        d = {"url": n["url"]}
    else:
        d = {"type": n["transport"], "url": n["url"]}
    if n.get("headers"):
        d["headers"] = n["headers"]
    return d


def _mcp_hash(n):
    core = {k: n.get(k) for k in ("transport", "command", "args", "env", "url", "headers")}
    return hashlib.sha1(json.dumps(core, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def _is_secret(key, val):
    v = str(val or "")
    if not v or v.startswith("${") or v.startswith("$"):
        return False
    return bool(SECRET_KEY.search(key or "")) or bool(SECRET_VAL.search(v))


def _mask_arg(prev, a):
    s = str(a)
    if "=" in s and s.startswith("-"):
        k, v = s.split("=", 1)
        return f"{k}=•••" if _is_secret(k, v) else s
    if prev and prev.startswith("-") and _is_secret(prev, s):
        return "•••"
    return "•••" if SECRET_VAL.search(s) and not s.startswith(("/", "@", ".")) and "/" not in s else s


def _home(p):
    return p.replace(HOME, "~", 1) if isinstance(p, str) and p.startswith(HOME) else p


def _public(n):
    """O que a tela pode ver do MCP: comando/URL com segredo mascarado e só os nomes de env/headers."""
    secrets = sorted({k for k, v in (n.get("env") or {}).items() if _is_secret(k, v)}
                     | {k for k, v in (n.get("headers") or {}).items() if _is_secret(k, v)})
    args, prev = [], None
    for a in n.get("args") or []:
        m = _mask_arg(prev, a)
        if m != str(a) and "argumento" not in secrets:
            secrets.append("argumento")
        args.append(_home(m))
        prev = str(a)
    url = n.get("url") or ""
    if url:
        url = re.sub(r"([?&][^=&]*(key|token|secret|auth)[^=&]*=)[^&]+", r"\1•••", url, flags=re.I)
    cmd = " ".join([_home(n.get("command") or "")] + args).strip()
    return {"transport": n["transport"], "command": cmd or None, "url": url or None, "env": sorted((n.get("env") or {}).keys()),
            "headers": sorted((n.get("headers") or {}).keys()), "secrets": secrets, "disabled": bool(n.get("disabled"))}


# ---------------------------------------------------------------- skills
def _frontmatter(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            txt = f.read(20000)
    except OSError:
        return {}, ""
    meta, body = {}, txt
    # arquivo gerado costuma abrir com um comentário <!-- … --> antes do frontmatter
    txt = re.sub(r"^\s*(<!--.*?-->\s*)+", "", txt, flags=re.S)
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", txt, re.S)
    if m:
        body = m.group(2)
        key = None
        for line in m.group(1).splitlines():
            km = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
            if km:
                key = km.group(1)
                v = km.group(2).strip()
                meta[key] = v.strip("\"'") if v not in (">", "|", ">-", "|-") else ""
            elif key and line.startswith((" ", "\t")):
                meta[key] = (meta[key] + " " + line.strip()).strip()
    return meta, body


def _tree_hash(d):
    h = hashlib.sha1()
    for root, dirs, files in os.walk(d, followlinks=True):
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x not in ("node_modules", "__pycache__"))
        for fn in sorted(files):
            if fn.startswith(".") or fn == ".DS_Store":
                continue
            p = os.path.join(root, fn)
            h.update(os.path.relpath(p, d).encode())
            try:
                if os.path.getsize(p) < 2_000_000:
                    with open(p, "rb") as f:
                        h.update(f.read())
            except OSError:
                pass
    return h.hexdigest()[:12]


def _skill(d, readonly=False):
    md = os.path.join(d, "SKILL.md")
    if not os.path.isfile(md):
        return None
    meta, body = _frontmatter(md)
    link = os.path.realpath(d) if os.path.islink(d) else None
    files = sum(len(fs) for _, _, fs in os.walk(d, followlinks=True))
    return {"name": meta.get("name") or os.path.basename(d), "desc": (meta.get("description") or body.strip().split("\n")[0])[:400],
            "version": meta.get("version") or None, "hash": _tree_hash(d), "path": d, "link": _home(link) if link else None,
            "files": files, "readonly": readonly, "invocable": str(meta.get("user-invocable", "")).lower() == "true"}


def _skills_in(base, synced=True):
    out = []
    if not os.path.isdir(base):
        return out
    for n in sorted(os.listdir(base)):
        p = os.path.join(base, n)
        if n.startswith(".") or n == "synced" or not os.path.isdir(p):
            continue
        s = _skill(p)
        if s:
            s["dirname"] = n
            out.append(s)
    if synced:
        # sincronizadas do claude.ai: synced/<bucket>/<skill>/SKILL.md — só leitura (o claude.ai sobrescreve)
        for md in sorted(glob.glob(os.path.join(base, "synced", "[!.]*", "[!.]*", "SKILL.md"))):
            s = _skill(os.path.dirname(md), readonly=True)
            if s:
                s["dirname"] = os.path.basename(os.path.dirname(md))
                s["synced"] = True
                out.append(s)
    return out


# ---------------------------------------------------------------- locais
def _claude_json(a):
    return os.path.join(HOME, ".claude.json") if os.path.normpath(a["dir"]) == os.path.join(HOME, ".claude") else os.path.join(a["dir"], ".claude.json")


def _account_loc(a):
    p = a["provider"]
    loc = {"id": "a:" + a["id"], "kind": "account", "provider": p, "accountId": a["id"], "name": a.get("name"), "color": a.get("color"),
           "group": a.get("group"), "caps": {"skill": p in SKILL_CAP, "mcp": p in MCP_CAP}}
    if p == "claude":
        loc["files"] = {"skill": _home(os.path.join(a["dir"], "skills")), "mcp": _home(_claude_json(a))}
    elif p == "codex":
        loc["files"] = {"skill": _home(os.path.join(a["dir"], "skills")), "mcp": _home(os.path.join(a["dir"], "config.toml"))}
    elif p == "cursor":
        loc["files"] = {"mcp": _home(os.path.join(a["dir"], "mcp.json"))}
    elif p == "gemini":
        loc["files"] = {"mcp": _home(os.path.join(a["dir"], "settings.json"))}
    return loc


def _project_locs(path, provs):
    out = [{"id": "p:claude", "kind": "project", "provider": "claude", "caps": {"skill": True, "mcp": True},
            "files": {"skill": ".claude/skills", "mcp": ".mcp.json"}, "shared": True}]
    extra = {"codex": {"skill": _codex_skill_rel(path), "mcp": ".codex/config.toml"}, "cursor": {"mcp": ".cursor/mcp.json"},
             "gemini": {"mcp": ".gemini/settings.json"}}
    for p, files in extra.items():
        if p in provs or os.path.isdir(os.path.join(path, "." + p)):
            out.append({"id": "p:" + p, "kind": "project", "provider": p, "caps": {"skill": "skill" in files, "mcp": True}, "files": files, "shared": True})
    return out


def _codex_skill_rel(path):
    """Skills do Codex no repositório: .agents/skills (o padrão atual); .codex/skills só se for a que já existe."""
    return ".codex/skills" if os.path.isdir(os.path.join(path, ".codex", "skills")) and not os.path.isdir(os.path.join(path, ".agents", "skills")) else ".agents/skills"


def _accounts():
    return [a for a in agents.accounts()["accounts"] if a["provider"] in MCP_CAP and os.path.isdir(a["dir"])]


def _read_mcps(loc, a=None, path=None):
    """{nome: spec normalizado} do local."""
    p, k = loc["provider"], loc["kind"]
    raw = {}
    if p == "claude":
        if k == "project":
            raw = (load_json(os.path.join(path, ".mcp.json"), {}) or {}).get("mcpServers") or {}
        else:
            cj = load_json(_claude_json(a), {}) or {}
            raw = cj.get("mcpServers") or {} if k == "account" else ((cj.get("projects") or {}).get(path) or {}).get("mcpServers") or {}
    elif p == "codex":
        f = os.path.join(path, ".codex", "config.toml") if k == "project" else os.path.join(a["dir"], "config.toml")
        raw = {n: {kk: vv for kk, vv in v.items() if kk != "_span"} for n, v in _codex_mcps(f).items()}
    elif p == "cursor":
        f = os.path.join(path, ".cursor", "mcp.json") if k == "project" else os.path.join(a["dir"], "mcp.json")
        raw = (load_json(f, {}) or {}).get("mcpServers") or {}
    elif p == "gemini":
        f = os.path.join(path, ".gemini", "settings.json") if k == "project" else os.path.join(a["dir"], "settings.json")
        raw = (load_json(f, {}) or {}).get("mcpServers") or {}
    return {n: _norm(v, p) for n, v in raw.items() if isinstance(v, dict)}


def _skill_base(loc, a=None, path=None):
    if not loc["caps"].get("skill"):
        return None
    if loc["kind"] == "project":
        return os.path.join(path, _codex_skill_rel(path) if loc["provider"] == "codex" else ".claude/skills")
    return os.path.join(a["dir"], "skills") if loc["kind"] == "account" else None


def _ctx(repo_id):
    path = git.get_repo(repo_id)["path"] if repo_id else None
    accs = _accounts()
    locs = []
    if path:
        locs += _project_locs(path, {a["provider"] for a in accs})
    for a in accs:
        locs.append(_account_loc(a))
        if path and a["provider"] == "claude":
            # MCP "local" do Claude: da conta, mas só vale neste projeto (não vai para o Git)
            locs.append({**_account_loc(a), "id": "l:" + a["id"], "kind": "local", "caps": {"skill": False, "mcp": True}})
    byid = {a["id"]: a for a in accs}
    return path, locs, byid


def inventory(repo_id=None):
    """Tudo que existe, agrupado por skill/MCP, com cada lugar onde aparece."""
    path, locs, byid = _ctx(repo_id)
    items = {}

    def add(kind, name, loc, entry):
        it = items.setdefault(kind + ":" + name, {"key": kind + ":" + name, "type": kind, "name": name, "entries": []})
        it["entries"].append({"loc": loc["id"], **entry})

    for loc in locs:
        a = byid.get(loc.get("accountId"))
        base = _skill_base(loc, a, path)
        if base:
            for s in _skills_in(base, synced=loc["kind"] == "account"):
                add("skill", s["dirname"], loc, {k: (_home(v) if k == "path" else v) for k, v in s.items() if k != "dirname"})
        if loc["caps"].get("mcp"):
            try:
                for n, spec in _read_mcps(loc, a, path).items():
                    add("mcp", n, loc, {"hash": _mcp_hash(spec), **_public(spec)})
            except Exception as e:  # noqa: BLE001 — um arquivo quebrado não derruba a tela
                loc["error"] = str(e)[:200]
    for it in items.values():
        e0 = it["entries"][0]
        it["desc"] = next((e.get("desc") for e in it["entries"] if e.get("desc")), None)
        it["same"] = len({e["hash"] for e in it["entries"]}) == 1
        it["readonly"] = all(e.get("readonly") for e in it["entries"])
        it["transport"] = e0.get("transport")
    proj = None
    if repo_id:
        r = git.get_repo(repo_id)
        proj = {"id": repo_id, "name": r.get("name") or os.path.basename(path), "path": _home(path),
                "tracked": {f: _tracked(path, f) for f in (".mcp.json", ".claude/skills")}}
    return {"project": proj, "locations": locs, "items": sorted(items.values(), key=lambda x: (x["type"], x["name"].lower()))}


def _tracked(path, rel):
    """Se o arquivo está (ou entraria) no Git: True = versionado, False = ignorado, None = não existe ainda."""
    try:
        r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=path, capture_output=True, timeout=5)
        return r.returncode != 0
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- escrever
def _find(repo_id, loc_id):
    path, locs, byid = _ctx(repo_id)
    loc = next((x for x in locs if x["id"] == loc_id), None)
    if not loc:
        raise LookupError("Local não encontrado — a conta ou o projeto mudou")
    return path, loc, byid.get(loc.get("accountId"))


def _backup_name(kind, name):
    os.makedirs(TRASH, exist_ok=True)
    return os.path.join(TRASH, f"{time.strftime('%Y%m%d-%H%M%S')}-{os.urandom(2).hex()}-{kind}-{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}")


def _write_json_key(f, keys, name, value):
    """Grava/remove mcpServers[name] num JSON, relendo o arquivo na hora (a CLI pode ter escrito no meio)."""
    d = load_json(f, {}) if os.path.exists(f) else {}
    if not isinstance(d, dict):
        raise ValueError(f"{_home(f)} não é um objeto JSON")
    cur = d
    for k in keys:
        cur = cur.setdefault(k, {})
    if value is None:
        cur.pop(name, None)
    else:
        cur[name] = value
    os.makedirs(os.path.dirname(f), exist_ok=True)
    tmp = f + ".codeck-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    try:
        os.chmod(tmp, os.stat(f).st_mode & 0o777 if os.path.exists(f) else 0o600)
    except OSError:
        pass
    os.replace(tmp, f)


def _codex_write(f, name, n):
    """Tira a seção antiga (se houver) e anexa a nova no fim do config.toml."""
    _codex_remove(f, name)
    lines = [f"[mcp_servers.{_toml_key(name)}]"]
    if n["transport"] == "stdio":
        lines += [f"command = {_toml_str(n['command'])}", "args = [" + ", ".join(_toml_str(x) for x in n["args"]) + "]"]
        if n.get("cwd"):
            lines.append(f"cwd = {_toml_str(n['cwd'])}")
    else:
        lines.append(f"url = {_toml_str(n['url'])}")
        if n.get("headers"):
            lines.append(f"http_headers = {_toml_inline(n['headers'])}")
    if n.get("env"):
        lines += ["", f"[mcp_servers.{_toml_key(name)}.env]"] + [f"{_toml_key(k)} = {_toml_str(v)}" for k, v in n["env"].items()]
    os.makedirs(os.path.dirname(f), exist_ok=True)
    txt = open(f, encoding="utf-8").read() if os.path.exists(f) else ""
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(txt.rstrip("\n") + ("\n\n" if txt.strip() else "") + "\n".join(lines) + "\n")


def _codex_remove(f, name):
    secs = _codex_mcps(f)
    if name not in secs:
        return
    lines = open(f, encoding="utf-8").read().splitlines()
    # a seção vai do cabeçalho até antes do próximo cabeçalho que não seja dela
    start = secs[name]["_span"][0]
    end = start + 1
    while end < len(lines):
        m = re.match(r"^\s*\[([^\[\]]+)\]", lines[end])
        if m:
            p = _header_path(m.group(1))
            if not (len(p) >= 2 and p[0] == "mcp_servers" and p[1] == name):
                break
        end += 1
    del lines[start:end]   # as linhas em branco do fim da seção vão junto; a de antes fica separando
    with open(f, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip("\n") + "\n")


def _mcp_file(loc, a, path):
    p, k = loc["provider"], loc["kind"]
    if p == "claude":
        if k == "project":
            return os.path.join(path, ".mcp.json"), ["mcpServers"]
        return _claude_json(a), (["mcpServers"] if k == "account" else ["projects", path, "mcpServers"])
    if p == "codex":
        return (os.path.join(path, ".codex", "config.toml") if k == "project" else os.path.join(a["dir"], "config.toml")), None
    if p == "cursor":
        return (os.path.join(path, ".cursor", "mcp.json") if k == "project" else os.path.join(a["dir"], "mcp.json")), ["mcpServers"]
    return (os.path.join(path, ".gemini", "settings.json") if k == "project" else os.path.join(a["dir"], "settings.json")), ["mcpServers"]


def _claude_cli(a, path, kind, name, spec, overwrite):
    """MCP da conta do Claude pela própria CLI (claude mcp add-json/remove): o .claude.json é reescrito o tempo todo
    pelas sessões abertas, e a CLI é quem sabe gravar nele sem perder nada. False = sem CLI ou falhou (grava direto)."""
    exe = agents.which_all().get("claude")
    if not exe:
        return False
    env = {**os.environ}
    if os.path.normpath(a["dir"]) != os.path.join(HOME, ".claude"):
        env["CLAUDE_CONFIG_DIR"] = a["dir"]
    scope = "user" if kind == "account" else "local"
    cwd = path if kind == "local" else HOME

    def cli(*args):
        try:
            return subprocess.run([exe, "mcp", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=40).returncode == 0
        except Exception:  # noqa: BLE001
            return False
    if spec is None or overwrite:
        ok = cli("remove", "-s", scope, name)
        if spec is None:
            return ok
    return cli("add-json", "-s", scope, name, json.dumps(spec, ensure_ascii=False))


def _env_refs(n, name):
    """Troca os valores secretos por ${VAR} — para levar ao .mcp.json sem pôr a chave no Git."""
    n = json.loads(json.dumps(n))
    vars_ = []
    for k, v in list((n.get("env") or {}).items()):
        if _is_secret(k, v):
            n["env"][k] = "${" + k + "}"
            vars_.append(k)
    for k, v in list((n.get("headers") or {}).items()):
        if _is_secret(k, v):
            var = re.sub(r"[^A-Z0-9]+", "_", f"{name}_{k}".upper()).strip("_")
            pre = "Bearer " if str(v).lower().startswith("bearer ") else ""
            n["headers"][k] = pre + "${" + var + "}"
            vars_.append(var)
    return n, vars_


def copy(repo_id, kind, name, src_id, dst_id, overwrite=False, env_refs=False):
    """Leva a skill/MCP de um local para outro. Skill de conta que é link continua link (as duas ficam em sincronia);
    para o projeto vai sempre a cópia dos arquivos (o Git não segue link)."""
    path, src, sa = _find(repo_id, src_id)
    _, dst, da = _find(repo_id, dst_id)
    if src_id == dst_id:
        raise ValueError("Origem e destino são o mesmo lugar")
    if kind == "skill":
        if not dst["caps"].get("skill"):
            raise ValueError("Esse lugar não tem skills")
        sbase, dbase = _skill_base(src, sa, path), _skill_base(dst, da, path)
        s = next((x for x in _skills_in(sbase) if x["dirname"] == name), None) if sbase else None
        if not s:
            raise LookupError("Skill não encontrada na origem")
        target = os.path.join(dbase, name)
        if os.path.lexists(target):
            if not overwrite:
                raise FileExistsError(f"Já existe “{name}” no destino")
            _trash_path(target, "skill", name)
        os.makedirs(dbase, exist_ok=True)
        if s["link"] and dst["kind"] != "project":
            os.symlink(os.path.realpath(s["path"]), target)
            how = "link"
        else:
            shutil.copytree(os.path.realpath(s["path"]), target, symlinks=False,
                            ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__", ".DS_Store"))
            how = "copy"
        return {"ok": True, "how": how, "path": _home(target)}
    if not dst["caps"].get("mcp"):
        raise ValueError("Esse lugar não tem MCPs")
    specs = _read_mcps(src, sa, path)
    if name not in specs:
        raise LookupError("MCP não encontrado na origem")
    n, vars_ = (_env_refs(specs[name], name) if env_refs else (specs[name], []))
    if name in _read_mcps(dst, da, path) and not overwrite:
        raise FileExistsError(f"Já existe “{name}” no destino")
    f, keys = _mcp_file(dst, da, path)
    if os.path.exists(f):
        shutil.copy2(f, _backup_name("file", os.path.basename(f)))
    if dst["provider"] == "codex":
        _codex_write(f, name, n)
    elif dst["provider"] == "claude" and dst["kind"] != "project" and _claude_cli(da, path, dst["kind"], name, _denorm(n, "claude"), overwrite):
        pass
    else:
        _write_json_key(f, keys, name, _denorm(n, dst["provider"]))
    return {"ok": True, "how": "mcp", "path": _home(f), "vars": vars_}


def _trash_path(p, kind, name):
    dst = _backup_name(kind, name)
    if os.path.islink(p):
        with open(dst + ".link", "w") as fh:
            fh.write(os.readlink(p))
        os.unlink(p)
    else:
        shutil.move(p, dst)
    return dst


def remove(repo_id, kind, name, loc_id):
    path, loc, a = _find(repo_id, loc_id)
    if kind == "skill":
        base = _skill_base(loc, a, path)
        # só o que a listagem mostra (nada de "../"); as sincronizadas do claude.ai não saem daqui
        if not base or name not in {x["dirname"] for x in _skills_in(base, synced=False)}:
            raise LookupError("Skill não encontrada")
        target = os.path.join(base, name)
        return {"ok": True, "backup": _home(_trash_path(target, "skill", name))}
    specs = _read_mcps(loc, a, path)
    if name not in specs:
        raise LookupError("MCP não encontrado")
    bk = _backup_name("mcp", name) + ".json"
    save_json(bk, {"at": now_iso(), "loc": loc_id, "provider": loc["provider"], "name": name, "spec": specs[name]}, private=True)
    f, keys = _mcp_file(loc, a, path)
    if loc["provider"] == "codex":
        _codex_remove(f, name)
    elif not (loc["provider"] == "claude" and loc["kind"] != "project" and _claude_cli(a, path, loc["kind"], name, None, True)):
        _write_json_key(f, keys, name, None)
    return {"ok": True, "backup": _home(bk)}


def skill_text(repo_id, loc_id, name):
    """O SKILL.md para ler antes de levar (até 60 KB)."""
    path, loc, a = _find(repo_id, loc_id)
    base = _skill_base(loc, a, path)
    s = next((x for x in _skills_in(base) if x["dirname"] == name), None) if base else None
    if not s:
        raise LookupError("Skill não encontrada")
    with open(os.path.join(s["path"], "SKILL.md"), encoding="utf-8", errors="replace") as fh:
        txt = fh.read(60000)
    files = []
    for root, dirs, fs in os.walk(s["path"], followlinks=True):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        files += [os.path.relpath(os.path.join(root, x), s["path"]) for x in fs if not x.startswith(".")]
    return {"text": txt, "files": sorted(files)[:200]}
