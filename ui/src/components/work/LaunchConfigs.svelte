<script lang="ts">
  // Configurações de execução do projeto: as detectadas, as do .vscode/launch.json e as salvas no app — editar (no
  // formato do launch.json), personalizar uma detectada, compor várias (iniciar juntas), ocultar, e a ponte com o VS
  // Code: ler ao vivo, sincronizar (o launch.json vira a fonte), importar e exportar (com as tarefas de compilação).
  import { ArrowDownToLine, ArrowUpFromLine, Copy, Eye, EyeOff, FileJson, Layers, Pencil, Play, Plus, Trash2 } from "@lucide/svelte";
  import { get, post } from "../../lib/api";
  import { debug, KIND_LABEL, type LaunchCfg } from "../../lib/debug.svelte";
  import { ui } from "../../lib/ui.svelte";
  import Drawer from "../Drawer.svelte";

  let { repoId, taskId = null, onclose, onopenfile }: { repoId: string; taskId?: string | null; onclose: () => void; onopenfile: (path: string) => void } = $props();
  const k = $derived(debug.key(repoId, taskId));
  const L = $derived(debug.lists[k]);
  const list = $derived(L?.configs || []);
  const bySource = $derived([
    ["codeck", "Salvas no Codeck", list.filter(c => c.source === "codeck")],
    ["vscode", "VS Code (.vscode/launch.json)", list.filter(c => c.source === "vscode")],
    ["detected", "Detectadas no projeto", list.filter(c => c.source === "detected")],
  ] as [string, string, LaunchCfg[]][]);
  let busy = $state(false);

  async function setSync(sync: string) {
    try { await post("launch/settings", { repoId, sync }); await debug.load(repoId, taskId); ui.toast(sync === "vscode" ? "Sincronizando com o .vscode/launch.json" : sync === "off" ? "O launch.json será ignorado" : "Lendo o launch.json automaticamente"); }
    catch (e) { ui.error(e); }
  }
  // ------------------------------------------------------------ exportar / importar
  let picked = $state<Record<string, boolean>>({});
  const exportable = $derived(list.filter(c => c.source !== "vscode" && !c.type.startsWith("codeck-")));
  async function exportVs() {
    const ids = Object.keys(picked).filter(x => picked[x]);
    const pv = await get<{ launchExists: boolean; comments: boolean; count: number }>("launch/export-preview", { repoId, taskId });
    const n = ids.length || "as principais";
    if (!(await ui.ask({ title: "Exportar para o VS Code?", confirm: "Exportar",
      message: `Grava ${n} configuração(ões) no .vscode/launch.json${pv.launchExists ? " (substitui as de mesmo nome e mantém as outras)" : ""} e as tarefas de compilação no tasks.json.`
        + (pv.comments ? " Atenção: os comentários desses arquivos não são mantidos." : "") }))) return;
    busy = true;
    try {
      const r = await post<{ configurations: number; compounds: number; tasks: number }>("launch/export", { repoId, taskId, ids: ids.length ? ids : null });
      ui.toast(`${r.configurations} configuração(ões)${r.tasks ? ` e ${r.tasks} tarefa(s)` : ""} no .vscode`);
      picked = {};
      await debug.load(repoId, taskId);
    } catch (e) { ui.error(e); }
    busy = false;
  }
  async function importVs() {
    busy = true;
    try { const r = await post<{ configurations: number }>("launch/import", { repoId, taskId }); ui.toast(`${r.configurations} configuração(ões) importada(s) para o app`); await debug.load(repoId, taskId); }
    catch (e) { ui.error(e); }
    busy = false;
  }

  // ------------------------------------------------------------ editar
  const TEMPLATES: Record<string, { label: string; cfg: any }> = {
    dotnet: { label: ".NET (projeto)", cfg: { type: "coreclr", request: "launch", preLaunchTask: "", program: "${workspaceFolder}/src/Api/bin/Debug/net8.0/Api.dll", args: [], cwd: "${workspaceFolder}/src/Api",
      env: { ASPNETCORE_ENVIRONMENT: "Development", ASPNETCORE_URLS: "http://localhost:5000" }, serverReadyAction: { action: "openExternally", pattern: "\\bNow listening on:\\s+(https?://\\S+)", uriFormat: "%s/swagger" } } },
    npm: { label: "Node / script do npm (Nest, Next, Vite…)", cfg: { type: "node-terminal", request: "launch", command: "npm run start:dev", cwd: "${workspaceFolder}" } },
    node: { label: "Node (arquivo)", cfg: { type: "node", request: "launch", program: "${workspaceFolder}/dist/main.js", cwd: "${workspaceFolder}", envFile: "${workspaceFolder}/.env" } },
    chrome: { label: "Navegador (Chrome) — front-end", cfg: { type: "chrome", request: "launch", url: "http://localhost:3000", webRoot: "${workspaceFolder}" } },
    flutter: { label: "Flutter", cfg: { type: "dart", request: "launch", program: "lib/main.dart", cwd: "${workspaceFolder}", toolArgs: [] } },
    shell: { label: "Comando do terminal (sem depurador)", cfg: { type: "codeck-shell", request: "launch", command: "make run", cwd: "${workspaceFolder}" } },
  };
  let edit = $state<{ oldName: string | null; name: string; json: string; err: string | null; source: string } | null>(null);
  function newCfg(t: string) {
    const c = TEMPLATES[t].cfg;
    edit = { oldName: null, name: "", json: JSON.stringify(c, null, 2), err: null, source: "codeck" };
  }
  async function openEdit(c: LaunchCfg, copyIt = false) {
    try {
      const r = await get<{ config?: any; compound?: any; source: string }>("launch/raw", { repoId, taskId, id: c.id });
      if (r.compound) { comp = { oldName: r.compound.name, name: r.compound.name, names: [...(r.compound.configurations || [])] }; return; }
      const { name, ...rest } = r.config;
      edit = { oldName: copyIt ? null : name, name: copyIt && r.source === "detected" ? name : copyIt ? `${name} (cópia)` : name, json: JSON.stringify(rest, null, 2), err: null,
        source: copyIt ? "codeck" : r.source };
    } catch (e) { ui.error(e); }
  }
  async function saveEdit() {
    if (!edit) return;
    let cfg: any;
    try { cfg = JSON.parse(edit.json); } catch (e: any) { edit.err = `JSON inválido: ${e.message}`; return; }
    if (!edit.name.trim()) { edit.err = "Dê um nome"; return; }
    busy = true;
    try {
      const r = await post<{ id: string }>("launch/save", { repoId, taskId, config: { ...cfg, name: edit.name.trim() }, oldName: edit.oldName });
      await debug.load(repoId, taskId);
      debug.select(repoId, r.id);
      ui.toast(L?.sync === "vscode" ? "Salvo no .vscode/launch.json" : "Configuração salva");
      edit = null;
    } catch (e) { if (edit) edit.err = (e as any)?.message || String(e); }
    busy = false;
  }
  async function remove(c: LaunchCfg) {
    const det = c.source === "detected";
    if (!det && !(await ui.ask({ title: `Excluir “${c.name}”?`, message: c.source === "vscode" ? "Sai do .vscode/launch.json." : "Sai das configurações salvas no app.", confirm: "Excluir", danger: true }))) return;
    try { await post("launch/delete", { repoId, taskId, id: c.id }); await debug.load(repoId, taskId); if (det) ui.toast("Oculta — “Mostrar ocultas” traz de volta"); }
    catch (e) { ui.error(e); }
  }
  let showHidden = $state(false);
  async function unhide(id: string) {
    try { await post("launch/settings", { repoId, hidden: (L?.hidden || []).filter(x => x !== id) }); await debug.load(repoId, taskId); } catch (e) { ui.error(e); }
  }

  // ------------------------------------------------------------ composta (iniciar várias juntas, como "vários projetos de inicialização")
  let comp = $state<{ oldName: string | null; name: string; names: string[] } | null>(null);
  async function saveComp() {
    if (!comp) return;
    busy = true;
    try {
      const r = await post<{ id: string }>("launch/compound", { repoId, taskId, name: comp.name, names: comp.names, oldName: comp.oldName });
      await debug.load(repoId, taskId); debug.select(repoId, r.id); comp = null; ui.toast("Composta salva");
    } catch (e) { ui.error(e); }
    busy = false;
  }
  const SRC = { detected: "detectada", vscode: "launch.json", codeck: "app" } as Record<string, string>;
</script>

<Drawer title="Configurações de execução" subtitle="O que o ▶ inicia neste projeto — no formato do launch.json do VS Code" {onclose} width={720}>
  <div class="lc">
    <section class="sync">
      <h4>VS Code</h4>
      <div class="seg" role="radiogroup" aria-label="Sincronização com o VS Code">
        {#each [["auto", "Ler o launch.json", "Lê ao vivo; o que você salva aqui fica no app"], ["vscode", "Sincronizar", "O .vscode/launch.json é a fonte: salvar aqui grava lá (e o que mudar lá aparece aqui)"], ["off", "Ignorar", "Não lê o launch.json"]] as [v, t, d] (v)}
          <button role="radio" aria-checked={L?.sync === v} class:on={L?.sync === v} title={d} onclick={() => setSync(v)}>{t}</button>
        {/each}
      </div>
      <p class="small muted">{L?.sync === "vscode" ? "Salvar aqui grava no .vscode/launch.json — o VS Code vê na hora, e o que você muda lá aparece aqui." : L?.sync === "off" ? "O launch.json deste projeto não entra na lista." : "O launch.json entra na lista ao vivo; o que você salva aqui fica no app (não suja o repositório)."}</p>
      <div class="row">
        <button class="btn sm" disabled={busy} onclick={exportVs} title="Grava no .vscode/launch.json (e as tarefas de compilação no tasks.json)"><ArrowUpFromLine size={13} /> Exportar para o VS Code{Object.values(picked).filter(Boolean).length ? ` (${Object.values(picked).filter(Boolean).length})` : ""}</button>
        <button class="btn sm" disabled={busy || !L?.vscode.launch} onclick={importVs} title="Copia as do launch.json para o app"><ArrowDownToLine size={13} /> Importar do VS Code</button>
        {#if L?.vscode.launch}<button class="btn sm ghost" onclick={() => { onopenfile(".vscode/launch.json"); onclose(); }}><FileJson size={13} /> Abrir launch.json</button>{/if}
      </div>
    </section>

    <section>
      <div class="row hd">
        <h4>Nova</h4>
        {#each Object.entries(TEMPLATES) as [t, x] (t)}<button class="btn sm ghost" onclick={() => newCfg(t)}><Plus size={12} /> {x.label}</button>{/each}
        <button class="btn sm ghost" onclick={() => (comp = { oldName: null, name: "", names: [] })}><Layers size={12} /> Composta (várias juntas)</button>
      </div>
    </section>

    {#if edit}
      <section class="ed">
        <h4>{edit.oldName ? `Editar “${edit.oldName}”` : "Nova configuração"} <span class="tiny muted">· {edit.source === "vscode" || L?.sync === "vscode" ? "grava no .vscode/launch.json" : "fica no app"}</span></h4>
        <label><span class="small muted">Nome</span><input class="input" bind:value={edit.name} placeholder="ex.: API (Local)" /></label>
        <label><span class="small muted">Configuração (JSON do launch.json — ${"{"}workspaceFolder{"}"}, env, envFile, args, preLaunchTask, serverReadyAction…)</span>
          <textarea class="input mono" rows="14" bind:value={edit.json} spellcheck="false"></textarea></label>
        {#if edit.err}<p class="small err">{edit.err}</p>{/if}
        <div class="row"><button class="btn sm primary" disabled={busy} onclick={saveEdit}>Salvar</button><button class="btn sm ghost" onclick={() => (edit = null)}>Cancelar</button></div>
      </section>
    {/if}
    {#if comp}
      <section class="ed">
        <h4>{comp.oldName ? `Editar “${comp.oldName}”` : "Nova composta"} <span class="tiny muted">· inicia todas juntas; parar para todas</span></h4>
        <label><span class="small muted">Nome</span><input class="input" bind:value={comp.name} placeholder="ex.: API + Front" /></label>
        <div class="picks">
          {#each list.filter(c => c.type !== "compound") as c (c.id)}
            <label class="pk"><input type="checkbox" checked={comp.names.includes(c.name)} onchange={() => comp && (comp.names = comp.names.includes(c.name) ? comp.names.filter(x => x !== c.name) : [...comp.names, c.name])} />
              {c.name} <span class="tiny muted">{c.group}</span></label>
          {/each}
        </div>
        <div class="row"><button class="btn sm primary" disabled={busy || comp.names.length < 2 || !comp.name.trim()} onclick={saveComp}>Salvar</button><button class="btn sm ghost" onclick={() => (comp = null)}>Cancelar</button></div>
      </section>
    {/if}

    {#each bySource as [src, title, items] (src)}
      {#if items.length || src !== "codeck"}
        <section>
          <h4>{title} <span class="tiny muted">{items.length}</span></h4>
          {#each items as c (c.id)}
            <div class="cfg" class:sel={debug.selected(repoId, taskId)?.id === c.id}>
              {#if src !== "vscode" && !c.type.startsWith("codeck-") && c.type !== "compound"}
                <input type="checkbox" title="Marcar para exportar" checked={!!picked[c.id]} onchange={() => (picked = { ...picked, [c.id]: !picked[c.id] })} />
              {:else}<span class="ph"></span>{/if}
              <button class="nm" onclick={() => debug.select(repoId, c.id)} title="Escolher como o ▶ (F5)">
                <b class="ell">{c.name}</b>
                <span class="tiny muted ell">{c.group}{c.detail ? " · " + c.detail : ""}</span>
              </button>
              <span class="chip">{KIND_LABEL[c.kind] || c.kind}</span>
              {#if !c.debug}<span class="chip warn" title={c.why || "Sem depurador para este tipo — executa sem depurar"}>sem depurador</span>{/if}
              <button class="ib" title="Depurar" onclick={() => debug.start(repoId, taskId, c.id)}><Play size={12} /></button>
              {#if src === "detected"}
                <button class="ib" title="Personalizar (copia para o app para editar)" onclick={() => openEdit(c, true)}><Pencil size={12} /></button>
                <button class="ib" title="Ocultar" onclick={() => remove(c)}><EyeOff size={12} /></button>
              {:else}
                <button class="ib" title="Editar" onclick={() => openEdit(c)}><Pencil size={12} /></button>
                {#if c.type !== "compound"}<button class="ib" title="Duplicar" onclick={() => openEdit(c, true)}><Copy size={12} /></button>{/if}
                <button class="ib danger" title="Excluir" onclick={() => remove(c)}><Trash2 size={12} /></button>
              {/if}
            </div>
          {:else}
            <p class="small muted none">{src === "vscode" ? (L?.sync === "off" ? "Ignorando o launch.json." : "Sem .vscode/launch.json — “Exportar para o VS Code” cria um com as configurações escolhidas.") : "Nada detectado. Crie uma acima."}</p>
          {/each}
        </section>
      {/if}
    {/each}
    {#if L?.hidden.length}
      <section>
        <button class="btn sm ghost" onclick={() => (showHidden = !showHidden)}><Eye size={12} /> {showHidden ? "Esconder" : "Mostrar"} ocultas ({L.hidden.length})</button>
        {#if showHidden}{#each L.hidden as h (h)}<div class="cfg"><span class="ph"></span><span class="nm"><span class="ell">{h.split(":").slice(1).join(":")}</span></span><button class="btn sm ghost" onclick={() => unhide(h)}>Mostrar</button></div>{/each}{/if}
      </section>
    {/if}
    <p class="tiny muted">Origem: {Object.values(SRC).join(" · ")}. Atalhos: F5 depurar · Ctrl+F5 sem depurar · Shift+F5 parar · F9 breakpoint · F10/F11 passo a passo.</p>
  </div>
</Drawer>

<style>
  .lc { display: grid; gap: 14px; }
  section { display: grid; gap: 6px; }
  h4 { margin: 0; font: 650 12px var(--font); color: var(--text); }
  .row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .row.hd h4 { margin-right: 4px; }
  .seg { display: inline-flex; gap: 2px; padding: 2px; border-radius: 9px; background: var(--bg-2); border: 1px solid var(--line); width: max-content; }
  .seg button { height: 26px; padding: 0 12px; border: 0; border-radius: 7px; background: none; color: var(--muted); font: 600 12px var(--font); cursor: pointer; }
  .seg button.on { background: var(--surface-3); color: var(--text); box-shadow: var(--shadow-1); }
  .ed { padding: 12px; border-radius: 10px; border: 1px solid var(--accent-line); background: var(--accent-soft); }
  .ed label { display: grid; gap: 4px; }
  textarea.mono { font: 12px/1.5 var(--mono); resize: vertical; }
  .err { color: var(--bad); margin: 0; }
  .picks { display: grid; gap: 2px; max-height: 240px; overflow: auto; padding: 4px; border-radius: 8px; background: var(--surface); border: 1px solid var(--line); }
  .pk { display: flex; align-items: center; gap: 7px; font-size: 12.5px; padding: 2px 4px; cursor: pointer; }
  .cfg { display: flex; align-items: center; gap: 6px; padding: 4px 6px; border-radius: 8px; }
  .cfg:hover { background: var(--surface-2); }
  .cfg.sel { background: color-mix(in srgb, var(--good) 9%, transparent); }
  .ph { width: 13px; flex: none; }
  .nm { display: grid; flex: 1; min-width: 0; border: 0; background: none; color: var(--text-2); text-align: left; padding: 0; cursor: pointer; font: 12.5px var(--font); }
  .nm b { color: var(--text); font-weight: 600; }
  .chip { padding: 1px 6px; border-radius: 5px; background: var(--surface-3); color: var(--text-2); font: 600 10.5px var(--font); flex: none; }
  .chip.warn { background: var(--warn-soft); color: var(--warn); }
  .ib { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; flex: none; }
  .ib:hover { background: var(--surface-3); color: var(--text); }
  .ib.danger:hover { color: var(--bad); }
  .none { margin: 0; padding-left: 4px; }
  .ell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
