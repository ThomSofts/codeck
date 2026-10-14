"""Projetos .NET como no Visual Studio: soluções (.sln/.slnx) com os projetos, configurações (Debug|Any CPU…),
projeto(s) de inicialização, Compilar/Recompilar/Limpar, Restaurar NuGet, Iniciar (compila e abre o .exe, o site no
IIS Express ou o `dotnet run`) e a Lista de Erros lida da saída do MSBuild.

.NET Framework (csproj "antigo", TargetFrameworkVersion v4.x) compila com o MSBuild do Visual Studio/Build Tools
(achado pelo vswhere) no Windows — ou o do Mono no Mac. Projetos SDK (net6+, ou net4x em formato SDK) usam o `dotnet`.
A compilação roda num terminal do projeto (você vê a saída ao vivo); a tela lê os erros dessa saída.
"""
import glob
import os
import re
import shlex
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

from . import terminals
from .workspace import _root, _safe, _settings, glob_one

IS_WIN = os.name == "nt"
WEB_GUIDS = {"349c5851-65df-11da-9384-00065b846f21", "e24c65dc-7377-472b-9aba-bc803b73c61a", "603c0e0b-db56-11dc-be95-000d561079b0",
             "f85e285d-a4e0-4152-9332-ab1d724d3325", "e53f8fea-eae0-44a6-8774-ffd645390401"}
TEST_GUIDS = {"3ac096d0-a1c2-e12c-1390-a8335801fdab"}
FOLDER_GUID = "2150e333-8fdc-42a3-9474-1a3956d46de8"
DONE = "__CODECK_BUILD_DONE__"


# ---------------------------------------------------------------- ferramentas da máquina
_tools = {"at": 0, "v": None}


def toolchain(force=False):
    """MSBuild do Visual Studio (vswhere), IIS Express, dotnet, Mono — o que existir nesta máquina."""
    if _tools["v"] and not force and time.time() - _tools["at"] < 300:
        return _tools["v"]
    path = terminals.clean_env().get("PATH")
    which = lambda n: shutil.which(n, path=path)   # noqa: E731
    out = {"msbuild": None, "vs": None, "iisexpress": None, "dotnet": which("dotnet"), "mono": None, "nuget": which("nuget"), "devenv": None}
    if IS_WIN:
        pf86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
        pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
        vswhere = os.path.join(pf86, "Microsoft Visual Studio", "Installer", "vswhere.exe")
        if os.path.exists(vswhere):
            try:
                r = subprocess.run([vswhere, "-latest", "-prerelease", "-products", "*", "-requires", "Microsoft.Component.MSBuild",
                                    "-find", r"MSBuild\**\Bin\MSBuild.exe"], capture_output=True, text=True, timeout=20, creationflags=0x08000000)
                found = [x.strip() for x in r.stdout.splitlines() if x.strip().lower().endswith("msbuild.exe") and "amd64" not in x.lower()]
                out["msbuild"] = found[0] if found else None
                r = subprocess.run([vswhere, "-latest", "-prerelease", "-products", "*", "-property", "displayName"],
                                   capture_output=True, text=True, timeout=20, creationflags=0x08000000)
                out["vs"] = r.stdout.strip().splitlines()[0] if r.stdout.strip() else None
                r = subprocess.run([vswhere, "-latest", "-prerelease", "-products", "*", "-property", "productPath"],
                                   capture_output=True, text=True, timeout=20, creationflags=0x08000000)
                dv = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
                out["devenv"] = dv if dv.lower().endswith("devenv.exe") and os.path.exists(dv) else None
            except Exception:  # noqa: BLE001
                pass
        if not out["msbuild"]:
            for c in glob.glob(os.path.join(pf, "Microsoft Visual Studio", "*", "*", "MSBuild", "Current", "Bin", "MSBuild.exe")) + \
                     glob.glob(os.path.join(pf86, "Microsoft Visual Studio", "*", "*", "MSBuild", "Current", "Bin", "MSBuild.exe")) + \
                     [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Microsoft.NET", "Framework64", "v4.0.30319", "MSBuild.exe")]:
                if os.path.exists(c):
                    out["msbuild"] = c
                    break
        for c in (os.path.join(pf, "IIS Express", "iisexpress.exe"), os.path.join(pf86, "IIS Express", "iisexpress.exe")):
            if os.path.exists(c):
                out["iisexpress"] = c
                break
    else:
        out["mono"] = which("mono") or next((p for p in ("/Library/Frameworks/Mono.framework/Versions/Current/Commands/mono",
                                                          "/opt/homebrew/bin/mono", "/usr/local/bin/mono") if os.path.exists(p)), None)
        mb = which("msbuild") or next((p for p in ("/Library/Frameworks/Mono.framework/Versions/Current/Commands/msbuild",
                                                    "/opt/homebrew/bin/msbuild", "/usr/local/bin/msbuild") if os.path.exists(p)), None)
        out["msbuild"] = mb
    _tools.update(at=time.time(), v=out)
    return out


# ---------------------------------------------------------------- solução e projetos
def _ns(tag):
    return tag.split("}", 1)[-1]


def _find(root_el, name):
    return [e for e in root_el.iter() if _ns(e.tag) == name]


def _text(root_el, name):
    for e in _find(root_el, name):
        if (e.text or "").strip():
            return e.text.strip()
    return None


def parse_project(full):
    """O que o Visual Studio mostra de um .csproj/.vbproj/.fsproj: tipo, framework, saída, site (IIS Express)."""
    info = {"path": full, "name": os.path.splitext(os.path.basename(full))[0], "sdk": None, "kind": "library", "framework": None,
            "netfx": False, "assembly": None, "outputType": None, "outputPaths": {}, "iisUrl": None, "port": None, "test": False, "profiles": []}
    try:
        tree = ET.parse(full)
    except Exception:  # noqa: BLE001 — csproj inválido: entra só com o nome
        return info
    r = tree.getroot()
    sdk = r.get("Sdk") or next((e.get("Name") for e in _find(r, "Sdk") if e.get("Name")), None)
    info["sdk"] = sdk
    tf = _text(r, "TargetFramework") or (_text(r, "TargetFrameworks") or "").split(";")[0] or None
    tfv = _text(r, "TargetFrameworkVersion")
    info["framework"] = tf or (f".NET Framework {tfv.lstrip('v')}" if tfv else None)
    info["netfx"] = bool(tfv) or bool(tf and re.fullmatch(r"net[1-4]\d*", tf))
    info["assembly"] = _text(r, "AssemblyName") or info["name"]
    ot = (_text(r, "OutputType") or "").lower()
    info["outputType"] = ot or None
    guids = {g.strip("{} ").lower() for g in (_text(r, "ProjectTypeGuids") or "").split(";") if g.strip()}
    refs = " ".join((e.get("Include") or "") for e in _find(r, "PackageReference") + _find(r, "Reference")).lower()
    info["test"] = bool(guids & TEST_GUIDS) or any(x in refs for x in ("mstest.testframework", "xunit", "nunit", "microsoft.net.test.sdk",
                                                                       "microsoft.visualstudio.qualitytools.unittestframework"))
    if guids & WEB_GUIDS or (sdk or "").lower() in ("microsoft.net.sdk.web", "microsoft.net.sdk.blazorwebassembly"):
        info["kind"] = "web"
    elif info["test"]:
        info["kind"] = "test"
    elif ot in ("exe", "winexe"):
        info["kind"] = "winexe" if ot == "winexe" else "console"
    for pg in _find(r, "PropertyGroup"):
        cond = pg.get("Condition") or ""
        m = re.search(r"==\s*'([^|']+)\|([^']+)'", cond)
        op = next((c.text.strip() for c in pg if _ns(c.tag) == "OutputPath" and (c.text or "").strip()), None)
        if m and op:
            info["outputPaths"][f"{m.group(1)}|{m.group(2)}"] = op.replace("\\", "/")
        elif op and not cond:
            info["outputPaths"]["*"] = op.replace("\\", "/")
    iis = _text(r, "IISUrl")
    if iis:
        info["iisUrl"] = iis if iis.endswith("/") else iis + "/"
        m = re.search(r":(\d+)", iis)
        info["port"] = int(m.group(1)) if m else None
    elif _text(r, "DevelopmentServerPort"):
        info["port"] = int(_text(r, "DevelopmentServerPort"))
        info["iisUrl"] = f"http://localhost:{info['port']}/"
    ls = os.path.join(os.path.dirname(full), "Properties", "launchSettings.json")
    if os.path.isfile(ls):
        try:
            from .workspace import _jsonc
            for name, cfg in (_jsonc(open(ls, encoding="utf-8").read()).get("profiles") or {}).items():
                if (cfg or {}).get("commandName") in ("Project", "IISExpress", None):
                    info["profiles"].append({"name": name, "kind": (cfg or {}).get("commandName") or "Project",
                                             "url": (cfg or {}).get("applicationUrl") or (cfg or {}).get("launchUrl")})
        except Exception:  # noqa: BLE001
            pass
    return info


SLN_PROJ = re.compile(r'^Project\("\{([^}]+)\}"\)\s*=\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"\{([^}]+)\}"', re.M)


def parse_solution(full):
    text = open(full, encoding="utf-8-sig", errors="replace").read()
    base = os.path.dirname(full)
    projects, folders, configs = [], {}, []
    if full.lower().endswith(".slnx"):
        try:
            r = ET.fromstring(text)
            for e in r.iter():
                if _ns(e.tag) == "Project" and e.get("Path"):
                    p = os.path.normpath(os.path.join(base, e.get("Path").replace("\\", os.sep)))
                    projects.append({"guid": None, "file": p, "folder": None})
                if _ns(e.tag) == "BuildType" and e.get("Name"):
                    configs.append(e.get("Name"))
            configs = [f"{c}|Any CPU" for c in configs] or ["Debug|Any CPU", "Release|Any CPU"]
        except ET.ParseError:
            pass
    else:
        for m in SLN_PROJ.finditer(text):
            tguid, name, rel, guid = m.group(1).lower(), m.group(2), m.group(3), m.group(4).upper()
            if tguid == FOLDER_GUID:
                folders[guid] = name
                continue
            if not re.search(r"\.(cs|vb|fs|vcx|sql)proj$", rel, re.I):
                continue
            projects.append({"guid": guid, "file": os.path.normpath(os.path.join(base, rel.replace("\\", os.sep))), "folder": None})
        nest = re.search(r"GlobalSection\(NestedProjects\)[^\n]*\n(.*?)EndGlobalSection", text, re.S)
        if nest:
            parent = dict((a.upper(), b.upper()) for a, b in re.findall(r"\{([^}]+)\}\s*=\s*\{([^}]+)\}", nest.group(1)))
            for p in projects:
                chain, g = [], parent.get(p["guid"] or "")
                while g and g in folders and len(chain) < 8:
                    chain.insert(0, folders[g]); g = parent.get(g)
                p["folder"] = "/".join(chain) or None
        sc = re.search(r"GlobalSection\(SolutionConfigurationPlatforms\)[^\n]*\n(.*?)EndGlobalSection", text, re.S)
        if sc:
            for ln in sc.group(1).splitlines():
                k = ln.split("=")[0].strip()
                if "|" in k and k not in configs:
                    configs.append(k)
    return {"path": full, "name": os.path.splitext(os.path.basename(full))[0], "configs": configs or ["Debug|Any CPU", "Release|Any CPU"],
            "projects": projects}


def solution(repo_id, task_id=None):
    """Soluções do projeto (até 3 níveis de pasta) com os projetos de cada uma; sem .sln, os .csproj soltos."""
    root = _root(repo_id, task_id)
    rel = lambda p: os.path.relpath(p, root).replace(os.sep, "/")   # noqa: E731
    slns = sorted(glob_one(root, "**/*.sln", limit=20) + glob_one(root, "**/*.slnx", limit=20), key=lambda p: (p.count(os.sep), p))
    out = []
    seen = set()
    for s in slns:
        try:
            sol = parse_solution(s)
        except Exception:  # noqa: BLE001
            continue
        projs = []
        for p in sol["projects"]:
            if not os.path.isfile(p["file"]):
                projs.append({"name": os.path.splitext(os.path.basename(p["file"]))[0], "path": rel(p["file"]), "missing": True, "folder": p["folder"]})
                continue
            info = parse_project(p["file"])
            seen.add(os.path.normcase(p["file"]))
            projs.append(_public(info, rel) | {"folder": p["folder"]})
        out.append({"path": rel(s), "name": sol["name"], "configs": sol["configs"], "projects": projs})
    loose = []
    for p in sorted(glob_one(root, "**/*.csproj", limit=60) + glob_one(root, "**/*.vbproj", limit=20) + glob_one(root, "**/*.fsproj", limit=20)):
        if os.path.normcase(p) not in seen:
            loose.append(_public(parse_project(p), rel) | {"folder": None})
    if loose and not out:
        out.append({"path": None, "name": os.path.basename(root), "configs": ["Debug|Any CPU", "Release|Any CPU"], "projects": loose})
    t = toolchain()
    return {"solutions": out, "toolchain": {k: (bool(v) if k != "vs" else v) for k, v in t.items()},
            "platform": "windows" if IS_WIN else "macos" if os.uname().sysname == "Darwin" else "linux"}


def _public(info, rel):
    return {"name": info["name"], "path": rel(info["path"]), "dir": rel(os.path.dirname(info["path"])) or ".", "kind": info["kind"],
            "sdk": info["sdk"], "framework": info["framework"], "netfx": info["netfx"], "assembly": info["assembly"],
            "iisUrl": info["iisUrl"], "test": info["test"], "profiles": info["profiles"]}


# ---------------------------------------------------------------- compilar / executar
def _q(x):
    return subprocess.list2cmdline([x]) if IS_WIN else shlex.quote(x)


def _call(exe):
    """Chamar um executável pelo caminho: no PowerShell precisa do "&"."""
    return f"& {_q(exe)}" if IS_WIN else _q(exe)


def _chain(*cmds):
    cmds = [c for c in cmds if c]
    if IS_WIN:
        out = cmds[0]
        for c in cmds[1:]:
            out = f"{out}; if ($?) {{ {c} }}"
        return out
    return " && ".join(cmds)


def _done_marker(cmd):
    if IS_WIN:
        return f"{cmd}; Write-Host \"{DONE} $(if ($?) {{ 0 }} else {{ 1 }})\""
    return f"{cmd}; echo \"{DONE} $?\""


def _split_cfg(cfg):
    c, _, p = (cfg or "Debug|Any CPU").partition("|")
    return c.strip() or "Debug", (p.strip() or "Any CPU")


def _needs_msbuild(full_target):
    """Projeto (ou solução com algum projeto) no formato antigo do .NET Framework: só o MSBuild compila."""
    paths = [full_target]
    if full_target.lower().endswith((".sln", ".slnx")):
        paths = [p["file"] for p in parse_solution(full_target)["projects"] if os.path.isfile(p["file"])]
    for p in paths:
        info = parse_project(p)
        if info["netfx"] and not info["sdk"]:
            return True
    return False


def build_command(root, target, config, action="Build", restore=True):
    full = _safe(root, target)
    conf, plat = _split_cfg(config)
    t = toolchain()
    legacy = _needs_msbuild(full)
    if t["msbuild"] and (legacy or not t["dotnet"]):
        # restore de packages.config + PackageReference (MSBuild 16.5+), compilação paralela, saída enxuta
        args = [full, f"-t:{action}", f"-p:Configuration={conf}", f"-p:Platform={plat}", "-m", "-nologo", "-v:minimal", "-clp:Summary"]
        if restore and action != "Clean":
            args += ["-restore", "-p:RestorePackagesConfig=true"]
        return _call(t["msbuild"]) + " " + " ".join(_q(a) for a in args)
    if t["dotnet"]:
        if legacy:
            raise ValueError("Este projeto é .NET Framework no formato antigo — precisa do MSBuild do Visual Studio/Build Tools "
                             "(Windows) ou do Mono (Mac). O `dotnet` não compila csproj antigo.")
        verb = {"Build": "build", "Rebuild": "build --no-incremental", "Clean": "clean"}[action]
        plat_arg = [] if plat.replace(" ", "").lower() == "anycpu" else [f"-p:Platform={plat}"]
        return f"dotnet {verb} {_q(full)} -c {_q(conf)} " + " ".join(_q(a) for a in plat_arg) + ("" if restore or action == "Clean" else " --no-restore")
    raise ValueError("Nenhum compilador .NET encontrado: instale o Visual Studio/Build Tools (Windows), o .NET SDK ou o Mono")


def _output_exe(proj_full, info, config):
    conf, plat = _split_cfg(config)
    op = info["outputPaths"].get(f"{conf}|{plat.replace(' ', '')}") or info["outputPaths"].get(f"{conf}|{plat}") or info["outputPaths"].get("*") \
        or f"bin/{conf}/"
    d = os.path.normpath(os.path.join(os.path.dirname(proj_full), op.replace("\\", "/").replace("$(Configuration)", conf)))
    exe = os.path.join(d, info["assembly"] + ".exe")
    if not os.path.exists(exe):   # SDK com TargetFramework: bin/Debug/net48/App.exe
        cand = glob.glob(os.path.join(d, "*", info["assembly"] + ".exe"))
        exe = cand[0] if cand else exe
    return exe


def start_command(root, project, config, profile=None):
    """Como o F5 do Visual Studio (sem depurador): o que abrir depois de compilar. Devolve (comando, url)."""
    full = _safe(root, project)
    info = parse_project(full)
    conf, _ = _split_cfg(config)
    t = toolchain()
    if info["kind"] == "library":
        raise ValueError(f"{info['name']} é uma biblioteca — escolha um projeto executável (console, Windows ou web) como projeto de inicialização")
    if info["kind"] == "test":
        if info["sdk"] and t["dotnet"]:
            return f"dotnet test {_q(full)} -c {_q(conf)} --no-build", None
        raise ValueError("Testes de .NET Framework: rode pelo Gerenciador de Testes do Visual Studio (ou converta para o formato SDK)")
    if info["sdk"] and t["dotnet"] and not info["netfx"]:
        prof = f" --launch-profile {_q(profile)}" if profile else ""
        url = next((p["url"] for p in info["profiles"] if p["name"] == profile), None) if profile else None
        return f"dotnet run --project {_q(full)} -c {_q(conf)} --no-build{prof}", (url.split(";")[0] if url else None)
    if info["kind"] == "web":
        if not t["iisexpress"]:
            raise ValueError("Site .NET Framework precisa do IIS Express (vem com o Visual Studio) — não encontrei nesta máquina")
        port = info["port"] or 8080
        url = info["iisUrl"] or f"http://localhost:{port}/"
        # o Visual Studio guarda a configuração do site em .vs/<solução>/config/applicationhost.config: usa ela se existir
        cfgs = glob.glob(os.path.join(root, ".vs", "*", "config", "applicationhost.config")) + glob.glob(os.path.join(root, "*", ".vs", "*", "config", "applicationhost.config"))
        if cfgs and info["name"] in open(cfgs[0], encoding="utf-8", errors="replace").read():
            return f"{_call(t['iisexpress'])} {_q('/config:' + cfgs[0])} {_q('/site:' + info['name'])}", url
        return f"{_call(t['iisexpress'])} {_q('/path:' + os.path.dirname(full))} /port:{port}", url
    exe = _output_exe(full, info, config)
    if IS_WIN:
        return _call(exe), None
    if t["mono"]:
        return f"{_q(t['mono'])} {_q(exe)}", None
    raise ValueError("Executável .NET Framework fora do Windows precisa do Mono")


def _close_previous(repo_id, task_id, role):
    for t in terminals.list_all(project=repo_id):
        if t["meta"].get("dotnet") == role and t["meta"].get("task") == task_id:
            terminals.close(t["id"])


def build(repo_id, task_id, target, config, action="Build"):
    """Compilar/Recompilar/Limpar a solução ou um projeto num terminal "⚙" (reaproveitado a cada compilação)."""
    if action not in ("Build", "Rebuild", "Clean", "Restore"):
        raise ValueError("Ação inválida")
    root = _root(repo_id, task_id)
    if action == "Restore":
        t = toolchain()
        full = _safe(root, target)
        cmd = (_call(t["msbuild"]) + f" {_q(full)} -t:Restore -p:RestorePackagesConfig=true -nologo -v:minimal") if t["msbuild"] and _needs_msbuild(full) \
            else f"dotnet restore {_q(full)}" if t["dotnet"] else None
        if not cmd:
            raise ValueError("Nenhum compilador .NET encontrado para restaurar os pacotes")
    else:
        cmd = build_command(root, target, config, action)
    _close_previous(repo_id, task_id, "build")
    label = {"Build": "Compilar", "Rebuild": "Recompilar", "Clean": "Limpar", "Restore": "Restaurar NuGet"}[action]
    meta = {"project": repo_id, "dotnet": "build", "target": target, "config": config, **({"task": task_id} if task_id else {})}
    term = terminals.create(root, f"⚙ {label} · {os.path.basename(target)}", _done_marker(cmd), "run", meta,
                            shell=_settings(repo_id).get("shell") or None)
    return {"term": term.info()}


def start(repo_id, task_id, projects, config, profile=None):
    """Inicia o(s) projeto(s) de inicialização (já compilados). Um terminal "▶" por projeto; site abre no navegador."""
    root = _root(repo_id, task_id)
    out, urls = [], []
    for p in projects or []:
        cmd, url = start_command(root, p, config, profile if len(projects) == 1 else None)
        name = os.path.splitext(os.path.basename(p))[0]
        _close_previous(repo_id, task_id, "start:" + p)
        meta = {"project": repo_id, "dotnet": "start:" + p, **({"task": task_id} if task_id else {})}
        term = terminals.create(os.path.dirname(_safe(root, p)), f"▶ {name}", cmd, "run", meta, shell=_settings(repo_id).get("shell") or None)
        out.append(term.info())
        if url:
            urls.append(url)
    return {"terms": out, "urls": urls}


# ---------------------------------------------------------------- lista de erros (saída do MSBuild/dotnet)
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\r")
DIAG = re.compile(r"^\s*(?:\d+>)?\s*(?P<file>[^\s(][^()]*?)\((?P<line>\d+)(?:,(?P<col>\d+))?(?:,\d+,\d+)?\)\s*:\s*(?P<sev>error|warning)\s+(?P<code>[A-Z]+\d+)\s*:\s*(?P<msg>.*?)(?:\s+\[(?P<proj>[^\]]+)\])?\s*$", re.I)
DIAG_NOFILE = re.compile(r"^\s*(?:\d+>)?\s*(?P<file>(?:[A-Za-z]:)?[^:]+?)\s*:\s*(?P<sev>error|warning)\s+(?P<code>[A-Z]+\d+)\s*:\s*(?P<msg>.*?)(?:\s+\[(?P<proj>[^\]]+)\])?\s*$", re.I)


def problems(term_id, root=None):
    """Erros e avisos da compilação que está (ou esteve) neste terminal, e se ela já terminou."""
    t = terminals.get(term_id)
    raw = bytes(t.scroll).decode("utf-8", errors="replace")
    text = ANSI.sub("", raw)
    done, code = False, None
    m = re.search(DONE + r" (\d+)", text)
    if m:
        done, code = True, int(m.group(1))
    root = root or t.cwd
    seen, out = set(), []
    for ln in text.splitlines():
        if DONE in ln:
            continue
        d = DIAG.match(ln) or DIAG_NOFILE.match(ln)
        if not d:
            continue
        f = d.group("file").strip()
        if not re.search(r"[\\/.]", f):   # "MSBUILD : error …", "CSC : error …": erro sem arquivo
            f = ""
        line = int(d.groupdict().get("line") or 0) or 1
        col = int(d.groupdict().get("col") or 0) or 1
        if os.path.isabs(f) or re.match(r"^[A-Za-z]:\\", f):
            try:
                rel = os.path.relpath(f, root).replace(os.sep, "/")
                f = rel if not rel.startswith("..") else f
            except ValueError:
                pass
        key = (f, line, col, d.group("code"), d.group("msg"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"path": f.replace("\\", "/") or None, "line": line, "col": col, "severity": d.group("sev").lower(), "code": d.group("code"),
                    "message": d.group("msg").strip(), "project": os.path.basename(d.group("proj") or "") or None, "source": "MSBuild"})
    return {"done": done, "exitCode": code, "ok": done and code == 0, "problems": out[:2000],
            "errors": sum(1 for p in out if p["severity"] == "error"), "warnings": sum(1 for p in out if p["severity"] == "warning")}


def open_in_vs(repo_id, task_id, target):
    """Abre a solução no Visual Studio (Windows)."""
    root = _root(repo_id, task_id)
    full = _safe(root, target)
    t = toolchain()
    if IS_WIN and t["devenv"]:
        subprocess.Popen([t["devenv"], full], creationflags=0x08000000)
        return {"ok": True}
    if IS_WIN:
        os.startfile(full)   # noqa: S606 — associação do sistema (.sln → Visual Studio)
        return {"ok": True}
    raise ValueError("O Visual Studio só existe no Windows — no Mac, use o Rider ou o VS Code")
