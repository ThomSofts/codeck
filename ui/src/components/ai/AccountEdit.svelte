<script lang="ts">
  // Editar a conta ali mesmo (sem janela): o apelido, o grupo (o cliente — Dematec, Pessoal…; a recomendação de um
  // projeto fica entre as contas do mesmo grupo) e a cor. Enter salva, Esc cancela.
  import { Check, X } from "@lucide/svelte";
  import { tick, untrack } from "svelte";
  import { ui } from "../../lib/ui.svelte";
  import { work, type AiAccount } from "../../lib/work.svelte";
  import AccountAvatar from "./AccountAvatar.svelte";
  import { ACC_COLORS, accColor } from "./limits.svelte";

  let { a, ondone }: { a: AiAccount; ondone: () => void } = $props();
  // o formulário começa com o que a conta tem agora (e não acompanha mudanças de fora enquanto edita)
  let name = $state(untrack(() => a.name));
  let group = $state(untrack(() => a.group || ""));
  let color = $state<string | null>(untrack(() => a.color || null));
  let busy = $state(false);
  let first: HTMLInputElement | undefined = $state();
  $effect(() => { tick().then(() => { first?.focus(); first?.select(); }); });
  const groups = $derived([...new Set(work.ai.map(x => x.group).filter(Boolean) as string[])].sort());
  const uid = $derived(`grp-${a.id}`);

  async function save() {
    if (!name.trim() || busy) return;
    busy = true;
    try { await work.updateAccount(a.id, { name: name.trim(), group: group.trim() || null, color }); ondone(); }
    catch (e) { ui.error(e); }
    finally { busy = false; }
  }
  function key(e: KeyboardEvent) {
    if (e.key === "Enter") { e.preventDefault(); save(); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); ondone(); }
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="ed" onkeydown={key}>
  <AccountAvatar a={{ ...a, name: name || a.name, color }} size={34} />
  <label class="f"><span>Apelido</span><input class="input" bind:this={first} bind:value={name} maxlength="40" placeholder="ex.: Ademar" /></label>
  <label class="f"><span>Grupo</span><input class="input" bind:value={group} list={uid} maxlength="30" placeholder="ex.: Dematec" />
    <datalist id={uid}>{#each groups as g (g)}<option value={g}></option>{/each}</datalist></label>
  <div class="f"><span>Cor</span>
    <div class="sw" role="radiogroup" aria-label="Cor da conta">
      {#each ACC_COLORS as c (c)}
        <button role="radio" aria-checked={color === c} aria-label="cor" class:on={color === c} style="--c:{c}" onclick={() => (color = c)}></button>
      {/each}
      <button role="radio" aria-checked={!color} class="auto" class:on={!color} style="--c:{accColor({ id: a.id })}" title="Automática" aria-label="automática" onclick={() => (color = null)}></button>
    </div>
  </div>
  <div class="acts">
    <button class="btn sm ghost icon" title="Cancelar (Esc)" onclick={ondone}><X size={14} /></button>
    <button class="btn sm primary" disabled={!name.trim() || busy} onclick={save}><Check size={13} /> Salvar</button>
  </div>
</div>

<style>
  .ed { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; padding: 12px 14px; border-radius: var(--r); background: var(--surface-2);
    border: 1px solid var(--accent-line); animation: open 0.2s var(--ease-out); }
  .ed > :global(.av) { align-self: center; }
  .f { display: grid; gap: 4px; min-width: 0; }
  .f > span { font-size: 11.5px; color: var(--text-2); }
  .f .input { width: 170px; height: 30px; }
  .sw { display: flex; gap: 6px; height: 30px; align-items: center; }
  .sw button { width: 20px; height: 20px; border-radius: 50%; border: 0; background: var(--c); cursor: pointer; padding: 0; opacity: 0.75;
    transition: transform var(--t-fast), opacity var(--t-fast), box-shadow var(--t-fast); }
  .sw button:hover { opacity: 1; transform: scale(1.1); }
  .sw button.on { opacity: 1; box-shadow: 0 0 0 2px var(--surface-2), 0 0 0 4px var(--c); }
  .sw .auto { background: conic-gradient(var(--cat1), var(--cat3), var(--cat4), var(--cat2), var(--cat5), var(--cat6), var(--cat1)); }
  .acts { display: flex; gap: 6px; margin-left: auto; align-self: center; }
  @keyframes open { from { opacity: 0; transform: translateY(-4px); } }
  @media (prefers-reduced-motion: reduce) { .ed { animation: none; } }
</style>
