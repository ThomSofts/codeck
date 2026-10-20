"""Executar e depurar como no VS Code / Visual Studio: o que dá para iniciar em cada projeto, no formato do
`.vscode/launch.json` (o mesmo formato vale para depurar, executar sem depurar e levar/trazer do VS Code).

De onde vêm as configurações (nesta ordem na lista):
  - **Codeck**: as que você salvou no app (guardadas na pasta de dados, por projeto — não sujam o repositório);
  - **VS Code**: o `.vscode/launch.json` do projeto, lido ao vivo (com o `tasks.json` para o preLaunchTask);
  - **Detectadas**: o app olha o projeto e monta sozinho — APIs .NET (um item por perfil do launchSettings.json),
    NestJS, Next.js, React/Vite, Node (scripts do package.json), Flutter (um por lib/main*.dart, com flavor), Go,
    Rust, Docker Compose.

Sincronização com o VS Code, por projeto (`sync`):
  - "auto" (padrão): lê o launch.json do projeto; o que você salva no app fica no app;
  - "vscode": o launch.json é a fonte — salvar no app grava lá (o VS Code vê na hora, e vice-versa);
  - "off": ignora o launch.json.
"Exportar para o VS Code" grava as escolhidas no launch.json (e as tarefas de compilação no tasks.json); "Importar"
copia as do launch.json para o app.
"""
import copy
import json
import os
import re
import threading

from .core import DATA, load_json, save_json
from .workspace import _and, _env_file, _join, _jsonc, _q, _root, _settings, _vars, _vscode_tasks, glob_one

LAUNCH_FILE = os.path.join(DATA, "launch.json")
_lock = threading.RLock()
IS_WIN = os.name == "nt"
SYNC_MODES = ("auto", "vscode", "off")
# tipos que o app depura (adaptador de depuração disponível); os outros só executam
DEBUG_TYPES = {"coreclr": "dotnet", "dotnet": "dotnet", "node": "js", "pwa-node": "js", "node-terminal": "js", "chrome": "js",
               "pwa-chrome": "js", "msedge": "js", "pwa-msedge": "js", "dart": "dart", "flutter": "dart"}


# ---------------------------------------------------------------- armazenamento do app (por projeto)
def _db():
    return load_json(LAUNCH_FILE, {})


def _proj(d, repo_id):
    p = d.setdefault(repo_id, {})
    p.setdefault("configurations", [])
    p.setdefault("compounds", [])
    p.setdefault("sync", "auto")
    return p


def project_settings(repo_id):
    with _lock:
        p = _proj(_db(), repo_id)
        return {"sync": p["sync"], "hidden": p.get("hidden") or [], "order": p.get("order") or []}


def save_project_settings(repo_id, body):
    with _lock:
        d = _db()
        p = _proj(d, repo_id)
        if body.get("sync") in SYNC_MODES:
            p["sync"] = body["sync"]
        for k in ("hidden", "order"):
            if isinstance(body.get(k), list):
                p[k] = [str(x)[:300] for x in body[k]][:400]
        save_json(LAUNCH_FILE, d)
        return project_settings(repo_id)


# ---------------------------------------------------------------- .vscode/launch.json e tasks.json
def _vscode_path(root, name):
    return os.path.join(root, ".vscode", name)


def _read_vscode(root, name):
    f = _vscode_path(root, name)
    if not os.path.isfile(f):
        return None, False
    text = open(f, encoding="utf-8-sig").read()
    try:
        data = _jsonc(text)
    except Exception:  # noqa: BLE001 — inválido: não lista (e não sobrescreve sem perguntar)
        return None, True
    has_comments = bool(re.search(r"(^|[^:\"])//|/\*", text))
    return data, has_comments


def _write_vscode(root, name, data):
    d = os.path.join(root, ".vscode")
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, name)
    tmp = f + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=4)
        fh.write("\n")
    os.replace(tmp, f)


# ---------------------------------------------------------------- detecção automática
def _rel(root, p):
    r = os.path.relpath(p, root).replace(os.sep, "/")
    return "." if r in ("", ".") else r


def _wf(rel):
    """Caminho relativo → ${workspaceFolder}/… (o que o VS Code entende)."""
    return "${workspaceFolder}" if rel in (".", "") else "${workspaceFolder}/" + rel


def _detect_dotnet(root):
    from . import dotnet
    out, tasks = [], []
    projs = glob_one(root, "**/*.csproj", limit=80) + glob_one(root, "**/*.fsproj", limit=20) + glob_one(root, "**/*.vbproj", limit=20)
    for full in sorted(projs, key=lambda p: (p.count(os.sep), p)):
        info = dotnet.parse_project(full)
        if info["kind"] not in ("web", "console", "winexe"):
            continue
        rel_proj, rel_dir = _rel(root, full), _rel(root, os.path.dirname(full))
        name = info["name"]
        group = ".NET · " + name
        if info["netfx"] or not info["sdk"]:
            # .NET Framework: executa como o Visual Studio (IIS Express/exe); depurar, só no Visual Studio
            out.append({"name": f"{name}", "type": "codeck-dotnet-fx", "request": "launch", "codeck": {
                "kind": "dotnet", "project": rel_proj, "framework": info["framework"], "web": info["kind"] == "web", "group": group,
                "debug": False, "why": "Projeto .NET Framework: depure pelo Visual Studio (Windows)"}})
            continue
        tfm = (info["framework"] or "").split(";")[0] or "net8.0"
        prog = f"{_wf(rel_dir)}/bin/Debug/{tfm}/{info['assembly']}.dll"
        build = f"build: {name}"
        tasks.append({"label": build, "command": "dotnet", "type": "process",
                      "args": ["build", _wf(rel_proj), "/property:GenerateFullPaths=true", "/consoleloggerparameters:NoSummary;ForceNoAlign"],
                      "problemMatcher": "$msCompile", "group": "build"})
        profiles = _launch_profiles(os.path.dirname(full))
        base = {"type": "coreclr", "request": "launch", "preLaunchTask": build, "program": prog, "args": [], "cwd": _wf(rel_dir),
                "stopAtEntry": False, "console": "internalConsole"}
        if not profiles:
            out.append({**base, "name": name, "codeck": {"kind": "dotnet", "project": rel_proj, "web": info["kind"] == "web", "group": group, "framework": tfm}})
            continue
        for pname, prof in profiles:
            env = {k: str(v) for k, v in (prof.get("environmentVariables") or {}).items()}
            url = (prof.get("applicationUrl") or "").split(";")[0] or None
            if prof.get("applicationUrl"):
                env.setdefault("ASPNETCORE_URLS", prof["applicationUrl"])
            cfg = {**base, "name": f"{name} · {pname}", "env": env,
                   "args": [a for a in re.split(r"\s+", prof.get("commandLineArgs") or "") if a],
                   "launchSettingsProfile": pname,
                   "codeck": {"kind": "dotnet", "project": rel_proj, "profile": pname, "web": info["kind"] == "web", "group": group, "framework": tfm, "url": url}}
            if prof.get("launchBrowser") and info["kind"] == "web":
                lu = (prof.get("launchUrl") or "").strip("/")
                cfg["serverReadyAction"] = {"action": "openExternally", "pattern": r"\bNow listening on:\s+(https?://\S+)",
                                            "uriFormat": "%s/" + lu if lu else "%s"}
            out.append(cfg)
    return out, tasks


def _launch_profiles(proj_dir):
    ls = os.path.join(proj_dir, "Properties", "launchSettings.json")
    if not os.path.isfile(ls):
        return []
    try:
        profs = _jsonc(open(ls, encoding="utf-8-sig").read()).get("profiles") or {}
    except Exception:  # noqa: BLE001
        return []
    return [(n, p or {}) for n, p in profs.items() if (p or {}).get("commandName") in (None, "Project")]


def _pm(d):
    return "pnpm" if os.path.exists(os.path.join(d, "pnpm-lock.yaml")) else "yarn" if os.path.exists(os.path.join(d, "yarn.lock")) else \
        "bun" if os.path.exists(os.path.join(d, "bun.lockb")) or os.path.exists(os.path.join(d, "bun.lock")) else "npm"


def _port_of(script, default):
    m = re.search(r"(?:--port[ =]|-p\s+)(\d{2,5})", script or "")
    return int(m.group(1)) if m else default


def _detect_node(root):
    out = []
    pjs = [os.path.join(root, "package.json")] + sorted(glob_one(root, "*/package.json")) + sorted(glob_one(root, "*/*/package.json", limit=40))
    for pj in pjs:
        if not os.path.isfile(pj) or "node_modules" in pj:
            continue
        try:
            data = json.load(open(pj, encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            continue
        scripts = data.get("scripts") or {}
        if not scripts:
            continue
        d = os.path.dirname(pj)
        rel = _rel(root, d)
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        pm = _pm(d)
        pname = data.get("name") or os.path.basename(d)
        where = "" if rel == "." else f" ({rel})"
        cwd = _wf(rel)
        run = lambda s: f"{pm} run {s}"   # noqa: E731
        if "@nestjs/core" in deps:
            kind, label = "nest", "NestJS"
            main = next((s for s in ("start:dev", "start:debug", "dev", "start") if s in scripts), None)
        elif "next" in deps:
            kind, label = "next", "Next.js"
            main = next((s for s in ("dev", "start") if s in scripts), None)
        elif "vite" in deps or "react-scripts" in deps or "@angular/core" in deps or "@vue/cli-service" in deps:
            kind = "react" if ("react" in deps) else "web"
            label = "React" if kind == "react" else "Angular" if "@angular/core" in deps else "Vue" if "vue" in deps else "Web"
            main = next((s for s in ("dev", "start", "serve") if s in scripts), None)
        elif any(k in deps for k in ("express", "fastify", "koa", "@hapi/hapi")) or data.get("main") or "start" in scripts:
            kind, label = "node", "Node"
            main = next((s for s in ("dev", "start:dev", "start") if s in scripts), None)
        else:
            kind, label, main = "node", "Node", None
        group = f"{label} · {pname}"
        if main:
            cfg = {"name": f"{label}: {main}{where}", "type": "node-terminal", "request": "launch", "command": run(main), "cwd": cwd,
                   "codeck": {"kind": kind, "group": group, "script": main, "main": True}}
            if kind in ("next", "react", "web"):
                port = _port_of(scripts[main], 3000 if kind == "next" or "react-scripts" in deps else 4200 if label == "Angular" else 5173)
                pat = r"(?:Local|ready[^\n]*?on|started server on)[:\s]+(https?://[^\s,]+)" if kind == "next" else r"(?:Local|running at|on)[:\s]+(https?://[^\s,]+)"
                cfg["serverReadyAction"] = {"action": "openExternally", "pattern": pat, "uriFormat": "%s"}
                cfg["codeck"]["url"] = f"http://localhost:{port}"
                # front-end: depurar o código do navegador (breakpoints no .tsx) — o servidor sobe e o Chrome abre depurando
                full = {**copy.deepcopy(cfg), "name": f"{label}: depurar no navegador{where}",
                        "serverReadyAction": {"action": "debugWithChrome", "pattern": pat, "uriFormat": "%s", "webRoot": cwd},
                        "codeck": {"kind": kind, "group": group, "script": main, "browser": True, "url": f"http://localhost:{port}"}}
                out += [cfg, full]
                if kind == "next":
                    out.append({"name": f"Next.js: só o navegador{where}", "type": "chrome", "request": "launch", "url": f"http://localhost:{port}",
                                "webRoot": cwd, "codeck": {"kind": kind, "group": group, "browser": True, "url": f"http://localhost:{port}"}})
            else:
                out.append(cfg)
        for s in scripts:
            if s == main:
                continue
            out.append({"name": f"{s}{where}", "type": "node-terminal", "request": "launch", "command": run(s), "cwd": cwd,
                        "codeck": {"kind": "script", "group": f"Scripts · {pname}", "script": s, "detail": str(scripts[s])[:140]}})
    return out


def _detect_flutter(root):
    out = []
    for ps in [os.path.join(root, "pubspec.yaml")] + sorted(glob_one(root, "*/pubspec.yaml")) + sorted(glob_one(root, "*/*/pubspec.yaml", limit=20)):
        if not os.path.isfile(ps):
            continue
        try:
            text = open(ps, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        d = os.path.dirname(ps)
        rel = _rel(root, d)
        is_flutter = bool(re.search(r"^\s+sdk:\s*flutter\s*$", text, re.M))
        name = (re.search(r"^name:\s*(\S+)", text, re.M) or [None, os.path.basename(d)])[1]
        mains = sorted(glob_one(d, "lib/main*.dart"), key=lambda p: (os.path.basename(p) != "main.dart", p))
        if not mains and os.path.isfile(os.path.join(d, "bin", f"{name}.dart")):
            mains = [os.path.join(d, "bin", f"{name}.dart")]
        flavors = _flutter_flavors(d) if is_flutter else []
        for m in mains:
            prog = _rel(d, m)
            fname = os.path.basename(m)[:-5]
            flavor = next((f for f in flavors if fname in (f"main_{f}", f"main-{f}")), None)
            cfg = {"name": f"{'Flutter' if is_flutter else 'Dart'}: {fname}" + (f" ({flavor})" if flavor else "") + ("" if rel == "." else f" ({rel})"),
                   "type": "dart", "request": "launch", "program": prog, "cwd": _wf(rel),
                   "codeck": {"kind": "flutter" if is_flutter else "dart", "group": f"{'Flutter' if is_flutter else 'Dart'} · {name}", "device": is_flutter}}
            if flavor:
                cfg["toolArgs"] = ["--flavor", flavor]
            out.append(cfg)
            if is_flutter:
                out.append({**copy.deepcopy(cfg), "name": cfg["name"].replace(": ", ": ", 1) + " · profile", "flutterMode": "profile",
                            "codeck": {**cfg["codeck"], "variant": "profile"}})
    return out


def _flutter_flavors(d):
    for g in ("android/app/build.gradle", "android/app/build.gradle.kts"):
        f = os.path.join(d, g)
        if os.path.isfile(f):
            text = open(f, encoding="utf-8", errors="replace").read()
            m = re.search(r"productFlavors\s*\{(.*?)\n\s{4}\}", text, re.S)
            if m:
                return re.findall(r"^\s{8}(?:create\(\")?(\w+)\"?\)?\s*\{", m.group(1), re.M)
    return []


def _detect_other(root):
    out = []
    if os.path.exists(os.path.join(root, "go.mod")):
        out.append({"name": "go run .", "type": "codeck-shell", "request": "launch", "command": "go run .", "cwd": "${workspaceFolder}",
                    "codeck": {"kind": "go", "group": "Go"}})
    if os.path.exists(os.path.join(root, "Cargo.toml")):
        out.append({"name": "cargo run", "type": "codeck-shell", "request": "launch", "command": "cargo run", "cwd": "${workspaceFolder}",
                    "codeck": {"kind": "rust", "group": "Rust"}})
    for f in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        if os.path.exists(os.path.join(root, f)):
            out.append({"name": "docker compose up", "type": "codeck-shell", "request": "launch", "command": "docker compose up", "cwd": "${workspaceFolder}",
                        "codeck": {"kind": "docker", "group": "Docker"}})
            break
    return out


_cache = {}


def _signature(root):
    """Muda quando um arquivo que define o que executar muda (cache da detecção)."""
    sig = []
    for pat in ("**/*.csproj", "**/Properties/launchSettings.json", "package.json", "*/package.json", "*/*/package.json", "pubspec.yaml",
                "*/pubspec.yaml", "lib/main*.dart", "*/lib/main*.dart", ".vscode/launch.json", ".vscode/tasks.json"):
        for f in glob_one(root, pat, limit=120):
            try:
                sig.append((f, os.path.getmtime(f)))
            except OSError:
                pass
    return hash(tuple(sorted(sig)))


def detect(root):
    sig = _signature(root)
    c = _cache.get(root)
    if c and c[0] == sig:
        return c[1]
    dn, tasks = _detect_dotnet(root)
    res = {"configurations": dn + _detect_node(root) + _detect_flutter(root) + _detect_other(root), "tasks": tasks}
    _cache[root] = (sig, res)
    return res


# ---------------------------------------------------------------- lista unificada
def _cid(source, name):
    return f"{source}:{name}"


def _public(cfg, source, root, tasks):
    c = cfg.get("codeck") or {}
    t = cfg.get("type")
    kind = c.get("kind") or {"coreclr": "dotnet", "dotnet": "dotnet", "node": "node", "pwa-node": "node", "node-terminal": "node",
                             "chrome": "browser", "pwa-chrome": "browser", "msedge": "browser", "pwa-msedge": "browser", "dart": "flutter"}.get(t, "other")
    debug = t in DEBUG_TYPES and c.get("debug") is not False
    runnable = bool(run_command(cfg, root, tasks, probe=True)) or t in ("chrome", "pwa-chrome", "msedge", "pwa-msedge", "dart")
    detail = c.get("detail") or cfg.get("command") or cfg.get("program") or cfg.get("url") or ""
    return {"id": _cid(source, cfg.get("name", "?")), "name": cfg.get("name", "?"), "type": t, "request": cfg.get("request", "launch"),
            "source": source, "kind": kind, "group": c.get("group") or {"vscode": "VS Code (launch.json)", "codeck": "Salvas no Codeck"}.get(source, "Outros"),
            "debug": bool(debug), "run": bool(runnable), "why": c.get("why"), "device": bool(c.get("device") or t == "dart" and kind == "flutter"),
            "url": c.get("url") or cfg.get("url"), "profile": c.get("profile"), "project": c.get("project"), "browser": bool(c.get("browser")),
            "main": bool(c.get("main")), "variant": c.get("variant"), "detail": str(detail).replace("${workspaceFolder}", ".")[:160],
            "envKeys": sorted((cfg.get("env") or {}).keys()), "envFile": os.path.basename(cfg["envFile"]) if cfg.get("envFile") else None,
            "preLaunchTask": cfg.get("preLaunchTask")}


def _all(repo_id, task_id=None):
    """Todas as configurações (cruas) do escopo: [(origem, config)], compounds e tarefas do tasks.json."""
    root = _root(repo_id, task_id)
    with _lock:
        p = copy.deepcopy(_proj(_db(), repo_id))
    items, compounds = [], []
    vs, _ = (None, False) if p["sync"] == "off" else _read_vscode(root, "launch.json")
    if p["sync"] != "vscode":
        items += [("codeck", c) for c in p["configurations"]]
        compounds += [("codeck", c) for c in p["compounds"]]
    if vs:
        items += [("vscode", c) for c in vs.get("configurations") or [] if isinstance(c, dict)]
        compounds += [("vscode", c) for c in vs.get("compounds") or [] if isinstance(c, dict)]
    det = detect(root)
    taken = {c.get("name") for _, c in items}
    items += [("detected", c) for c in det["configurations"] if c["name"] not in taken]
    tasks = {**{t["label"]: t for t in det["tasks"]}, **_vscode_tasks_raw(root)}
    return root, p, items, compounds, tasks


def _vscode_tasks_raw(root):
    data, _ = _read_vscode(root, "tasks.json")
    return {t.get("label") or t.get("command"): t for t in (data or {}).get("tasks") or [] if isinstance(t, dict) and (t.get("label") or t.get("command"))}


def configs(repo_id, task_id=None):
    root, p, items, compounds, tasks = _all(repo_id, task_id)
    out = [_public(c, s, root, tasks) for s, c in items]
    ids = {c["id"] for c in out}
    for s, comp in compounds:
        parts = [x for x in (_cid(src, n) for n in comp.get("configurations") or [] for src in ("codeck", "vscode", "detected")) if x in ids]
        seen, uniq = set(), []
        for x in parts:   # o mesmo nome em duas origens: fica a 1ª (codeck > vscode > detectada)
            n = x.split(":", 1)[1]
            if n not in seen:
                seen.add(n)
                uniq.append(x)
        if uniq:
            out.append({"id": _cid(s, comp.get("name", "?")), "name": comp.get("name", "?"), "type": "compound", "source": s, "kind": "compound",
                        "group": "Compostas", "debug": True, "run": True, "compound": uniq, "detail": " + ".join(x.split(":", 1)[1] for x in uniq)})
    hidden = set(p.get("hidden") or [])
    vs_exists = os.path.isfile(_vscode_path(root, "launch.json"))
    return {"configs": [c for c in out if c["id"] not in hidden], "hidden": sorted(hidden), "sync": p["sync"], "root": root,
            "vscode": {"launch": vs_exists, "tasks": os.path.isfile(_vscode_path(root, "tasks.json"))}}


def resolve(repo_id, task_id, config_id):
    """A configuração crua (com as variáveis do VS Code resolvidas) + as tarefas, para executar/depurar."""
    root, _, items, compounds, tasks = _all(repo_id, task_id)
    for s, c in items:
        if _cid(s, c.get("name", "?")) == config_id:
            return root, resolve_vars(copy.deepcopy(c), root), tasks
    for s, comp in compounds:
        if _cid(s, comp.get("name", "?")) == config_id:
            return root, {"type": "compound", "name": comp.get("name"), "configurations": comp.get("configurations") or [],
                          "stopAll": comp.get("stopAll")}, tasks
    raise LookupError("Configuração não encontrada — recarregue a lista")


def resolve_vars(obj, root, folder=None):
    folder = folder or root
    if isinstance(obj, dict):
        return {k: resolve_vars(v, root, folder) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_vars(v, root, folder) for v in obj]
    if isinstance(obj, str):
        s = obj.replace("${workspaceFolderBasename}", os.path.basename(root)).replace("${pathSeparator}", os.sep)
        s = s.replace("${cwd}", root).replace("${defaultBuildTask}", "")
        return _vars(s, root)
    return obj


def find_by_name(repo_id, task_id, name):
    _, _, items, _, _ = _all(repo_id, task_id)
    for s, c in items:
        if c.get("name") == name:
            return _cid(s, name)
    return None


# ---------------------------------------------------------------- executar sem depurar: o comando do terminal
def task_command(task, root):
    if not task or not task.get("command"):
        return None
    parts = [resolve_vars(task["command"], root)] + [resolve_vars(a if isinstance(a, str) else (a or {}).get("value", ""), root) for a in task.get("args") or []]
    cmd = _join(parts) if task.get("type") == "process" else " ".join(parts)
    cwd = resolve_vars((task.get("options") or {}).get("cwd"), root)
    return _and(f"cd {_q(cwd)}", cmd) if cwd else cmd


def pre_launch(cfg, root, tasks):
    """O preLaunchTask resolvido num comando (segue dependsOn de um nível)."""
    name = cfg.get("preLaunchTask")
    if not name or name.startswith("${"):
        return None
    t = tasks.get(name)
    if not t:
        # "build" sem tasks.json (o C# do VS Code dava esse nome): compila o projeto do programa
        prog = str(cfg.get("program") or "").replace("\\", "/")
        if cfg.get("type") in ("coreclr", "dotnet") and "/bin/" in prog:
            return "dotnet build " + _q(prog.split("/bin/")[0])
        return None
    chain = []
    deps = t.get("dependsOn")
    for dname in ([deps] if isinstance(deps, str) else deps or []):
        if tasks.get(dname):
            chain.append(task_command(tasks[dname], root))
    chain.append(task_command(t, root))
    return _and(*[c for c in chain if c])


def run_command(cfg, root, tasks, probe=False, device=None):
    """O comando de terminal que executa a configuração SEM depurar (como o Ctrl+F5)."""
    t, c = cfg.get("type"), cfg.get("codeck") or {}
    cmd = None
    if t == "codeck-shell" or t == "node-terminal":
        cmd = cfg.get("command")
    elif t == "codeck-dotnet-fx":
        if probe:
            return "fx"
        from . import dotnet
        cmd, _ = dotnet.start_command(root, c["project"], "Debug|Any CPU")
        return _and(dotnet.build_command(root, c["project"], "Debug|Any CPU"), cmd)
    elif t in ("coreclr", "dotnet"):
        if c.get("project"):
            # detectada: dotnet run com o perfil (compila, usa o launchSettings — URL, ambiente — igual ao Visual Studio)
            cmd = f"dotnet run --project {_q(os.path.dirname(os.path.join(root, c['project'])))}" + (f" --launch-profile {_q(c['profile'])}" if c.get("profile") else "")
            return cmd
        if cfg.get("program"):
            prog = cfg["program"]
            cmd = _join((["dotnet", prog] if prog.endswith(".dll") else [prog]) + list(cfg.get("args") or []))
        elif cfg.get("projectPath"):
            cmd = "dotnet run --project " + _q(cfg["projectPath"])
    elif t in ("node", "pwa-node"):
        exe = cfg.get("runtimeExecutable") or "node"
        parts = [exe] + list(cfg.get("runtimeArgs") or [])
        if cfg.get("program"):
            parts.append(cfg["program"])
        parts += list(cfg.get("args") or [])
        cmd = _join(parts)
    elif t in ("debugpy", "python"):
        py = "python3" if not IS_WIN else "python"
        if cfg.get("module"):
            cmd = _join([py, "-m", cfg["module"]] + list(cfg.get("args") or []))
        elif cfg.get("program"):
            cmd = _join([py, cfg["program"]] + list(cfg.get("args") or []))
    elif t == "go":
        cmd = "go run " + _q(cfg.get("program") or ".")
    elif t == "dart":
        flutter = (c.get("kind") == "flutter") or c.get("device")
        parts = (["flutter", "run"] if flutter else ["dart", "run"]) + list(cfg.get("toolArgs") or [])
        if flutter and device:
            parts += ["-d", device]
        if flutter and cfg.get("flutterMode") in ("profile", "release"):
            parts.append("--" + cfg["flutterMode"])
        if cfg.get("program"):
            parts += (["-t", cfg["program"]] if flutter else [cfg["program"]])
        parts += list(cfg.get("args") or [])
        cmd = _join(parts)
    if not cmd or probe:
        return cmd
    return _and(pre_launch(cfg, root, tasks), cmd)


def run_env(cfg):
    """envFile primeiro; o "env" da configuração por cima (como o VS Code)."""
    return {**_env_file(cfg.get("envFile")), **{k: str(v) for k, v in (cfg.get("env") or {}).items() if v is not None}}


# ---------------------------------------------------------------- salvar, ocultar, importar e exportar
def _clean(cfg):
    x = {k: v for k, v in cfg.items() if not str(k).startswith("_")}
    if not str(x.get("name") or "").strip():
        raise ValueError("Dê um nome à configuração")
    x["name"] = str(x["name"]).strip()[:120]
    x.setdefault("request", "launch")
    if not x.get("type"):
        raise ValueError("Escolha o tipo")
    return x


def save_config(repo_id, task_id, cfg, old_name=None):
    """Salva uma configuração: no app ou, com sync "vscode", direto no .vscode/launch.json."""
    cfg = _clean(cfg)
    root = _root(repo_id, task_id)
    with _lock:
        d = _db()
        p = _proj(d, repo_id)
        if p["sync"] == "vscode":
            data, _ = _read_vscode(root, "launch.json")
            data = data or {"version": "0.2.0", "configurations": []}
            confs = [c for c in data.get("configurations") or [] if c.get("name") not in (old_name, cfg["name"])]
            data["configurations"] = confs + [cfg]
            _write_vscode(root, "launch.json", data)
            return {"id": _cid("vscode", cfg["name"])}
        p["configurations"] = [c for c in p["configurations"] if c.get("name") not in (old_name, cfg["name"])] + [cfg]
        save_json(LAUNCH_FILE, d)
        return {"id": _cid("codeck", cfg["name"])}


def delete_config(repo_id, task_id, config_id):
    src, _, name = config_id.partition(":")
    root = _root(repo_id, task_id)
    with _lock:
        d = _db()
        p = _proj(d, repo_id)
        if src == "codeck":
            p["configurations"] = [c for c in p["configurations"] if c.get("name") != name]
            p["compounds"] = [c for c in p["compounds"] if c.get("name") != name]
        elif src == "vscode":
            data, _ = _read_vscode(root, "launch.json")
            if data:
                data["configurations"] = [c for c in data.get("configurations") or [] if c.get("name") != name]
                data["compounds"] = [c for c in data.get("compounds") or [] if c.get("name") != name]
                _write_vscode(root, "launch.json", data)
        else:   # detectada: só some da lista (dá para mostrar de novo)
            p["hidden"] = sorted(set(p.get("hidden") or []) | {config_id})
        save_json(LAUNCH_FILE, d)
    return {"ok": True}


def save_compound(repo_id, task_id, name, names, old_name=None):
    name = str(name or "").strip()[:120]
    if not name or len(names or []) < 2:
        raise ValueError("Uma configuração composta tem nome e pelo menos duas configurações")
    comp = {"name": name, "configurations": [str(n) for n in names][:20], "stopAll": True}
    root = _root(repo_id, task_id)
    with _lock:
        d = _db()
        p = _proj(d, repo_id)
        if p["sync"] == "vscode":
            data, _ = _read_vscode(root, "launch.json")
            data = data or {"version": "0.2.0", "configurations": []}
            data["compounds"] = [c for c in data.get("compounds") or [] if c.get("name") not in (old_name, name)] + [comp]
            _write_vscode(root, "launch.json", data)
            return {"id": _cid("vscode", name)}
        p["compounds"] = [c for c in p["compounds"] if c.get("name") not in (old_name, name)] + [comp]
        save_json(LAUNCH_FILE, d)
    return {"id": _cid("codeck", name)}


def raw_config(repo_id, task_id, config_id):
    """A configuração como está no arquivo (para editar)."""
    _, _, items, compounds, _ = _all(repo_id, task_id)
    for s, c in items:
        if _cid(s, c.get("name", "?")) == config_id:
            return {"config": {k: v for k, v in c.items() if k != "codeck"}, "source": s}
    for s, c in compounds:
        if _cid(s, c.get("name", "?")) == config_id:
            return {"compound": c, "source": s}
    raise LookupError("Configuração não encontrada")


def preview_export(repo_id, task_id, ids):
    root = _root(repo_id, task_id)
    _, comments = _read_vscode(root, "launch.json")
    _, tcomments = _read_vscode(root, "tasks.json")
    return {"launchExists": os.path.isfile(_vscode_path(root, "launch.json")), "comments": bool(comments or tcomments), "count": len(ids or [])}


def export_vscode(repo_id, task_id, ids=None):
    """Leva configurações para o .vscode/launch.json (substitui as de mesmo nome; mantém as outras) e as tarefas de
    compilação que elas usam para o tasks.json. Sem ids: todas as do app + as detectadas principais."""
    root, _, items, compounds, tasks = _all(repo_id, task_id)
    want = set(ids or [])
    chosen = [(s, c) for s, c in items if s != "vscode" and (_cid(s, c.get("name", "?")) in want if want else
                                                              (s == "codeck" or (c.get("codeck") or {}).get("main") or (c.get("codeck") or {}).get("kind") in ("dotnet", "flutter")))]
    chosen = [(s, c) for s, c in chosen if not str(c.get("type", "")).startswith("codeck-")]
    comps = [c for s, c in compounds if s != "vscode" and (not want or _cid(s, c.get("name", "?")) in want)]
    if not chosen and not comps:
        raise ValueError("Nada para exportar")
    data, _ = _read_vscode(root, "launch.json")
    data = data or {"version": "0.2.0", "configurations": []}
    names = {c["name"] for _, c in chosen}
    data["configurations"] = [c for c in data.get("configurations") or [] if c.get("name") not in names] + \
        [{k: v for k, v in c.items() if k != "codeck"} for _, c in chosen]
    if comps:
        cn = {c["name"] for c in comps}
        data["compounds"] = [c for c in data.get("compounds") or [] if c.get("name") not in cn] + comps
    _write_vscode(root, "launch.json", data)
    need = {c.get("preLaunchTask") for _, c in chosen if c.get("preLaunchTask")}
    det_tasks = {t["label"]: t for t in detect(root)["tasks"]}
    new_tasks = [det_tasks[n] for n in need if n in det_tasks]
    if new_tasks:
        tdata, _ = _read_vscode(root, "tasks.json")
        tdata = tdata or {"version": "2.0.0", "tasks": []}
        have = {t.get("label") for t in tdata.get("tasks") or []}
        tdata["tasks"] = (tdata.get("tasks") or []) + [t for t in new_tasks if t["label"] not in have]
        _write_vscode(root, "tasks.json", tdata)
    return {"configurations": len(chosen), "compounds": len(comps), "tasks": len(new_tasks)}


def import_vscode(repo_id, task_id):
    """Copia as configurações do .vscode/launch.json para o app (substitui as de mesmo nome)."""
    root = _root(repo_id, task_id)
    data, _ = _read_vscode(root, "launch.json")
    if not data:
        raise ValueError("Este projeto não tem .vscode/launch.json")
    confs = [c for c in data.get("configurations") or [] if isinstance(c, dict) and c.get("name")]
    comps = [c for c in data.get("compounds") or [] if isinstance(c, dict) and c.get("name")]
    with _lock:
        d = _db()
        p = _proj(d, repo_id)
        names = {c["name"] for c in confs}
        p["configurations"] = [c for c in p["configurations"] if c.get("name") not in names] + confs
        cn = {c["name"] for c in comps}
        p["compounds"] = [c for c in p["compounds"] if c.get("name") not in cn] + comps
        save_json(LAUNCH_FILE, d)
    return {"configurations": len(confs), "compounds": len(comps)}


def scope_settings_shell(repo_id):
    return _settings(repo_id).get("shell") or None
