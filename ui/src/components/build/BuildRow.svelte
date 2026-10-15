<script lang="ts">
  import { GitBranch, Lock } from "@lucide/svelte";
  import { ago, fmtDur } from "../../lib/format";
  import { store } from "../../lib/store.svelte";
  import type { Build } from "../../lib/types";
  import ProviderIcon from "../ProviderIcon.svelte";
  import { buildState, REASON } from "./status";
  let { b, selected = false, onselect }: { b: Build; selected?: boolean; onselect: () => void } = $props();
  const st = $derived(buildState(b));
  const prot = $derived(store.s?.rules.protectedTargets.map(t => t.toLowerCase()).includes(b.branch.toLowerCase()));
  const branchLabel = $derived(b.branch.startsWith("refs/pull/") ? `PR #${b.prNumber}` : b.branch);
</script>

<div class="list-row" class:sel={selected} data-row={b.key} onclick={onselect} role="button" tabindex="-1" onkeydown={(e) => e.key === "Enter" && onselect()}>
  <span class="st {st.cls}" class:spin-ring={st.spin}>{st.icon}</span>
  <div class="grow">
    <div class="t"><span class="title ell">{b.pipeline}</span><span class="num">{b.number}</span></div>
    <div class="meta">
      <span class="row" style="gap:5px"><ProviderIcon provider={b.provider} size={12} />{b.org}{#if b.provider === "github" && b.repo}<span class="faint">/</span>{b.repo}{/if}</span>
      <span class="branch">{#if prot}<Lock size={10} />{:else}<GitBranch size={11} />{/if}<b>{branchLabel}</b></span>
      <span class="pill neutral">{REASON[b.reason] || b.reason}</span>
      {#if b.message}<span class="msg ell" title={b.message}>{b.message}</span>{/if}
      <span>{b.requestedFor.split(" ").slice(0, 2).join(" ")} · {ago(b.queued)}</span>
      {#if b.waiting}<span class="pill warn">esperando aprovação</span>{/if}
    </div>
  </div>
  <div class="right"><span class="pill {st.cls}">{st.icon} {st.label}</span>
    {#if st.detail}<span class="ph ell" title={st.detail}>{st.detail}</span>{/if}<span class="dur">{fmtDur(b.started, b.finished)}</span></div>
</div>

<style>
  .st { width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center; font-weight: 800; font-size: 13px; position: relative; }
  .st.good { background: var(--good-soft); color: var(--good); }
  .st.bad { background: var(--bad-soft); color: var(--bad); }
  .st.warn { background: var(--warn-soft); color: var(--warn); }
  .st.neutral { background: var(--surface-2); color: var(--muted); }
  .spin-ring::after { content: ""; position: absolute; inset: -2px; border-radius: 50%; border: 2px solid transparent; border-top-color: currentColor; animation: spin 1s linear infinite; }
  .t { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
  .title { font-weight: 600; }
  .num { color: var(--muted); font-size: 12.5px; flex-shrink: 0; font-variant-numeric: tabular-nums; }
  .faint { color: var(--faint); }
  .msg { font-style: italic; color: var(--muted); max-width: 380px; }
  .right { display: grid; justify-items: end; gap: 4px; }
  .ph { max-width: 220px; font-size: 11.5px; color: var(--text-2); }
  .dur { font-size: 11.5px; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
</style>
