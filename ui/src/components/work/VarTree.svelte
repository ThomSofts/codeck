<script lang="ts">
  // Uma variável da depuração (e os filhos, carregados ao abrir): nome, valor e tipo, como na janela Locais do Visual
  // Studio. Duplo clique no valor edita (quando o depurador deixa).
  import { ChevronRight } from "@lucide/svelte";
  import { debug, type Variable } from "../../lib/debug.svelte";
  import { ui } from "../../lib/ui.svelte";
  import VarTree from "./VarTree.svelte";

  let { sid, v, parentRef = 0, depth = 0, editable = false }: { sid: string; v: Variable; parentRef?: number; depth?: number; editable?: boolean } = $props();
  let open = $state(false);
  let kids = $state<Variable[] | null>(null);
  let value = $state<string | null>(null);
  const shown = $derived(value ?? v.value);
  async function toggle() {
    if (!v.ref) return;
    open = !open;
    if (open && !kids) kids = await debug.variables(sid, v.ref);
  }
  async function edit() {
    if (!editable || !parentRef) return;
    const nv = await ui.ask({ title: `Mudar ${v.name}`, input: { label: "Novo valor (expressão)", value: shown }, confirm: "Aplicar" });
    if (nv === null || nv === false) return;
    try { value = (await debug.setVariable(sid, parentRef, v.name, String(nv))).value; } catch (e) { ui.error(e); }
  }
  const tone = $derived(/^-?\d/.test(shown) ? "num" : /^["'`]/.test(shown) ? "str" : /^(true|false|null|undefined)$/i.test(shown) ? "kw" : "");
</script>

<div class="v" style="--d:{depth}">
  <button class="row" onclick={toggle} ondblclick={edit} title={`${v.name}${v.type ? `: ${v.type}` : ""} = ${shown}`}>
    <span class="tw">{#if v.ref}<ChevronRight size={12} class={open ? "rot" : ""} />{/if}</span>
    <span class="n">{v.name}</span><span class="eq">:</span>
    <span class="val {tone}">{shown}</span>
    {#if v.type}<span class="ty">{v.type}</span>{/if}
  </button>
  {#if open && kids}
    {#each kids as c, i (c.name + i)}<VarTree {sid} v={c} parentRef={v.ref} depth={depth + 1} {editable} />{/each}
    {#if !kids.length}<div class="none" style="--d:{depth + 1}">vazio</div>{/if}
  {/if}
</div>

<style>
  .row { display: flex; align-items: center; gap: 4px; width: 100%; height: 22px; padding: 0 8px 0 calc(6px + var(--d) * 12px); border: 0; background: none;
    color: var(--text-2); font: 12px var(--mono); cursor: default; text-align: left; white-space: nowrap; overflow: hidden; }
  .row:hover { background: var(--surface-2); }
  .tw { display: grid; place-items: center; width: 12px; flex: none; color: var(--muted); }
  .tw :global(.rot) { transform: rotate(90deg); }
  .n { color: #b07cff; flex: none; }
  .eq { color: var(--faint); flex: none; }
  .val { color: var(--text); overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  .val.num { color: #f5b84f; } .val.str { color: #3ccf91; } .val.kw { color: #4fc3f7; }
  .ty { margin-left: auto; padding-left: 8px; color: var(--faint); font-size: 11px; flex: none; max-width: 40%; overflow: hidden; text-overflow: ellipsis; }
  .none { padding: 2px 8px 2px calc(24px + var(--d) * 12px); color: var(--faint); font: italic 11.5px var(--font); }
</style>
