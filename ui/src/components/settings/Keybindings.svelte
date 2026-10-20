<script lang="ts">
  // Configurações → Atalhos: todos os comandos (os do VS Code, com os mesmos atalhos), busca por nome, id ou tecla,
  // e trocar/adicionar/tirar atalho — clique em "+" e pressione as teclas (até duas, para um acorde como ⌘K ⌘F);
  // Enter confirma, Esc cancela. Avisa quando o atalho já é de outro comando.
  import { Plus, RotateCcw, Search, X } from "@lucide/svelte";
  import { COMMANDS, GROUPS, canonical, kb, showKey, strokeOf, type Command } from "../../lib/keybindings.svelte";
  import { kbd } from "../../lib/keys";
  import { ui } from "../../lib/ui.svelte";

  let q = $state("");
  let onlyCustom = $state(false);
  // gravando: para qual comando, as teclas até agora e qual atalho está sendo trocado (índice; null = novo)
  let rec = $state<{ id: string; strokes: string[]; replace: number | null } | null>(null);

  const SCOPE: Record<string, string> = { app: "", editor: "no editor", explorer: "no explorador" };
  const shown = $derived.by(() => {
    void kb.custom();
    const t = q.trim().toLowerCase();
    const keyQ = t.replace(/\s+/g, "");
    return COMMANDS.filter(c => {
      if (onlyCustom && !kb.isCustom(c.id)) return false;
      if (!t) return true;
      const keys = kb.keys(c.id).map(k => showKey(k).toLowerCase().replace(/\s+/g, "") + " " + k);
      return c.label.toLowerCase().includes(t) || c.id.toLowerCase().includes(t) || c.group.toLowerCase().includes(t) || keys.some(k => k.includes(keyQ) || k.includes(t));
    });
  });
  const byGroup = $derived(GROUPS.map(g => [g, shown.filter(c => c.group === g)] as const).filter(([, l]) => l.length));
  const customCount = $derived(Object.keys(kb.custom()).length);

  function start(c: Command, replace: number | null = null) { rec = { id: c.id, strokes: [], replace }; kb.recording = true; }
  function stop() { rec = null; kb.recording = false; }
  function commit() {
    const r = rec;
    if (!r || !r.strokes.length) return stop();
    const combo = r.strokes.join(" ");
    const keys = [...kb.keys(r.id)];
    if (r.replace === null) keys.push(combo); else keys[r.replace] = combo;
    kb.set(r.id, keys);
    stop();
  }
  function removeKey(c: Command, i: number) { kb.set(c.id, kb.keys(c.id).filter((_, j) => j !== i)); }
  async function resetAll() {
    if (!(await ui.ask({ title: "Voltar todos os atalhos ao padrão?", message: `${customCount} comando${customCount === 1 ? "" : "s"} personalizado${customCount === 1 ? "" : "s"} volta${customCount === 1 ? "" : "m"} ao atalho do VS Code.`, confirm: "Restaurar", danger: true }))) return;
    kb.resetAll();
  }
  // enquanto grava, as teclas não chegam ao app (nem ao Monaco)
  $effect(() => {
    if (!rec) return;
    const onKey = (e: KeyboardEvent) => {
      const r = rec;
      if (!r) return;
      e.preventDefault(); e.stopPropagation();
      if (e.key === "Escape" && !r.strokes.length) return stop();
      if (e.key === "Enter" && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey && r.strokes.length) return commit();
      const s = strokeOf(e);
      if (!s) return;
      rec = { ...r, strokes: r.strokes.length >= 2 ? [s] : [...r.strokes, s] };
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });
  const conflicts = $derived(rec?.strokes.length ? kb.usedBy(rec.strokes.join(" "), rec.id) : []);
  const prefixOf = $derived(rec?.strokes.length === 1 ? COMMANDS.filter(c => c.id !== rec!.id && kb.keys(c.id).some(k => canonical(k).startsWith(canonical(rec!.strokes[0]) + " "))) : []);
</script>

<div class="kb">
  <div class="bar">
    <label class="flt"><Search size={14} /><input bind:value={q} placeholder="Buscar comando, id ou tecla (ex.: ⌘⇧P, format, ctrl+g)…" />
      {#if q}<button class="x" aria-label="Limpar" onclick={() => (q = "")}><X size={11} /></button>{/if}</label>
    <label class="chk small"><input type="checkbox" bind:checked={onlyCustom} /> Só os personalizados{customCount ? ` (${customCount})` : ""}</label>
    <button class="btn sm ghost" disabled={!customCount} onclick={resetAll}><RotateCcw size={13} /> Restaurar padrões</button>
  </div>
  <p class="tiny muted hint">Os mesmos atalhos do VS Code. Clique em <b>+</b> e pressione as teclas — duas seguidas viram um acorde ({kbd("mod+k")} {kbd("mod+f")}); <b>Enter</b> confirma, <b>Esc</b> cancela. Clique num atalho para trocá-lo.</p>

  {#each byGroup as [g, list] (g)}
    <div class="card org grp">
      <h4>{g}</h4>
      {#each list as c (c.id)}
        <div class="row" class:custom={kb.isCustom(c.id)}>
          <div class="nm"><span>{c.label}</span>{#if SCOPE[c.scope]}<span class="tiny muted"> · {SCOPE[c.scope]}</span>{/if}<span class="id tiny mono">{c.id}</span></div>
          <div class="keys">
            {#each kb.keys(c.id) as k, i (k + i)}
              {#if rec?.id === c.id && rec.replace === i}
                <span class="kbd rec">{rec.strokes.length ? rec.strokes.map(s => kbd(s)).join(" ") : "Pressione…"}</span>
              {:else}
                <span class="chip"><button class="kbd" title="Trocar este atalho" onclick={() => start(c, i)}>{showKey(k)}</button><button class="rm" title="Tirar este atalho" onclick={() => removeKey(c, i)}><X size={10} /></button></span>
              {/if}
            {/each}
            {#if rec?.id === c.id && rec.replace === null}
              <span class="kbd rec">{rec.strokes.length ? rec.strokes.map(s => kbd(s)).join(" ") : "Pressione…"}</span>
            {/if}
            {#if rec?.id === c.id}
              <button class="btn sm" disabled={!rec.strokes.length} onclick={commit}>OK</button><button class="btn sm ghost" onclick={stop}>Cancelar</button>
            {:else}
              <button class="ib" title="Adicionar um atalho" onclick={() => start(c)}><Plus size={13} /></button>
              {#if kb.isCustom(c.id)}<button class="ib" title={`Voltar ao padrão (${kb.defaults(c.id).map(showKey).join(", ") || "sem atalho"})`} onclick={() => kb.reset(c.id)}><RotateCcw size={12} /></button>{/if}
            {/if}
          </div>
          {#if rec?.id === c.id && (conflicts.length || prefixOf.length)}
            <div class="warn tiny">
              {#if conflicts.length}Também é de: {conflicts.map(x => x.label).join(", ")} — no mesmo lugar, vale o primeiro que puder agir.{/if}
              {#if prefixOf.length} Começa acordes de: {prefixOf.slice(0, 3).map(x => x.label).join(", ")}{prefixOf.length > 3 ? "…" : ""} (aperte a 2ª tecla ou confirme).{/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {:else}
    <div class="none small muted">Nenhum comando com “{q}”.</div>
  {/each}

  <div class="card org grp">
    <h4>Fixos</h4>
    <div class="row"><div class="nm">Depuração: alternar breakpoint na linha</div><div class="keys"><span class="kbd">F9</span></div></div>
    <div class="row"><div class="nm">Revisão da tarefa: comentar a linha</div><div class="keys"><span class="kbd">{kbd("mod+shift+c")}</span></div></div>
    <div class="row"><div class="nm">Hub de projetos: abrir sem sair do hub</div><div class="keys"><span class="kbd">{kbd("mod+enter")}</span></div></div>
  </div>
</div>

<style>
  .kb { display: grid; gap: 12px; }
  .bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .flt { flex: 1; min-width: 240px; display: flex; align-items: center; gap: 7px; height: 32px; padding: 0 8px 0 10px; border-radius: 8px; border: 1px solid var(--line-2);
    background: var(--bg-2); color: var(--muted); }
  .flt:focus-within { border-color: var(--accent); }
  .flt input { flex: 1; min-width: 0; border: 0; outline: none; background: none; color: var(--text); font: 13px var(--font); }
  .x { display: grid; place-items: center; width: 16px; height: 16px; border: 0; border-radius: 50%; background: var(--surface-3); color: var(--text-2); cursor: pointer; }
  .chk { display: inline-flex; align-items: center; gap: 6px; color: var(--text-2); cursor: pointer; }
  .hint { margin: -4px 0 0; }
  .grp h4 { margin: 0 0 6px; }
  .row { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 4px 12px; padding: 5px 0; border-top: 1px solid var(--line); }
  .row:first-of-type { border-top: 0; }
  .row.custom .nm > span:first-child { color: var(--accent); }
  .nm { min-width: 0; font-size: 13px; color: var(--text); }
  .id { display: block; color: var(--faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .keys { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; justify-content: flex-end; }
  .chip { display: inline-flex; align-items: center; }
  .chip .kbd { cursor: pointer; border: 1px solid var(--line-2); font: inherit; }
  .chip .kbd:hover { border-color: var(--accent); }
  .rm { display: grid; place-items: center; width: 16px; height: 16px; margin-left: 1px; border: 0; border-radius: 50%; background: none; color: var(--faint); cursor: pointer; opacity: 0; }
  .chip:hover .rm, .rm:focus-visible { opacity: 1; }
  .rm:hover { color: var(--danger, #ff6b7d); background: var(--surface-3); }
  .kbd.rec { border: 1px dashed var(--accent); color: var(--accent); min-width: 80px; text-align: center; }
  .ib { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; }
  .ib:hover { background: var(--surface-3); color: var(--text); }
  .warn { grid-column: 1 / -1; padding: 5px 8px; border-radius: 6px; background: var(--warn-soft); color: var(--text-2); }
  .none { padding: 10px 2px; }
</style>
