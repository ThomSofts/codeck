<script lang="ts">
  // Histórico do app. #/history/pr/<chave>: só o de uma PR (o arquivo inteiro — votos, aprovações do piloto,
  // comentários, builds/deploys com o número dela), com atalhos para a PR e para os commits da branch no clone local.
  // #/history/prs: já abre no tipo "PRs" (atalho da tela de PRs).
  import { ExternalLink, GitCommitHorizontal, GitPullRequest, X } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { get } from "../lib/api";
  import { dateTime } from "../lib/format";
  import { repos } from "../lib/repos.svelte";
  import { go, router } from "../lib/router.svelte";
  import { store } from "../lib/store.svelte";
  import type { Activity } from "../lib/types";
  import Empty from "../components/Empty.svelte";
  import Page from "../components/Page.svelte";
  import ProviderIcon from "../components/ProviderIcon.svelte";
  import Segmented from "../components/Segmented.svelte";
  import { findPr, localClone, openPr, openPrCommits, prHistoryPath } from "../components/pr/history";
  import { VOTES } from "../components/pr/votes";

  let who = $state("all");
  let kind = $state(router.parts[1] === "prs" ? "pr" : "");
  $effect(() => { if (router.parts[1] === "prs") untrack(() => (kind = "pr")); });
  const prKey = $derived(router.parts[1] === "pr" && router.parts.length > 2 ? decodeURIComponent(router.parts.slice(2).join("/")) : "");

  // PR em foco: a das listas do app (título, branch, clone) ou, se já saiu delas, o que o próprio histórico guardou
  const found = $derived(prKey ? findPr(prKey) : null);
  let prLog = $state<Activity[] | null>(null);
  let prErr = $state<string | null>(null);
  $effect(() => {
    const k = prKey;
    untrack(() => {
      prLog = null; prErr = null;
      if (!k) return;
      const p = findPr(k)?.pr;
      const n = p?.prId ?? (store.s?.activity || []).find(a => a.key === k)?.prId;
      get<{ activity: Activity[] }>("activity", { key: k, prId: n ?? undefined, org: p?.org }).then(r => { if (prKey === k) prLog = r.activity; })
        .catch(e => { if (prKey === k) prErr = e.message; });
    });
  });
  $effect(() => { if (prKey && !repos.loaded) repos.load(false); });
  const seed = $derived(prKey ? (prLog || store.s?.activity || []).find(a => a.key === prKey) : null);
  const head = $derived(prKey ? { title: found?.pr.title || seed?.title || "PR", prId: found?.pr.prId ?? seed?.prId, org: found?.pr.org || seed?.org || "",
    repo: found?.pr.repo || "", provider: found?.pr.provider || seed?.provider, url: found?.pr.url || seed?.url, source: found?.pr.source, target: found?.pr.target || seed?.target } : null);
  const local = $derived(found ? localClone(found.pr.repoKey) : null);

  const all = $derived(prKey ? (prLog ?? (store.s?.activity || []).filter(a => a.key === prKey)) : store.s?.activity || []);
  const list = $derived(all.filter(a => (who === "all" || (who === "auto" ? a.by === "auto" : a.by !== "auto"))
    && (prKey || !kind || (kind === "pr" ? !a.kind : kind === "git" ? a.kind === "git" : a.kind && a.kind !== "git"))));
  const LABEL: Record<string, [string, string]> = {
    "deploy-approve": ["Aprovou deploy", "good"], "deploy-reject": ["Rejeitou deploy", "bad"], permit: ["Liberou permissão", "good"], cancel: ["Cancelou run", "bad"],
    "build-retry": ["Tentou de novo", "neutral"], "build-rerun": ["Rodou de novo", "neutral"], "build-cancel": ["Cancelou build", "bad"],
    archive: ["Arquivou", "neutral"], unarchive: ["Desarquivou", "neutral"], "pr-create": ["Criou PR", "accent"], comment: ["Comentou", "info"],
  };
  function label(a: Activity): [string, string] {
    if (LABEL[a.action]) return LABEL[a.action];
    if (a.action.startsWith("git-")) return [a.action.slice(4).replace("-", " "), "info"];
    return VOTES[a.vote as number] || ["Removeu o voto", "neutral"];
  }
  const isPr = (a: Activity) => !a.kind && !!a.key;
</script>

<Page title="Histórico" sub={prKey ? "O que você e o piloto fizeram nesta PR" : "Tudo que você e o piloto fizeram — votos, deploys, builds e operações de Git"}>
  {#if head}
    <div class="focus">
      <span class="fi"><GitPullRequest size={15} /></span>
      <div class="ft">
        <div class="row" style="gap:6px"><ProviderIcon provider={head.provider} size={12} /><b class="ell">{head.prId ? `#${head.prId} ` : ""}{head.title}</b></div>
        <div class="tiny muted ell">{head.org}{head.repo ? ` / ${head.repo}` : ""}{#if head.source} · <span class="mono">{head.source} → {head.target}</span>{/if}</div>
      </div>
      <div class="fa">
        {#if found}<button class="btn sm" onclick={() => openPr(prKey)}><GitPullRequest size={13} /> Ver a PR</button>{/if}
        {#if found}<button class="btn sm" onclick={() => openPrCommits(found!.pr)} disabled={!local} title={local ? `Commits de ${found.pr.source} no clone local` : "Repositório não clonado nesta máquina"}>
          <GitCommitHorizontal size={13} /> Commits da branch</button>{/if}
        {#if head.url}<a class="btn sm ghost icon" href={head.url} target="_blank" rel="noopener" title="Abrir no navegador"><ExternalLink size={14} /></a>{/if}
        <button class="btn sm ghost" onclick={() => go("/history", "soft")} title="Voltar ao histórico completo"><X size={14} /> Tudo</button>
      </div>
    </div>
  {/if}
  <div class="toolbar">
    <Segmented bind:value={who} options={[{ value: "all", label: "Tudo" }, { value: "auto", label: "Piloto" }, { value: "manual", label: "Você" }]} />
    {#if !prKey}<Segmented bind:value={kind} options={[{ value: "", label: "Todos os tipos" }, { value: "pr", label: "PRs" }, { value: "deploy", label: "Deploys e builds" }, { value: "git", label: "Git" }]} />{/if}
    <span class="muted small">{#if prKey}{prLog ? `${all.length} evento(s) desta PR` : "lendo o histórico…"}{:else}últimos {store.s?.activity.length || 0} eventos{/if}</span>
  </div>
  <div class="card scroll">
    <table>
      <thead><tr><th>Quando</th><th>Quem</th><th>Ação</th>{#if !prKey}<th>Item</th>{:else}<th>Detalhe</th>{/if}</tr></thead>
      <tbody>
        {#each list as a, i (a.ts + i)}
          {@const l = label(a)}
          <tr>
            <td class="small muted nowrap">{dateTime(a.ts)}</td>
            <td>{#if a.by === "auto"}<span class="pill accent">⚡ piloto</span>{:else}<span class="pill neutral">você</span>{/if}{#if a.detail && !prKey}<div class="tiny muted">{a.detail}</div>{/if}</td>
            <td><span class="pill {l[1]}">{l[0]}</span></td>
            {#if prKey}
              <td class="small">{#if a.kind}<span class="ell">{a.pipeline ? `${a.pipeline}${a.stage ? " → " + a.stage : ""}` : a.title}</span>{:else if a.detail}{a.detail}{:else}<span class="muted">—</span>{/if}</td>
            {:else}
              <td>
                <div class="row" style="gap:6px"><ProviderIcon provider={a.kind === "git" ? null : a.provider} size={12} />
                  {#if isPr(a)}<button class="lk ell" onclick={() => go(prHistoryPath(a.key!), "soft")} title="Ver só o histórico desta PR">{a.prId ? `#${a.prId} ` : ""}{a.title}</button>
                    {#if a.url}<a href={a.url} target="_blank" rel="noopener" class="ext" title="Abrir no navegador"><ExternalLink size={11} /></a>{/if}
                  {:else if a.url}<a href={a.url} target="_blank" rel="noopener" class="ell">{a.prId ? `#${a.prId} ` : ""}{a.pipeline ? `${a.pipeline}${a.stage ? " → " + a.stage : ""}` : a.title}</a><ExternalLink size={11} class="muted" />
                  {:else}<span class="ell">{a.title}</span>{/if}</div>
                <div class="tiny muted">{a.org}{#if a.creatorName} · {a.creatorName} → {a.target}{/if}{#if a.branch} · {a.branch}{/if}</div>
              </td>
            {/if}
          </tr>
        {/each}
      </tbody>
    </table>
    {#if prErr}<div class="err small">{prErr}</div>
    {:else if !list.length && (!prKey || prLog)}<Empty title={prKey ? "Nada registrado nesta PR" : "Nada por aqui ainda"} text={prKey ? "Votos, aprovações do piloto e comentários feitos pelo app aparecem aqui." : ""} />{/if}
  </div>
</Page>

<style>
  .focus { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; padding: 10px 12px; flex: none;
    background: var(--surface); border: 1px solid var(--line); border-radius: var(--r); box-shadow: var(--shadow-1); }
  .fi { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 8px; background: var(--accent-soft); color: var(--accent); flex: none; }
  .ft { display: grid; gap: 2px; flex: 1 1 240px; min-width: 0; }
  .ft b { font-weight: 650; }
  .fa { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex: none; flex-wrap: wrap; }
  .scroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; }
  table { width: 100%; border-collapse: collapse; }
  th { position: sticky; top: 0; z-index: 1; text-align: left; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted);
    padding: 11px 14px; background: var(--surface); box-shadow: inset 0 -1px 0 var(--line); }
  td { padding: 9px 14px; border-top: 1px solid var(--line); vertical-align: middle; font-size: 13px; }
  tbody tr { transition: background var(--t-fast); }
  tbody tr:hover { background: var(--surface-2); }
  .lk { border: 0; background: none; padding: 0; color: var(--text); font: inherit; text-align: left; cursor: pointer; }
  .lk:hover { color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
  .ext { display: inline-grid; color: var(--muted); }
  .ext:hover { color: var(--text); }
  .err { padding: 14px; color: var(--bad); }
</style>
