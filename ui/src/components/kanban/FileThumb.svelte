<script lang="ts">
  // Miniatura de um anexo do cartão. A imagem vem por fetch (a chave vai no cabeçalho) e vira blob URL — um <img src>
  // direto na API não passaria na autenticação. Sem imagem (PDF, zip…): o tipo do arquivo em letras.
  import { kanban, isImage, type CardFile } from "../../lib/kanban.svelte";

  let { cardId, file, fit = "cover" }: { cardId: string; file: CardFile; fit?: "cover" | "contain" } = $props();
  let url = $state<string | null>(null);
  let failed = $state(false);
  $effect(() => {
    url = null; failed = false;
    if (!isImage(file)) return;
    let live = true;
    kanban.fileUrl(cardId, file.id).then(u => { if (live) url = u; }).catch(() => { if (live) failed = true; });
    return () => { live = false; };
  });
  const ext = $derived((file.name.split(".").pop() || "").slice(0, 4).toUpperCase());
</script>

{#if url}
  <img src={url} alt={file.name} style="object-fit:{fit}" draggable="false" onerror={() => { url = null; failed = true; }} />
{:else}
  <span class="ph" class:img={isImage(file) && !failed}>{isImage(file) && !failed ? "" : ext || "ARQ"}</span>
{/if}

<style>
  img { display: block; width: 100%; height: 100%; }
  .ph { display: grid; place-items: center; width: 100%; height: 100%; font: 700 10.5px var(--font); letter-spacing: 0.04em; color: var(--muted);
    background: var(--surface-3); }
  .ph.img { background: linear-gradient(90deg, var(--surface-2), var(--surface-3), var(--surface-2)); background-size: 200% 100%; animation: shimmer 1.4s linear infinite; }
  @media (prefers-reduced-motion: reduce) { .ph.img { animation: none; } }
</style>
