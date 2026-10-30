<script lang="ts">
  import { AlertTriangle, Lock } from "@lucide/svelte";
  import { ui } from "../lib/ui.svelte";
  let value = $state("");
  let checked = $state(false);
  let inputEl: HTMLInputElement | HTMLTextAreaElement | undefined = $state();

  $effect(() => {
    if (ui.dialog) {
      value = ui.dialog.input?.value || "";
      checked = false;
      setTimeout(() => (inputEl || document.querySelector<HTMLButtonElement>(".dlg .confirm"))?.focus(), 30);
    }
  });
  function ok() {
    const d = ui.dialog!;
    if (d.blocked?.length) return ui.close(false);
    if (d.input) {
      if (d.input.required && !value.trim()) return;
      return ui.close(value);
    }
    ui.close(d.check && checked ? "check" : true);
  }
  function onkey(e: KeyboardEvent) {
    if (!ui.dialog) return;
    if (e.key === "Escape") ui.close(ui.dialog.input ? null : false);
    if (e.key === "Enter" && !(e.target instanceof HTMLTextAreaElement)) { e.preventDefault(); ok(); }
  }
</script>

<svelte:window onkeydown={onkey} />

{#if ui.dialog}
  {@const d = ui.dialog}
  <div class="wrap">
    <button class="scrim" aria-label="Cancelar" onclick={() => ui.close(d.input ? null : false)}></button>
    <div class="dlg" role="alertdialog" aria-label={d.title}>
      <div class="head">
        {#if d.blocked?.length}<span class="ic lock"><Lock size={18} /></span>{:else if d.danger}<span class="ic warn"><AlertTriangle size={18} /></span>{/if}
        <h3>{d.title}</h3>
      </div>
      {#if d.message}<p class="msg">{d.message}</p>{/if}
      {#if d.detail?.length}<ul class="detail">{#each d.detail as x (x)}<li>{x}</li>{/each}</ul>{/if}
      {#if d.blocked?.length}<ul class="blocked">{#each d.blocked as x (x)}<li>{x}</li>{/each}</ul>{/if}
      {#if d.input}
        <label class="label">{d.input.label}
          {#if d.input.multiline}
            <textarea class="textarea" rows="4" bind:value bind:this={inputEl} placeholder={d.input.placeholder}></textarea>
          {:else}
            <input class="input" bind:value bind:this={inputEl} placeholder={d.input.placeholder} />
          {/if}
        </label>
      {/if}
      {#if d.check}<label class="check"><input type="checkbox" bind:checked /> {d.check}</label>{/if}
      <div class="foot">
        {#if d.blocked?.length}
          <button class="btn confirm" onclick={() => ui.close(false)}>Entendi</button>
        {:else}
          <button class="btn ghost" onclick={() => ui.close(d.input ? null : false)}>{d.cancel || "Cancelar"}</button>
          {#if d.alt}<button class="btn" onclick={() => ui.close("alt")}>{d.alt}</button>{/if}
          <button class="btn confirm {d.danger ? 'danger-solid' : 'primary'}" onclick={ok} disabled={!!d.input?.required && !value.trim()}>{d.confirm || "Confirmar"}</button>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  .wrap { position: fixed; inset: 0; z-index: 80; display: grid; place-items: center; padding: 24px; }
  .scrim { position: absolute; inset: 0; border: 0; background: rgba(5, 7, 12, 0.6); backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px); animation: fade 0.18s both; }
  .dlg { position: relative; width: min(460px, 100%); background: var(--elevated); border: 1px solid var(--line-2); border-radius: 16px; padding: 20px;
    box-shadow: var(--shadow-3); animation: dlg-in 0.32s var(--spring) both; }
  @keyframes dlg-in { from { opacity: 0; transform: scale(0.94) translateY(8px); } }
  .head { display: flex; align-items: center; gap: 10px; }
  h3 { margin: 0; font-size: 16px; letter-spacing: -0.015em; }
  .ic { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; flex-shrink: 0; }
  .warn { background: var(--bad-soft); color: var(--bad); }
  .lock { background: var(--warn-soft); color: var(--warn); }
  .msg { color: var(--text-2); margin: 12px 0 0; white-space: pre-line; }
  .detail, .blocked { margin: 12px 0 0; padding-left: 18px; color: var(--text-2); display: grid; gap: 4px; overflow-wrap: anywhere; }
  .blocked li::marker { color: var(--warn); }
  .label { margin-top: 14px; }
  .check { display: flex; align-items: center; gap: 8px; margin-top: 14px; color: var(--text-2); font-size: 13px; cursor: pointer; }
  .foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
</style>
