<script lang="ts">
  // Imagem do resultado: escolha colunas, mascare dados pessoais (CPF, e-mail…), o tema e se leva a consulta — a prévia
  // é a imagem final. O destino (área de transferência, arquivo ou os dois) vem dos ajustes e pode ser lembrado aqui.
  import { Copy, Download, EyeOff } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { post } from "../../lib/api";
  import { db, type Column, type EnvKind } from "../../lib/db.svelte";
  import { renderPng } from "../../lib/dbpng";
  import { ui } from "../../lib/ui.svelte";
  import Drawer from "../Drawer.svelte";
  import Mark from "../Mark.svelte";
  import Segmented from "../Segmented.svelte";
  import Switch from "../Switch.svelte";

  let { columns, rows, sql, ms, totalRows, title, envKind, envLabel, database, engineLabel, legacy = false, onclose }:
    { columns: Column[]; rows: any[][]; sql: string | null; ms: number | null; totalRows: number; title: string; envKind: EnvKind; envLabel: string;
      database: string; engineLabel: string; legacy?: boolean; onclose: () => void } = $props();

  const SENSITIVE = /cpf|cnpj|rg\b|email|e_mail|telefone|fone|celular|phone|senha|password|token|cartao|card|nascimento|birth/i;
  let include = $state(untrack(() => columns.map(() => true)));
  let mask = $state(untrack(() => columns.map(c => SENSITIVE.test(c.name))));
  let maskMode = $state<"partial" | "full">("partial");
  let theme = $state<"dark" | "light">(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  let withSql = $state(false);
  let mascot = $state(true);
  let limit = $state(untrack(() => Math.min(rows.length, 50)));
  let dest = $state(db.data?.prefs.png.dest || "clipboard");
  let remember = $state(false);
  let markEl: HTMLDivElement | undefined = $state();
  let preview = $state<string | null>(null);
  let canvas: HTMLCanvasElement | null = null;
  let busy = $state(false);

  $effect(() => {
    const cols = columns.map((c, i) => ({ c, i })).filter(x => include[x.i]);
    const m = new Set(cols.map((x, j) => (mask[x.i] ? j : -1)).filter(j => j >= 0));
    const input = {
      title, envKind, envLabel, database, engineLabel, legacy, sql: withSql ? sql : null, ms, totalRows,
      columns: cols.map(x => x.c), rows: rows.slice(0, Math.max(0, limit)).map(r => cols.map(x => r[x.i])),
      mask: m, maskMode, theme, mascot, logoSvg: markEl?.querySelector("svg")?.outerHTML || null, when: new Date(),
    };
    let alive = true;
    renderPng(input).then(cv => { if (alive) { canvas = cv; preview = cv.toDataURL("image/png"); } });
    return () => { alive = false; };
  });

  async function go(mode: "clipboard" | "file" | "both") {
    if (!canvas) return;
    busy = true;
    try {
      if (remember) db.set(await post("db/prefs", { png: { dest: mode, dir: db.data?.prefs.png.dir || "" } }));
      const blob: Blob = await new Promise(res => canvas!.toBlob(b => res(b!), "image/png"));
      let copied = false;
      if (mode !== "file") {
        try { await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]); copied = true; } catch { /* a WebView recusou: vai pelo backend */ }
      }
      const needBackend = mode !== "clipboard" || !copied;
      let path: string | null = null;
      if (needBackend) {
        const r = await post("db/png", { png: canvas.toDataURL("image/png"), name: title, copy: mode !== "file" && !copied, save: mode !== "clipboard" });
        path = r.path;
      }
      ui.toast(mode === "clipboard" ? "Imagem copiada — é só colar" : mode === "file" ? `Imagem salva em ${path}` : `Copiada e salva em ${path}`);
      onclose();
    } catch (e) { ui.error(e); } finally { busy = false; }
  }
</script>

<div class="hidden" bind:this={markEl}><Mark size={68} /></div>

<Drawer title="Imagem do resultado" subtitle={`${title} · ${envLabel}`} {onclose} width={Math.min(1180, window.innerWidth - 80)} resizeKey="dbpng">
  <div class="wrap">
    <div class="opts">
      <div class="row2">
        <Segmented size="sm" bind:value={theme} options={[{ value: "dark", label: "Escuro" }, { value: "light", label: "Claro" }]} />
        <label class="label lim">Linhas <input class="input" type="number" min="1" max={rows.length} bind:value={limit} /></label>
      </div>
      <Switch bind:checked={withSql} label="Mostrar a consulta" disabled={!sql} />
      <Switch bind:checked={mascot} label="Mascote do Codeck" hint="O ponto verde comenta o resultado" />
      <div class="sect">Colunas</div>
      <p class="tiny muted hint"><EyeOff size={11} /> mascara o valor — CPF, e-mail, telefone… já vêm marcados</p>
      <div class="cols">
        {#each columns as c, i (i)}
          <div class="pc" class:off={!include[i]}>
            <input type="checkbox" bind:checked={include[i]} title="Incluir na imagem" />
            <span class="ell grow" title={c.name}>{c.name}</span>
            <button class="btn sm ghost icon" class:on={mask[i]} disabled={!include[i]} title={mask[i] ? "Mascarado" : "Mascarar"} onclick={() => (mask[i] = !mask[i])}><EyeOff size={13} /></button>
          </div>
        {/each}
      </div>
      <Segmented size="sm" bind:value={maskMode} options={[{ value: "partial", label: "Máscara: 12••••89" }, { value: "full", label: "Máscara total" }]} />
      <div class="sect">Destino</div>
      <Segmented size="sm" bind:value={dest} options={[{ value: "clipboard", label: "Copiar" }, { value: "file", label: "Salvar" }, { value: "both", label: "Os dois" }]} />
      <label class="tiny muted rem"><input type="checkbox" bind:checked={remember} /> Lembrar este destino</label>
      <button class="btn primary go" disabled={busy || !preview} onclick={() => go(dest)}>
        {#if dest === "file"}<Download size={15} /> Salvar imagem{:else}<Copy size={15} /> {dest === "both" ? "Copiar e salvar" : "Copiar imagem"}{/if}
      </button>
    </div>
    <div class="prev">{#if preview}<img src={preview} alt="Prévia da imagem" />{:else}<span class="muted">Gerando…</span>{/if}</div>
  </div>
</Drawer>

<style>
  .hidden { position: fixed; left: -9999px; top: 0; }
  .wrap { display: grid; grid-template-columns: 290px 1fr; gap: 18px; height: 100%; min-height: 0; }
  .opts { display: flex; flex-direction: column; gap: 12px; min-height: 0; overflow: auto; padding-right: 4px; }
  .row2 { display: flex; align-items: end; gap: 10px; justify-content: space-between; }
  .lim { width: 90px; }
  .sect { font-weight: 650; font-size: 12.5px; margin-top: 4px; display: flex; align-items: center; gap: 4px; }
  .cols { display: grid; gap: 2px; max-height: 280px; overflow: auto; border: 1px solid var(--line); border-radius: var(--r-sm); padding: 4px; }
  .pc { display: flex; align-items: center; gap: 8px; font-size: 12.5px; padding: 2px 4px; }
  .pc.off { opacity: 0.5; }
  .pc .on { color: var(--warn); background: var(--warn-soft); }
  .hint { margin: -8px 0 0; display: flex; gap: 5px; align-items: center; }
  .rem { display: flex; gap: 6px; align-items: center; }
  .go { margin-top: 4px; }
  .prev { min-height: 0; overflow: auto; display: grid; place-items: start center; background: var(--bg-2); border-radius: var(--r); padding: 14px; }
  .prev img { max-width: 100%; height: auto; border-radius: 10px; }
  @media (max-width: 900px) { .wrap { grid-template-columns: 1fr; } }
</style>
