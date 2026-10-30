<script lang="ts">
  // O DevTools do Flutter numa aba (como o VS Code faz): a interface servida pelo `dart devtools`, conectada à VM do app
  // que está rodando no escopo. Reiniciou o app (VM nova) ou trocou a página pelo menu: recarrega sozinho.
  import { ExternalLink, Gauge, Loader2, RefreshCw } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { debug } from "../../lib/debug.svelte";
  import { DEVTOOLS_PAGES, openInBrowser } from "../../lib/flutter";

  let { repoId, taskId = null, page = "" }: { repoId: string; taskId?: string | null; page?: string } = $props();
  const s = $derived(debug.flutterSession(repoId, taskId));
  const vm = $derived(s?.flutter?.vmUri || null);
  const sid = $derived(s?.id || null);   // primitivos: a sessão chega nova a cada /poll, a URL só muda com a VM
  let url = $state<string | null>(null);
  let err = $state<string | null>(null);
  let loading = $state(false);
  let n = $state(0);

  $effect(() => {
    const id = sid, uri = vm, pg = page, _ = n;
    if (!id || !uri) { url = null; return; }
    untrack(async () => {
      loading = true; err = null;
      try { const u = await debug.devtoolsUrl(s!, pg, true); if (sid === id) url = u; }
      catch (e) { err = (e as any)?.message || String(e); url = null; }
      finally { loading = false; }
    });
  });
  const title = $derived(DEVTOOLS_PAGES.find(p => p.page === page)?.label || "DevTools");
</script>

<div class="dtp">
  <div class="bar">
    <Gauge size={13} /><b>{title}</b>
    {#if s}<span class="tiny muted ell">· {s.name}{s.device ? ` · ${s.device}` : ""}</span>{/if}
    <span class="grow"></span>
    {#if loading}<Loader2 size={12} class="spin" />{/if}
    <button class="ib" title="Recarregar" disabled={!vm} onclick={() => n++}><RefreshCw size={12} /></button>
    <button class="ib" title="Abrir no navegador" disabled={!vm || !s} onclick={() => s && openInBrowser(s, page)}><ExternalLink size={12} /></button>
  </div>
  {#if url}
    {#key `${url}#${n}`}<iframe src={url} title="Flutter DevTools" allow="clipboard-read; clipboard-write" sandbox="allow-scripts allow-same-origin allow-popups allow-forms allow-downloads"></iframe>{/key}
  {:else}
    <div class="empty">
      <Gauge size={28} />
      {#if err}<p>{err}</p>
      {:else if s && !vm}<p>Esperando o app subir{s.status === "booting" ? ` (ligando ${s.boot || "o emulador"})` : ""}…</p>
      {:else if loading}<p>Abrindo o DevTools…</p>
      {:else}<p>Nenhum app Flutter rodando aqui. <b>F5</b> depura o escolhido na barra de executar — o DevTools conecta sozinho.</p>{/if}
    </div>
  {/if}
</div>

<style>
  .dtp { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--bg); }
  .bar { display: flex; align-items: center; gap: 6px; height: 30px; padding: 0 6px 0 10px; border-bottom: 1px solid var(--line); flex: none; font-size: 12px; color: var(--text-2); }
  .bar b { color: var(--text); font-weight: 650; }
  .grow { flex: 1; }
  .ib { display: grid; place-items: center; width: 24px; height: 22px; border: 0; border-radius: 5px; background: none; color: var(--muted); cursor: pointer; }
  .ib:hover:not(:disabled) { background: var(--surface-3); color: var(--text); }
  .ib:disabled { opacity: 0.4; cursor: default; }
  iframe { flex: 1; width: 100%; min-height: 0; border: 0; background: var(--bg); }
  .empty { flex: 1; display: grid; place-content: center; justify-items: center; gap: 10px; padding: 24px; color: var(--muted); text-align: center; font-size: 13px; }
  .empty p { max-width: 420px; line-height: 1.5; margin: 0; }
  .ell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
</style>
