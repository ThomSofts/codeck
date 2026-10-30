<script lang="ts">
  // A marca de cada banco: um ladrilho na cor que todo mundo associa ao banco, com a sigla. Não são os logotipos (marcas
  // registradas) — é o suficiente para reconhecer de relance numa lista de dezenas de bancos.
  import type { Engine } from "../../lib/db.svelte";

  let { engine, size = 34 }: { engine: Engine | "app"; size?: number } = $props();
  const M: Record<string, [string, string, string]> = {
    sqlserver: ["#d23a35", "#8e1f1c", "SQL"], postgres: ["#4b7fb5", "#264a72", "PG"], mysql: ["#1a8aa6", "#0b5468", "My"],
    sqlite: ["#3a9be0", "#145f94", "Lt"], libsql: ["#2fc9a8", "#137a66", "Tu"], mongodb: ["#4caf50", "#23692a", "Mg"],
    firebase: ["#ffb300", "#e65100", "Fb"], redis: ["#e5483f", "#9b1d16", "Rd"], app: ["#3ccf91", "#16775a", "App"],
  };
  const m = $derived(M[engine] || ["#888", "#444", "?"]);
</script>

<span class="em" style="--a:{m[0]};--b:{m[1]};--s:{size}px" aria-hidden="true">
  <svg viewBox="0 0 24 24" class="cyl"><ellipse cx="12" cy="5.5" rx="8" ry="3" /><path d="M4 5.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13" /><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></svg>
  <b>{m[2]}</b>
</span>

<style>
  .em { position: relative; display: grid; place-items: center; width: var(--s); height: var(--s); border-radius: calc(var(--s) * 0.3); flex: none; overflow: hidden;
    background: linear-gradient(145deg, var(--a), var(--b)); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.25), 0 4px 12px -6px var(--a); }
  .cyl { position: absolute; width: 78%; height: 78%; right: -18%; bottom: -16%; fill: none; stroke: rgba(255, 255, 255, 0.28); stroke-width: 1.6; }
  b { position: relative; font: 800 calc(var(--s) * 0.34)/1 var(--font); color: #fff; letter-spacing: -0.03em; text-shadow: 0 1px 2px rgba(0, 0, 0, 0.25); }
</style>
