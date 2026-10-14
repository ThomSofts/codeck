<script lang="ts">
  // ⌘P / Ctrl+P (como no VS Code): abrir arquivo por busca aproximada ("wkst" acha workspace.ts), os recentes primeiro,
  // "arquivo:42" abre na linha 42 e ":42" vai para a linha no arquivo aberto.
  import { CornerDownLeft } from "@lucide/svelte";
  import { get } from "../../lib/api";
  import { edState } from "../../lib/editorstate.svelte";
  import { ui } from "../../lib/ui.svelte";
  import FileIcon from "./FileIcon.svelte";

  let { repoId, taskId = null, recent = [], decor = new Map(), onpick, onclose }:
    { repoId: string; taskId?: string | null; recent?: string[]; decor?: Map<string, { tone: string; letter: string }>; onpick: (path: string, line?: number) => void; onclose: () => void } = $props();
  let q = $state("");
  let files = $state<string[]>([]);
  let sel = $state(0);
  let listEl: HTMLDivElement | undefined = $state();

  $effect(() => { get<{ files: string[] }>("ws/files", { repoId, taskId }).then(r => (files = r.files)).catch(e => ui.error(e)); });

  /** pontua um caminho: subsequência da busca, com bônus para começo de palavra, letras seguidas e nome do arquivo */
  function score(path: string, query: string): { s: number; hits: number[] } | null {
    const p = path.toLowerCase();
    const base = p.lastIndexOf("/") + 1;
    let s = 0, qi = 0, last = -2;
    const hits: number[] = [];
    // tenta casar a busca toda no nome do arquivo primeiro (o caso mais comum)
    const inName = p.indexOf(query, base);
    if (inName >= 0) {
      for (let i = 0; i < query.length; i++) hits.push(inName + i);
      return { s: 1000 - (p.length - base) + (inName === base ? 300 : 0) - base * 0.2, hits };
    }
    for (let i = 0; i < p.length && qi < query.length; i++) {
      if (p[i] !== query[qi]) continue;
      let b = 1;
      if (i === last + 1) b += 6;
      const prev = path[i - 1];
      if (i === 0 || prev === "/" || prev === "." || prev === "_" || prev === "-" || (prev && prev === prev.toLowerCase() && path[i] !== path[i].toLowerCase())) b += 8;
      if (i >= base) b += 3;
      s += b; hits.push(i); last = i; qi++;
    }
    if (qi < query.length) return null;
    return { s: s - p.length * 0.05 - (hits[0] || 0) * 0.02, hits };
  }
  const parsed = $derived.by(() => {
    const m = /^(.*?)(?::(\d+))?\s*$/.exec(q.trim());
    return { text: (m?.[1] || "").replace(/\s+/g, "").toLowerCase(), line: m?.[2] ? +m[2] : undefined };
  });
  const results = $derived.by(() => {
    const t = parsed.text;
    if (!t) {
      const rec = recent.filter(r => files.includes(r) || !files.length);
      const rest = files.filter(f => !rec.includes(f)).slice(0, 60);
      return [...rec.map(path => ({ path, hits: [] as number[], recent: true })), ...rest.map(path => ({ path, hits: [] as number[], recent: false }))];
    }
    const out: { path: string; hits: number[]; s: number; recent: boolean }[] = [];
    for (const f of files) {
      const r = score(f, t);
      if (r) out.push({ path: f, hits: r.hits, s: r.s + (recent.includes(f) ? 40 : 0), recent: recent.includes(f) });
    }
    return out.sort((a, b) => b.s - a.s).slice(0, 80);
  });
  $effect(() => { void q; sel = 0; });
  function pick(i = sel) {
    if (/^:\d+$/.test(q.trim())) {   // ":42": vai para a linha no arquivo aberto
      const ln = +q.trim().slice(1), e = edState.editor;
      if (e) { e.revealLineInCenter(ln); e.setPosition({ lineNumber: ln, column: 1 }); e.focus(); }
      return onclose();
    }
    const r = results[i];
    if (!r) return;
    onpick(r.path, parsed.line);
    onclose();
  }
  function key(e: KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(results.length - 1, sel + 1); scroll(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(0, sel - 1); scroll(); }
    else if (e.key === "Enter") { e.preventDefault(); pick(); }
    else if (e.key === "Escape") { e.preventDefault(); onclose(); }
  }
  const scroll = () => requestAnimationFrame(() => listEl?.querySelector(".r.on")?.scrollIntoView({ block: "nearest" }));
  function marked(path: string, hits: number[], from: number) {
    const set = new Set(hits);
    const out: { s: string; m: boolean }[] = [];
    for (let i = from; i < path.length; i++) {
      const m = set.has(i);
      if (out.length && out[out.length - 1].m === m) out[out.length - 1].s += path[i];
      else out.push({ s: path[i], m });
    }
    return out;
  }
</script>

<div class="qo-back" role="presentation" onclick={onclose}>
  <div class="qo" role="dialog" aria-label="Abrir arquivo" tabindex="-1" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
    <!-- svelte-ignore a11y_autofocus -->
    <input autofocus bind:value={q} onkeydown={key} placeholder="Buscar arquivo pelo nome (arquivo:linha abre na linha · :linha vai para a linha)" spellcheck="false" />
    <div class="list" bind:this={listEl}>
      {#if /^:\d*$/.test(q.trim())}
        <div class="hint"><CornerDownLeft size={13} /> Ir para a linha {q.trim().slice(1) || "…"} {edState.path ? `em ${edState.path.split("/").pop()}` : ""}</div>
      {:else}
        {#each results as r, i (r.path)}
          {@const base = r.path.lastIndexOf("/") + 1}
          {@const d = decor.get(r.path)}
          <button class="r {d?.tone || ''}" class:on={i === sel} onmousemove={() => (sel = i)} onclick={() => pick(i)}>
            <FileIcon name={r.path.slice(base)} size={16} />
            <span class="nm">{#each marked(r.path, r.hits, base) as p, j (j)}{#if p.m}<b>{p.s}</b>{:else}{p.s}{/if}{/each}</span>
            <span class="dir ell">{r.path.slice(0, Math.max(0, base - 1))}</span>
            {#if d}<span class="lt">{d.letter}</span>{/if}
            {#if r.recent}<span class="tag">recente</span>{/if}
          </button>
        {:else}
          <div class="hint">{files.length ? "Nenhum arquivo combina." : "Carregando os arquivos…"}</div>
        {/each}
      {/if}
    </div>
  </div>
</div>

<style>
  .qo-back { position: fixed; inset: 0; z-index: 80; background: rgba(0, 0, 0, 0.18); animation: fade 0.12s; }
  .qo { position: absolute; top: 64px; left: 50%; transform: translateX(-50%); width: min(640px, calc(100vw - 32px)); border-radius: 12px; overflow: hidden;
    background: var(--elevated); border: 1px solid var(--line-2); box-shadow: var(--shadow-3); animation: rise 0.16s var(--ease-out); }
  input { width: 100%; height: 42px; border: 0; border-bottom: 1px solid var(--line); outline: none; background: none; color: var(--text); font: 14px var(--font); padding: 0 14px; }
  .list { max-height: min(460px, 60vh); overflow: auto; padding: 4px; }
  .r { display: flex; align-items: center; gap: 8px; width: 100%; height: 30px; padding: 0 10px; border: 0; border-radius: 7px; background: none; color: var(--text);
    font: 13px var(--font); text-align: left; cursor: pointer; }
  .r.on { background: var(--accent-soft); }
  .nm { flex: none; max-width: 55%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .nm b { color: var(--accent); font-weight: 700; }
  .dir { flex: 1; min-width: 0; color: var(--muted); font-size: 12px; }
  .lt { font: 650 11px var(--mono); }
  .r.mod .lt, .r.mod .nm { color: #e2c08d; } .r.add .lt, .r.add .nm { color: #73c991; } .r.del .lt { color: #e5717d; }
  .tag { font-size: 10.5px; color: var(--muted); padding: 1px 6px; border-radius: 99px; border: 1px solid var(--line-2); }
  .hint { display: flex; align-items: center; gap: 6px; padding: 12px; color: var(--muted); font-size: 12.5px; }
</style>
