"""Regras de automação (PRs e releases/permissões): formato, casamento, simulação e estatística."""
import fnmatch
import uuid
from datetime import timedelta

from .core import RULES_FILE, load_json, lock, now, parse_dt, read_activity, save_json, state

ACTIONS = ("approve", "archive", "notify", "review")
DEPLOY_KINDS = ("release", "permission")
DEPLOY_ACTIONS = ("approve", "notify")
DEFAULT_SETTINGS = {
    "paused": False,          # pausa só as ações automáticas; a tela continua funcionando
    "notifyPending": True,    # PR nova esperando o meu voto
    "notifyAuto": True,       # quando o piloto aprova sozinho
    "resurfaceOnPush": True,  # PR arquivada volta para a fila se receber push novo
    "notifyDeploys": True,    # release/permissão/deploy esperando você
    "notifyMyPrs": True,      # minha PR com conflito, build vermelho ou voto de recusa/espera
    "notifyBuildFailures": True,  # build falhou em branch protegida ou disparado por mim
    "cascadeOnApprove": True,     # aprovou uma PR (você ou uma regra): acompanha até o deploy (merge → build → deploy)
    "notifyCascade": True,        # cada passo do acompanhamento em cascata (merge, build, deploy, falhas)
}
# Regra: listas vazias = "qualquer". targets vazio = qualquer branch NÃO protegida.
DEFAULT_RULES = {"protectedTargets": ["master", "main"], "settings": DEFAULT_SETTINGS, "rules": [], "deployRules": []}


def _as_list(v):
    if v is None:
        return []
    items = v if isinstance(v, list) else [v]
    return [str(i).strip() for i in items if str(i).strip() and str(i).strip() != "*"]


def normalize_rule(r):
    """Aceita o formato antigo (org/creator/target/repo/title como string) e o novo (listas)."""
    return {
        "id": r.get("id") or uuid.uuid4().hex[:8],
        "name": (r.get("name") or "").strip(),
        "enabled": bool(r.get("enabled", True)),
        "action": r.get("action") if r.get("action") in ACTIONS else "approve",
        "orgs": _as_list(r.get("orgs", r.get("org"))),
        "creators": _as_list(r.get("creators", r.get("creator"))),
        "targets": _as_list(r.get("targets", r.get("target"))),
        "repos": _as_list(r.get("repos", r.get("repo"))),
        "titleContains": (r.get("titleContains", r.get("title")) or "").strip(),
        "requireBuild": bool(r.get("requireBuild")),
        # "review" (Revisar com IA): a conta que revisa, se aprova sozinha quando está tudo certo, o que olhar com mais
        # atenção e se revisa também as minhas PRs (nelas só comenta)
        "aiAccount": (r.get("aiAccount") or None),
        "aiApprove": bool(r.get("aiApprove", True)),
        "aiFocus": (r.get("aiFocus") or "").strip()[:2000],
        "aiMine": bool(r.get("aiMine")),
    }


def normalize_deploy_rule(r):
    kind = r.get("kind") if r.get("kind") in DEPLOY_KINDS else "release"
    return {
        "id": r.get("id") or uuid.uuid4().hex[:8],
        "name": (r.get("name") or "").strip(),
        "enabled": bool(r.get("enabled", True)),
        "kind": kind,
        "action": r.get("action") if r.get("action") in DEPLOY_ACTIONS else "approve",
        "orgs": _as_list(r.get("orgs")),
        "pipelines": _as_list(r.get("pipelines")),
        "stages": _as_list(r.get("stages")) if kind == "release" else [],
        "branches": _as_list(r.get("branches")),
        "resources": _as_list(r.get("resources")) if kind == "permission" else [],
        "requirePrApproved": bool(r.get("requirePrApproved")) and kind == "release",
    }


def clean_rules(body):
    st = {**DEFAULT_SETTINGS, **{k: bool(v) for k, v in (body.get("settings") or {}).items() if k in DEFAULT_SETTINGS}}
    return {
        "protectedTargets": _as_list(body.get("protectedTargets", ["master", "main"])),
        "settings": st,
        "rules": [normalize_rule(r) for r in body.get("rules", [])],
        "deployRules": [normalize_deploy_rule(r) for r in body.get("deployRules", [])],
    }


def get_rules():
    raw = load_json(RULES_FILE, DEFAULT_RULES)
    r = clean_rules(raw)
    if r != raw:
        save_json(RULES_FILE, r)  # migra o formato antigo e fixa os ids
    return r


def glob_match(pattern, value):
    return fnmatch.fnmatchcase(value.lower(), (pattern or "*").strip().lower() or "*")


def target_matches(patterns, target, protected):
    target = target.lower()
    if not patterns:
        return target not in protected
    for pattern in patterns:
        pattern = pattern.lower()
        # Curinga nunca alcança branch protegida; para agir na master, a regra precisa dizer "master".
        if any(ch in pattern for ch in "*?[") and target in protected:
            continue
        if glob_match(pattern, target):
            return True
    return False


def rule_matches(r, pr, protected):
    if r["orgs"] and pr["org"] not in r["orgs"]:
        return False
    if r["creators"]:
        name, unique = pr["creatorName"].lower(), (pr.get("creatorUnique") or "").lower()
        if not any(c.lower() == unique or c.lower() in name for c in r["creators"]):
            return False
    if not target_matches(r["targets"], pr["target"], protected):
        return False
    if r["repos"] and not any(glob_match(x, pr["repo"]) for x in r["repos"]):
        return False
    if r["titleContains"] and r["titleContains"].lower() not in pr["title"].lower():
        return False
    return True


def protected_set(rules_cfg):
    return {t.strip().lower() for t in rules_cfg.get("protectedTargets", [])}


def matching_rule(pr, rules_cfg):
    protected = protected_set(rules_cfg)
    for idx, r in enumerate(rules_cfg.get("rules", [])):
        if r.get("enabled", True) and rule_matches(r, pr, protected):
            return idx
    return None


def text_match(patterns, value):
    """Sem curinga = parte do texto ("financeiro" pega "minhaempresa-financeiro-api - deploy"); com curinga = glob."""
    value = (value or "").lower()
    for pt in patterns:
        pt = pt.lower()
        if (any(ch in pt for ch in "*?[") and fnmatch.fnmatchcase(value, pt)) or (not any(ch in pt for ch in "*?[") and pt in value):
            return True
    return not patterns


def deploy_rule_matches(r, item):
    kind = "release" if item["kind"] in ("release", "approval") else "permission"
    if r["kind"] != kind or (r["orgs"] and item["org"] not in r["orgs"]):
        return False
    if not text_match(r["pipelines"], item["pipeline"]) or not text_match(r["stages"], item.get("stage")):
        return False
    if r["branches"] and not any(glob_match(b, item.get("branch") or "") for b in r["branches"]):
        return False
    # Permissão: a regra só libera se TODOS os recursos pedidos estiverem cobertos.
    if r["resources"] and not all(text_match(r["resources"], x["name"]) for x in item["resources"]):
        return False
    return True


def matching_deploy_rule(item, rules_cfg):
    return next((r for r in rules_cfg.get("deployRules", []) if r["enabled"] and deploy_rule_matches(r, item)), None)


def rule_label(rules_cfg, idx):
    r = rules_cfg["rules"][idx]
    return r["name"] or f"regra {idx + 1}"


def simulate_rule(body):
    """Testa UMA regra (em edição) contra as PRs abertas e as concluídas nos últimos 30 dias."""
    saved = get_rules()
    rule = normalize_rule(body.get("rule") or {})
    rule["enabled"] = True
    protected = protected_set({"protectedTargets": body.get("protectedTargets", saved["protectedTargets"])})
    # Precedência: a regra em edição entra na posição dela; as outras salvas continuam valendo.
    others = [r for r in saved["rules"] if r["id"] != rule["id"]]
    pos = next((i for i, r in enumerate(saved["rules"]) if r["id"] == rule["id"]), len(others))
    ordered = others[:pos] + [rule] + others[pos:]

    def describe(p):
        return {k: p.get(k) for k in ("key", "provider", "org", "prId", "title", "creatorName", "target", "repo", "url")}

    with lock:
        open_prs = list(state["prs"])
    now_list = []
    for p in open_prs:
        if not rule_matches(rule, p, protected):
            continue
        first = next(r for r in ordered if r["enabled"] and rule_matches(r, p, protected))
        now_list.append({**describe(p), "myVote": p.get("myVote"),
                         "shadowedBy": None if first["id"] == rule["id"] else (first["name"] or f"regra {ordered.index(first) + 1}")})
    from .analytics import completed_prs
    hist, errors = completed_prs(30)
    hist_matches = [p for p in hist if rule_matches(rule, p, protected)]
    by_target = {}
    for p in hist_matches:
        by_target[p["target"]] = by_target.get(p["target"], 0) + 1
    return {
        "open": now_list,
        "openTotal": len(open_prs),
        "history": {"count": len(hist_matches), "total": len(hist), "byTarget": by_target,
                    "sample": [describe(p) for p in sorted(hist_matches, key=lambda p: p["closed"] or "", reverse=True)[:6]]},
        "errors": errors,
    }


def simulate_deploy_rule(body):
    rule = normalize_deploy_rule(body.get("rule") or {})
    rule["enabled"] = True
    saved = [r for r in get_rules()["deployRules"] if r["enabled"]]
    pos = next((i for i, r in enumerate(saved) if r["id"] == rule["id"]), len(saved))
    ordered = [r for r in saved if r["id"] != rule["id"]]
    ordered = ordered[:pos] + [rule] + ordered[pos:]
    with lock:
        items, rels = list(state["deploys"]), list(state["releases"])
    now_list = []
    for it in items:
        if deploy_rule_matches(rule, it):
            first = next(r for r in ordered if deploy_rule_matches(r, it))
            now_list.append({k: it.get(k) for k in ("kind", "org", "title", "pipeline", "stage", "branch", "version", "prNumber", "resources")}
                            | {"shadowedBy": None if first["id"] == rule["id"] else (first["name"] or "outra regra")})
    hist = []
    if rule["kind"] == "release":
        # Cada estágio de cada release recente vira um "teria agido" se casar com a regra.
        for r in rels:
            for e in r["envs"]:
                fake = {"kind": "release", "org": r["org"], "pipeline": r["pipeline"], "stage": e["name"], "branch": r["branch"], "resources": []}
                if e["status"] != "notStarted" and deploy_rule_matches(rule, fake):
                    hist.append({"org": r["org"], "pipeline": r["pipeline"], "stage": e["name"], "branch": r["branch"],
                                 "version": r["version"], "created": r["created"], "status": e["status"]})
    return {"open": now_list, "openTotal": len(items), "history": hist[:50], "historyCount": len(hist),
            "historyTotal": sum(len(r["envs"]) for r in rels)}


def rule_stats():
    since = now() - timedelta(days=30)
    stats = {}
    for a in read_activity():
        rid = a.get("ruleId")
        if not rid or a["by"] != "auto" or parse_dt(a["ts"]) < since:
            continue
        st = stats.setdefault(rid, {"count": 0, "last": None})
        st["count"] += 1
        st["last"] = max(st["last"] or "", a["ts"])
    return stats


