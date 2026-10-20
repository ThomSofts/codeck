"""Tela bloqueada, protetor de tela e computador ocioso: continuar trabalhando ou pausar a automação.

Configurações → Geral → "Com a tela bloqueada…" (`power.mode` nas preferências da tela):
  keep   continuar trabalhando: o app nativo segura o computador acordado (o monitor pode apagar) e não deixa o
         sistema pôr o app para dormir (App Nap no Mac, tela em segundo plano no Windows)
  busy   o mesmo, só enquanto houver algo rodando: agente trabalhando, projeto executando ou regra de automação ativa
  pause  deixa o computador dormir; com a tela bloqueada, o protetor de tela ou o sistema suspenso, as leituras, as
         regras, o quadro e a leitura de limites param — e voltam ao desbloquear/acordar

O app nativo lê o modo e o `hold` em /api/summary (a cada 15 s) e avisa os eventos em /api/power/event. Em qualquer
modo, ao acordar ou desbloquear, tudo é relido na hora (o que aconteceu enquanto dormia aparece logo).

Acordar não depende só do aviso do app nativo: `clock_loop` percebe sozinho que o computador dormiu (o relógio de
parede andou e o monotônico não — no macOS ele para durante a suspensão). Sem isso, depois de abrir a tampa os
laços de leitura ainda esperavam o resto do intervalo (as esperas do Python contam só o tempo acordado) e um aviso
"sleep" que chegasse DEPOIS do "wake" (a requisição sai ao dormir e só é entregue ao acordar) deixava a automação
pausada para sempre no modo pausar.
"""
import threading
import time

from .core import ctx, now_iso, wake

MODES = ("keep", "busy", "pause")
AWAY_ON = {"sleep": "sleep", "lock": "lock", "screensaver-start": "screensaver", "display-sleep": "display"}
AWAY_OFF = {"wake": "sleep", "unlock": "lock", "screensaver-stop": "screensaver", "display-wake": "display"}
EVENTS = set(AWAY_ON) | set(AWAY_OFF)

_lock = threading.Lock()
_away = set()               # por que o usuário está fora: sleep, lock, screensaver, display
_last = {"event": None, "at": None, "resumedAt": None}
_resumed = threading.Event()
_seen = {"at": 0.0}         # hora (do app nativo) do último evento aplicado: um atrasado não desfaz um mais novo
SLEPT = 30                  # o relógio de parede passou o monotônico em mais que isso: o computador dormiu


def mode():
    m = ((ctx.config or {}).get("ui") or {}).get("power.mode")
    return m if m in MODES else "keep"


def paused():
    """A automação está parada agora (modo pausar e o usuário fora)?"""
    with _lock:
        return mode() == "pause" and bool(_away)


def wait_resume(timeout):
    """Dorme até voltar (ou o tempo acabar). Para os laços que respeitam a pausa."""
    _resumed.wait(timeout)


def _busy():
    from . import agents, rules, terminals
    try:
        if any((s or {}).get("status") in ("working", "compacting", "starting") for s in agents.all_sessions().values()):
            return True
        if any(t["alive"] and t["kind"] == "run" for t in terminals.list_all()):
            return True
        r = rules.get_rules()
        return bool((ctx.orgs or ctx.gh) and not (r.get("settings") or {}).get("paused") and (r.get("rules") or r.get("deployRules")))
    except Exception:  # noqa: BLE001 — na dúvida, segura acordado
        return True


def hold():
    """O app nativo deve impedir a suspensão por ociosidade (e o App Nap/estrangulamento da tela)?"""
    m = mode()
    return m == "keep" or (m == "busy" and _busy())


def event(name, at=None):
    """`at`: quando o evento aconteceu (epoch, do app nativo). Fora de ordem (o "sleep" entregue depois do "wake"), ignora."""
    if name not in EVENTS:
        raise ValueError("Evento inválido")
    try:
        at = float(at) if at is not None else None
    except (TypeError, ValueError):
        at = None
    with _lock:
        stale = at is not None and at < _seen["at"]
        if not stale and at is not None:
            _seen["at"] = at
    if stale:
        print(f"[power] evento atrasado ignorado ({name})", flush=True)
        return summary()
    with _lock:
        was = mode() == "pause" and bool(_away)
        if name in AWAY_ON:
            _away.add(AWAY_ON[name])
        else:
            _away.discard(AWAY_OFF[name])
            if name == "wake":
                _away.discard("display")      # acordou: o monitor voltou junto (a tela bloqueada segue até o desbloqueio)
            if name == "unlock":
                _away.difference_update({"screensaver", "display"})   # desbloquear encerra o protetor (nem sempre chega o "didstop")
        now = mode() == "pause" and bool(_away)
        _last.update(event=name, at=now_iso())
        back = name in AWAY_OFF and not _away
        if back:
            _last["resumedAt"] = now_iso()
    if was and not now:
        _resumed.set()
        _resumed.clear()
    if back or (name == "wake" and not now):
        wake.set()   # acordou/desbloqueou: relê tudo agora (com qualquer modo, se não estiver pausado)
    if was != now:
        print(f"[power] automação {'pausada' if now else 'retomada'} ({name})", flush=True)
    return summary()


def summary():
    with _lock:
        away = sorted(_away)
    m = mode()
    return {"mode": m, "hold": hold(), "paused": m == "pause" and bool(away), "away": away, **_last}


def woke(slept):
    """O computador dormiu `slept` segundos e acordou (percebido pelo relógio, sem depender do app nativo)."""
    with _lock:
        was = mode() == "pause" and bool(_away)
        _away.difference_update({"sleep", "display"})   # a tela bloqueada segue até o desbloqueio
        now = mode() == "pause" and bool(_away)
        _last["resumedAt"] = now_iso()
        _seen["at"] = max(_seen["at"], time.time() - 1)   # um "sleep" de antes da suspensão que chegue agora não vale mais
    if was and not now:
        _resumed.set()
        _resumed.clear()
    wake.set()
    print(f"[power] o computador dormiu ~{int(slept // 60)} min — relendo tudo agora", flush=True)


def clock_loop(tick=5):
    """Compara o relógio de parede com o monotônico a cada `tick` s: um salto grande = o computador dormiu."""
    wall, mono = time.time(), time.monotonic()
    while True:
        time.sleep(tick)
        w, m = time.time(), time.monotonic()
        gap = (w - wall) - (m - mono)
        wall, mono = w, m
        if gap > SLEPT:
            try:
                woke(gap)
            except Exception as e:  # noqa: BLE001
                print(f"[power] falha ao retomar depois de dormir: {e}", flush=True)


def kanban_loop():
    """O movimento automático do quadro rodava só quando a tela relia o quadro — e a tela só relê visível: com o
    protetor de tela ou a janela escondida, os cartões paravam. Aqui ele roda sozinho."""
    from . import kanban
    time.sleep(8)
    while True:
        try:
            if not paused():
                kanban.automate()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
