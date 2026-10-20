<script lang="ts">
  // Console de depuração (como no VS Code / a janela Saída do Visual Studio): o que o programa e o depurador escrevem
  // (logs, exceções, logpoints) e, embaixo, avaliar expressões no quadro em foco (REPL).
  import { ChevronRight, Trash2, X } from "@lucide/svelte";
  import { tick } from "svelte";
  import { debug, type Session } from "../../lib/debug.svelte";

  let { repoId, taskId = null, onclose }: { repoId: string; taskId?: string | null; onclose: () => void } = $props();
  const all = $derived(debug.scopeSessions(repoId, taskId).filter(s => s.kind === "debug"));
  const roots = $derived(all.filter(s => !s.parent));
  let pick = $state<string | null>(null);
  // a sessão escolhida (ou a mais recente) e as filhas dela (js-debug: cada processo node é uma filha)
  const root = $derived(roots.find(s => s.id === pick) || [...roots].sort((a, b) => (a.status === "ended" ? 1 : 0) - (b.status === "ended" ? 1 : 0) || b.started - a.started)[0] || null);
  const family = $derived(root ? all.filter(s => s.group === root.group) : []);
  let q = $state("");
  const lines = $derived(family.flatMap(s => (debug.output[s.id] || []).map(l => ({ ...l, sid: s.id }))).filter(l => !q || l.text.toLowerCase().includes(q.toLowerCase())));
  let box: HTMLDivElement | undefined = $state();
  let stick = true;
  $effect(() => { void lines.length; if (stick) tick().then(() => box && (box.scrollTop = box.scrollHeight)); });
  const onScroll = () => { if (box) stick = box.scrollHeight - box.scrollTop - box.clientHeight < 30; };

  // avaliar: no quadro em foco; sem foco, na sessão da família que tem threads (a filha do js-debug)
  let expr = $state("");
  let hist: string[] = [];
  let hi = -1;
  const target = $derived(family.find(s => s.id === debug.focus.sid && s.status !== "ended") || family.find(s => s.status === "stopped")
    || family.find(s => s.status !== "ended" && s.threads.length) || null);
  async function run() {
    const t = expr.trim();
    if (!t || !target) return;
    hist = [t, ...hist.filter(x => x !== t)].slice(0, 50); hi = -1;
    expr = "";
    stick = true;
    try { await debug.evaluate(target.id, t, target.id === debug.focus.sid ? debug.focus.frameId : target.stopped?.top?.id ?? null, "repl"); } catch { /* o erro já vai para o console */ }
  }
  function key(e: KeyboardEvent) {
    if (e.key === "ArrowUp" && hist.length) { e.preventDefault(); hi = Math.min(hi + 1, hist.length - 1); expr = hist[hi]; }
    else if (e.key === "ArrowDown" && hi >= 0) { e.preventDefault(); hi--; expr = hi >= 0 ? hist[hi] : ""; }
  }
  const label = (s: Session) => `${s.name}${s.status === "ended" ? " (terminou)" : ""}`;
</script>

<div class="dc">
  <div class="hd">
    <b>Console de depuração</b>
    {#if roots.length > 1}
      <select class="ss" value={root?.id || ""} onchange={(e) => (pick = (e.target as HTMLSelectElement).value)}>
        {#each roots as s (s.id)}<option value={s.id}>{label(s)}</option>{/each}
      </select>
    {:else if root}<span class="tiny muted ell">{label(root)}</span>{/if}
    <input class="flt" bind:value={q} placeholder="Filtrar" />
    <span class="grow"></span>
    <button class="ib" title="Limpar" onclick={() => family.forEach(s => debug.clearOutput(s.id))}><Trash2 size={13} /></button>
    <button class="ib" title="Fechar o painel" onclick={onclose}><X size={14} /></button>
  </div>
  <div class="out" bind:this={box} onscroll={onScroll}>
    {#each lines as l (l.sid + ":" + l.seq)}<div class="ln {l.cat}">{l.text}</div>{/each}
    {#if !lines.length}<div class="none">{root ? "Sem saída ainda." : "Inicie a depuração (F5): logs, exceções e logpoints aparecem aqui."}</div>{/if}
  </div>
  <form class="repl" class:off={!target} onsubmit={(e) => { e.preventDefault(); run(); }}>
    <ChevronRight size={13} />
    <input bind:value={expr} onkeydown={key} spellcheck="false" disabled={!target}
      placeholder={target ? (target.status === "stopped" ? "Avaliar no quadro em foco (Enter)" : "Avaliar (Enter) — pause ou pare num breakpoint para ver as variáveis locais") : "Avaliar expressões durante a depuração"} />
  </form>
</div>

<style>
  .dc { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--surface); }
  .hd { display: flex; align-items: center; gap: 8px; height: 32px; padding: 0 8px 0 12px; border-bottom: 1px solid var(--line); flex: none; font-size: 12px; }
  .hd b { font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-2); flex: none; }
  .ss { height: 22px; max-width: 220px; border: 1px solid var(--line-2); border-radius: 6px; background: var(--surface-2); color: var(--text-2); font: 11.5px var(--font); }
  .flt { height: 22px; width: 150px; border: 1px solid var(--line-2); border-radius: 6px; background: var(--surface-2); color: var(--text); font: 11.5px var(--font); padding: 0 7px; }
  .grow { flex: 1; }
  .ib { display: grid; place-items: center; width: 22px; height: 22px; border: 0; border-radius: 5px; background: none; color: var(--muted); cursor: pointer; }
  .ib:hover { background: var(--surface-3); color: var(--text); }
  .out { flex: 1; min-height: 0; overflow: auto; padding: 4px 12px; font: 12px/1.5 var(--mono); }
  .ln { white-space: pre-wrap; word-break: break-word; color: var(--text-2); }
  .ln.stderr, .ln.important { color: var(--bad); }
  .ln.console { color: var(--muted); }
  .ln.input { color: var(--accent); }
  .ln.result { color: var(--text); }
  .ln.stdout { color: var(--text); }
  .none { color: var(--muted); font: 12px var(--font); padding: 6px 0; }
  .repl { display: flex; align-items: center; gap: 6px; padding: 0 10px; height: 30px; border-top: 1px solid var(--line); color: var(--accent); flex: none; }
  .repl.off { opacity: 0.6; }
  .repl input { flex: 1; min-width: 0; height: 24px; border: 0; background: none; color: var(--text); font: 12px var(--mono); outline: none; }
  .ell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; max-width: 260px; }
</style>
