<script lang="ts">
  // Editor de regra de deploy/permissão: tipo, ação, pipeline, estágio/branch ou recursos, origem e prévia.
  import { untrack } from "svelte";
  import { post } from "../../lib/api";
  import { blankDRule, DACTIONS, dRuleSentence, saveRules } from "../../lib/rules";
  import { store } from "../../lib/store.svelte";
  import type { DeployRule } from "../../lib/types";
  import { ui } from "../../lib/ui.svelte";
  import Drawer from "../Drawer.svelte";
  import Switch from "../Switch.svelte";
  import ActionCards from "./ActionCards.svelte";
  import ChipPicker from "./ChipPicker.svelte";

  let { rule, isNew, onclose }: { rule: DeployRule; isNew: boolean; onclose: () => void } = $props();
  // svelte-ignore state_referenced_locally
  let r = $state<DeployRule>(blankDRule(rule));
  let sim = $state<any>(null);
  let timer: ReturnType<typeof setTimeout>;
  const s = $derived(store.s!);
  const rel = $derived(r.kind === "release");
  const pipes = $derived([...new Set([...s.deploys.filter(d => (d.kind === "permission") === !rel).map(d => d.pipeline), ...(rel ? s.releases.map(x => x.pipeline) : [])])].slice(0, 30));
  const stages = $derived([...new Set([...s.releases.flatMap(x => x.envs.map(e => e.name)), ...s.deploys.map(d => d.stage)])].filter(Boolean));
  const branches = $derived([...new Set([...s.rules.protectedTargets, "develop", ...s.releases.map(x => x.branch)])].filter(Boolean).slice(0, 12));
  const resources = $derived([...new Set(s.deploys.flatMap(d => d.resources.map(x => x.name)))]);
  const risky = $derived(rel && r.action === "approve" && !r.requirePrApproved && (!r.stages.length || r.stages.some(x => /prod/i.test(x))));

  $effect(() => {
    if (r.kind === "permission") untrack(() => { r.stages = []; r.branches = []; r.requirePrApproved = false; });
    else untrack(() => { r.resources = []; });
  });
  $effect(() => {
    const snap = JSON.stringify(r);
    untrack(() => { sim = null; clearTimeout(timer); });
    timer = setTimeout(async () => {
      try { const res = await post("simulate-deploy", { rule: JSON.parse(snap) }); if (JSON.stringify(r) === snap) sim = res; }
      catch (e: any) { sim = { error: e.message }; }
    }, 300);
  });
  async function save() {
    const list = s.rules.deployRules.map(x => ({ ...x }));
    if (isNew) list.push({ ...r }); else list[list.findIndex(x => x.id === r.id)] = { ...r };
    if (await saveRules({ deployRules: list }, isNew ? "Regra criada — aplicando agora" : "Regra salva — aplicando agora")) onclose();
  }
  async function remove() {
    if (!(await ui.ask({ title: "Excluir esta regra?", message: dRuleSentence(r).replace(/<[^>]+>/g, ""), confirm: "Excluir", danger: true }))) return;
    if (await saveRules({ deployRules: s.rules.deployRules.filter(x => x.id !== r.id) }, "Regra excluída")) onclose();
  }
</script>

<Drawer title={isNew ? "Nova regra de deploy" : "Editar regra de deploy"} subtitle="Releases e environments (Azure e GitHub) e permissões de pipeline" {onclose}>
  <section><h4><span class="step">1</span>Quando aparecer</h4>
    <ActionCards bind:value={r.kind} options={[
      { value: "release", icon: "🚀", label: "Deploy esperando aprovação", desc: "Estágio de release (Azure) ou environment protegido (GitHub Actions) aguardando aprovador." },
      { value: "permission", icon: "🔑", label: "Pipeline pedindo permissão", desc: "Run travado em “needs permission to access a resource” (grupo de variáveis, service connection…)." }]} /></section>
  <section><h4><span class="step">2</span>O que fazer</h4>
    <ActionCards bind:value={r.action} options={Object.entries(DACTIONS[r.kind]).map(([k, a]) => ({ value: k, icon: a.icon, label: a.label, desc: a.desc }))} /></section>
  <section><h4><span class="step">3</span>De qual pipeline ou workflow</h4>
    <ChipPicker bind:value={r.pipelines} options={pipes} anyLabel="Qualquer um" placeholder="Parte do nome + Enter — aceita curinga" /></section>
  {#if rel}
    <section><h4><span class="step">4</span>Em qual estágio e de qual branch</h4>
      <ChipPicker bind:value={r.stages} options={stages} anyLabel="Qualquer estágio" placeholder="Outro estágio/environment + Enter" />
      <h5>Branch de origem</h5>
      <ChipPicker bind:value={r.branches} options={branches} anyLabel="Qualquer branch" placeholder="Outra branch + Enter" />
      {#if r.action === "approve"}<div class="opt"><Switch bind:checked={r.requirePrApproved} label="Só se eu já aprovei a PR de origem" hint="Lê a PR do commit e confere o seu voto. Sem PR identificada, espera você." /></div>{/if}
      {#if risky}<div class="warnbox">🔒 Esta regra pode aprovar <b>produção</b> sem você olhar. Ligue “Só se eu já aprovei a PR de origem” para manter o seu crivo.</div>{/if}
    </section>
  {:else}
    <section><h4><span class="step">4</span>Para quais recursos</h4>
      <ChipPicker bind:value={r.resources} options={resources} anyLabel="Qualquer recurso" placeholder="Nome do grupo de variáveis / service connection + Enter (*-PROD)" />
      <p class="small muted">Só libera quando <b>todos</b> os recursos pedidos pelo run se encaixam.</p></section>
  {/if}
  <section><h4><span class="step">5</span>Em qual origem</h4><ChipPicker bind:value={r.orgs} options={s.sources} anyLabel="Todas" /></section>
  <section><h4>Nome <span class="muted small hint">(opcional)</span></h4><input class="input" bind:value={r.name} placeholder="ex.: Prod após minha aprovação" /></section>
  <section class="preview"><h4>Prévia</h4>
    <div class="sentence">{@html dRuleSentence(r)} → <b>{DACTIONS[r.kind][r.action].label.toLowerCase()}</b>.</div>
    {#if !sim}<div class="simgrid"><i class="shim" style="height:62px"></i><i class="shim" style="height:62px"></i></div>
    {:else if sim.error}<div class="warnbox">{sim.error}</div>
    {:else}
      <div class="simgrid">
        <div class="simstat"><div class="v">{sim.open.length}</div><div class="l">de {sim.openTotal} itens na fila agora</div></div>
        <div class="simstat"><div class="v">{rel ? sim.historyCount : "—"}</div><div class="l">{rel ? `estágios nas releases recentes (de ${sim.historyTotal})` : "permissões não têm histórico"}</div></div>
      </div>
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
  section, .opt { display: block; padding: 16px 0; border-bottom: 1px solid var(--line); }
  .opt { border: 0; padding-bottom: 0; }
  h4 { margin: 0 0 10px; font: 650 11px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-2); display: flex; align-items: center; gap: 8px; }
  .hint { text-transform: none; letter-spacing: 0; font-weight: 400; }
  h5 { margin: 14px 0 8px; font-size: 12px; color: var(--text-2); }
  .step { width: 20px; height: 20px; border-radius: 50%; background: var(--accent); color: var(--accent-ink); display: inline-grid; place-items: center; font-size: 11px; }
  .preview { border-bottom: 0; }
  .sentence { background: var(--bg-2); border: 1px solid var(--line); border-radius: 11px; padding: 11px 13px; line-height: 1.55; }
  .warnbox { margin-top: 10px; padding: 9px 12px; border-radius: 10px; background: var(--warn-soft); color: var(--warn); font-size: 13px; }
  .simgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
  .simstat { border: 1px solid var(--line); border-radius: 11px; padding: 10px 12px; }
  .simstat .v { font-size: 22px; font-weight: 700; letter-spacing: -0.03em; }
  .simstat .l { font-size: 12px; color: var(--text-2); }
  p { margin: 8px 0 0; }
</style>
