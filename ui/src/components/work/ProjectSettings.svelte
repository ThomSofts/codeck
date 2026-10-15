<script lang="ts">
  // Ajustes do projeto (projeto = repositório): os agentes (conta de IA e pular permissões), o que copiar para cada
  // worktree (arquivos locais que o Git não leva), a preparação, os repositórios relacionados e o shell.
  import { Plus, ShieldOff, X } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { post } from "../../lib/api";
  import { ui } from "../../lib/ui.svelte";
  import type { Project } from "../../lib/work.svelte";
  import { work } from "../../lib/work.svelte";
  import { repos } from "../../lib/repos.svelte";
  import Drawer from "../Drawer.svelte";
  import Switch from "../Switch.svelte";

  let { project, onclose }: { project: Project; onclose: () => void } = $props();
  const s0 = untrack(() => project.settings);
  let copy = $state<string[]>([...(s0.copy || [])]);
  let setup = $state(s0.setup || "");
  let shell = $state((s0 as any).shell || "");
  let addDirs = $state<string[]>([...((s0 as any).addDirs || [])]);
  let bypass = $state(!!s0.bypass);
  let account = $state<string>(untrack(() => work.defaultAccount(project) || ""));
  // só grava a conta se ela mudou aqui: salvar outro ajuste não pode fixar o padrão da organização no projeto
  const account0 = untrack(() => account);
  let novo = $state("");
  let relQ = $state("");
  // relacionados = outros repositórios da sua lista (sem os worktrees das tarefas)
  const isWt = (p: string) => /[\\/]\.worktrees[\\/]/.test(p);
  const related = $derived(repos.local.filter(r => addDirs.includes(r.path)));
  const candidates = $derived(repos.local.filter(r => r.exists && r.id !== project.id && !isWt(r.path) && !addDirs.includes(r.path)
    && r.name.toLowerCase().includes(relQ.trim().toLowerCase())).slice(0, 12));
  let busy = $state(false);
  const SUGGEST = ["workspace.local.json", "nuget.config", ".env", ".env.local", "**/appsettings.Development.json", "**/appsettings.Local.json",
    ".claude/settings.local.json", ".vscode/settings.json", "*.pem", "*.p12"];

  async function save() {
    busy = true;
    try {
      await post("ws/settings", { repoId: project.id, copy, setup, shell, addDirs, bypass, ...(account && account !== account0 ? { account } : {}) });
      await work.load();
      ui.toast("Ajustes do projeto salvos");
      onclose();
    } catch (e) { ui.error(e); }
    busy = false;
  }
  const add = (p: string) => { p = p.trim(); if (p && !copy.includes(p)) copy = [...copy, p]; novo = ""; };
</script>

<Drawer title={`Ajustes de ${project.name}`} subtitle="Valem para as próximas tarefas e terminais deste projeto" {onclose} width={560}>
  <div class="form">
    <section>
      <h4>Agentes de IA</h4>
      <label class="acc"><span class="small muted">Conta deste projeto</span>
        <select class="input" bind:value={account}>
          {#each work.ai.filter(a => a.installed) as a (a.id)}<option value={a.id}>{a.label} · {a.name}{a.email ? ` (${a.email})` : ""}</option>{/each}
        </select></label>
      <p class="small muted">Vem marcada no “Pedir à IA” e no “Abrir agente”. Muda sozinha para a última conta usada neste projeto.</p>
      <div class="byp" class:on={bypass}>
        <Switch bind:checked={bypass} label="Pular permissões (bypass)"
          hint="Os agentes abertos neste projeto — pedido, tarefa nova, cartão do quadro — editam arquivos e rodam comandos sem perguntar." />
        {#if bypass}<p class="small warn"><ShieldOff size={12} /> Só ligue em repositório em que você confia: o agente pode apagar arquivos, instalar pacotes e fazer push sem confirmação.
          Claude Code: <span class="mono">--dangerously-skip-permissions</span> (no “Planejar”, o plano continua esperando sua aprovação) · Codex: <span class="mono">--dangerously-bypass-approvals-and-sandbox</span> ·
          Gemini: <span class="mono">--yolo</span> · Cursor: <span class="mono">--force</span> · OpenCode: sem flag (use o <span class="mono">opencode.json</span>).</p>{/if}
      </div>
    </section>
    <section>
      <h4>Copiar para cada worktree</h4>
      <p class="small muted">Arquivos locais que o Git não leva e sem os quais o projeto não roda. Aceita padrões (<span class="mono">**/appsettings.Development.json</span>).
        Os copiados entram no exclude do Git — nunca vão para commit.</p>
      <div class="chips">{#each copy as c (c)}<span class="chip mono">{c}<button aria-label="Tirar" onclick={() => (copy = copy.filter(x => x !== c))}><X size={11} /></button></span>{/each}</div>
      <div class="row"><input class="input mono" bind:value={novo} placeholder="ex.: config/local.json" onkeydown={(e) => e.key === "Enter" && add(novo)} />
        <button class="btn" disabled={!novo.trim()} onclick={() => add(novo)}><Plus size={14} /></button></div>
      <div class="sugg">{#each SUGGEST.filter(x => !copy.includes(x)) as s (s)}<button class="pill neutral" onclick={() => add(s)}>+ {s}</button>{/each}</div>
    </section>
    <section>
      <h4>Preparação</h4>
      <p class="small muted">Roda num terminal quando a tarefa é criada (ex.: <span class="mono">npm ci</span>, <span class="mono">bash .claude/scripts/ws-dotnet.sh restore</span>).</p>
      <textarea class="input mono" rows="3" bind:value={setup} placeholder="vazio = nada"></textarea>
    </section>
    <section>
      <h4>Repositórios relacionados</h4>
      <p class="small muted">Outros repositórios que o agente pode ler e editar junto com este (ex.: a lib de entidades e a de infra). No Claude vira <span class="mono">--add-dir</span>.</p>
      <div class="chips">{#each related as r (r.id)}<span class="chip">{r.name}<button aria-label="Tirar" onclick={() => (addDirs = addDirs.filter(x => x !== r.path))}><X size={11} /></button></span>{/each}</div>
      <input class="input" bind:value={relQ} placeholder="buscar repositório…" />
      {#if relQ.trim()}<div class="sugg">{#each candidates as r (r.id)}<button class="pill neutral" onclick={() => { addDirs = [...addDirs, r.path]; relQ = ""; }}>+ {r.name}</button>{/each}</div>{/if}
    </section>
    <section>
      <h4>Shell dos terminais</h4>
      <input class="input mono" bind:value={shell} placeholder="padrão do sistema (ex.: /bin/zsh, pwsh, bash)" />
    </section>
  </div>
  {#snippet footer()}
    <span class="spacer"></span>
    <button class="btn" onclick={onclose}>Cancelar</button>
    <button class="btn primary" disabled={busy} onclick={save}>Salvar</button>
  {/snippet}
</Drawer>

<style>
  .form { display: grid; gap: 18px; padding-top: 12px; }
  section { display: grid; gap: 8px; }
  h4 { margin: 0; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
  p { margin: 0; }
  .row { display: flex; gap: 6px; }
  .row .input { flex: 1; }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; }
  .chip { display: inline-flex; align-items: center; gap: 5px; padding: 3px 4px 3px 9px; border-radius: 99px; background: var(--surface-2); border: 1px solid var(--line-2); font-size: 12px; }
  .chip button { display: grid; place-items: center; width: 16px; height: 16px; border: 0; border-radius: 50%; background: none; color: var(--muted); cursor: pointer; }
  .chip button:hover { background: var(--surface-3); color: var(--text); }
  .sugg { display: flex; flex-wrap: wrap; gap: 4px; }
  .sugg .pill { cursor: pointer; border: 1px dashed var(--line-3); }
  textarea { resize: vertical; height: auto; font-size: 12.5px; padding: 8px 10px; }
  .spacer { flex: 1; }
  .acc { display: grid; gap: 5px; }
  .byp { display: grid; gap: 8px; padding: 10px 12px; border-radius: var(--r-sm); border: 1px solid var(--line-2); transition: border-color var(--t), background var(--t); }
  .byp.on { border-color: color-mix(in srgb, var(--warn) 45%, transparent); background: var(--warn-soft); }
  .byp .warn { color: var(--text-2); line-height: 1.5; }
  .byp .warn :global(svg) { color: var(--warn); vertical-align: -2px; }
</style>
