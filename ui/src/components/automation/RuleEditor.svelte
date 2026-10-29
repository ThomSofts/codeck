<script lang="ts">
  // Editor de regra de PR (Azure e GitHub): ação, criador, branch, origem, filtros e prévia ao vivo (agora + 30 dias).
  import { untrack } from "svelte";
  import { post } from "../../lib/api";
  import { ACTIONS, blankRule, esc, ruleSentence, saveRules } from "../../lib/rules";
  import { store } from "../../lib/store.svelte";
  import type { Rule } from "../../lib/types";
  import { ui } from "../../lib/ui.svelte";
  import { work } from "../../lib/work.svelte";
  import Drawer from "../Drawer.svelte";
  import Switch from "../Switch.svelte";
  import ActionCards from "./ActionCards.svelte";
  import ChipPicker from "./ChipPicker.svelte";

  let { rule, isNew, onclose }: { rule: Rule; isNew: boolean; onclose: () => void } = $props();
  // svelte-ignore state_referenced_locally
  let r = $state<Rule>(blankRule(rule));
  let sim = $state<any>(null);
  let timer: ReturnType<typeof setTimeout>;
  const s = $derived(store.s!);
  const protectedSel = $derived(r.targets.filter(t => s.rules.protectedTargets.map(x => x.toLowerCase()).includes(t.toLowerCase())));
  // quem revisa: as contas do Claude Code e do Codex instaladas (as que rodam sem terminal)
  $effect(() => { if (!work.ai.length) work.loadAi(); });
  const reviewers = $derived(work.ai.filter(a => a.installed && (a.provider === "claude" || a.provider === "codex")));
  const approves = $derived(r.action === "approve" || (r.action === "review" && r.aiApprove !== false));

  $effect(() => {
    const snap = JSON.stringify(r);
    untrack(() => { sim = null; clearTimeout(timer); });
    timer = setTimeout(async () => {
      try { const res = await post("simulate", { rule: JSON.parse(snap) }); if (JSON.stringify(r) === snap) sim = res; }
      catch (e: any) { sim = { error: e.message }; }
    }, 320);
  });
  async function save() {
    const rules = s.rules.rules.map(x => ({ ...x }));
    if (isNew) rules.push({ ...r }); else rules[rules.findIndex(x => x.id === r.id)] = { ...r };
    if (await saveRules({ rules }, isNew ? "Regra criada — aplicando agora" : "Regra salva — aplicando agora")) onclose();
  }
  async function remove() {
    if (!(await ui.ask({ title: "Excluir esta regra?", message: ruleSentence(r).replace(/<[^>]+>/g, ""), confirm: "Excluir", danger: true }))) return;
    if (await saveRules({ rules: s.rules.rules.filter(x => x.id !== r.id) }, "Regra excluída")) onclose();
  }
  const preview = $derived(`${ruleSentence(r)} → <b>${ACTIONS[r.action].short}</b>${(r.action === "approve" || r.action === "review") && r.requireBuild ? " depois do build verde" : ""}`
    + (r.action === "review" ? (r.aiApprove !== false ? ": aprova se estiver tudo certo, senão “Aguardando autor” com os pontos" : ": só comenta e pede ajustes — aprovar fica com você") : "") + ".");
</script>

<Drawer title={isNew ? "Nova regra de PR" : "Editar regra de PR"} subtitle="Vale para PRs do GitHub e do Azure DevOps" {onclose}>
  <section><h4><span class="step">1</span>O que fazer</h4>
    <ActionCards bind:value={r.action} options={Object.entries(ACTIONS).map(([k, a]) => ({ value: k, icon: a.icon, label: a.label, desc: a.desc }))} /></section>
  <section><h4><span class="step">2</span>Quando a PR for criada por</h4>
    <ChipPicker bind:value={r.creators} options={s.creators} anyLabel="Qualquer pessoa" placeholder="Nome, login ou e-mail + Enter — parte do nome basta" /></section>
  <section><h4><span class="step">3</span>Para a branch</h4>
    <ChipPicker bind:value={r.targets} options={[...s.targets, ...s.rules.protectedTargets]} locked={s.rules.protectedTargets} anyLabel="Qualquer uma, menos as protegidas" placeholder="Outra branch + Enter — aceita curinga (release/*)" />
    {#if protectedSel.length && approves}<div class="warnbox">🔒 Esta regra vai aprovar sozinha PRs para <b>{protectedSel.join(", ")}</b> — isso é subida para produção sem você olhar.</div>{/if}
  </section>
  <section><h4><span class="step">4</span>Em qual origem</h4>
    <ChipPicker bind:value={r.orgs} options={s.sources} anyLabel="Todas" placeholder="Organização do Azure ou dono no GitHub + Enter" /></section>
  <details class="more" open={!!(r.repos.length || r.titleContains)}>
    <summary>Mais filtros — repositório e título</summary>
    <h5>Repositórios</h5>
    <ChipPicker bind:value={r.repos} options={s.repos.slice(0, 30)} anyLabel="Todos" placeholder="Repositório + Enter — aceita curinga (*-api)" />
    <h5>Título contém</h5>
    <input class="input" bind:value={r.titleContains} placeholder="ex.: hotfix" />
  </details>
  {#if r.action === "review"}
    <section><h4><span class="step">5</span>Revisão da IA</h4>
      {#if !reviewers.length}<div class="warnbox">Nenhuma conta do Claude Code ou do Codex instalada — adicione uma em Configurações → Contas de IA.</div>{/if}
      <label class="fl"><span>Quem revisa</span>
        <select class="input" bind:value={r.aiAccount}>
          <option value={null}>A conta padrão</option>
          {#each reviewers as a (a.id)}<option value={a.id}>{a.label} · {a.name}</option>{/each}
        </select></label>
      <div class="sw"><Switch checked={r.aiApprove !== false} onchange={(v) => (r.aiApprove = v)} label="Aprovar quando estiver tudo certo"
        hint="Desligado, a IA só comenta e pede ajustes — aprovar fica com você. Nunca recusa: com problema, vota “Aguardando autor”." /></div>
      <div class="sw"><Switch bind:checked={r.aiMine} label="Revisar também as minhas PRs"
        hint="Na sua PR a IA só comenta (não vota). Depois, “Ajustar com IA” na PR leva os pontos para um agente corrigir." /></div>
      <label class="fl"><span>O que olhar com mais atenção <span class="muted">(opcional)</span></span>
        <textarea class="input" rows="3" bind:value={r.aiFocus} placeholder="ex.: migrations do EF, permissões nos endpoints, testes para regra nova"></textarea></label>
      <p class="small muted">Revisa num worktree à parte (o seu checkout não muda), sem poder alterar arquivos. Push novo → revisa de novo; se o autor resolveu, aprova.</p>
    </section>
  {/if}
  {#if r.action === "approve" || r.action === "review"}<div class="opt"><Switch bind:checked={r.requireBuild} label={r.action === "review" ? "Esperar o build passar antes de revisar" : "Esperar o build passar antes de aprovar"} hint="Com o build vermelho ou rodando, a PR espera na fila." /></div>{/if}
  <section><h4>Nome <span class="muted small hint">(opcional — aparece no histórico)</span></h4><input class="input" bind:value={r.name} placeholder="ex.: Ana — tudo menos produção" /></section>
  <section class="preview"><h4>Prévia</h4>
    <div class="sentence">{@html preview}</div>
    {#if !r.creators.length && approves && !r.repos.length && !r.titleContains}<div class="warnbox">Sem filtro de criador, esta regra {r.action === "review" ? "revisa e pode aprovar" : "aprova"} PRs de <b>todo mundo</b>.</div>{/if}
    {#if !sim}<div class="simgrid"><i class="shim" style="height:62px"></i><i class="shim" style="height:62px"></i></div>
    {:else if sim.error}<div class="warnbox">{sim.error}</div>
    {:else}
      <div class="simgrid">
        <div class="simstat"><div class="v">{sim.open.length}</div><div class="l">de {sim.openTotal} PRs abertas agora</div></div>
        <div class="simstat"><div class="v">{sim.history.count}</div><div class="l">de {sim.history.total} concluídas (30 dias, Azure)</div></div>
      </div>
      {#if sim.open.length}
        <div class="simlist">{#each sim.open as p (p.key)}
          <div class="simrow"><div class="ell"><span class="muted">#{p.prId}</span> {p.title}<div class="small muted">{p.creatorName} → {p.target} · {p.org}</div></div>
            {#if p.shadowedBy}<span class="pill warn" title="Uma regra acima decide antes">decide: {p.shadowedBy}</span>{:else if p.myVote}<span class="pill neutral">você já votou</span>{:else}<span class="pill accent">{ACTIONS[r.action].verb}</span>{/if}</div>{/each}</div>
      {:else if sim.history.count}<p class="small muted">Nenhuma aberta agora. Últimas que teria pego: {@html sim.history.sample.slice(0, 4).map((p: any) => `#${p.prId} (${esc(p.creatorName.split(" ")[0])} → ${esc(p.target)})`).join(", ")}</p>
      {:else}<div class="warnbox">Nenhuma PR recente se encaixa — confira o nome do criador e a branch.</div>{/if}
    {/if}
  </section>
  {#snippet footer()}
    {#if !isNew}<button class="btn danger" onclick={remove}>Excluir</button>{/if}
    <span class="spacer"></span>
    <button class="btn ghost" onclick={onclose}>Cancelar</button>
    <button class="btn primary" onclick={save}>{isNew ? "Criar regra" : "Salvar regra"}</button>
  {/snippet}
</Drawer>

<style>
  section, .more, .opt { display: block; padding: 16px 0; border-bottom: 1px solid var(--line); }
  h4 { margin: 0 0 10px; font: 650 11px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-2); display: flex; align-items: center; gap: 8px; }
  .hint { text-transform: none; letter-spacing: 0; font-weight: 400; }
  h5 { margin: 14px 0 8px; font-size: 12px; color: var(--text-2); }
  .step { width: 20px; height: 20px; border-radius: 50%; background: var(--accent); color: var(--accent-ink); display: inline-grid; place-items: center; font-size: 11px; }
  summary { cursor: pointer; font-size: 13px; font-weight: 600; color: var(--text-2); }
  .preview { border-bottom: 0; }
  .fl { display: grid; gap: 6px; margin-top: 10px; font-size: 12.5px; color: var(--text-2); }
  .fl textarea { resize: vertical; font: 13px/1.45 var(--font); }
  .sw { margin-top: 12px; }
  .sentence { background: var(--bg-2); border: 1px solid var(--line); border-radius: 11px; padding: 11px 13px; line-height: 1.55; }
  .warnbox { margin-top: 10px; padding: 9px 12px; border-radius: 10px; background: var(--warn-soft); color: var(--warn); font-size: 13px; }
  .simgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
  .simstat { border: 1px solid var(--line); border-radius: 11px; padding: 10px 12px; animation: rise 0.3s var(--ease-out); }
  .simstat .v { font-size: 22px; font-weight: 700; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; }
  .simstat .l { font-size: 12px; color: var(--text-2); }
  .simlist { margin-top: 10px; border: 1px solid var(--line); border-radius: 11px; max-height: 240px; overflow: auto; }
  .simrow { display: flex; gap: 10px; align-items: center; justify-content: space-between; padding: 8px 11px; border-top: 1px solid var(--line); font-size: 13px; }
  .simrow:first-child { border-top: 0; }
</style>
