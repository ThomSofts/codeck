<script lang="ts">
  // Ícone de arquivo/pasta: o do tema de ícones ativo (extensão do VS Code) ou o embutido.
  import { icons } from "../../lib/fileicons.svelte";
  let { name, dir = false, open = false, size = 15 }: { name: string; dir?: boolean; open?: boolean; size?: number } = $props();
  const r = $derived(icons.resolve(name, dir, open));
</script>

{#if r.kind === "img"}
  <img class="fi" src={r.url} alt="" width={size} height={size} draggable="false" />
{:else if r.kind === "glyph"}
  <span class="fi glyph" style="font-family:'{r.font}';color:{r.color || 'inherit'};font-size:{r.size && /%$/.test(r.size) ? `calc(${size}px * ${parseFloat(r.size) / 100})` : size + 'px'};width:{size}px;height:{size}px">{r.char}</span>
{:else}
  {@const I = r.icon}
  <span class="fi" style="color:{r.color}"><I size={size - 1} strokeWidth={1.9} /></span>
{/if}

<style>
  .fi { display: inline-grid; place-items: center; flex: none; line-height: 1; }
  img.fi { object-fit: contain; }
  .glyph { overflow: hidden; }
</style>
