<script lang="ts">
  import { ExternalLink, Lock } from "@lucide/svelte";
  import { shortDate, time } from "../lib/format";
  import { go, router } from "../lib/router.svelte";
  import { store } from "../lib/store.svelte";
  import DeployPane from "../components/deploy/DeployPane.svelte";
  import DeployRow from "../components/deploy/DeployRow.svelte";
  import Empty from "../components/Empty.svelte";
  import Page from "../components/Page.svelte";
  import ProviderIcon from "../components/ProviderIcon.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Skeleton from "../components/Skeleton.svelte";
  import Switch from "../components/Switch.svelte";

  let kind = $state("");
  let onlyProt = $state(false);
  const s = $derived(store.s);
  const deps = $derived((s?.deploys || []).filter(d => !kind || kind === (d.kind === "permission" ? "permission" : "release")));
  const isProt = (b: string) => !!s?.rules.protectedTargets.map(t => t.toLowerCase()).includes((b || "").toLowerCase());
  const rels = $derived((s?.releases || []).filter(r => !onlyProt || isProt(r.branch)));
  const selKey = $derived(router.param && deps.some(d => d.key === router.param) ? router.param : null);
  const sel = $derived(deps.find(d => d.key === selKey));
  const ENV: Record<string, [string, string]> = { succeeded: ["✓", "good"], partiallySucceeded: ["!", "warn"], rejected: ["✕", "bad"], canceled: ["⊘", "neutral"],
    inProgress: ["⟳", "warn"], queued: ["⟳", "warn"], scheduled: ["⏱", "warn"], notStarted: ["–", "neutral"] };
</script>

<Page live={["deploys"]} title="Deploys" sub="Aprovações de release e de environment, permissões de pipeline e o que subiu por último">
  {#snippet actions()}<a class="btn sm" href="#/automation">⚡ Regras de deploy</a>{/snippet}
  {#if !store.deploysReady}
    <Skeleton rows={8} />
  {:else}
    <div class="cols">
      <div class="card col-card">
        <div class="card-h"><h3>Esperando liberação</h3><span class="muted small">{deps.length}</span><span class="spacer"></span>
          <Segmented size="sm" bind:value={kind} options={[{ value: "", label: "Tudo" }, { value: "release", label: "Deploys" }, { value: "permission", label: "Permissões" }]} /></div>
        <div class="scroll">
          {#each deps as d (d.key)}<DeployRow {d} selected={d.key === selKey} onselect={() => go("/deploys/" + encodeURIComponent(d.key), "soft")} />
          {:else}<Empty done title="Nada parado" text="Nenhum deploy ou pipeline esperando você." />{/each}
        </div>
      </div>
      {#if sel}
        {#key sel.key}<div class="card col-card pane"><div class="scroll"><DeployPane d={sel} /></div></div>{/key}
      {:else}
        <div class="card col-card">
          <div class="card-h"><h3>Releases recentes</h3><span class="muted small">Azure DevOps</span><span class="spacer"></span>
            <Switch bind:checked={onlyProt} label="Só de branch protegida" /></div>
          <div class="scroll">
            <table>
              <thead><tr><th>Release</th><th>Origem</th><th>Estágios</th><th>Criada</th></tr></thead>
              <tbody>
                {#each rels.slice(0, 80) as r (r.org + r.id)}
                  <tr>
                    <td><a href={r.url} target="_blank" rel="noopener" class="rl"><b>{r.pipeline.replace(/ - deploy$/, "")}</b><ExternalLink size={11} /></a>
                      <div class="small muted row" style="gap:5px"><ProviderIcon provider={r.provider} size={11} />{r.org} · {r.name}</div></td>
                    <td class="small"><span class="branch">{#if isProt(r.branch)}<Lock size={10} />{/if}<b>{r.branch || "—"}</b></span><div class="muted">{r.version}</div></td>
                    <td><div class="envs">{#each r.envs as e (e.name)}{@const x = ENV[e.status] || ["?", "neutral"]}<span class="pill {x[1]}" title={e.status}>{x[0]} {e.name}</span>{/each}</div></td>
                    <td class="small muted nowrap">{shortDate(r.created)} {time(r.created)}<div>{r.createdBy.split(" ").slice(0, 2).join(" ")}</div></td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        </div>
      {/if}
    </div>
  {/if}
</Page>

<style>
  .cols { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr); gap: 14px; }
  @media (max-width: 1180px) { .cols { grid-template-columns: minmax(0, 1fr); grid-auto-rows: minmax(0, 1fr); } }
  .col-card { min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
  .scroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; }
  .pane { animation: rise 0.3s var(--ease-out); }
  table { width: 100%; border-collapse: collapse; }
  th { position: sticky; top: 0; z-index: 1; text-align: left; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted);
    padding: 10px 14px; background: var(--surface); box-shadow: inset 0 -1px 0 var(--line); }
  td { padding: 9px 14px; border-top: 1px solid var(--line); vertical-align: middle; }
  tbody tr { transition: background var(--t-fast); }
  tbody tr:hover { background: var(--surface-2); }
  .rl { display: inline-flex; align-items: center; gap: 5px; }
  .rl :global(svg) { color: var(--muted); }
  .envs { display: flex; gap: 4px; flex-wrap: wrap; }
</style>
