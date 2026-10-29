<script lang="ts">
  import { ArrowDown, ArrowUp, Copy, Lock, Plus, Trash2, X } from "@lucide/svelte";
  import { ago } from "../lib/format";
  import { go, router } from "../lib/router.svelte";
  import { ACTIONS, blankDRule, blankRule, DACTIONS, DTEMPLATES, dRuleSentence, ruleSentence, saveRules, TEMPLATES } from "../lib/rules";
  import { store } from "../lib/store.svelte";
  import type { DeployRule, Rule } from "../lib/types";
  import { ui } from "../lib/ui.svelte";
  import DeployRuleEditor from "../components/automation/DeployRuleEditor.svelte";
  import RuleEditor from "../components/automation/RuleEditor.svelte";
  import Empty from "../components/Empty.svelte";
  import Menu from "../components/Menu.svelte";
  import Page from "../components/Page.svelte";
  import Skeleton from "../components/Skeleton.svelte";
  import Switch from "../components/Switch.svelte";

  const s = $derived(store.s);
  let edit = $state<{ kind: "pr"; rule: Rule; isNew: boolean } | { kind: "deploy"; rule: DeployRule; isNew: boolean } | null>(null);
  let newProt = $state("");

  $effect(() => {
    const p = router.param;
    if (!s || !p) return;
    if (p === "new") edit = { kind: "pr", rule: blankRule(), isNew: true };
    else if (p === "new-deploy") edit = { kind: "deploy", rule: blankDRule(), isNew: true };
    else {
      const r = s.rules.rules.find(x => x.id === p), d = s.rules.deployRules.find(x => x.id === p);
      if (r) edit = { kind: "pr", rule: r, isNew: false };
      else if (d) edit = { kind: "deploy", rule: d, isNew: false };
    }
  });
  function close() { edit = null; if (router.param) go("/automation", "soft"); }
  function move<T>(list: T[], i: number, dir: number) { const l = [...list]; l.splice(i + dir, 0, l.splice(i, 1)[0]); return l; }
  const sw = (id: string, label: string, hint: string) => ({ id, label, hint });
  const behaviors = [
    sw("notifyPending", "Notificar PR nova na fila", "Quando chega PR esperando o seu voto (uma vez por PR)."),
    sw("notifyAuto", "Notificar o que o piloto fizer", "A cada aprovação ou liberação automática."),
    sw("resurfaceOnPush", "Desarquivar com push novo", "PR arquivada volta para a fila se o autor subir commit."),
    sw("notifyDeploys", "Notificar deploy/permissão pendente", "Quando um deploy ou pipeline passa a esperar você."),
    sw("notifyMyPrs", "Notificar problema nas minhas PRs", "Conflito, build vermelho, recusa ou pedido de mudança."),
    sw("notifyBuildFailures", "Notificar build que falhou", "Em branch protegida ou disparado por você."),
  ];
  async function setSetting(id: string, v: boolean) { await saveRules({ settings: { ...s!.rules.settings, [id]: v } }, "Salvo"); }
</script>

<Page title="Automação" sub="Regras avaliadas de cima para baixo — a primeira que se aplicar decide">
  {#if !s}<Skeleton rows={6} />{:else}
    <div class="layout">
      <div class="col scroll">
        <div class="card">
          <div class="card-h"><h3>Pull requests</h3><span class="muted small">GitHub e Azure DevOps</span><span class="spacer"></span>
            <Menu small={false} items={TEMPLATES.map(t => ({ label: t.label, onclick: () => (edit = { kind: "pr", rule: blankRule(t.rule), isNew: true }) }))}>
              {#snippet trigger()}<span class="btn sm">Modelos</span>{/snippet}</Menu>
            <button class="btn sm primary" onclick={() => (edit = { kind: "pr", rule: blankRule(), isNew: true })}><Plus size={14} /> Nova regra</button></div>
          {#each s.rules.rules as r, i (r.id)}
            {@const a = ACTIONS[r.action]}
            {@const st = s.ruleStats[r.id]}
            {@const prot = r.targets.filter(t => s.rules.protectedTargets.map(x => x.toLowerCase()).includes(t.toLowerCase()))}
            <div class="rule" class:off={!r.enabled}>
              <Switch checked={r.enabled} onchange={(v) => saveRules({ rules: s.rules.rules.map(x => x.id === r.id ? { ...x, enabled: v } : x) }, v ? "Regra ativada" : "Regra desativada")} />
              <button class="body" onclick={() => (edit = { kind: "pr", rule: r, isNew: false })}>
                <div class="top"><span class="prio">{i + 1}</span>{#if r.name}<b>{r.name}</b>{/if}<span class="pill {a.cls}">{a.icon} {a.label}{(r.action === "approve" || r.action === "review") && r.requireBuild ? " · após build verde" : ""}{r.action === "review" && r.aiApprove === false ? " · só comenta" : ""}{r.action === "review" && r.aiMine ? " · inclui as minhas" : ""}</span>
                  {#if prot.length && (r.action === "approve" || (r.action === "review" && r.aiApprove !== false))}<span class="pill warn"><Lock size={10} /> aprova {prot.join(", ")}</span>{/if}</div>
                <div class="sentence">{@html ruleSentence(r)}</div>
                <div class="stats">{st ? `${st.count} ${a.done} nos últimos 30 dias · última há ${ago(st.last)}` : r.action === "notify" ? "avisos não entram no histórico" : "ainda não agiu"}
                  {#if s.prs.filter(p => p.ruleId === r.id && !p.archived).length} · <b>{s.prs.filter(p => p.ruleId === r.id && !p.archived).length}</b> aberta(s) agora{/if}</div>
              </button>
              <div class="ra">
                <button class="btn sm ghost icon" disabled={!i} onclick={() => saveRules({ rules: move(s.rules.rules, i, -1) }, "Prioridade alterada")} title="Subir"><ArrowUp size={14} /></button>
                <button class="btn sm ghost icon" disabled={i === s.rules.rules.length - 1} onclick={() => saveRules({ rules: move(s.rules.rules, i, 1) }, "Prioridade alterada")} title="Descer"><ArrowDown size={14} /></button>
                <Menu items={[{ label: "Duplicar", icon: Copy, onclick: () => (edit = { kind: "pr", rule: { ...r, id: "", name: r.name ? r.name + " (cópia)" : "" }, isNew: true }) },
                  { label: "Excluir", icon: Trash2, danger: true, onclick: async () => { if (await ui.ask({ title: "Excluir esta regra?", confirm: "Excluir", danger: true })) saveRules({ rules: s.rules.rules.filter(x => x.id !== r.id) }, "Regra excluída"); } }]} />
              </div>
            </div>
          {:else}
            <Empty title="Nenhuma regra de PR" text="Comece por um modelo.">{#each TEMPLATES as t (t.label)}<button class="btn sm" onclick={() => (edit = { kind: "pr", rule: blankRule(t.rule), isNew: true })}>{t.label}</button>{/each}</Empty>
          {/each}
        </div>

        <div class="card">
          <div class="card-h"><h3>Deploys e permissões</h3><span class="muted small">Releases, environments e pipelines</span><span class="spacer"></span>
            <Menu small={false} items={DTEMPLATES.map(t => ({ label: t.label, onclick: () => (edit = { kind: "deploy", rule: blankDRule(t.rule), isNew: true }) }))}>
              {#snippet trigger()}<span class="btn sm">Modelos</span>{/snippet}</Menu>
            <button class="btn sm primary" onclick={() => (edit = { kind: "deploy", rule: blankDRule(), isNew: true })}><Plus size={14} /> Nova regra</button></div>
          {#each s.rules.deployRules as r, i (r.id)}
            {@const a = DACTIONS[r.kind][r.action]}
            {@const st = s.ruleStats[r.id]}
            {@const risky = r.kind === "release" && r.action === "approve" && !r.requirePrApproved && (!r.stages.length || r.stages.some(x => /prod/i.test(x)))}
            <div class="rule" class:off={!r.enabled}>
              <Switch checked={r.enabled} onchange={(v) => saveRules({ deployRules: s.rules.deployRules.map(x => x.id === r.id ? { ...x, enabled: v } : x) }, v ? "Regra ativada" : "Regra desativada")} />
              <button class="body" onclick={() => (edit = { kind: "deploy", rule: r, isNew: false })}>
                <div class="top"><span class="prio">{i + 1}</span>{#if r.name}<b>{r.name}</b>{/if}<span class="pill {r.action === 'approve' ? 'good' : 'accent'}">{r.kind === "permission" ? "🔑" : "🚀"} {a.label}</span>
                  {#if risky}<span class="pill warn"><Lock size={10} /> pode subir para produção</span>{/if}</div>
                <div class="sentence">{@html dRuleSentence(r)}</div>
                <div class="stats">{st ? `${st.count} vez(es) nos últimos 30 dias · última há ${ago(st.last)}` : r.action === "notify" ? "avisos não entram no histórico" : "ainda não agiu"}</div>
              </button>
              <div class="ra">
                <button class="btn sm ghost icon" disabled={!i} onclick={() => saveRules({ deployRules: move(s.rules.deployRules, i, -1) }, "Prioridade alterada")}><ArrowUp size={14} /></button>
                <button class="btn sm ghost icon" disabled={i === s.rules.deployRules.length - 1} onclick={() => saveRules({ deployRules: move(s.rules.deployRules, i, 1) }, "Prioridade alterada")}><ArrowDown size={14} /></button>
                <Menu items={[{ label: "Duplicar", icon: Copy, onclick: () => (edit = { kind: "deploy", rule: { ...r, id: "", name: r.name ? r.name + " (cópia)" : "" }, isNew: true }) },
                  { label: "Excluir", icon: Trash2, danger: true, onclick: async () => { if (await ui.ask({ title: "Excluir esta regra?", confirm: "Excluir", danger: true })) saveRules({ deployRules: s.rules.deployRules.filter(x => x.id !== r.id) }, "Regra excluída"); } }]} />
              </div>
            </div>
          {:else}
            <Empty title="Nenhuma regra de deploy" text="Deploys e permissões esperam o seu clique na Fila.">{#each DTEMPLATES as t (t.label)}<button class="btn sm" onclick={() => (edit = { kind: "deploy", rule: blankDRule(t.rule), isNew: true })}>{t.label}</button>{/each}</Empty>
          {/each}
        </div>
      </div>

      <div class="col scroll">
        <div class="card">
          <div class="card-h"><h3>Branches protegidas</h3></div>
          <div class="card-b">
            <div class="chips">{#each s.rules.protectedTargets as t (t)}<span class="tag"><Lock size={11} /> {t}<button aria-label="Remover" onclick={() => saveRules({ protectedTargets: s.rules.protectedTargets.filter(x => x !== t) }, `${t} não é mais protegida`)}><X size={11} /></button></span>{/each}</div>
            <input class="input" style="margin-top:10px" bind:value={newProt} placeholder="+ adicionar (Enter)"
              onkeydown={(e) => { if (e.key === "Enter" && newProt.trim()) { saveRules({ protectedTargets: [...s.rules.protectedTargets, newProt.trim()] }, `${newProt} agora é protegida`); newProt = ""; } }} />
            <p class="small muted">Regras com “qualquer branch” ou curinga nunca agem nelas. Para automatizar uma delas, escolha-a explicitamente na regra.</p>
          </div>
        </div>
        <div class="card">
          <div class="card-h"><h3>Comportamento</h3><span class="muted small">salva na hora</span></div>
          <div class="card-b settings">
            <Switch checked={!s.rules.settings.paused} onchange={(v) => setSetting("paused", !v)} label="Automação ativa" hint="Desligada, nenhuma regra age — o app continua funcionando." />
            {#each behaviors as b (b.id)}<Switch checked={s.rules.settings[b.id]} onchange={(v) => setSetting(b.id, v)} label={b.label} hint={b.hint} />{/each}
          </div>
        </div>
      </div>
    </div>
  {/if}
</Page>

{#if edit?.kind === "pr"}<RuleEditor rule={edit.rule} isNew={edit.isNew} onclose={close} />{/if}
{#if edit?.kind === "deploy"}<DeployRuleEditor rule={edit.rule} isNew={edit.isNew} onclose={close} />{/if}

<style>
  .layout { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) minmax(300px, 360px); gap: 14px; }
  @media (max-width: 1180px) { .layout { grid-template-columns: minmax(0, 1fr); } }
  .scroll { min-height: 0; overflow: auto; overscroll-behavior: contain; display: flex; flex-direction: column; gap: 14px; padding-right: 2px; }
  .rule { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 14px; align-items: center; padding: 14px 16px; border-top: 1px solid var(--line); }
  .card-h + .rule { border-top: 0; }
  .rule.off .body { opacity: 0.5; }
  .body { border: 0; background: none; color: var(--text); text-align: left; cursor: pointer; font: inherit; min-width: 0; padding: 0; }
  .body:hover .sentence { color: var(--accent); }
  .top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 5px; }
  .prio { width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center; background: var(--surface-2); border: 1px solid var(--line-2); font-size: 11px; color: var(--text-2); font-weight: 650; }
  .sentence { font-size: 14px; line-height: 1.5; transition: color var(--t); }
  .sentence :global(b) { font-weight: 650; }
  .stats { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .ra { display: flex; gap: 2px; align-items: center; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .tag { display: inline-flex; align-items: center; gap: 5px; padding: 4px 4px 4px 10px; border-radius: 99px; background: var(--warn-soft); color: var(--warn); font-size: 13px; font-weight: 600; }
  .tag button { border: 0; background: none; color: inherit; cursor: pointer; display: grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; }
  .settings { display: grid; gap: 14px; }
  p { margin: 10px 0 0; }
</style>
