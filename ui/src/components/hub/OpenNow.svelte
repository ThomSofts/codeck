<script lang="ts">
  // "Abertos agora": um cartão por projeto aberto, na ordem das abas, com o que está acontecendo nele — agentes
  // trabalhando, precisando de você, tarefas, branch e alterações. Clique vai para o projeto; o x fecha.
  import { ArrowDown, ArrowUp, ChevronDown, GitBranch, ListTodo, X } from "@lucide/svelte";
  import { prefs } from "../../lib/prefs.svelte";
  import { repos } from "../../lib/repos.svelte";
  import { go } from "../../lib/router.svelte";
  import { STATUS, work } from "../../lib/work.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import AgentIcon from "../work/AgentIcon.svelte";
  import { agentsByProject, noAgents, openOrdered, tone } from "./open";

  const ordered = $derived(openOrdered());
  const ags = $derived(agentsByProject());
  const shut = $derived(prefs.get("hub.collapsed").includes("@open"));
  const toggle = () => { const c = prefs.get("hub.collapsed"); prefs.set("hub.collapsed", shut ? c.filter(x => x !== "@open") : [...c, "@open"]); };
  const summary = $derived.by(() => {
    let need = 0, working = 0;
    for (const a of ags.values()) { need += a.need; working += a.working; }
    return { need, working };
  });
</script>

<section class="on" class:shut>
  <header>
    <button class="ttl" onclick={toggle} aria-expanded={!shut}>
      <ChevronDown size={14} class="chev" />
      <h2>Abertos agora</h2><span class="cnt">{ordered.length}</span>
    </button>
    {#if summary.need}<span class="pill warn">{summary.need} precisa{summary.need === 1 ? "" : "m"} de você</span>{/if}
    {#if summary.working}<span class="pill accent"><span class="live"></span>{summary.working} trabalhando</span>{/if}
    <span class="grow"></span>
    {#if ordered.length}<span class="tiny muted hint">clique para ir · x fecha</span>{/if}
  </header>
  {#if !shut}
    {#if ordered.length}
      <div class="cards">
        {#each ordered as p, i (p.id)}
          {@const a = ags.get(p.id) || noAgents}
          {@const g = work.groupOf(p.id)}
          {@const st = repos.byId(p.id)?.status}
          {@const tasks = p.tasks.length}
          <div class="oc {tone(a)}" class:cur={p.id === work.active} style="--i:{Math.min(i, 12)};{g ? `--g:${g.color}` : ''}" role="button" tabindex="0"
            onclick={() => go("/work/" + p.id, "soft")} onkeydown={(e) => e.key === "Enter" && go("/work/" + p.id, "soft")}
            onauxclick={(e) => e.button === 1 && work.close(p.id)}>
            <div class="r1">
              <span class="ic"><ProviderIcon provider={(p.provider as any) || null} size={15} /></span>
              <b class="ell">{p.name}</b>
              {#if p.id === work.active}<span class="cur-tag">atual</span>{/if}
              <button class="x" title="Fechar projeto" onclick={(e) => { e.stopPropagation(); work.close(p.id); }}><X size={13} /></button>
            </div>
            <div class="r2">
              {#if g}<span class="gtag"><span class="gd"></span>{g.name}</span>{/if}
              {#if st?.branch}<span class="br mono"><GitBranch size={11} /><span class="ell">{st.branch}</span></span>{/if}
              {#if st?.changes}<span class="pill warn">{st.changes}</span>{/if}
              {#if st?.ahead}<span class="pill accent"><ArrowUp size={10} />{st.ahead}</span>{/if}
              {#if st?.behind}<span class="pill info"><ArrowDown size={10} />{st.behind}</span>{/if}
            </div>
            <div class="r3">
              {#if a.n}
                <span class="ags">{#each a.list.slice(0, 5) as x (x.id)}<span class="ag {STATUS[x.status || '']?.[1] || ''}" class:pulse={x.status === "working"}><AgentIcon provider={x.provider} size={12} /></span>{/each}</span>
                <span class="st">{a.need ? "precisa de você" : a.working ? `${a.working} trabalhando` : a.done ? "terminou" : `${a.n} agente${a.n === 1 ? "" : "s"}`}</span>
              {:else}<span class="st faint">sem agente</span>{/if}
              <span class="grow"></span>
              {#if tasks}<span class="tk" title="tarefas (worktrees)"><ListTodo size={11} />{tasks}</span>{/if}
            </div>
          </div>
        {/each}
      </div>
    {:else}
      <div class="empty">
        Nenhum projeto aberto — clique num projeto abaixo ou busque e aperte <span class="kbd">Enter</span>.
      </div>
    {/if}
  {/if}
</section>

<style>
  .on { display: grid; gap: 10px; padding: 12px; border-radius: 14px; border: 1px solid var(--accent-line);
    background: linear-gradient(180deg, color-mix(in srgb, var(--accent) 7%, var(--surface)), var(--surface) 70%); box-shadow: var(--shadow-1); }
  .on.shut { padding-bottom: 12px; }
  header { display: flex; align-items: center; gap: 8px; min-height: 24px; }
  .ttl { display: inline-flex; align-items: center; gap: 7px; border: 0; background: none; padding: 0; cursor: pointer; color: var(--text); }
  .ttl :global(.chev) { color: var(--muted); transition: transform var(--t) var(--ease); }
  .shut .ttl :global(.chev) { transform: rotate(-90deg); }
  h2 { margin: 0; font-size: 14px; font-weight: 700; letter-spacing: -0.01em; }
  .cnt { font: 700 11px/1 var(--font); padding: 3px 7px; border-radius: 99px; background: var(--accent); color: var(--accent-ink); font-variant-numeric: tabular-nums; }
  .pill { display: inline-flex; align-items: center; gap: 5px; }
  .grow { flex: 1; }
  .hint { white-space: nowrap; }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 8px; }
  .oc { position: relative; display: grid; gap: 6px; padding: 9px 10px 8px 12px; border-radius: 11px; border: 1px solid var(--line-2); background: var(--surface-2);
    cursor: pointer; min-width: 0; animation: on-rise 0.32s var(--ease-out) both; animation-delay: calc(var(--i) * 25ms);
    transition: border-color var(--t), transform var(--t) var(--spring), box-shadow var(--t), background var(--t); }
  .oc::before { content: ""; position: absolute; left: 0; top: 9px; bottom: 9px; width: 3px; border-radius: 0 3px 3px 0; background: var(--g, var(--line-3)); }
  .oc:hover { border-color: var(--line-3); transform: translateY(-2px); box-shadow: var(--shadow-2); background: var(--surface-3); }
  .oc:focus-visible { outline: none; box-shadow: var(--ring); }
  .oc.cur { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 9%, var(--surface-2)); }
  .oc.warn { border-color: color-mix(in srgb, var(--warn) 55%, transparent); }
  .oc.accent::after { content: ""; position: absolute; inset: -1px; border-radius: 11px; pointer-events: none;
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 40%, transparent); animation: on-glow 2.2s var(--ease) infinite; }
  .r1 { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .r1 b { flex: 1; font-weight: 650; font-size: 13.5px; }
  .ic { display: grid; place-items: center; width: 24px; height: 24px; border-radius: 7px; background: var(--surface); border: 1px solid var(--line); flex: none; }
  .cur-tag { font: 650 10px/1 var(--font); text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent); }
  .x { display: grid; place-items: center; width: 22px; height: 22px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; opacity: 0.35; flex: none;
    transition: opacity var(--t-fast), background var(--t-fast); }
  .oc:hover .x, .x:focus-visible { opacity: 1; }
  .x:hover { background: var(--bad-soft); color: var(--bad); }
  .r2 { display: flex; align-items: center; gap: 6px; min-width: 0; min-height: 19px; }
  .r2 .pill { font-size: 10.5px; padding: 1px 6px; }
  .br { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; color: var(--text-2); min-width: 0; overflow: hidden; }
  .br :global(svg) { flex: none; }
  .gtag { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 600; color: var(--text-2); padding: 1px 7px 1px 5px; border-radius: 99px;
    background: color-mix(in srgb, var(--g) 16%, transparent); flex: none; max-width: 120px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .gd { width: 7px; height: 7px; border-radius: 50%; background: var(--g); flex: none; }
  .r3 { display: flex; align-items: center; gap: 7px; font-size: 11.5px; color: var(--text-2); min-height: 18px; }
  .ags { display: inline-flex; gap: 3px; }
  .ag { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; background: var(--surface); }
  .ag.accent { box-shadow: 0 0 0 1.5px var(--accent); } .ag.warn { box-shadow: 0 0 0 1.5px var(--warn); } .ag.good { box-shadow: 0 0 0 1.5px var(--good); }
  .ag.pulse { animation: on-ping 1.3s var(--ease) infinite; }
  .oc.warn .st { color: var(--warn); font-weight: 600; }
  .oc.accent .st { color: var(--accent); font-weight: 600; }
  .faint { color: var(--faint); }
  .tk { display: inline-flex; align-items: center; gap: 3px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .live { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: on-ping 1.2s var(--ease) infinite; }
  .empty { padding: 0 2px 0 23px; font-size: 12.5px; color: var(--muted); }
  @keyframes on-rise { from { opacity: 0; transform: translateY(6px); } }
  @keyframes on-ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 65%, transparent); } 80%, 100% { box-shadow: 0 0 0 6px transparent; } }
  @keyframes on-glow { 50% { box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent); } }
  @media (prefers-reduced-motion: reduce) { .oc, .oc.accent::after, .ag.pulse, .live { animation: none; } .oc:hover { transform: none; } }
</style>
