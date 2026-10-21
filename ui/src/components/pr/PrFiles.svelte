<script lang="ts">
  // "Arquivos modificados" da PR: cada arquivo com o status (A/M/D/R) e o +/- (o Azure não informa: conta ao abrir o
  // diff). Clique abre o diff lado a lado (base do merge × cabeça da PR) numa gaveta larga, com a lista ao lado.
  import { FileDiff, RefreshCw, Search } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { fade } from "svelte/transition";
  import { get } from "../../lib/api";
  import type { PR } from "../../lib/types";
  import FileIcon from "../work/FileIcon.svelte";
  import PrDiff, { type PrFile, type PrFileList } from "./PrDiff.svelte";

  let { pr, count = $bindable(null) }: { pr: PR; count?: number | null } = $props();
  let data = $state<PrFileList | null>(null);
  let err = $state("");
  let loading = $state(false);
  let q = $state("");
  let open = $state<number | null>(null);
  // contagem de +/- que o diff descobre (Azure): fica na lista também
  let counted = $state<Record<string, { add: number; del: number }>>({});

  async function load() {
    loading = true;
    try { data = await get<PrFileList>("pr/files", { key: pr.key }); err = ""; count = data.files.length; }
    catch (e: any) { err = e.message || String(e); }
    loading = false;
  }
  // relê quando a PR ganha commit novo (a lista de PRs atualiza `commit`)
  $effect(() => { void pr.key; void pr.commit; untrack(load); });

  const files = $derived((data?.files || []).filter(f => !q || f.path.toLowerCase().includes(q.toLowerCase())));
  const STATUS: Record<string, [string, string]> = { A: ["adicionado", "good"], D: ["apagado", "bad"], M: ["modificado", "warn"], R: ["renomeado", "info"], C: ["copiado", "info"] };
  const tot = $derived.by(() => {
    let a = 0, d = 0;
    for (const f of data?.files || []) { a += f.add ?? counted[f.path]?.add ?? 0; d += f.del ?? counted[f.path]?.del ?? 0; }
    return { a, d };
  });
  const bar = (f: PrFile) => {
    const a = f.add ?? counted[f.path]?.add, d = f.del ?? counted[f.path]?.del;
    if (a == null || d == null) return null;
    const n = a + d || 1, blocks = 5, ga = Math.round((a / n) * blocks);
    return { a, d, ga: a + d ? ga : 0, gd: a + d ? blocks - ga : 0 };
  };
</script>

<div class="pf">
  <div class="head">
    <span class="sum small">
      {#if data}<b>{data.files.length}</b> arquivo{data.files.length === 1 ? "" : "s"}{#if data.total > data.files.length} <span class="muted">(de {data.total})</span>{/if}
        {#if tot.a || tot.d}<span class="st"><b class="a">+{tot.a}</b> <b class="d">−{tot.d}</b></span>{/if}
      {:else}<span class="muted">Lendo arquivos…</span>{/if}
    </span>
    <label class="find"><Search size={12} /><input placeholder="Filtrar" bind:value={q} /></label>
    <button class="btn sm ghost icon" title="Ler de novo" onclick={load}><RefreshCw size={13} class={loading ? "spin" : ""} /></button>
  </div>
  {#if err}<p class="small err">Não consegui ler os arquivos: {err}</p>
  {:else if !data}
    <div class="sk">{#each Array(6) as _, i (i)}<div class="skr"><i class="shim" style="width:14px;height:14px"></i><i class="shim" style="width:{60 - ((i * 11) % 30)}%;height:11px"></i><i class="shim" style="width:46px;height:9px;margin-left:auto"></i></div>{/each}</div>
  {:else}
    <div class="list" in:fade={{ duration: 160 }}>
      {#each files as f (f.path)}
        {@const b = bar(f)}
        {@const i = data.files.indexOf(f)}
        <button class="f" class:sel={open === i} onclick={() => (open = i)} title={f.oldPath && f.oldPath !== f.path ? `${f.oldPath} → ${f.path}` : f.path}>
          <FileIcon name={f.path.split("/").pop() || f.path} size={14} />
          <span class="nm ell"><span class:del={f.status === "D"}>{f.path.split("/").pop()}</span> <span class="dir tiny">{f.path.split("/").slice(0, -1).join("/")}</span></span>
          {#if b}<span class="st tiny"><b class="a">+{b.a}</b> <b class="d">−{b.d}</b></span>
            <span class="blk">{#each Array(b.ga) as _, k (k)}<i class="ga"></i>{/each}{#each Array(b.gd) as _, k (k)}<i class="gd"></i>{/each}{#each Array(5 - b.ga - b.gd) as _, k (k)}<i></i>{/each}</span>{/if}
          <span class="code {STATUS[f.status]?.[1] || 'warn'}" title={STATUS[f.status]?.[0]}>{f.status}</span>
        </button>
      {:else}<p class="small muted pad">{q ? "Nenhum arquivo com esse nome." : "Nenhum arquivo modificado."}</p>{/each}
    </div>
    {#if data.files.length}<p class="tiny muted hint"><FileDiff size={11} /> Clique num arquivo para ver o diff.</p>{/if}
  {/if}
</div>

{#if open !== null && data}
  <PrDiff {pr} files={data.files} base={data.base} head={data.head} bind:index={open} onclose={() => (open = null)}
    oncount={(p, c) => (counted = { ...counted, [p]: c })} />
{/if}

<style>
  .pf { display: grid; gap: 8px; }
  .head { display: flex; align-items: center; gap: 8px; }
  .sum { flex: 1; display: flex; align-items: center; gap: 8px; }
  .st { font: 600 11.5px var(--mono); }
  .st .a { color: var(--good); } .st .d { color: var(--bad); }
  .find { display: inline-flex; align-items: center; gap: 5px; height: 26px; padding: 0 8px; border: 1px solid var(--line-2); border-radius: 7px; color: var(--muted); }
  .find:focus-within { border-color: var(--accent); }
  .find input { width: 110px; border: 0; background: none; color: var(--text); font: 12px var(--font); outline: none; }
  .list { border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
  .f { display: flex; align-items: center; gap: 8px; width: 100%; padding: 6px 10px; border: 0; border-top: 1px solid var(--line); background: none; color: var(--text);
    font: 12.5px var(--font); text-align: left; cursor: pointer; transition: background var(--t-fast); }
  .f:first-child { border-top: 0; }
  .f:hover { background: var(--surface-2); }
  .f.sel { background: var(--accent-soft); }
  .nm { flex: 1; display: flex; align-items: baseline; gap: 6px; }
  .nm .del { text-decoration: line-through; color: var(--text-2); }
  .dir { color: var(--muted); overflow: hidden; text-overflow: ellipsis; }
  .blk { display: inline-flex; gap: 1px; }
  .blk i { width: 7px; height: 7px; border-radius: 1.5px; background: var(--surface-3); }
  .blk i.ga { background: var(--good); } .blk i.gd { background: var(--bad); }
  .code { width: 16px; text-align: center; font: 700 11px var(--mono); }
  .code.good { color: var(--good); } .code.bad { color: var(--bad); } .code.warn { color: var(--warn); } .code.info { color: var(--info); }
  .sk { display: grid; border: 1px solid var(--line); border-radius: 10px; }
  .skr { display: flex; align-items: center; gap: 8px; padding: 9px 10px; border-top: 1px solid var(--line); }
  .skr:first-child { border-top: 0; }
  .hint { display: flex; align-items: center; gap: 5px; margin: 0; }
  .pad { padding: 10px 12px; margin: 0; }
  .err { color: var(--bad); }
</style>
