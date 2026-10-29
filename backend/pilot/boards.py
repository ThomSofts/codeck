"""Sprints e projetos: o quadro de cada time do Azure Boards (a sprint em colunas) e de cada Project do GitHub.

Quadro = `az|<org>|<projeto>|<time>` ou `gh|<login>|<id do Project>`. Os cartões têm o formato das issues/work items
(Issues e tarefas), então a gaveta de detalhes, o "Pedir à IA" e o quadro local valem igual para eles.
"""
from concurrent.futures import ThreadPoolExecutor

from . import github
from .core import ctx


def _gh(login):
    acc = next((a for a in ctx.gh.values() if a.login == login), None)
    if not acc:
        raise LookupError(f"Conta do GitHub @{login} não está mais conectada")
    return acc


def _parse(bid):
    parts = (bid or "").split("|")
    if parts[0] == "az" and len(parts) == 4:
        org = ctx.orgs.get(parts[1])
        if not org:
            raise LookupError(f"Organização {parts[1]} não está mais configurada")
        return "azure", org, parts[2], parts[3]
    if parts[0] == "gh" and len(parts) == 3:
        return "github", _gh(parts[1]), parts[2], None
    raise ValueError("Quadro inválido")


def list_boards():
    """Os quadros que dá para abrir. Uma conta fora do ar (ou sem permissão) só some da lista, com o motivo."""
    jobs = [(name, org.boards) for name, org in ctx.orgs.items()] + [(f"@{a.login}", a.projects_v2) for a in ctx.gh.values()]
    out, errors = [], {}

    def run(job):
        name, fn = job
        try:
            return name, fn(), None
        except Exception as e:  # noqa: BLE001
            return name, [], github.github_message(e) if name.startswith("@") else str(e)[:200]
    with ThreadPoolExecutor(6) as ex:
        for name, bs, err in ex.map(run, jobs):
            out += bs
            if err:
                errors[name] = err
    return {"boards": out, "errors": errors}


def board(bid, sprint=None):
    prov, acc, a, b = _parse(bid)
    if prov == "azure":
        return {"id": bid, "provider": "azure", **acc.sprint_board(a, b, sprint)}
    return {"id": bid, "provider": "github", **acc.project_board(a, sprint)}


def move(bid, item, column):
    """Muda o cartão de coluna: no Azure, o estado (o 1º do tipo na categoria da coluna); no GitHub, o campo Status."""
    prov, acc, a, _b = _parse(bid)
    if prov == "azure":
        state = acc.move_to_category(item.get("repo") or a, int(item["number"]), item.get("type") or "Task", column)
        return {"state": state}
    if not item.get("statusField"):
        raise ValueError("Este Project não tem campo de status para mover os cartões")
    acc.project_move(a, item["itemId"], item["statusField"], column or "")
    return {"ok": True}


def draft_to_issue(bid, item_id, repo):
    prov, acc, _a, _b = _parse(bid)
    if prov != "github":
        raise ValueError("Só rascunhos de Projects do GitHub viram issue")
    return acc.project_draft_to_issue(item_id, repo)
