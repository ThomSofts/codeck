"""Extensões do VS Code no Codeck: temas de cores, temas de ícones, snippets e configurações de linguagem.

De onde vêm:
  · as que você já tem no VS Code, Cursor, Windsurf ou VSCodium (lidas direto da pasta de extensões deles);
  · os temas que vêm junto com o VS Code instalado (Dark+, Monokai, Solarized…);
  · as instaladas pelo Codeck a partir do Open VSX (o marketplace aberto), em <dados>/extensions.

O Codeck usa o que a extensão DECLARA no package.json ("contributes"). Extensões que precisam rodar código (o
"main" — depuradores, linters, Copilot…) não rodam aqui: a tela mostra isso. Também lê as configurações do VS Code
(tema, ícones, fonte) para "usar a mesma aparência".
"""
import io
import json
import os
import plistlib
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import zipfile

from .core import DATA

EXT_DIR = os.path.join(DATA, "extensions")
OPENVSX = "https://open-vsx.org/api"
MAX_VSIX = 150 * 1024 * 1024


class RawFile:
    """Resposta com bytes de arquivo (ícone, fonte) no lugar de JSON."""
    def __init__(self, data, ctype):
        self.data, self.ctype = data, ctype


def _home(*p):
    return os.path.join(os.path.expanduser("~"), *p)


def sources():
    """Pastas de extensões desta máquina: (rótulo, pasta, embutida?)."""
    out = [("Codeck", EXT_DIR, False)]
    for label, d in (("VS Code", ".vscode"), ("VS Code Insiders", ".vscode-insiders"), ("Cursor", ".cursor"), ("Windsurf", ".windsurf"),
                     ("VSCodium", ".vscode-oss")):
        out.append((label, _home(d, "extensions"), False))
    if sys.platform == "darwin":
        for app in ("Visual Studio Code", "Cursor", "Visual Studio Code - Insiders"):
            out.append((f"{app} (embutida)", f"/Applications/{app}.app/Contents/Resources/app/extensions", True))
    elif os.name == "nt":
        la = os.environ.get("LOCALAPPDATA") or _home("AppData", "Local")
        for d, label in ((r"Programs\Microsoft VS Code", "VS Code"), (r"Programs\cursor", "Cursor")):
            out.append((f"{label} (embutida)", os.path.join(la, d, "resources", "app", "extensions"), True))
            out.append((f"{label} (embutida)", os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Microsoft VS Code", "resources", "app", "extensions"), True))
    else:
        out.append(("VS Code (embutida)", "/usr/share/code/resources/app/extensions", True))
    return out


def _jsonc(text):
    from .workspace import _jsonc as parse
    return parse(text)


def _nls(base, value, cache):
    """Rótulos "%chave%" vêm do package.nls.json."""
    if not isinstance(value, str) or not (value.startswith("%") and value.endswith("%")):
        return value
    if "nls" not in cache:
        cache["nls"] = {}
        for n in ("package.nls.pt-br.json", "package.nls.json"):
            f = os.path.join(base, n)
            if os.path.isfile(f):
                try:
                    cache["nls"] = {**_jsonc(open(f, encoding="utf-8-sig").read()), **cache["nls"]}
                except Exception:  # noqa: BLE001
                    pass
    v = cache["nls"].get(value.strip("%"), value)
    return v.get("message", value) if isinstance(v, dict) else v


def _vkey(v):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-+]", v or "0")[:4])


_cache = {"at": 0, "list": None}


def scan(force=False):
    """Todas as extensões com algo que o Codeck usa (ou que precisariam de código), a versão mais nova de cada."""
    if _cache["list"] is not None and not force and time.time() - _cache["at"] < 60:
        return _cache["list"]
    best = {}
    for label, base, builtin in sources():
        if not os.path.isdir(base):
            continue
        for d in os.listdir(base):
            full = os.path.join(base, d)
            pj = os.path.join(full, "package.json")
            if not os.path.isfile(pj):
                continue
            try:
                j = _jsonc(open(pj, encoding="utf-8-sig").read())
            except Exception:  # noqa: BLE001
                continue
            c = j.get("contributes") or {}
            nls = {}
            ext_id = f"{j.get('publisher') or 'vscode'}.{j.get('name') or d}".lower()
            themes = [{"label": _nls(full, t.get("label") or t.get("id"), nls), "id": t.get("id") or t.get("label"), "uiTheme": t.get("uiTheme") or "vs-dark",
                       "path": t.get("path")} for t in c.get("themes") or [] if t.get("path")]
            icons = [{"label": _nls(full, t.get("label") or t.get("id"), nls), "id": t.get("id"), "path": t.get("path")} for t in c.get("iconThemes") or [] if t.get("path")]
            snippets = [{"language": s.get("language"), "path": s.get("path")} for s in c.get("snippets") or [] if s.get("path") and s.get("language")]
            langs = [{"id": x.get("id"), "extensions": x.get("extensions") or [], "filenames": x.get("filenames") or [], "aliases": x.get("aliases") or [],
                      "configuration": x.get("configuration")} for x in c.get("languages") or [] if x.get("id")]
            if builtin and not (themes or icons):
                continue   # das embutidas, só os temas interessam (o resto o Monaco já tem)
            if not (themes or icons or snippets or langs or j.get("main") or j.get("browser")):
                continue
            item = {
                "id": ext_id, "key": f"{label}:{d}", "dir": full, "source": label, "builtin": builtin, "removable": base == EXT_DIR,
                "name": j.get("name"), "publisher": j.get("publisher") or "vscode", "version": j.get("version") or "",
                "displayName": _nls(full, j.get("displayName"), nls) or j.get("name"), "description": _nls(full, j.get("description"), nls) or "",
                "icon": j.get("icon"), "categories": j.get("categories") or [],
                "themes": themes, "iconThemes": icons, "snippets": snippets, "languages": langs,
                "grammars": len(c.get("grammars") or []), "code": bool(j.get("main") or j.get("browser")),
            }
            prev = best.get(ext_id)
            # mesma extensão em vários lugares: a do Codeck primeiro, depois a versão mais nova
            if not prev or (base == EXT_DIR and not prev["removable"]) or (prev["removable"] == (base == EXT_DIR) and _vkey(item["version"]) > _vkey(prev["version"])):
                best[ext_id] = item
    out = sorted(best.values(), key=lambda x: (x["builtin"], (x["displayName"] or "").lower()))
    _cache.update(at=time.time(), list=out)
    return out


def public_list(force=False):
    return {"extensions": [{k: v for k, v in e.items() if k != "dir"} for e in scan(force)], "vscodeSettings": vscode_settings()}


def _ext(key):
    e = next((x for x in scan() if x["key"] == key or x["id"] == key), None)
    if not e:
        raise LookupError("Extensão não encontrada")
    return e


def _inside(base, rel):
    full = os.path.realpath(os.path.join(base, (rel or "").lstrip("/\\")))
    if full != os.path.realpath(base) and not full.startswith(os.path.realpath(base) + os.sep):
        raise ValueError("Caminho fora da extensão")
    return full


CTYPES = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".woff": "font/woff",
          ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf", ".json": "application/json", ".webp": "image/webp"}


def file(key, rel):
    full = _inside(_ext(key)["dir"], rel)
    if not os.path.isfile(full) or os.path.getsize(full) > 8 * 1024 * 1024:
        raise LookupError("Arquivo não encontrado")
    with open(full, "rb") as f:
        return RawFile(f.read(), CTYPES.get(os.path.splitext(full)[1].lower(), "application/octet-stream"))


def json_file(key, rel):
    full = _inside(_ext(key)["dir"], rel)
    return _jsonc(open(full, encoding="utf-8-sig").read())


def _tm_theme(path):
    """Tema TextMate (.tmTheme, plist) → tokenColors."""
    with open(path, "rb") as f:
        p = plistlib.load(f)
    out = []
    for s in p.get("settings") or []:
        st = s.get("settings") or {}
        out.append({"scope": s.get("scope"), "settings": {k: v for k, v in st.items() if k in ("foreground", "background", "fontStyle")}})
    return out


def theme(key, rel):
    """Tema de cores resolvido: segue os "include" e lê tokenColors em .tmTheme. Devolve colors, tokenColors e o tipo."""
    e = _ext(key)
    base = e["dir"]
    colors, tokens, semantic, name, kind = {}, [], {}, None, None
    seen = set()

    def load(path):
        nonlocal name, kind
        full = _inside(base, path)
        if full in seen or len(seen) > 10:
            return
        seen.add(full)
        if full.lower().endswith(".tmtheme"):
            tokens[:0] = _tm_theme(full)
            return
        j = _jsonc(open(full, encoding="utf-8-sig").read())
        if j.get("include"):
            load(os.path.relpath(os.path.join(os.path.dirname(full), j["include"]), base))
        colors.update(j.get("colors") or {})
        tc = j.get("tokenColors")
        if isinstance(tc, str):
            p = os.path.relpath(os.path.join(os.path.dirname(full), tc), base)
            tokens.extend(_tm_theme(_inside(base, p)) if p.lower().endswith(".tmtheme") else (_jsonc(open(_inside(base, p), encoding="utf-8-sig").read()).get("tokenColors") or []))
        elif isinstance(tc, list):
            tokens.extend(tc)
        semantic.update(j.get("semanticTokenColors") or {})
        name = j.get("name") or name
        kind = j.get("type") or kind

    load(rel)
    t = next((x for x in e["themes"] if x["path"] == rel or x["path"].lstrip("./") == rel.lstrip("./")), None)
    ui = (t or {}).get("uiTheme") or ""
    kind = kind or ("light" if ui == "vs" else "hc" if ui.startswith("hc") else "dark")
    return {"name": name or (t or {}).get("label"), "type": kind, "uiTheme": ui, "colors": colors, "tokenColors": tokens, "semanticTokenColors": semantic}


def snippets(key):
    """Snippets da extensão por linguagem (o corpo no formato do VS Code: $1, ${2:texto}, $0)."""
    e = _ext(key)
    out = []
    for s in e["snippets"]:
        try:
            data = _jsonc(open(_inside(e["dir"], s["path"]), encoding="utf-8-sig").read())
        except Exception:  # noqa: BLE001
            continue
        for name, sn in (data or {}).items():
            if not isinstance(sn, dict) or "body" not in sn:
                continue
            prefixes = sn.get("prefix") or name
            for pf in (prefixes if isinstance(prefixes, list) else [prefixes]):
                out.append({"language": s["language"], "name": name, "prefix": pf, "body": sn["body"] if isinstance(sn["body"], str) else "\n".join(sn["body"]),
                            "description": sn.get("description") or ""})
    return {"snippets": out[:3000]}


def language_configs(key):
    e = _ext(key)
    out = []
    for lang in e["languages"]:
        cfg = None
        if lang.get("configuration"):
            try:
                cfg = _jsonc(open(_inside(e["dir"], lang["configuration"]), encoding="utf-8-sig").read())
            except Exception:  # noqa: BLE001
                cfg = None
        out.append({**{k: lang[k] for k in ("id", "extensions", "filenames", "aliases")}, "configuration": cfg})
    return {"languages": out}


# ---------------------------------------------------------------- configurações do VS Code (para usar a mesma aparência)
VSCODE_KEYS = ("workbench.colorTheme", "workbench.iconTheme", "editor.fontFamily", "editor.fontSize", "editor.fontLigatures", "editor.tabSize",
               "editor.minimap.enabled", "editor.wordWrap", "editor.renderWhitespace", "editor.cursorStyle", "editor.cursorBlinking",
               "editor.stickyScroll.enabled", "editor.bracketPairColorization.enabled", "editor.formatOnSave", "files.autoSave", "terminal.integrated.fontSize",
               "editor.lineNumbers", "editor.detectIndentation")


def _vscode_bases():
    if sys.platform == "darwin":
        bases = [("VS Code", _home("Library", "Application Support", "Code", "User")), ("Cursor", _home("Library", "Application Support", "Cursor", "User"))]
    elif os.name == "nt":
        ad = os.environ.get("APPDATA") or _home("AppData", "Roaming")
        bases = [("VS Code", os.path.join(ad, "Code", "User")), ("Cursor", os.path.join(ad, "Cursor", "User"))]
    else:
        bases = [("VS Code", _home(".config", "Code", "User")), ("Cursor", _home(".config", "Cursor", "User"))]
    return bases


def vscode_settings():
    """Tema, ícones e fonte das configurações do VS Code/Cursor desta máquina (só as chaves de aparência)."""
    keys = VSCODE_KEYS
    out = []
    for label, base in _vscode_bases():
        f = os.path.join(base, "settings.json")
        if not os.path.isfile(f):
            continue
        try:
            j = _jsonc(open(f, encoding="utf-8-sig").read())
        except Exception:  # noqa: BLE001
            continue
        vals = {k: j[k] for k in keys if k in j and isinstance(j[k], (str, int, float, bool))}
        out.append({"app": label, "settings": vals, "mtime": os.path.getmtime(f)})
    return out


def write_vscode_settings(app, values):
    """Leva os ajustes do editor do Codeck para o settings.json do VS Code/Cursor: só as chaves de aparência/editor,
    as outras ficam como estão. Comentários do arquivo não sobrevivem (o JSON é regravado) — a tela avisa."""
    base = dict(_vscode_bases()).get(app)
    if not base:
        raise ValueError("Editor desconhecido")
    f = os.path.join(base, "settings.json")
    data, comments = {}, False
    if os.path.isfile(f):
        text = open(f, encoding="utf-8-sig").read()
        comments = bool(re.search(r"(^|[^:\"])//|/\*", text))
        try:
            data = _jsonc(text)
        except Exception:  # noqa: BLE001
            raise ValueError("O settings.json do " + app + " está inválido — corrija no editor antes") from None
    changed = {}
    for k, v in (values or {}).items():
        if k in VSCODE_KEYS and isinstance(v, (str, int, float, bool)) and data.get(k) != v:
            data[k] = changed[k] = v
    if changed:
        os.makedirs(base, exist_ok=True)
        if os.path.isfile(f) and comments:
            shutil.copy2(f, f + ".codeck.bak")   # tinha comentários: guarda o original ao lado
        tmp = f + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=4)
            fh.write("\n")
        os.replace(tmp, f)
    return {"changed": sorted(changed), "backup": bool(changed and comments)}


# ---------------------------------------------------------------- Open VSX: buscar, instalar, remover
def _get_json(url, timeout=20):
    r = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Codeck"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read())


def search(q, category=None, size=30):
    qs = {"query": q or "", "size": min(int(size or 30), 60), "sortBy": "relevance" if q else "downloadCount", "sortOrder": "desc"}
    if category:
        qs["category"] = category
    data = _get_json(f"{OPENVSX}/-/search?" + urllib.parse.urlencode(qs))
    have = {e["id"]: e for e in scan()}
    out = []
    for x in data.get("extensions") or []:
        eid = f"{x.get('namespace')}.{x.get('name')}".lower()
        out.append({"id": eid, "namespace": x.get("namespace"), "name": x.get("name"), "displayName": x.get("displayName") or x.get("name"),
                    "description": x.get("description") or "", "version": x.get("version"), "downloads": x.get("downloadCount") or 0,
                    "rating": x.get("averageRating"), "icon": (x.get("files") or {}).get("icon"), "verified": bool(x.get("verified")),
                    "installed": eid in have, "installedFrom": have[eid]["source"] if eid in have else None})
    return {"results": out, "total": data.get("totalSize", len(out))}


def install(namespace, name, version=None):
    if not re.fullmatch(r"[\w\-.]{1,80}", namespace or "") or not re.fullmatch(r"[\w\-.]{1,80}", name or ""):
        raise ValueError("Extensão inválida")
    meta = _get_json(f"{OPENVSX}/{namespace}/{name}" + (f"/{urllib.parse.quote(version)}" if version else ""))
    url = (meta.get("files") or {}).get("download")
    if not url or not url.startswith("https://"):
        raise ValueError("O Open VSX não tem o pacote desta extensão")
    req = urllib.request.Request(url, headers={"User-Agent": "Codeck"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read(MAX_VSIX + 1)
    if len(data) > MAX_VSIX:
        raise ValueError("Pacote grande demais")
    ver = meta.get("version") or "0"
    dest = os.path.join(EXT_DIR, f"{namespace}.{name}-{ver}".lower())
    tmp = dest + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            n = info.filename.replace("\\", "/")
            if not n.startswith("extension/") or n.endswith("/"):
                continue
            rel = n[len("extension/"):]
            if not rel or rel.startswith("/") or ".." in rel.split("/") or ":" in rel:
                continue   # nada fora da pasta da extensão
            target = os.path.join(tmp, *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    if not os.path.isfile(os.path.join(tmp, "package.json")):
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError("Pacote sem package.json")
    # versões antigas da mesma extensão saem
    for d in os.listdir(EXT_DIR) if os.path.isdir(EXT_DIR) else []:
        if d.startswith(f"{namespace}.{name}-".lower()) and not d.endswith(".tmp"):
            shutil.rmtree(os.path.join(EXT_DIR, d), ignore_errors=True)
    os.replace(tmp, dest)
    _cache["list"] = None
    e = next((x for x in scan(True) if x["id"] == f"{namespace}.{name}".lower()), None)
    return {"extension": {k: v for k, v in (e or {}).items() if k != "dir"}}


def uninstall(key):
    e = _ext(key)
    if not e["removable"]:
        raise ValueError(f"Esta extensão é do {e['source']} — desinstale por lá")
    shutil.rmtree(e["dir"], ignore_errors=True)
    _cache["list"] = None
    return {"ok": True}
