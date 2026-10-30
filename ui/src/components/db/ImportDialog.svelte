<script lang="ts">
  // Importar conexões do DBeaver, Tabularis e Beekeeper: lista o que achou, você marca, e o Codeck cria um banco por
  // conexão (a pasta/grupo vira a pasta). Senhas só se você pedir — vão direto para o cofre.
  import { Download, ShieldCheck } from "@lucide/svelte";
  import { onMount } from "svelte";
  import { get, post } from "../../lib/api";
  import { db, ENGINE_SHORT, type Engine } from "../../lib/db.svelte";
  import { ui } from "../../lib/ui.svelte";
  import Drawer from "../Drawer.svelte";
  import Switch from "../Switch.svelte";

  let { onclose }: { onclose: () => void } = $props();
  type Item = { source: string; id: string; name: string; engine: Engine | null; folder: string; kind: string; host: string; port: number | null;
    database: string; user: string; file: string; hasPassword: boolean; supported: boolean; already: boolean; driver?: string; tls: { mode: string; legacy: boolean } };
  let items = $state<Item[] | null>(null);
  let found = $state<Record<string, boolean>>({});
  let picked = $state<Set<string>>(new Set());
  let passwords = $state(true);
  let busy = $state(false);
  const k = (i: Item) => i.source + ":" + i.id;
  const LABEL: Record<string, string> = { dbeaver: "DBeaver", tabularis: "Tabularis", beekeeper: "Beekeeper Studio" };

  onMount(async () => {
    try {
      const r = await get("db/import");
      items = r.items; found = r.found;
      picked = new Set(r.items.filter((i: Item) => i.supported && !i.already).map(k));
    } catch (e) { ui.error(e); items = []; }
  });

  async function run() {
    busy = true;
    try {
      const sel = (items || []).filter(i => picked.has(k(i))).map(i => ({ source: i.source, id: i.id }));
      if (passwords && sel.some(s => s.source === "tabularis"))
        ui.toast("O macOS vai perguntar se o Codeck pode ler cada senha do Tabularis — escolha Permitir", "info");
      const r = await post("db/import", { items: sel, passwords });
      db.set(r);
      ui.toast(`${r.created} ${r.created === 1 ? "banco importado" : "bancos importados"}${r.noPassword.length ? ` — sem senha: ${r.noPassword.slice(0, 3).join(", ")}${r.noPassword.length > 3 ? "…" : ""}` : ""}`);
      onclose();
    } catch (e) { ui.error(e); } finally { busy = false; }
  }
</script>

<Drawer title="Importar conexões" subtitle="DBeaver, Tabularis e Beekeeper Studio — só leitura dos arquivos deles" {onclose} width={720}>
  {#if !items}
    <p class="muted">Procurando…</p>
  {:else if !items.length}
    <p class="muted">Nenhuma conexão encontrada{Object.values(found).some(Boolean) ? "" : " (DBeaver, Tabularis e Beekeeper não estão instalados neste usuário)"}.</p>
  {:else}
    {#each ["dbeaver", "tabularis", "beekeeper"].filter(s => items!.some(i => i.source === s)) as src (src)}
      <div class="src">{LABEL[src]}</div>
      {#each items.filter(i => i.source === src) as i (k(i))}
        <label class="it" class:off={!i.supported}>
          <input type="checkbox" disabled={!i.supported} checked={picked.has(k(i))}
            onchange={(e) => { const s = new Set(picked); if ((e.target as HTMLInputElement).checked) s.add(k(i)); else s.delete(k(i)); picked = s; }} />
          <span class="eng tiny">{i.engine ? ENGINE_SHORT[i.engine] : i.driver || "?"}</span>
          <span class="nm"><b class="ell">{i.name}</b><span class="tiny muted ell">{i.folder ? i.folder + " · " : ""}{i.file || [i.host, i.port].filter(Boolean).join(":")}{i.database ? " / " + i.database : ""}{i.user ? " · " + i.user : ""}</span></span>
          <span class="tags">
            <span class="pill {i.kind === 'prod' ? 'bad' : i.kind === 'hml' ? 'warn' : 'good'}">{i.kind === "prod" ? "PROD" : i.kind}</span>
            {#if i.tls.legacy}<span class="pill warn">legado</span>{/if}
            {#if !i.supported}<span class="tiny muted">ainda não suportado</span>{:else if i.already}<span class="tiny muted">já existe</span>{/if}
          </span>
        </label>
      {/each}
    {/each}
    <div class="opts">
      <Switch bind:checked={passwords} label="Trazer as senhas" hint="Vão direto para o cofre do Codeck. Do Tabularis, o macOS pede sua permissão para cada uma; do Beekeeper não dá (você digita depois)." />
      <p class="tiny muted"><ShieldCheck size={12} /> Conexões marcadas como produção (pelo tipo no DBeaver ou "PROD" no nome) entram somente leitura. Confira cada uma depois: ambiente, TLS e projetos.</p>
    </div>
  {/if}
  {#snippet footer()}
    <span class="tiny muted">{picked.size} selecionada{picked.size === 1 ? "" : "s"}</span>
    <span class="grow"></span>
    <button class="btn ghost" onclick={onclose}>Cancelar</button>
    <button class="btn primary" disabled={busy || !picked.size} onclick={run}><Download size={14} /> Importar</button>
  {/snippet}
</Drawer>

<style>
  .src { font: 680 12px var(--font); text-transform: uppercase; letter-spacing: .03em; color: var(--text-2); margin: 14px 0 6px; }
  .src:first-child { margin-top: 0; }
  .it { display: grid; grid-template-columns: auto 52px minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 7px 8px; border-radius: 8px; cursor: pointer; }
  .it:hover { background: var(--surface-2); }
  .it.off { opacity: .55; cursor: default; }
  .eng { font-weight: 650; color: var(--text-2); }
  .nm { display: flex; flex-direction: column; min-width: 0; }
  .tags { display: flex; gap: 6px; align-items: center; }
  .opts { margin-top: 16px; display: grid; gap: 10px; }
  .opts p { display: flex; gap: 6px; align-items: flex-start; margin: 0; }
</style>
