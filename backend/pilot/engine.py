"""Engine: contas (Azure DevOps + GitHub), ciclos de leitura, regras automáticas e notificações.

Cada fonte (PRs, releases/deploys, builds/Actions, issues) lê as duas plataformas no próprio laço e no próprio
intervalo; PRs aprovadas podem ser seguidas até o deploy (cascade.py). Os itens têm o mesmo formato, então regras,
arquivo e notificações valem igual para Azure e GitHub. Uma conta fora do ar não derruba as outras: os itens dela
ficam como estavam até a próxima leitura dar certo.
"""
import os
import threading
import time
import uuid
from datetime import timedelta

from . import azure, cascade, catalogs, git, github, power, prreview, secrets, tracking, watch
from .analytics import analytics_cache
from .core import (ARCHIVE_FILE, CONFIG_FILE, NOTIFIED_FILE, ctx, http_code, load_json, lock, log_activity, log_deploy, notify,
                   is_network_error, now, now_iso, parse_dt, pr_summary, save_json, state, wake, wants)
from .rules import get_rules, matching_deploy_rule, matching_rule, protected_set, rule_label

deploy_failures = {}  # key -> ts da última falha automática (não insiste a cada ciclo)
# Intervalo de leitura: 15 s a 10 min. Mais que isso, a fila e as regras automáticas (aprovar PR/deploy) ficam paradas
# tempo demais e a tela parece "travada" — versões antigas aceitavam até 1 h.
POLL_MIN, POLL_MAX, POLL_DEFAULT = 15, 600, 60
# Cada fonte tem o próprio intervalo (Configurações → Leitura e automação): (padrão, mínimo, máximo) em segundos.
# Issues e tarefas mudam menos e custam mais (busca do GitHub, WIQL): até 30 min.
POLL_KINDS = {"prs": (60, 15, 600), "builds": (60, 15, 600), "deploys": (60, 15, 600), "issues": (180, 30, 1800)}


def clamp_poll(v, kind=None):
    default, lo, hi = POLL_KINDS.get(kind) or (POLL_DEFAULT, POLL_MIN, POLL_MAX)
    try:
        return min(max(int(v or default), lo), hi)
    except (TypeError, ValueError):
        return default


def intervals(cfg=None):
    """Intervalo de cada fonte. Sem `pollIntervals` (versões antigas): sai do `pollSeconds` único — PRs, builds e
    deploys no mesmo valor, issues a cada 3 (como era o ciclo antigo)."""
    cfg = ctx.config if cfg is None else cfg
    got = cfg.get("pollIntervals") if isinstance(cfg.get("pollIntervals"), dict) else {}
    legacy = cfg.get("pollSeconds")
    out = {}
    for k in POLL_KINDS:
        v = got.get(k)
        if v is None and legacy:
            v = legacy * (3 if k == "issues" else 1)
        out[k] = clamp_poll(v, k)
    return out


# ---------------------------------------------------------------- contas
def migrate_plain_secrets(cfg):
    """Versões antigas gravavam o PAT em texto no config.json: move para o cofre e apaga do arquivo."""
    changed = False
    for o in cfg.get("orgs", []):
        if not o.get("id"):
            o["id"] = uuid.uuid4().hex[:12]
            changed = True
        if o.get("pat"):
            o["secret"] = secrets.put(o["id"], o.pop("pat"), secrets.AZURE)
            changed = True
    return changed


def load_accounts():
    cfg = load_json(CONFIG_FILE, {})
    try:
        poll = cfg.get("pollSeconds", POLL_DEFAULT)
        fixed = POLL_DEFAULT if isinstance(poll, (int, float)) and poll > POLL_MAX else clamp_poll(poll)
        if poll != fixed:   # 30 min / 1 h das versões antigas voltam para o padrão (1 min)
            cfg["pollSeconds"] = fixed
            save_json(CONFIG_FILE, cfg, private=True)
        if cfg and not isinstance(cfg.get("pollIntervals"), dict):   # intervalo único → um por fonte (mesmo ritmo de antes)
            cfg["pollIntervals"] = intervals(cfg)
            save_json(CONFIG_FILE, cfg, private=True)
        if migrate_plain_secrets(cfg):
            save_json(CONFIG_FILE, cfg, private=True)
    except Exception as e:  # noqa: BLE001 — sem cofre, não sobe nada com credencial em texto
        print(f"Não migrei os PATs para o cofre: {e}", flush=True)
    orgs = {o["name"]: azure.Org(o) for o in cfg.get("orgs", []) if o.get("enabled", True)}
    gh = {}
    for a in cfg.get("github", []):
        if a.get("enabled", True):
            acc = github.GitHub(a)
            acc.login = acc.name = a.get("login") or acc.login
            gh[a["id"]] = acc
    return orgs, gh, cfg


def reload_accounts():
    orgs, gh, cfg = load_accounts()
    with lock:
        ctx.orgs, ctx.gh, ctx.config = orgs, gh, cfg
        live = set(orgs) | {f"gh:{a.login}" for a in gh.values()}

        def keep(item):
            return item.get("org") in orgs if item.get("provider", "azure") == "azure" else f"gh:{item.get('account')}" in live
        for k in ("prs", "myPrs", "deploys", "releases", "builds", "issues"):
            state[k] = [x for x in state[k] if keep(x)]
        state["errors"], state["deployErrors"], state["buildErrors"], state["ghErrors"] = {}, {}, {}, {}
    analytics_cache.clear()
    wake.set()
    catalogs.warm_async()   # conta nova: a lista de repositórios dela já vem para o cache (contadores do painel)


def gh_by_login(login):
    return next((a for a in ctx.gh.values() if a.login.lower() == (login or "").lower()), None)


def account_for_item(item):
    if item.get("provider") == "github":
        acc = gh_by_login(item.get("account")) or next(iter(ctx.gh.values()), None)
        if not acc:
            raise ValueError("Conta do GitHub desconectada — conecte de novo em Contas")
        return acc
    org = ctx.orgs.get(item["org"])
    if not org:
        raise ValueError(f"Organização {item['org']} não está mais configurada")
    return org


def git_auth(provider, owner):
    """Credencial das contas do app para pull/push/clone https (se o Git da máquina não tiver uma)."""
    try:
        if provider == "github" and ctx.gh:
            acc = gh_by_login(owner) or next(iter(ctx.gh.values()))
            return git.basic_header("x-access-token", acc.token())
        if provider == "azure":
            for o in ctx.orgs.values():
                slug = o.url.rstrip("/").rsplit("/", 1)[-1].lower()
                if slug == (owner or "").lower() or o.name.lower() == (owner or "").lower():
                    return git.basic_header("", o.pat())
    except Exception:  # noqa: BLE001 — sem credencial do app, o Git usa a da máquina
        return None
    return None


git._auth_lookup["fn"] = git_auth


def watched_repos():
    """Repositórios do GitHub acompanhados (PRs abertas, Actions): os clonados localmente + os das minhas PRs/revisões."""
    out = []
    for r in load_json(git.REPOS_FILE, []):
        info = git.parse_remote(r.get("remoteUrl"))
        if info.get("provider") == "github":
            out.append(info["slug"])
    out += tracking.watched_github()   # marcados para acompanhar em Repositórios (mesmo sem clone)
    with lock:
        for p in state["prs"] + state["myPrs"]:
            if p.get("provider") == "github":
                out.append(p["project"])
    seen, res = set(), []
    for s in out:
        if s.lower() not in seen:
            seen.add(s.lower())
            res.append(s)
    return res


# ---------------------------------------------------------------- PRs
def _sources():
    return [(name, org) for name, org in list(ctx.orgs.items())] + [(f"gh:{a.login}", a) for a in list(ctx.gh.values())]


# rede: uma fonte que falha por falta de conexão não vira erro da conta; se TODAS falham assim, o app está offline.
# Cada ciclo (PRs, builds, deploys, issues) roda na própria thread: o estado da rede é por thread.
class _NetState(threading.local):
    def __init__(self):
        self.d = {"down": False, "ok": False}

    def __getitem__(self, k):
        return self.d[k]

    def __setitem__(self, k, v):
        self.d[k] = v

    def update(self, **kw):
        self.d.update(kw)


_net = _NetState()


def _fail(errors, key, e, text=None):
    if is_network_error(e):
        _net["down"] = True
    elif isinstance(e, Throttled):
        errors[key] = str(e)
    else:
        errors[key] = text if text is not None else str(e)


class Throttled(RuntimeError):
    """A conta pediu para esperar (GitHub: cota no fim ou limite secundário; Azure: Retry-After). A leitura pula a
    conta e mantém o que ela já tinha até a hora de voltar."""


def throttled(acc):
    """Segundos até a conta poder ser lida de novo (0 = pode agora). GitHub: Retry-After/limite secundário ou menos
    de 2% da cota (espera o reset, no máximo 15 min). Azure: Retry-After do limite de uso (TSTUs)."""
    left = max(0.0, (getattr(acc, "retry_until", 0) or 0) - time.time())
    rate = getattr(acc, "rate", None) or {}
    if rate.get("limit") and rate.get("remaining", 1) <= max(10, rate["limit"] * 0.02) and rate.get("reset", 0) > time.time():
        left = max(left, min(rate["reset"] - time.time(), 900))
    return int(left)


def _check_throttle(acc):
    left = throttled(acc)
    if left:
        back = (now() + timedelta(seconds=left)).astimezone().strftime("%H:%M")
        raise Throttled(f"limite de chamadas atingido — volta a ler às {back}")


def _rate_low():
    """Alguma conta do GitHub com menos de 15% da cota: as leituras do GitHub desaceleram antes de travar."""
    return any((a.rate or {}).get("limit") and a.rate.get("remaining", 0) < a.rate["limit"] * 0.15 for a in list(ctx.gh.values()))


def poll_prs():
    started = time.monotonic()
    rules_cfg = get_rules()
    settings = rules_cfg["settings"]
    archive = load_json(ARCHIVE_FILE, {})
    notified = set(load_json(NOTIFIED_FILE, []))
    all_prs, all_mine, errors, me, failed = [], [], {}, {}, set()
    watch = watched_repos()

    for src_name, acc in _sources():
        try:
            _check_throttle(acc)
            prs, mine = acc.fetch_prs(watch) if isinstance(acc, github.GitHub) else acc.fetch_prs()
            prs, mine = tracking.apply(prs, "prs"), tracking.apply(mine, "prs")   # só os repositórios acompanhados
            me[src_name] = acc.me
            _net["ok"] = True
        except Exception as e:  # noqa: BLE001 — uma conta fora não derruba as outras
            _fail(errors, src_name, e, github.github_message(e) if isinstance(acc, github.GitHub) else str(e))
            failed.add(src_name)
            with lock:
                prov = "github" if isinstance(acc, github.GitHub) else "azure"
                mine_src = (lambda p: p.get("account") == acc.login) if prov == "github" else (lambda p: p["org"] == src_name)
                all_prs.extend(p for p in state["prs"] if p.get("provider", "azure") == prov and mine_src(p))
                all_mine.extend(p for p in state["myPrs"] if p.get("provider", "azure") == prov and mine_src(p))
            continue

        for pr in mine:
            pr.setdefault("blockers", azure.my_pr_blockers(pr))
            # regra "Revisar com IA" com "também as minhas": a IA comenta na minha PR (sem votar)
            mrule = rules_cfg["rules"][mi] if (mi := matching_rule(pr, rules_cfg)) is not None else None
            if mrule and mrule["action"] == "review" and mrule.get("aiMine") and not settings["paused"] and not pr.get("isDraft"):
                pr["ruleId"] = mrule["id"]
                pr["waiting"] = prreview.consider(pr, mrule, mine=True)
            for b in pr["blockers"]:
                nkey = f"mine:{pr['key']}:{b['code']}:{(pr['commit'] or '')[:8]}"
                if nkey not in notified:
                    notified.add(nkey)
                    if wants("pr.mine") and state["lastPoll"] is not None and not pr.get("quiet"):  # 1º ciclo só marca
                        notify(f"Sua PR: {b['label']}", f"{pr['org']}/{pr['repo']} #{pr['prId']} → {pr['target']}", pr["title"],
                               f"minhas/{pr['key']}", kind="pr.mine")
        all_mine.extend(mine)

        for pr in prs:
            key = pr["key"]
            arch = archive.get(key)
            if arch and settings["resurfaceOnPush"] and arch.get("commit") and pr["commit"] != arch["commit"]:
                archive.pop(key)
                arch = None
                log_activity("auto", "unarchive", pr, detail="novo push")
            pr["archived"] = arch is not None
            pr["rule"] = matching_rule(pr, rules_cfg)
            pr["waiting"] = None
            rule = rules_cfg["rules"][pr["rule"]] if pr["rule"] is not None else None
            pr["ruleId"] = rule["id"] if rule else None
            action = rule["action"] if rule else None
            if pr["archived"]:
                continue
            if action == "archive" and not settings["paused"]:
                archive[key] = {"ts": now_iso(), "commit": pr["commit"], "reason": rule_label(rules_cfg, pr["rule"]), **pr_summary(pr)}
                pr["archived"] = True
                log_activity("auto", "archive", pr, detail=rule_label(rules_cfg, pr["rule"]), rule_id=rule["id"])
                continue
            if action == "review":
                pr["waiting"] = "pausado" if settings["paused"] else prreview.consider(pr, rule)
                continue
            if action == "approve" and pr["myVote"] == 0:
                if settings["paused"]:
                    pr["waiting"] = "pausado"
                elif rule.get("requireBuild") and pr["build"] not in ("ok", "none"):
                    pr["waiting"] = "build"
                else:
                    try:
                        vote_pr(acc, pr, 10)
                        pr["myVote"] = 10
                        pr["approvals"] += 1
                        log_activity("auto", "vote", pr, vote=10, detail=rule_label(rules_cfg, pr["rule"]), rule_id=rule["id"])
                        cascade.on_approved(pr, "auto")
                        notify("PR aprovada pelo piloto", f"{pr['org']}/{pr['repo']} #{pr['prId']} · {pr['creatorName']} → {pr['target']}",
                               pr["title"], f"todas/{key}", kind="auto")
                    except Exception as e:  # noqa: BLE001
                        errors[src_name] = f"Falha ao auto-aprovar #{pr['prId']}: {e}"
                continue
            nkey = f"{key}@{pr['commit']}"
            if pr["myVote"] == 0 and nkey not in notified and (action == "notify" or wants("pr.pending")) \
                    and (pr.get("provider") != "github" or pr.get("reviewRequested")):
                notified.add(nkey)
                if any(n.startswith(key + "@") for n in notified - {nkey}) or pr.get("quiet"):
                    continue  # já avisei esta PR (push novo não renotifica) ou o repositório está sem notificações
                notify("PR aguardando seu voto", f"{pr['org']}/{pr['repo']} #{pr['prId']} · {pr['creatorName']} → {pr['target']}",
                       pr["title"], f"fila/{key}", kind="pr.pending")
        all_prs.extend(prs)

    active = {p["key"] for p in all_prs}
    active_mine = {p["key"] for p in all_mine}
    failed_azure = {s for s in failed if not s.startswith("gh:")}
    gh_failed = any(s.startswith("gh:") for s in failed)

    def src_failed(key):
        return gh_failed if key.startswith("gh:") else key.split("|", 1)[0] in failed_azure

    def keep(n):
        if n.startswith("mine:"):
            key = n[5:].rsplit(":", 2)[0]
            return key in active_mine or src_failed(key)
        if "@" in n:
            key = n.rsplit("@", 1)[0]
            return key in active or src_failed(key)
        parts = n.split("|")
        if len(parts) == 3 and parts[1].isdigit():   # formato antigo: org|id|commit
            return f"{parts[0]}|{parts[1]}" in active
        return True  # releases/deploys/builds: cuidados pelos ciclos deles

    archive = {k: v for k, v in archive.items() if k in active or src_failed(k)}
    prreview.prune()
    notified = {n for n in notified if keep(n)}
    save_json(ARCHIVE_FILE, archive)
    save_json(NOTIFIED_FILE, sorted(notified))
    all_prs.sort(key=lambda p: p["created"] or "", reverse=True)
    with lock:
        offline_now = bool(failed) and len(failed) == len(list(_sources())) and _net["down"]
        state.update(prs=all_prs, myPrs=sorted(all_mine, key=lambda p: p["created"] or "", reverse=True), errors=errors,
                     lastPoll=state["lastPoll"] if offline_now else now_iso(), me=me or state["me"],
                     pollMs=int((time.monotonic() - started) * 1000))


def vote_pr(acc, pr, vote, comment=""):
    if isinstance(acc, github.GitHub):
        acc.vote(pr["project"], pr["prId"], vote, comment)
    else:
        acc.vote(pr["project"], pr["repoId"], pr["prId"], vote)


# ---------------------------------------------------------------- releases, aprovações de ambiente, permissões
def poll_deploys():
    rules_cfg = get_rules()
    settings = rules_cfg["settings"]
    notified = set(load_json(NOTIFIED_FILE, []))
    all_items, all_rel, errors, failed = [], [], {}, set()
    pr_ok_cache = {}
    with lock:
        gh_runs = [b for b in state["builds"] if b.get("provider") == "github"]
    for src_name, acc in _sources():
        try:
            _check_throttle(acc)
            if isinstance(acc, github.GitHub):
                items, rels = acc.fetch_pending_deploys([b for b in gh_runs if b.get("account") == acc.login]), []
            else:
                items, rels = acc.fetch_deploys()
            items = tracking.apply(items, "deploys")
            _net["ok"] = True
        except Exception as e:  # noqa: BLE001
            _fail(errors, src_name, e)
            failed.add(src_name)
            with lock:
                prov = "github" if isinstance(acc, github.GitHub) else "azure"
                all_items.extend(d for d in state["deploys"] if d.get("provider", "azure") == prov
                                 and (d.get("account") == acc.login if prov == "github" else d["org"] == src_name))
                all_rel.extend(r for r in state["releases"] if r.get("org") == src_name)
            continue
        for it in items:
            rule = matching_deploy_rule(it, rules_cfg)
            it["ruleId"] = rule["id"] if rule else None
            it["ruleName"] = (rule["name"] or "regra de deploy") if rule else None
            it["waiting"] = None
            if rule and rule["action"] == "approve":
                if settings["paused"]:
                    it["waiting"] = "pausado"
                elif rule["requirePrApproved"]:
                    pk = (src_name, it.get("project"), it.get("prNumber"))
                    if not it.get("prNumber"):
                        it["waiting"] = "PR de origem não identificada"
                    else:
                        if pk not in pr_ok_cache:
                            try:
                                pr_ok_cache[pk] = acc.pr_approved_by_me(it["project"], it["prNumber"]) if isinstance(acc, github.GitHub) \
                                    else acc.pr_approved_by_me(it["prNumber"])
                            except Exception:  # noqa: BLE001
                                pr_ok_cache[pk] = False
                        if not pr_ok_cache[pk]:
                            it["waiting"] = f"sua aprovação na PR #{it['prNumber']}"
                if not it["waiting"] and time.time() - deploy_failures.get(it["key"], 0) > 600:
                    try:
                        acc.decide_deploy(it, True, "Aprovado pelo Codeck")
                        log_deploy("auto", "permit" if it["kind"] == "permission" else "deploy-approve", it,
                                   detail=it["ruleName"], rule_id=rule["id"])
                        notify("Permissão liberada pelo piloto" if it["kind"] == "permission" else "Deploy aprovado pelo piloto",
                               f"{it['org']} · {it['pipeline']}", f"{it.get('stage') or ''} {it.get('version') or ''}".strip(), "historico/", kind="auto")
                        continue
                    except Exception as e:  # noqa: BLE001
                        deploy_failures[it["key"]] = time.time()
                        errors[src_name] = f"Falha ao liberar {it['pipeline']}: {e}"
            nkey = it["key"]
            if nkey not in notified and wants("deploy.waiting") and not it.get("quiet") and (it["mine"] or (rule and rule["action"] == "notify")):
                notified.add(nkey)
                what = {"release": "Deploy aguardando aprovação", "approval": "Pipeline aguardando aprovação",
                        "permission": "Pipeline pedindo permissão"}[it["kind"]]
                notify(what, f"{it['org']} · {it['pipeline']}",
                       ", ".join(x["name"] for x in it["resources"]) or f"{it.get('stage') or ''} · {it.get('branch') or ''}",
                       f"fila/{it['key']}", kind="deploy.waiting")
            all_items.append(it)
        all_rel.extend(rels)
    live = {d["key"] for d in all_items}
    notified = {n for n in notified if not _is_deploy_key(n) or n in live or _key_source(n) in failed}
    save_json(NOTIFIED_FILE, sorted(notified))
    all_items.sort(key=lambda d: d.get("created") or "", reverse=True)
    all_rel.sort(key=lambda r: r.get("created") or "", reverse=True)
    with lock:
        state.update(deploys=all_items, releases=all_rel, deployErrors=errors, lastDeployPoll=now_iso())


def _is_deploy_key(n):
    return ("|rel:" in n or "|appr:" in n or "|perm:" in n) or (n.startswith("gh:") and ":env" in n)


def _key_source(n):
    return "gh:*" if n.startswith("gh:") else n.split("|", 1)[0]


# ---------------------------------------------------------------- builds e Actions
def poll_builds():
    rules_cfg = get_rules()
    settings = rules_cfg["settings"]
    protected = protected_set(rules_cfg)
    notified = set(load_json(NOTIFIED_FILE, []))
    all_b, errors, failed = [], {}, set()
    watch = watched_repos()
    for src_name, acc in _sources():
        try:
            _check_throttle(acc)
            if isinstance(acc, github.GitHub):
                acc.identity()
                builds, errs = acc.fetch_runs(watch)
                for repo, msg in list(errs.items())[:3]:
                    errors[f"{src_name} · {repo}"] = msg
            else:
                builds = acc.fetch_builds()
            builds = tracking.apply(builds, "builds")
            _net["ok"] = True
        except Exception as e:  # noqa: BLE001
            _fail(errors, src_name, e)
            failed.add(src_name)
            with lock:
                prov = "github" if isinstance(acc, github.GitHub) else "azure"
                all_b.extend(b for b in state["builds"] if b.get("provider", "azure") == prov
                             and (b.get("account") == acc.login if prov == "github" else b["org"] == src_name))
            continue
        _live_phases(acc, builds)
        me_id = (acc.me or {}).get("id")
        recent = now() - timedelta(hours=3)
        for b in builds:
            if b["result"] != "failed" or not b["finished"] or parse_dt(b["finished"]) < recent:
                continue
            if b["branch"].lower() not in protected and b["requestedForId"] != me_id:
                continue
            nkey = f"build:{b['key']}"
            if nkey not in notified:
                notified.add(nkey)
                if wants("build.failed") and state["builds"] and not b.get("quiet"):  # 1º ciclo só marca: não despeja o passado
                    notify("Build falhou", f"{b['org']} · {b['pipeline']} · {b['branch']}", b["message"] or b["number"], f"builds/{b['key']}", kind="build.failed")
        all_b.extend(builds)
    # um run aparece uma vez mesmo que duas contas enxerguem o mesmo repositório
    seen, unique = set(), []
    for b in all_b:
        if b["key"] not in seen:
            seen.add(b["key"])
            unique.append(b)
    live = {f"build:{b['key']}" for b in unique}
    notified = {n for n in notified if not n.startswith("build:") or n in live} | \
               {n for n in notified if "|build:" in n and n.split("|")[0] in failed}
    save_json(NOTIFIED_FILE, sorted(notified))
    unique.sort(key=lambda b: b.get("queued") or "", reverse=True)
    with lock:
        state.update(builds=unique, buildErrors=errors, lastBuildPoll=now_iso())


_phases = {}   # key do build -> último "o que está fazendo" lido (fica se uma leitura falhar)


def _live_phases(acc, builds):
    """Builds em andamento ganham `phase`: o status do Azure/GitHub continua "em andamento" enquanto uma etapa já
    falhou, espera aprovação ou espera agente — a tela mostra o que acontece de verdade."""
    from concurrent.futures import ThreadPoolExecutor
    running = [b for b in builds if b["status"] != "completed"][:15]

    def read(b):
        try:
            if isinstance(acc, github.GitHub):
                return b["key"], acc.run_phase(b["project"], b["id"])
            return b["key"], acc.build_phase(b["project"], b["id"])
        except Exception:  # noqa: BLE001 — sem a timeline, fica o que já se sabia
            return b["key"], _phases.get(b["key"])
    if running:
        with ThreadPoolExecutor(max_workers=6) as ex:
            got = dict(ex.map(read, running))
        _phases.update({k: v for k, v in got.items() if v})
    for b in running:
        if _phases.get(b["key"]):
            b["phase"] = _phases[b["key"]]
    done = {b["key"] for b in builds if b["status"] == "completed"}
    for k in [k for k in _phases if k in done]:
        _phases.pop(k, None)


# ---------------------------------------------------------------- issues e itens de trabalho
def poll_issues():
    out, errors = [], {}
    for src_name, acc in _sources():
        try:
            _check_throttle(acc)
            got = acc.fetch_issues() if isinstance(acc, github.GitHub) else acc.fetch_work_items()
            for i in got:
                i.setdefault("account", acc.login if isinstance(acc, github.GitHub) else None)
            out.extend(tracking.apply(got, "issues"))
            _net["ok"] = True
        except Exception as e:  # noqa: BLE001 — sem o escopo de work items/issues, só não aparece
            _fail(errors, src_name, e, str(e)[:240])
            with lock:
                out.extend(i for i in state["issues"] if (i["org"] == src_name) or (src_name.startswith("gh:") and i.get("provider") == "github"))
    out.sort(key=lambda i: i.get("updated") or "", reverse=True)
    with lock:
        state.update(issues=out, issueErrors=errors, lastIssuePoll=now_iso())


_browse = {}   # (escopo, estado) → (quando, resultado): a tela troca de filtro sem refazer todas as consultas


def browse_issues(scope="all", state="open", fresh=False):
    """Issues e work items sob demanda, para a tela (além dos meus abertos, que a leitura de fundo mantém): todos os
    dos projetos/repositórios ou um escopo meu, abertos, fechados ou ambos."""
    import time
    if scope not in ("all", "mine", "assigned", "created", "mentioned") or state not in ("open", "closed", "all"):
        raise ValueError("Filtro inválido")
    k = (scope, state)
    hit = _browse.get(k)
    if hit and not fresh and time.time() - hit[0] < 120:
        return hit[1]
    scopes = ("all",) if scope == "all" else ("assigned", "created", "mentioned") if scope == "mine" else (scope,)
    out, errors = [], {}
    for src_name, acc in _sources():
        try:
            got = acc.fetch_issues(scopes, state, 1000) if isinstance(acc, github.GitHub) else acc.fetch_work_items(scopes, state, 5000 if scope == "all" else 1000)
            for i in got:
                i.setdefault("account", acc.login if isinstance(acc, github.GitHub) else None)
            out.extend(tracking.apply(got, "issues"))
        except Exception as e:  # noqa: BLE001
            errors[src_name] = str(e)[:240]
    out.sort(key=lambda i: i.get("updated") or "", reverse=True)
    r = {"issues": out, "errors": errors, "at": now_iso()}
    _browse[k] = (time.time(), r)
    return r


POLL_STEP = {"poll_prs": "pull requests", "poll_builds": "builds", "poll_deploys": "deploys", "poll_issues": "issues e tarefas"}


# fonte → (função, atraso inicial em s). O intervalo de cada uma vem de `intervals()` (Configurações).
SOURCES = {"prs": (poll_prs, 0), "builds": (poll_builds, 2), "deploys": (poll_deploys, 4), "issues": (poll_issues, 6)}
_wakes = {k: threading.Event() for k in SOURCES}
_offline = {}
# laço de cada fonte: geração (o vigia troca um laço travado por um novo; o antigo, se um dia voltar, só sai) e
# desde quando (monotônico: não conta o tempo dormindo) a leitura atual está rodando
_gen = {k: 0 for k in SOURCES}
_busy_since = {}
_streak = {k: 0 for k in SOURCES}   # leituras seguidas em que TODAS as contas falharam (sem ser rede): espera dobra
STUCK = 240   # uma leitura leva segundos; 4 min acordado lendo = presa (DNS/socket morto depois de suspender)
BACKOFF_MAX = 900
IDLE_AFTER = 120   # janela sem foco/escondida há 2 min (ou tela bloqueada/protetor): modo econômico
# a tela avisa foco e visibilidade (/api/presence); sem aviso nenhum (tela antiga), conta como em uso
presence = {"focused": True, "visible": True, "since": time.monotonic()}


def refresh(source=None):
    """Lê agora: uma fonte (prs, builds, deploys, issues) ou todas."""
    for k in ([source] if source in _wakes else _wakes):
        _wakes[k].set()


def idle():
    """Ninguém olhando: janela sem foco/escondida há mais de 2 min, ou tela bloqueada/protetor de tela."""
    if power.away():
        return True
    return not (presence["focused"] and presence["visible"]) and time.monotonic() - presence["since"] > IDLE_AFTER


def set_presence(focused, visible):
    """A tela mudou de foco/visibilidade. Voltando depois de um tempo fora, relê na hora as fontes que passaram do
    intervalo normal (o que mudou enquanto a janela estava escondida aparece logo, como num app em tempo real)."""
    was_idle = idle()
    focused, visible = bool(focused), bool(visible)
    if (focused, visible) != (presence["focused"], presence["visible"]):
        presence.update(focused=focused, visible=visible, since=time.monotonic())
    if was_idle and focused and visible:
        every = intervals()
        with lock:
            upd = dict(state["updated"])
        for k in SOURCES:
            last = parse_dt(upd.get(k))
            if not last or (now() - last).total_seconds() > every[k]:
                refresh(k)
    return {"idle": idle()}


def _fast_builds():
    """Algum build andando de verdade (não parado esperando aprovação/agente) que começou há menos de 3 h?"""
    recent = now() - timedelta(hours=3)
    with lock:
        return any(b.get("status") == "inProgress" and (b.get("phase") or {}).get("state") in (None, "running", "failing")
                   and (parse_dt(b.get("started") or b.get("queued")) or recent) > recent for b in state["builds"])


def _deploy_in_flight():
    """Algum run parado esperando environment ou um deploy acompanhado em cascata: os deploys releem mais rápido."""
    with lock:
        waiting = any(b.get("waiting") for b in state["builds"])
    return waiting or cascade.active_stage("deploy")


def next_wait(key):
    """Quanto a fonte espera até a próxima leitura e por quê (a tela mostra em Configurações)."""
    base = intervals()[key]
    hi = max(POLL_KINDS[key][2], base)
    wait, why = base, "intervalo"
    adaptive = ctx.config.get("pollAdaptive", True)
    if adaptive and idle():
        wait, why = min(base * 3, hi), "sem ninguém olhando"
    if key == "builds" and _fast_builds() and wait > 20:
        wait, why = 20, "build rodando"
    if key == "deploys" and adaptive and _deploy_in_flight() and wait > 30:
        wait, why = 30, "deploy em andamento"
    if key in ("prs", "builds") and _rate_low():
        wait, why = min(wait * 2, hi * 2), "cota do GitHub baixa"
    if _streak[key]:
        wait, why = min(wait * 2 ** _streak[key], BACKOFF_MAX), f"falhou {_streak[key]}× seguidas"
    return int(wait), why


def _source_loop(key, gen=0):
    fn, delay = SOURCES[key]
    time.sleep(delay if gen == 0 else 0)   # não sai tudo junto na abertura
    while _gen[key] == gen:
        if power.paused():   # tela bloqueada/protetor/suspenso com "Pausar a automação": nada de ler nem aprovar
            power.wait_resume(60)
            _wakes[key].clear()
            continue
        _net.update(down=False, ok=False)
        with lock:
            state["loading"][key] = now_iso()
            state["polling"] = POLL_STEP[fn.__name__]   # compatível: "lendo <etapa>…" na barra lateral
        _busy_since[key] = time.monotonic()
        crashed = False
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            crashed = True
            with lock:
                state["errors"]["_geral"] = f"{fn.__name__}: {e}"
        if _gen[key] != gen:
            return   # o vigia já pôs outro laço no lugar deste (que ficou preso)
        _busy_since.pop(key, None)
        offline = _net["down"] and not _net["ok"]
        # nenhuma conta respondeu e não foi a rede (token recusado, limite, 5xx): espera dobra a cada vez, até 15 min
        _streak[key] = min(_streak[key] + 1, 6) if (crashed or (not _net["ok"] and not offline and _sources())) else 0
        with lock:
            state["loading"][key] = None
            state["updated"][key] = now_iso()
            busy = [k for k, v in state["loading"].items() if v]
            state["polling"] = POLL_STEP[SOURCES[busy[0]][0].__name__] if busy else None
            _offline[key] = offline
            # "offline" guarda DESDE QUANDO está sem rede; volta a None na 1ª leitura que funcionar
            state["offline"] = (state.get("offline") or now_iso()) if all(_offline.get(k) for k in SOURCES) else None
        # sem rede: tenta de novo a cada 10 s para reconectar logo; com rede, no intervalo da fonte (mais curto com build
        # rodando ou deploy em andamento, mais longo sem ninguém olhando, com a cota baixa ou falhando seguido)
        wait, why = (10, "sem conexão") if offline else next_wait(key)
        with lock:
            state.setdefault("schedule", {})[key] = {"every": wait, "why": why,
                                                     "next": (now() + timedelta(seconds=wait)).isoformat(timespec="seconds")}
        _wakes[key].wait(wait)
        _wakes[key].clear()


def _watchdog():
    """Uma leitura presa (requisição que nunca volta depois de o Mac suspender: DNS sem resposta, socket morto) parava
    a fonte inteira — e com ela as regras automáticas. Passou do limite: um laço novo assume e relê na hora."""
    while True:
        time.sleep(15)
        for key, since in list(_busy_since.items()):
            if time.monotonic() - since < STUCK:
                continue
            _busy_since.pop(key, None)
            _gen[key] += 1
            print(f"[engine] leitura de {key} presa há {int(time.monotonic() - since)} s — recomeçando", flush=True)
            with lock:
                state["loading"][key] = None
            threading.Thread(target=_source_loop, args=(key, _gen[key]), daemon=True, name=f"poll-{key}-{_gen[key]}").start()


def _wake_relay():
    """O `wake` global (Atualizar, conta nova, regra mudou) acorda todas as fontes."""
    while True:
        wake.wait()
        wake.clear()
        refresh()


# ---------------------------------------------------------------- GitHub: notificações como gatilho
NOTIF_SOURCES = {"PullRequest": ("prs",), "Issue": ("issues",), "CheckSuite": ("builds",), "WorkflowRun": ("builds",),
                 "Release": ("deploys",)}
notif_state = {}   # id da conta -> {"since", "every", "at", "off"}: última notificação vista, X-Poll-Interval, desligado por quê


def _gh_notifications_loop():
    """Quase tempo real sem servidor público: o endpoint de notificações do GitHub responde 304 (não gasta cota)
    enquanto nada muda e diz de quanto em quanto tempo pode ser consultado (X-Poll-Interval, normalmente 60 s).
    Mudou algo (revisão pedida, PR atualizada, CI, release): relê só a fonte certa na hora, sem esperar o intervalo
    dela — dá para deixar as PRs (GraphQL, sem ETag) num intervalo maior sem demorar a ver o que chega."""
    time.sleep(20)
    while True:
        for acc in list(ctx.gh.values()):
            st = notif_state.setdefault(acc.id, {"since": None, "every": 60, "at": 0.0, "off": None})
            if st["off"] or power.paused() or throttled(acc) or time.monotonic() - st["at"] < st["every"]:
                continue
            st["at"] = time.monotonic()
            h = {}
            try:
                items = acc.req("GET", "notifications?all=false&per_page=50", etag=True, headers_out=h) or []
            except Exception as e:  # noqa: BLE001
                if http_code(e) in (401, 403, 404, 422):   # token fino sem "notifications": segue só com os intervalos
                    st["off"] = github.github_message(e)
                continue
            if not h:
                continue   # 304: nada novo desde a última vez
            try:
                st["every"] = max(int(h.get("x-poll-interval") or 60), 30)
            except ValueError:
                st["every"] = 60
            newest = max((n.get("updated_at") or "" for n in items), default="")
            if st["since"] is None:   # 1ª leitura só marca
                st["since"] = newest or now_iso()
                continue
            fresh = [n for n in items if (n.get("updated_at") or "") > st["since"]]
            st["since"] = max(st["since"], newest)
            for k in {k for n in fresh for k in NOTIF_SOURCES.get((n.get("subject") or {}).get("type"), ())}:
                refresh(k)
            if fresh:
                cascade.poke()
        time.sleep(10)


def poll_loop():
    for k in SOURCES:
        threading.Thread(target=_source_loop, args=(k,), daemon=True, name=f"poll-{k}").start()
    threading.Thread(target=_watchdog, daemon=True, name="poll-watchdog").start()
    threading.Thread(target=power.clock_loop, daemon=True, name="power-clock").start()
    threading.Thread(target=cascade.loop, daemon=True, name="cascade").start()
    threading.Thread(target=_gh_notifications_loop, daemon=True, name="gh-notifications").start()
    threading.Thread(target=watch.loop, daemon=True, name="live-watch").start()   # tempo real (local), watch.py
    _wake_relay()


def start():
    orgs, gh, cfg = load_accounts()
    ctx.orgs, ctx.gh, ctx.config = orgs, gh, cfg
    catalogs.cleanup_auto()
    catalogs.warm_async()
    import threading
    threading.Thread(target=catalogs.discover, kwargs={"force": True}, daemon=True).start()   # clones novos nas pastas base
    if os.environ.get("CODECK_NO_POLL") != "1":
        import threading
        threading.Thread(target=poll_loop, daemon=True).start()
        threading.Thread(target=power.kanban_loop, daemon=True, name="kanban-auto").start()
