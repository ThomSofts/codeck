<script lang="ts" module>
  import type { LocalRepo } from "../../lib/types";
  import type { Group } from "../../lib/work.svelte";
  /** Um projeto em andamento e por quê: agente perguntando/trabalhando/em espera, alterações sem commit, commits para
   *  enviar, tarefas (worktrees) abertas, aberto nas abas. */
  export type Ongoing = { r: LocalRepo; g: Group | null; open: boolean; last: number; score: number;
    need: number; working: number; standby: number; agents: { id: string; provider?: any; status?: string }[];
    changes: number; ahead: number; behind: number; tasks: { title: string; branch: string }[]; ask: string | null };
</script>

<script lang="ts">
  // "Em andamento": um cartão por projeto com trabalho no meio do caminho — o que pede você primeiro (agente
  // perguntando), depois o que está rodando, depois o que ficou pela metade (alterações, commits para enviar, tarefas).
  // Os abertos nas abas entram sempre. Clique continua de onde parou; o x fecha o projeto aberto.
  import { ArrowRight, ArrowUp, ChevronDown, GitBranch, ListTodo, MessageCircleQuestion, Bot, X } from "@lucide/svelte";
  import { ago } from "../../lib/format";
  import { prefs } from "../../lib/prefs.svelte";
  import { work } from "../../lib/work.svelte";
  import Menu, { type MenuItem } from "../Menu.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import AgentIcon from "../work/AgentIcon.svelte";

  let { items, onopen, menu }: { items: Ongoing[]; onopen: (r: LocalRepo, mode?: "go" | "ask") => void; menu: (r: LocalRepo) => MenuItem[] } = $props();

  const LIMIT = 8;
  let all = $state(false);
  const shut = $derived(prefs.get("hub.collapsed").includes("@ongoing"));
  const toggle = () => { const c = prefs.get("hub.collapsed"); prefs.set("hub.collapsed", shut ? c.filter(x => x !== "@ongoing") : [...c, "@ongoing"]); };
  const shown = $derived(all ? items : items.slice(0, LIMIT));
  const need = $derived(items.reduce((n, x) => n + x.need, 0));
  const working = $derived(items.reduce((n, x) => n + x.working, 0));

  /** a frase principal do cartão: o que está acontecendo, do mais urgente ao mais calmo */
  function headline(x: Ongoing): { tone: string; text: string } {
    if (x.need) return { tone: "warn", text: x.ask ? x.ask : x.need > 1 ? `${x.need} agentes perguntando` : "Agente perguntando" };
    if (x.working) return { tone: "accent", text: x.working > 1 ? `${x.working} agentes trabalhando` : "Agente trabalhando" };
    if (x.standby) return { tone: "calm", text: x.standby > 1 ? `${x.standby} agentes em espera` : "Agente em espera" };
    const bits = [x.changes ? `${x.changes} ${x.changes === 1 ? "alteração" : "alterações"} sem commit` : "", x.ahead ? `${x.ahead} para enviar` : ""].filter(Boolean);
    if (bits.length) return { tone: "calm", text: bits.join(" · ") };
    if (x.tasks.length) return { tone: "calm", text: x.tasks.length === 1 ? `Tarefa aberta: ${x.tasks[0].title}` : `${x.tasks.length} tarefas abertas` };
    return { tone: "calm", text: "Aberto" };
  }
</script>

<section class="og" class:shut>
  <header>
    <button class="ttl" onclick={toggle} aria-expanded={!shut}>
      <ChevronDown size={14} class="chev" />
      <h2>Em andamento</h2><span class="cnt">{items.length}</span>
    </button>
    {#if need}<span class="sig warn"><MessageCircleQuestion size={12} /> {need} pergunta{need === 1 ? "" : "s"} esperando você</span>{/if}
    {#if working}<span class="sig accent"><span class="live"></span>{working} trabalhando</span>{/if}
  </header>
  {#if !shut}
    {#if items.length}
      <div class="cards">
        {#each shown as x, i (x.r.id)}
          {@const h = headline(x)}
          <div class="oc {h.tone}" class:open={x.open} class:cur={x.r.id === work.active} style="--i:{Math.min(i, 10)};{x.g ? `--g:${x.g.color}` : ''}"
            role="button" tabindex="0" title={x.r.path}
            onclick={() => onopen(x.r)} onkeydown={(e) => e.key === "Enter" && onopen(x.r)} data-menu-row>
            <div class="top">
              <span class="ic"><ProviderIcon provider={x.r.provider || null} size={14} /></span>
              <div class="nm">
                <b class="ell">{x.r.name}</b>
                <span class="sub ell">
                  {#if x.g}<span class="gd"></span>{x.g.name} · {/if}{#if x.r.status?.branch}<GitBranch size={10} /> {x.r.status.branch}{/if}
                </span>
              </div>
              {#if x.open}<button class="x" title="Fechar projeto" onclick={(e) => { e.stopPropagation(); work.close(x.r.id); }}><X size={13} /></button>{/if}
              <Menu items={menu(x.r)} />
            </div>
            <p class="hl ell" title={h.text}>
              {#if h.tone === "warn"}<MessageCircleQuestion size={13} />{:else if h.tone === "accent"}<span class="live"></span>{/if}
              <span class="ell">{h.text}</span>
            </p>
            <div class="foot">
              {#if x.agents.length}<span class="ags">{#each x.agents.slice(0, 4) as a (a.id)}<span class="ag {a.status === 'needs-you' ? 'warn' : a.status === 'working' ? 'accent' : ''}"><AgentIcon provider={a.provider} size={11} /></span>{/each}</span>{/if}
              {#if x.changes && (x.need || x.working || x.standby)}<span class="mt" title="alterações não commitadas">{x.changes} alt.</span>{/if}
              {#if x.ahead && (x.need || x.working || x.standby)}<span class="mt" title="commits para enviar"><ArrowUp size={10} />{x.ahead}</span>{/if}
              {#if x.tasks.length && (x.need || x.working || x.standby || x.changes || x.ahead)}<span class="mt" title={x.tasks.map(t => t.title).join("\n")}><ListTodo size={11} />{x.tasks.length}</span>{/if}
              <span class="grow"></span>
              {#if x.last}<span class="when">{ago(new Date(x.last).toISOString())}</span>{/if}
              <button class="ask" title="Abrir agente" onclick={(e) => { e.stopPropagation(); onopen(x.r, "ask"); }}><Bot size={12} /></button>
              <span class="go">{x.open ? "Ir" : "Continuar"} <ArrowRight size={12} /></span>
            </div>
          </div>
        {/each}
      </div>
      {#if items.length > LIMIT}
        <button class="more" onclick={() => (all = !all)}>{all ? "Mostrar menos" : `Ver todos os ${items.length} em andamento`}</button>
      {/if}
    {:else}
      <p class="empty">Nada pela metade — abra um projeto abaixo ou busque e aperte <span class="kbd">Enter</span>.</p>
    {/if}
  {/if}
</section>

<style>
  .og { display: grid; gap: 10px; flex: none; }
  header { display: flex; align-items: center; gap: 10px; min-height: 24px; flex-wrap: wrap; }
  .ttl { display: inline-flex; align-items: center; gap: 7px; border: 0; background: none; padding: 0; cursor: pointer; color: var(--text); }
  .ttl :global(.chev) { color: var(--muted); transition: transform var(--t) var(--ease); }
  .shut .ttl :global(.chev) { transform: rotate(-90deg); }
  h2 { margin: 0; font-size: 14px; font-weight: 680; letter-spacing: -0.01em; }
  .cnt { font: 600 11px/1 var(--font); color: var(--muted); font-variant-numeric: tabular-nums; }
  .sig { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 550; }
  .sig.warn { color: var(--warn); }
  .sig.accent { color: var(--accent); }
  .grow { flex: 1; }

  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); gap: 10px; }
  .oc { --tone: var(--line-3); position: relative; display: grid; gap: 8px; padding: 12px 12px 10px 14px; border-radius: 14px; border: 1px solid var(--line);
    background: var(--surface); cursor: pointer; min-width: 0; overflow: hidden; animation: og-rise 0.32s var(--ease-out) both; animation-delay: calc(var(--i) * 22ms);
    transition: border-color var(--t), transform var(--t) var(--spring), box-shadow var(--t), background var(--t); }
  /* a faixa da esquerda é a cor do grupo; sem grupo, quase invisível */
  .oc::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--g, transparent); opacity: 0.9; }
  .oc:hover { border-color: var(--line-3); transform: translateY(-2px); box-shadow: var(--shadow-2); }
  .oc:focus-visible { outline: none; box-shadow: var(--ring); }
  .oc.cur { border-color: var(--accent-line); }
  .oc.warn { border-color: color-mix(in srgb, var(--warn) 38%, var(--line)); background: linear-gradient(180deg, color-mix(in srgb, var(--warn) 6%, var(--surface)), var(--surface) 60%); }
  .top { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .ic { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px; background: var(--surface-2); border: 1px solid var(--line); flex: none; }
  .nm { display: grid; min-width: 0; flex: 1; gap: 1px; }
  .nm b { font-size: 13.5px; font-weight: 650; letter-spacing: -0.01em; }
  .sub { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; color: var(--muted); min-width: 0; }
  .sub :global(svg) { flex: none; }
  .gd { width: 7px; height: 7px; border-radius: 50%; background: var(--g); flex: none; }
  .x { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; opacity: 0; flex: none;
    transition: opacity var(--t-fast), background var(--t-fast), color var(--t-fast); }
  .oc:hover .x, .x:focus-visible { opacity: 1; }
  .x:hover { background: var(--bad-soft); color: var(--bad); }
  .top :global(.btn.sm.icon) { opacity: 0; transition: opacity var(--t-fast); }
  .oc:hover .top :global(.btn.sm.icon) { opacity: 1; }
  .hl { display: flex; align-items: center; gap: 7px; margin: 0; font-size: 12.5px; color: var(--text-2); min-width: 0; min-height: 18px; }
  .hl :global(svg) { flex: none; }
  .oc.warn .hl { color: var(--warn); font-weight: 560; }
  .oc.accent .hl { color: var(--text); }
  .foot { display: flex; align-items: center; gap: 8px; min-height: 22px; font-size: 11.5px; color: var(--muted); }
  .ags { display: inline-flex; gap: 3px; }
  .ag { display: inline-grid; place-items: center; width: 19px; height: 19px; border-radius: 50%; background: var(--surface-2); border: 1px solid var(--line); }
  .ag.accent { border-color: var(--accent-line); } .ag.warn { border-color: color-mix(in srgb, var(--warn) 55%, transparent); }
  .mt { display: inline-flex; align-items: center; gap: 3px; font-variant-numeric: tabular-nums; }
  .when { font-variant-numeric: tabular-nums; color: var(--faint); }
  .ask { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; opacity: 0;
    transition: opacity var(--t-fast), background var(--t-fast), color var(--t-fast); }
  .oc:hover .ask { opacity: 1; }
  .ask:hover { background: var(--accent-soft); color: var(--accent); }
  .go { display: inline-flex; align-items: center; gap: 4px; font-weight: 600; color: var(--text-2); transition: color var(--t-fast), gap var(--t) var(--spring); }
  .oc:hover .go { color: var(--accent); gap: 6px; }
  .live { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); flex: none; animation: og-ping 1.4s var(--ease) infinite; }
  .more { justify-self: center; border: 0; background: none; color: var(--accent); font: 550 12.5px var(--font); cursor: pointer; padding: 4px 8px; border-radius: 6px; }
  .more:hover { background: var(--accent-soft); }
  .empty { margin: 0; padding-left: 21px; font-size: 12.5px; color: var(--muted); }
  @keyframes og-rise { from { opacity: 0; transform: translateY(6px); } }
  @keyframes og-ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 5px transparent; } }
  @media (prefers-reduced-motion: reduce) { .oc, .live { animation: none; } .oc:hover { transform: none; } }
</style>
