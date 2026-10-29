<script lang="ts">
  // Skills e MCPs de um projeto e das contas de IA — de quem é cada um e levar de um lado para o outro.
  // Em cima, a constelação: o projeto no centro e as contas em volta; as partículas que correm em cada linha são o que
  // os dois têm em comum, e o anel em volta do projeto é a mistura com a conta em foco (iguais, diferentes, só de um lado).
  // Ao lado, o espectro (a mesma mistura, clicável para filtrar) e o que vale fazer agora. Embaixo, dois jeitos de ver:
  // "Ponte" (projeto ⇄ conta em foco, item por item — o pacote corre na direção da cópia) e "Matriz" (todos os lugares,
  // com o fio ligando onde cada item está). Sem projeto (repoId nulo), a constelação é das contas e a vista é a matriz.
  import { ArrowLeft, ArrowLeftRight, ArrowRight, Check, ChevronDown, Cloud, Eye, FileText, FolderGit2, KeyRound, Link2, Plug, Plus, RefreshCw, Search, ShieldAlert, Sparkles, Trash2, WandSparkles, X } from "@lucide/svelte";
  import { tick, untrack } from "svelte";
  import { get } from "../../lib/api";
  import { ui } from "../../lib/ui.svelte";
  import { work } from "../../lib/work.svelte";
  import Menu, { type MenuItem } from "../Menu.svelte";
  import Segmented from "../Segmented.svelte";
  import AgentIcon from "../work/AgentIcon.svelte";
  import AccountAvatar from "./AccountAvatar.svelte";
  import { bestSource, can, copyItem, locColor, locLabel, removeItem, type Entry, type Inv, type Item, type Loc } from "./tools.svelte";

  let { repoId = null }: { repoId?: string | null } = $props();

  let inv = $state<Inv | null>(null);
  let err = $state<string | null>(null);
  let loading = $state(false);
  let q = $state("");
  let kind = $state<"all" | "skill" | "mcp">("all");
  let view = $state<"bridge" | "matrix">(untrack(() => (repoId ? "bridge" : "matrix")));
  let open = $state<string | null>(null);
  let busy = $state<{ key: string; dst: string } | null>(null);
  let landed = $state<{ key: string; loc: string } | null>(null);
  let showCloud = $state(false);
  let showOther = $state(false);
  let preview = $state<{ key: string; loc: string; text: string; files: string[] } | null>(null);
  let only = $state<string | null>(null);
  let hl = $state<string | null>(null);
  let hov = $state<string | null>(null);
  let hc = $state<number | null>(null);

  async function load() {
    loading = true;
    try { inv = await get<Inv>("ai/tools", { repoId }); err = null; }
    catch (e: any) { err = e.message; }
    finally { loading = false; }
  }
  $effect(() => { void repoId; untrack(load); });
  $effect(() => { if (!work.ai.length) work.loadAi(); });

  const locs = $derived(new Map((inv?.locations || []).map(l => [l.id, l])));
  const accountLocs = $derived((inv?.locations || []).filter(l => l.kind === "account"));
  const project = $derived(repoId ? work.projects.find(p => p.id === repoId) : null);

  // a conta em foco: a escolhida aqui, senão a do projeto, senão a primeira do Claude
  let picked = $state<string | null>(null);
  const focusId = $derived(picked && accountLocs.some(l => l.accountId === picked) ? picked
    : (project?.settings?.account && accountLocs.some(l => l.accountId === project.settings.account) ? project.settings.account
      : accountLocs.find(l => l.provider === "claude")?.accountId || accountLocs[0]?.accountId || null));
  const accLoc = $derived(focusId ? locs.get("a:" + focusId) : undefined);
  const localLoc = $derived(focusId ? locs.get("l:" + focusId) : undefined);
  const projLoc = $derived(repoId ? (locs.get("p:" + (accLoc?.provider || "claude")) || locs.get("p:claude")) : undefined);
  const acc = (id?: string) => work.ai.find(a => a.id === id);

  const cloud = (it: Item) => it.entries.every(e => e.synced);
  const match = (it: Item) => (kind === "all" || it.type === kind) && (!q.trim() || (it.name + " " + (it.desc || "")).toLowerCase().includes(q.trim().toLowerCase()));
  const visible = $derived((inv?.items || []).filter(match));

  type Row = { it: Item; p?: Entry; a?: Entry; state: "diff" | "acc" | "proj" | "sync" | "other" | "cloud" };
  function rowOf(it: Item): Row {
    const p = projLoc ? it.entries.find(e => e.loc === projLoc.id) : undefined;
    const a = it.entries.find(e => e.loc === accLoc?.id) || it.entries.find(e => e.loc === localLoc?.id);
    const state = p && a ? (p.hash === a.hash ? "sync" : "diff") : a ? (cloud(it) ? "cloud" : "acc") : p ? "proj" : cloud(it) ? "cloud" : "other";
    return { it, p, a, state };
  }
  const rows = $derived(visible.map(rowOf));
  const by = $derived({
    diff: rows.filter(r => r.state === "diff"), acc: rows.filter(r => r.state === "acc"), proj: rows.filter(r => r.state === "proj"),
    sync: rows.filter(r => r.state === "sync"), other: rows.filter(r => r.state === "other"), cloud: rows.filter(r => r.state === "cloud"),
  });
  const shows = (s: Row["state"]) => !only || only === s;
  const spread = (it: Item) => new Set(it.entries.map(e => e.loc.replace(/^l:/, "a:"))).size;

  // ------------------------------------------------------------ o espectro: projeto × conta em foco
  const tint = $derived<Record<Row["state"], string>>({ diff: "var(--warn)", acc: locColor(accLoc), proj: "var(--accent)", sync: "var(--good)", other: "var(--muted)", cloud: "var(--info)" });
  type Spec = { id: string; label: string; color: string; has: (it: Item) => boolean };
  const specDef = $derived<Spec[]>(repoId ? (["sync", "diff", "proj", "acc"] as const).map(id => ({
    id, color: tint[id], has: (it: Item) => rowOf(it).state === id,
    label: { sync: "Nos dois", diff: "Diferentes", proj: "Só no projeto", acc: `Só em ${locLabel(accLoc)}` }[id],
  })) : [
    { id: "many", label: "Em várias contas", color: "var(--good)", has: it => it.same && spread(it) > 1 },
    { id: "diff", label: "Diferentes", color: "var(--warn)", has: it => !it.same },
    { id: "one", label: "Só em uma", color: "var(--accent)", has: it => it.same && spread(it) === 1 },
  ]);
  const spec = $derived(specDef.map(s => ({ ...s, n: visible.filter(it => !cloud(it) && s.has(it)).length })));
  const specTotal = $derived(spec.reduce((s, x) => s + x.n, 0));
  const arcs = $derived.by(() => {
    let at = 0;
    return spec.filter(s => s.n).map(s => { const len = (s.n / Math.max(1, specTotal)) * 100; const a = { ...s, from: at, len }; at += len; return a; });
  });
  async function show(s: string) {
    only = only === s ? null : s;
    if (only) { await tick(); document.getElementById("t-list")?.scrollIntoView({ behavior: "smooth", block: "start" }); }
  }

  // ------------------------------------------------------------ o que vale fazer agora
  const tracked = $derived(inv?.project?.tracked?.[".mcp.json"] !== false);
  const leaks = $derived(projLoc ? (inv?.items || []).filter(it => it.type === "mcp" && it.entries.some(e => locs.get(e.loc)?.kind === "project" && e.secrets?.length)) : []);
  const localOnly = $derived(by.acc.filter(r => r.a && locs.get(r.a.loc)?.kind === "local"));
  type Tip = { id: string; tone: "accent" | "warn" | "bad" | "good"; icon: any; title: string; text: string; act?: { label: string; run: () => void } };
  const tips = $derived.by((): Tip[] => {
    if (!inv) return [];
    const out: Tip[] = [];
    if (!repoId) {
      const real = visible.filter(it => !cloud(it));
      const single = real.filter(it => new Set(it.entries.map(e => e.loc.replace(/^l:/, "a:"))).size === 1);
      const diff = real.filter(it => !it.same);
      if (diff.length) out.push({ id: "diff", tone: "warn", icon: ArrowLeftRight, title: `${diff.length} com versões diferentes`,
        text: `${diff.slice(0, 3).map(x => x.name).join(", ")}${diff.length > 3 ? "…" : ""} — o mesmo nome com conteúdo diferente entre as contas (anel laranja na matriz).` });
      if (single.length) out.push({ id: "single", tone: "accent", icon: Sparkles, title: `${single.length} só em uma conta`,
        text: `${single.slice(0, 3).map(x => x.name).join(", ")}${single.length > 3 ? "…" : ""} — as outras contas não têm. O + na matriz leva com um clique.` });
      if (!out.length && real.length) out.push({ id: "ok", tone: "good", icon: Check, title: "Tudo em ordem", text: "As contas têm as mesmas coisas, nas mesmas versões." });
      return out;
    }
    const an = locLabel(accLoc);
    if (leaks.length) out.push({ id: "leak", tone: "bad", icon: ShieldAlert, title: `Segredo no ${projLoc?.files?.mcp || ".mcp.json"}`,
      text: `${leaks.map(x => x.name).join(", ")} ${leaks.length > 1 ? "têm" : "tem"} chave gravada ${tracked ? "num arquivo que vai para o Git" : "no arquivo do projeto"}. Troque por \${VARIÁVEL}.` });
    if (by.diff.length) out.push({ id: "diff", tone: "warn", icon: ArrowLeftRight, title: `${by.diff.length} com versões diferentes`,
      text: `${by.diff.slice(0, 3).map(r => r.it.name).join(", ")}${by.diff.length > 3 ? "…" : ""} — no projeto e em ${an} não batem. Escolha qual vale em “Igualar”.`, act: { label: "Mostrar", run: () => show("diff") } });
    if (localOnly.length) out.push({ id: "local", tone: "accent", icon: FolderGit2, title: `${localOnly.length} MCP só seu neste projeto`,
      text: `${localOnly.map(r => r.it.name).join(", ")} está em ${an}, só para este projeto. No projeto, todo mundo (e toda conta) usa.`,
      act: { label: "Levar ao projeto", run: () => bulk(localOnly, projLoc!) } });
    const accOnly = by.acc.filter(r => !localOnly.includes(r));
    if (accOnly.length && projLoc) out.push({ id: "acc", tone: "accent", icon: ArrowLeft, title: `${accOnly.length} só em ${an}`,
      text: "Outras contas e quem clonar o projeto não têm. Traga o que for do projeto.", act: { label: "Mostrar", run: () => show("acc") } });
    if (by.proj.length && accLoc) out.push({ id: "proj", tone: "accent", icon: ArrowRight, title: `${by.proj.length} só no projeto`,
      text: `Para usar em outros projetos com ${an}, leve para a conta.`, act: { label: "Mostrar", run: () => show("proj") } });
    if (!out.length && rows.length) out.push({ id: "ok", tone: "good", icon: Check, title: "Tudo em ordem", text: projLoc ? `Projeto e ${an} estão alinhados.` : "Nada fora do lugar." });
    return out;
  });

  // ------------------------------------------------------------ constelação: projeto (ou as contas) no centro, contas em volta
  const W = 360, H = 240, CX = W / 2, CY = H / 2;
  const ring = $derived.by(() => {
    const n = accountLocs.length;
    const rx = 128, ry = 84;
    return accountLocs.map((l, i) => {
      const ang = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(1, n);
      const x = CX + rx * Math.cos(ang), y = CY + ry * Math.sin(ang);
      const ids = new Set([l.id, "l:" + l.accountId]);
      const mine = (inv?.items || []).filter(it => it.entries.some(e => ids.has(e.loc)) && !cloud(it));
      const shared = projLoc ? mine.filter(it => it.entries.some(e => e.loc === projLoc.id)).length : mine.length;
      // a linha faz uma curva leve (o ponto de controle sai para o lado), as partículas seguem por ela
      const qx = (CX + x) / 2 - (y - CY) * 0.16, qy = (CY + y) / 2 + (x - CX) * 0.16;
      return { l, x, y, d: `M${CX},${CY} Q${qx.toFixed(1)},${qy.toFixed(1)} ${x.toFixed(1)},${y.toFixed(1)}`, total: mine.length, shared,
        skills: mine.filter(it => it.type === "skill").length, mcps: mine.filter(it => it.type === "mcp").length };
    });
  });
  const maxShared = $derived(Math.max(1, ...ring.map(r => r.shared)));
  const projCount = $derived(projLoc ? (inv?.items || []).filter(it => it.entries.some(e => locs.get(e.loc)?.kind === "project")).length : 0);
  const accCount = $derived((inv?.items || []).filter(it => !cloud(it) && it.entries.some(e => locs.get(e.loc)?.kind !== "project")).length);
  const cap = $derived(ring.find(n => n.l.accountId === (hov || focusId)));

  // ------------------------------------------------------------ ações
  async function take(r: Row, dst: Loc | undefined, from?: Entry) {
    if (!dst) return;
    busy = { key: r.it.key, dst: dst.id };
    const src = from || bestSource(r.it, locs, [accLoc?.id || "", localLoc?.id || "", projLoc?.id || ""].filter(id => id !== dst.id));
    const ok = await copyItem(repoId, r.it, src, dst, { projectTracked: tracked, overwrite: r.state === "diff" ? undefined : false });
    busy = null;
    if (ok) { await load(); flash(r.it.key, dst.id); }
  }
  function flash(key: string, loc: string) {
    landed = { key, loc };
    setTimeout(() => { if (landed?.key === key) landed = null; }, 1800);
  }
  async function bulk(list: Row[], dst: Loc) {
    if (!list.length) return;
    const yes = await ui.ask({ title: `Levar ${list.length} item(ns) para ${locLabel(dst)}?`, message: list.map(r => r.it.name).join(", "), confirm: "Levar" });
    if (!yes) return;
    const prog = ui.progress(`Levando para ${locLabel(dst)}…`);
    let n = 0;
    for (const r of list) {
      busy = { key: r.it.key, dst: dst.id };
      const src = bestSource(r.it, locs, [accLoc?.id || "", localLoc?.id || "", projLoc?.id || ""].filter(id => id !== dst.id));
      if (await copyItem(repoId, r.it, src, dst, { quiet: true, overwrite: false, projectTracked: tracked })) n++;
    }
    busy = null;
    prog.done(`${n} de ${list.length} em ${locLabel(dst)}`);
    await load();
  }
  async function drop(it: Item, l: Loc) { if (await removeItem(repoId, it, l)) await load(); }
  async function look(it: Item, e: Entry) {
    if (preview?.key === it.key && preview.loc === e.loc) { preview = null; return; }
    try { const r = await get<{ text: string; files: string[] }>("ai/tools/skill", { repoId, loc: e.loc, name: it.name }); preview = { key: it.key, loc: e.loc, ...r }; }
    catch (x) { ui.error(x); }
  }
  /** Para onde dá para levar: todos os lugares que aceitam o tipo e ainda não têm. */
  function targets(it: Item): MenuItem[] {
    const has = new Set(it.entries.map(e => e.loc));
    const free = (inv?.locations || []).filter(l => can(l, it.type) && !has.has(l.id));
    if (!free.length) return [{ label: "Já está em todos os lugares", disabled: true }];
    const proj = free.filter(l => l.kind === "project"), accs = free.filter(l => l.kind === "account"), loc = free.filter(l => l.kind === "local");
    const mk = (l: Loc): MenuItem => ({ label: locLabel(l), onclick: () => take(rowOf(it), l) });
    return [
      ...(proj.length ? [{ heading: "Projeto" }, ...proj.map(mk)] : []),
      ...(accs.length ? [{ heading: "Conta (todos os projetos)" }, ...accs.map(mk)] : []),
      ...(loc.length && it.type === "mcp" ? [{ heading: "Conta, só neste projeto" }, ...loc.map(mk)] : []),
    ];
  }
  function rowMenu(r: Row): MenuItem[] {
    const out: MenuItem[] = [...targets(r.it), { separator: true }];
    for (const e of r.it.entries) {
      const l = locs.get(e.loc);
      if (l && !e.readonly) out.push({ label: `Remover de ${locLabel(l)}`, icon: Trash2, danger: true, onclick: () => drop(r.it, l) });
    }
    return out;
  }
  const same = (it: Item, e: Entry) => it.entries.filter(x => x.hash === e.hash).length;
  const short = (s?: string | null, n = 110) => (s && s.length > n ? s.slice(0, n - 1) + "…" : s || "");
  const entryAt = (it: Item, l: Loc) => it.entries.find(x => x.loc === l.id) || (l.accountId ? it.entries.find(x => x.loc === "l:" + l.accountId) : undefined);
  const isBusy = (k: string, d?: string) => !!busy && busy.key === k && (!d || busy.dst === d);
</script>

{#snippet owner(l: Loc | undefined, e?: Entry)}
  {#if l}
    <span class="own {l.kind}" style="--oc:{locColor(l)}" title={`${locLabel(l)}${e?.path ? "\n" + e.path : ""}${e?.link ? "\n→ " + e.link : ""}`}>
      {#if l.kind === "project"}<FolderGit2 size={11} />{:else}<i></i>{/if}
      <span class="ell">{locLabel(l)}</span>
      {#if l.provider !== "claude"}<AgentIcon provider={l.provider} size={11} />{/if}
      {#if e?.link}<Link2 size={10} />{/if}{#if e?.synced}<Cloud size={10} />{/if}
    </span>
  {/if}
{/snippet}

{#snippet glyph(it: Item)}
  <span class="gl {it.type}">{#if it.type === "skill"}<WandSparkles size={14} />{:else}<Plug size={14} />{/if}</span>
{/snippet}

{#snippet detail(r: Row)}
  <div class="det">
    {#if r.it.desc}<p class="dd">{r.it.desc}</p>{/if}
    <div class="where">
      {#each r.it.entries as e, j (e.loc)}
        {@const l = locs.get(e.loc)}
        <div class="we" style="--oc:{locColor(l)};--j:{j}">
          {@render owner(l, e)}
          <span class="meta">
            {#if r.it.type === "skill"}
              {#if e.version}<span class="v">v{e.version}</span>{/if}<span>{e.files} arquivo{e.files === 1 ? "" : "s"}</span>
              {#if e.link}<span class="mono ell" title={e.link}>link → {e.link}</span>{/if}
            {:else}
              <span class="tp">{e.transport}</span>{#if e.disabled}<span class="off">desligado</span>{/if}
              <code class="ell" title={e.command || e.url || ""}>{e.command || e.url}</code>
            {/if}
          </span>
          <span class="hsh" class:solo={r.it.entries.length > 1 && same(r.it, e) === 1} title="Impressão do conteúdo: iguais = mesma versão">
            {r.it.entries.length > 1 ? (same(r.it, e) === r.it.entries.length ? "igual a todos" : same(r.it, e) > 1 ? `igual a ${same(r.it, e) - 1}` : "versão única") : ""}</span>
          <span class="wa">
            {#if r.it.type === "skill"}<button class="btn sm ghost icon" title="Ler o SKILL.md" aria-label="Ler o SKILL.md" onclick={() => look(r.it, e)}><Eye size={13} /></button>{/if}
            {#if !e.readonly && l}<button class="btn sm ghost icon" title={`Remover de ${locLabel(l)}`} aria-label={`Remover de ${locLabel(l)}`} onclick={() => drop(r.it, l)}><Trash2 size={13} /></button>{/if}
          </span>
          {#if (e.env?.length || e.headers?.length)}
            <div class="keys">
              {#each [...(e.env || []), ...(e.headers || [])] as k (k)}<span class="key" class:sec={e.secrets?.includes(k)}>{#if e.secrets?.includes(k)}<KeyRound size={10} />{/if}{k}</span>{/each}
            </div>
          {/if}
        </div>
      {/each}
    </div>
    {#if preview && preview.key === r.it.key}
      <div class="pv">
        <div class="pvh"><FileText size={12} /> SKILL.md · {locLabel(locs.get(preview.loc))}<span class="grow"></span>
          <span class="muted">{preview.files.length} arquivo(s)</span><button class="btn sm ghost icon" aria-label="Fechar" onclick={() => (preview = null)}><X size={12} /></button></div>
        <pre>{preview.text}</pre>
      </div>
    {/if}
    <div class="dact"><Menu items={targets(r.it)} align="left">{#snippet trigger()}<span class="btn sm"><Plus size={13} /> Levar para… <ChevronDown size={12} /></span>{/snippet}</Menu></div>
  </div>
{/snippet}

{#snippet bridgeRow(r: Row, i: number)}
  {@const pl = r.p ? locs.get(r.p.loc) : projLoc}
  {@const al = r.a ? locs.get(r.a.loc) : accLoc}
  {@const mv = busy?.key === r.it.key ? (busy.dst === pl?.id ? "to-p" : "to-a") : ""}
  <div class="br {r.state} {mv}" class:open={open === r.it.key} class:landed={landed?.key === r.it.key} style="--i:{i};--ac:{locColor(al)}" data-menu-row>
    <button class="bn" onclick={() => (open = open === r.it.key ? null : r.it.key)} aria-expanded={open === r.it.key}>
      {@render glyph(r.it)}
      <span class="nm"><b class="ell">{r.it.name}</b><span class="ds ell">{short(r.it.desc, 140) || (r.it.type === "mcp" ? (r.p || r.a)?.command || (r.p || r.a)?.url || "" : "")}</span></span>
    </button>
    <div class="side p">
      {#if r.p}<span class="has hp"><Check size={12} /> {pl?.provider === "claude" ? "no projeto" : locLabel(pl)}</span>
      {:else if projLoc && can(projLoc, r.it.type)}<button class="add to-p" disabled={!!mv} onclick={() => take(r, projLoc)}><ArrowLeft size={12} /> trazer</button>
      {:else}<span class="na">—</span>{/if}
    </div>
    <div class="cd" aria-hidden="true"><i class="tr"></i><i class="pk"></i>{#if r.state === "diff"}<span class="lb">diferentes</span>{/if}</div>
    <div class="side a">
      {#if r.a}<span class="has ha"><Check size={12} /> {al?.kind === "local" ? "só aqui" : "na conta"}</span>
      {:else if accLoc && can(accLoc, r.it.type)}<button class="add to-a" disabled={!!mv} onclick={() => take(r, accLoc)}>levar <ArrowRight size={12} /></button>
      {:else}<span class="na">—</span>{/if}
    </div>
    <div class="also">
      {#each r.it.entries.filter(e => e.loc !== r.p?.loc && e.loc !== r.a?.loc).slice(0, 4) as e (e.loc)}
        {@const l = locs.get(e.loc)}
        {#if l?.kind === "project"}<span class="dot proj" title={locLabel(l)}><FolderGit2 size={9} /></span>
        {:else if l && acc(l.accountId)}<span class="mini" title={locLabel(l)}><AccountAvatar a={{ ...acc(l.accountId)!, name: locLabel({ ...l, kind: "account" }) }} size={18} /></span>{/if}
      {/each}
      {#if r.it.entries.length - (r.p ? 1 : 0) - (r.a ? 1 : 0) > 4}<span class="more">+{r.it.entries.length - (r.p ? 1 : 0) - (r.a ? 1 : 0) - 4}</span>{/if}
    </div>
    <div class="act">
      {#if r.state === "diff"}
        <Menu align="right" items={[
          { heading: "Igualar usando" },
          { label: "a versão do projeto", onclick: () => take(r, al, r.p) },
          { label: `a versão de ${locLabel(al)}`, onclick: () => take(r, pl, r.a) },
        ]}>{#snippet trigger()}<span class="btn sm"><ArrowLeftRight size={12} /> Igualar</span>{/snippet}</Menu>
      {/if}
      <Menu items={rowMenu(r)} />
    </div>
  </div>
  {#if open === r.it.key}{@render detail(r)}{/if}
{/snippet}

{#snippet group(id: string, st: Row["state"], title: string, hint: string, list: Row[], bulkTo?: Loc, bulkLabel?: string)}
  {#if list.length && shows(st)}
    <section class="grp" id={id} style="--sc:{tint[st]}">
      <header><i class="sd"></i><h4>{title}</h4><span class="c">{list.length}</span><span class="h">{hint}</span><span class="grow"></span>
        {#if bulkTo && list.length > 1}<button class="btn sm ghost" onclick={() => bulk(list, bulkTo)}>{bulkLabel}</button>{/if}</header>
      <div class="rows">{#each list as r, i (r.it.key)}{@render bridgeRow(r, i)}{/each}</div>
    </section>
  {/if}
{/snippet}

<div class="tools" class:noproj={!repoId}>
  <div class="hero">
    <div class="const" aria-label={repoId ? "Contas e o que têm em comum com o projeto" : "Contas e o que cada uma tem"}>
      <div class="sky">
        <i class="sweep" aria-hidden="true"></i>
        {#if inv}
          <svg viewBox="0 0 {W} {H}" role="presentation">
            <defs>
              <radialGradient id="t-glow"><stop offset="0" stop-color="var(--accent)" stop-opacity=".38" /><stop offset="1" stop-color="var(--accent)" stop-opacity="0" /></radialGradient>
            </defs>
            <ellipse class="orbit" cx={CX} cy={CY} rx="128" ry="84" />
            <ellipse class="orbit in" cx={CX} cy={CY} rx="78" ry="52" />
            <circle cx={CX} cy={CY} r="74" fill="url(#t-glow)" class="breath" />
            {#each ring as n (n.l.id)}
              <path d={n.d} class="edge" class:on={n.l.accountId === focusId} class:hv={n.l.accountId === hov} class:none={!n.shared}
                style="--oc:{locColor(n.l)};stroke-width:{n.shared ? 1 + (2.6 * n.shared) / maxShared : 1}" />
            {/each}
            {#each ring as n, i (n.l.id)}
              {#if n.shared}
                {@const k = Math.min(3, Math.ceil((3 * n.shared) / maxShared))}
                {#each Array(k) as _, j}
                  {@const dur = 2.8 + ((i * 7 + j * 3) % 5) * 0.35}
                  <circle class="pkc" class:on={n.l.accountId === focusId || n.l.accountId === hov} r={n.l.accountId === focusId ? 2.4 : 1.7} style="fill:{locColor(n.l)}">
                    <animateMotion dur="{dur}s" begin="-{((dur / k) * j + i * 0.4).toFixed(2)}s" repeatCount="indefinite" path={n.d}
                      keyPoints={j % 2 ? "1;0" : "0;1"} keyTimes="0;1" calcMode="linear" />
                  </circle>
                {/each}
              {/if}
            {/each}
            {#if specTotal}
              <circle class="dn bg" cx={CX} cy={CY} r="50" />
              {#each arcs as a (a.id)}
                <circle class="dn" class:dim={(hl && hl !== a.id) || (only && only !== a.id)} cx={CX} cy={CY} r="50" pathLength="100" transform="rotate(-90 {CX} {CY})"
                  style="stroke:{a.color};stroke-dasharray:{Math.max(0.01, a.len - (arcs.length > 1 ? 1.4 : 0))} 100;stroke-dashoffset:{-a.from}" />
              {/each}
            {/if}
          </svg>
          <div class="core" title={inv.project?.path}>
            {#if repoId}<FolderGit2 size={15} /><b>{projCount}</b><span>no projeto</span>
            {:else}<Sparkles size={15} /><b>{accCount}</b><span>nas contas</span>{/if}
          </div>
          {#each ring as n, i (n.l.id)}
            {@const a = acc(n.l.accountId)}
            <button class="node" class:on={n.l.accountId === focusId} style="left:{(n.x / W) * 100}%;top:{(n.y / H) * 100}%;--oc:{locColor(n.l)};--i:{i}"
              aria-label={`${locLabel(n.l)}: ${n.total} item(ns)`} onclick={() => (picked = n.l.accountId!)}
              onpointerenter={() => (hov = n.l.accountId!)} onpointerleave={() => (hov = null)} onfocus={() => (hov = n.l.accountId!)} onblur={() => (hov = null)}>
              <span class="aw">
                {#if a}<AccountAvatar a={{ ...a, name: locLabel({ ...n.l, kind: "account" }) }} size={30} state={work.activity[a.id]?.state} />{:else}<span class="pv"><AgentIcon provider={n.l.provider} size={16} /></span>{/if}
                {#if n.shared}<span class="ns">{n.shared}</span>{/if}
              </span>
              <span class="nl ell">{locLabel(n.l)}</span>
            </button>
          {/each}
        {:else}
          <div class="core ghost"></div>
        {/if}
      </div>
      <div class="cap" style="--oc:{cap ? locColor(cap.l) : 'var(--muted)'}">
        {#if cap}
          <i></i><b class="ell">{locLabel(cap.l)}</b>
          <span class="ell">{cap.skills} skill{cap.skills === 1 ? "" : "s"} · {cap.mcps} MCP{cap.mcps === 1 ? "" : "s"}{#if repoId}{" · "}<em>{cap.shared} em comum</em>{/if}</span>
          <span class="grow"></span>
          {#if hov && hov !== focusId}<span class="hint">clique para focar</span>{:else}<span class="hint">em foco</span>{/if}
        {:else}<span class="hint">{inv ? "Nenhuma conta de IA" : "Lendo…"}</span>{/if}
      </div>
    </div>

    <div class="intel">
      <div class="ih">
        <div class="it">
          <h3>{repoId ? "Skills e MCPs" : "Skills e MCPs das contas"}</h3>
          <p>{#if repoId && accLoc}O projeto <b>{inv?.project?.name}</b> lado a lado com <b style="color:{locColor(accLoc)}">{locLabel(accLoc)}</b> — clique numa conta para trocar.
            {:else}Quem tem o quê em cada conta — clique numa conta para destacar, leve de uma para outra com um clique.{/if}</p>
        </div>
        <button class="btn sm ghost icon" title="Ler de novo" aria-label="Recarregar" onclick={load} disabled={loading}><RefreshCw size={14} class={loading ? "spin" : ""} /></button>
      </div>
      {#if specTotal}
        <div class="spec">
          <div class="sbar">
            {#each spec as s (s.id)}
              <button class="sg" class:dim={(hl && hl !== s.id) || (only && only !== s.id)} class:zero={!s.n} style="flex-grow:{s.n};--sc:{s.color}"
                aria-label={`${s.label}: ${s.n}`} tabindex={s.n ? 0 : -1} onclick={() => show(s.id)}
                onpointerenter={() => (hl = s.id)} onpointerleave={() => (hl = null)}></button>
            {/each}
          </div>
          <div class="slg">
            {#each spec as s (s.id)}
              <button class="sl" class:on={only === s.id} class:zero={!s.n} style="--sc:{s.color}" disabled={!s.n} aria-pressed={only === s.id}
                onclick={() => show(s.id)} onpointerenter={() => (hl = s.id)} onpointerleave={() => (hl = null)}><i></i><b>{s.n}</b><span class="ell">{s.label}</span></button>
            {/each}
            {#if only}<button class="lnk" onclick={() => (only = null)}>mostrar tudo</button>{/if}
          </div>
        </div>
      {/if}
      <div class="tips">
        {#each tips as t, i (t.id)}
          <div class="tip {t.tone}" style="--i:{i}">
            <span class="ti"><t.icon size={14} /></span>
            <div class="tt"><b>{t.title}</b><span>{t.text}</span></div>
            {#if t.act}<button class="btn sm" onclick={t.act.run}>{t.act.label}</button>{/if}
          </div>
        {/each}
      </div>
    </div>
  </div>

  <div class="bar" id="t-list">
    <label class="search"><Search size={14} /><input placeholder="Buscar skill ou MCP…" bind:value={q} />{#if q}<button aria-label="Limpar" onclick={() => (q = "")}><X size={12} /></button>{/if}</label>
    <Segmented size="sm" bind:value={kind} options={[
      { value: "all", label: "Tudo", count: (inv?.items || []).length },
      { value: "skill", label: "Skills", count: (inv?.items || []).filter(x => x.type === "skill").length },
      { value: "mcp", label: "MCPs", count: (inv?.items || []).filter(x => x.type === "mcp").length },
    ]} />
    {#if only}
      <button class="chip" style="--sc:{spec.find(s => s.id === only)?.color}" onclick={() => (only = null)}><i></i>{spec.find(s => s.id === only)?.label}<X size={11} /></button>
    {/if}
    <span class="grow"></span>
    {#if repoId}<Segmented size="sm" bind:value={view} options={[{ value: "bridge", label: "Ponte" }, { value: "matrix", label: "Matriz" }]} />{/if}
  </div>

  {#if err}<div class="err">{err}</div>
  {:else if !inv}
    <div class="sk" aria-label="Lendo skills e MCPs">{#each Array(5) as _, i}<div class="skr" style="--i:{i}"><i></i><span></span><span></span></div>{/each}</div>
  {:else if view === "bridge" && repoId}
    <div class="bhead"><span></span><span class="hp"><FolderGit2 size={12} /> Projeto</span><span></span>
      <span class="ha" style="--oc:{locColor(accLoc)}"><i></i>{locLabel(accLoc)}</span><span class="hx">também em</span><span></span></div>
    {@render group("g-diff", "diff", "Versões diferentes", "o mesmo nome, conteúdo diferente", by.diff)}
    {@render group("g-acc", "acc", `Só em ${locLabel(accLoc)}`, "trazer para o projeto deixa para todos", by.acc, projLoc, "Trazer todos")}
    {@render group("g-proj", "proj", "Só no projeto", "levar para a conta deixa em todos os projetos", by.proj, accLoc, "Levar todos")}
    {@render group("g-sync", "sync", "Nos dois", "projeto e conta iguais", by.sync)}
    {#if !only}
      {#if by.other.length}
        <button class="fold" onclick={() => (showOther = !showOther)} aria-expanded={showOther}><ChevronDown size={13} class={showOther ? "" : "rot"} />
          Em outras contas <span class="c">{by.other.length}</span><span class="h">nem no projeto nem em {locLabel(accLoc)}</span></button>
        {#if showOther}{@render group("g-other", "other", "Em outras contas", "", by.other, projLoc, "Trazer todos")}{/if}
      {/if}
      {#if by.cloud.length}
        <button class="fold" onclick={() => (showCloud = !showCloud)} aria-expanded={showCloud}><ChevronDown size={13} class={showCloud ? "" : "rot"} />
          <Cloud size={13} /> Do claude.ai <span class="c">{by.cloud.length}</span><span class="h">sincronizadas pela conta — só leitura, mas dá para copiar</span></button>
        {#if showCloud}{@render group("g-cloud", "cloud", "Do claude.ai", "", by.cloud)}{/if}
      {/if}
    {/if}
    {#if !rows.length}<div class="empty">{q ? "Nada com esse nome." : "Nenhuma skill ou MCP no projeto nem nas contas."}</div>{/if}
  {:else}
    {@const cols = (inv.locations || []).filter(l => l.kind !== "local" && (kind === "all" || can(l, kind)))}
    {@const sel = only ? spec.find(s => s.id === only) : null}
    {@const list = visible.filter(it => (showCloud || !cloud(it)) && (!sel || sel.has(it)))}
    <div class="mx" style="--n:{cols.length}" role="presentation" onpointerleave={() => (hc = null)}>
      <div class="mh">
        <span class="mc0" style="grid-column:1">{list.length} itens{#if visible.some(cloud)}{" · "}<button class="lnk" onclick={() => (showCloud = !showCloud)}>{showCloud ? "esconder" : "mostrar"} as do claude.ai</button>{/if}</span>
        {#each cols as l, j (l.id)}
          {@const a = acc(l.accountId)}
          {@const n = list.filter(it => entryAt(it, l)).length}
          <button class="col" class:on={l.accountId === focusId} class:hc={hc === j} title={locLabel(l)} style="grid-column:{j + 2};--oc:{locColor(l)}"
            onpointerenter={() => (hc = j)} onclick={() => l.accountId && (picked = l.accountId)}>
            {#if l.kind === "project"}<span class="pj"><FolderGit2 size={14} /></span>{:else if a}<AccountAvatar a={{ ...a, name: locLabel({ ...l, kind: "account" }) }} size={26} />{:else}<AgentIcon provider={l.provider} size={18} />{/if}
            <span class="ell">{locLabel(l)}</span>
            <span class="cn"><i style="width:{list.length ? (n / list.length) * 100 : 0}%"></i></span>
          </button>
        {/each}
      </div>
      {#each list as it, i (it.key)}
        {@const major = bestSource(it, locs).hash}
        {@const at = cols.map(l => entryAt(it, l))}
        {@const idx = at.flatMap((e, j) => (e ? [j] : []))}
        <div class="mr" style="--i:{i}" class:open={open === it.key} data-menu-row>
          {#if idx.length > 1}
            <span class="thr" class:odd={!it.same} aria-hidden="true"
              style="grid-column:{idx[0] + 2} / {idx[idx.length - 1] + 3};--c1:{locColor(cols[idx[0]])};--c2:{locColor(cols[idx[idx.length - 1]])}"></span>
          {/if}
          <button class="mc0" style="grid-column:1" onclick={() => (open = open === it.key ? null : it.key)}>{@render glyph(it)}<b class="ell">{it.name}</b>{#if !it.same}<span class="dif" title="Versões diferentes entre os lugares">≠</span>{/if}</button>
          {#each cols as l, j (l.id)}
            {@const e = at[j]}
            <div class="cell" class:hc={hc === j} style="grid-column:{j + 2};--oc:{locColor(l)};--j:{j}" role="presentation" onpointerenter={() => (hc = j)}>
              {#if e}
                <button class="pt" class:odd={!it.same && e.hash !== major} class:local={e.loc.startsWith("l:")} class:ro={e.synced} class:new={landed?.key === it.key && landed.loc === l.id}
                  aria-label={`${it.name} em ${locLabel(locs.get(e.loc))}`}
                  title={`${locLabel(locs.get(e.loc))}${!it.same && e.hash !== major ? " · versão diferente da maioria" : ""}${e.synced ? " · do claude.ai" : ""}`}
                  onclick={() => (open = open === it.key ? null : it.key)}></button>
              {:else if can(l, it.type)}
                <button class="pl" class:busy={isBusy(it.key, l.id)} aria-label={`Levar para ${locLabel(l)}`} title={`Levar para ${locLabel(l)}`} disabled={isBusy(it.key)} onclick={() => take(rowOf(it), l)}><Plus size={11} /></button>
              {/if}
            </div>
          {/each}
          <div class="mm" style="grid-column:{cols.length + 2}"><Menu items={rowMenu(rowOf(it))} /></div>
        </div>
        {#if open === it.key}<div class="mdet">{@render detail(rowOf(it))}</div>{/if}
      {/each}
      {#if !list.length}<div class="empty">{q ? "Nada com esse nome." : only ? "Nada nesse filtro." : "Nenhuma skill ou MCP."}</div>{/if}
    </div>
  {/if}
</div>

<style>
  .tools { display: grid; gap: 16px; align-content: start; container: tools / inline-size; min-width: 0; }
  .grow { flex: 1; }
  .ell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  .muted { color: var(--muted); }

  /* ---------------- topo: constelação + espectro + o que fazer */
  .hero { display: grid; grid-template-columns: minmax(300px, 400px) minmax(0, 1fr); gap: 18px; align-items: stretch; }
  .const { display: flex; flex-direction: column; border-radius: var(--r-lg); border: 1px solid var(--line); overflow: hidden; isolation: isolate;
    background: radial-gradient(110% 85% at 50% 45%, color-mix(in srgb, var(--accent) 9%, var(--surface)), var(--surface) 72%); box-shadow: var(--shadow-1); }
  .sky { position: relative; aspect-ratio: 360 / 240; overflow: hidden; }
  .sky::after { content: ""; position: absolute; inset: 0; pointer-events: none; opacity: 0.55; z-index: -1;
    background-image: radial-gradient(color-mix(in srgb, var(--text) 13%, transparent) 1px, transparent 1.2px); background-size: 15px 15px;
    -webkit-mask: radial-gradient(65% 70% at 50% 50%, #000, transparent); mask: radial-gradient(65% 70% at 50% 50%, #000, transparent); }
  /* varredura de radar: bem leve, dá a sensação de que a tela está viva */
  .sweep { position: absolute; left: 50%; top: 50%; width: 140%; aspect-ratio: 1; translate: -50% -50%; pointer-events: none; z-index: -1; opacity: 0.5;
    background: conic-gradient(from 0deg, transparent 0 78%, color-mix(in srgb, var(--accent) 16%, transparent) 97%, transparent 100%);
    -webkit-mask: radial-gradient(closest-side, #000 55%, transparent); mask: radial-gradient(closest-side, #000 55%, transparent); animation: spin 14s linear infinite; }
  .sky svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
  .orbit { fill: none; stroke: color-mix(in srgb, var(--text) 10%, transparent); stroke-width: 1; stroke-dasharray: 1 5; stroke-linecap: round; }
  .orbit.in { stroke: color-mix(in srgb, var(--accent) 18%, transparent); stroke-dasharray: 2 6; }
  .edge { fill: none; stroke: color-mix(in srgb, var(--oc) 40%, transparent); stroke-linecap: round; transition: stroke-width var(--t-slow) var(--ease-out), stroke var(--t); }
  .edge.none { stroke: var(--line-2); stroke-dasharray: 2 4; }
  .edge.on, .edge.hv { stroke: color-mix(in srgb, var(--oc) 85%, transparent); filter: drop-shadow(0 0 4px color-mix(in srgb, var(--oc) 60%, transparent)); }
  .pkc { opacity: 0.55; transition: opacity var(--t); filter: drop-shadow(0 0 3px currentColor); }
  .pkc.on { opacity: 1; }
  .breath { animation: breath 4.5s var(--ease) infinite; transform-origin: 180px 120px; }
  .dn { fill: none; stroke-width: 4; stroke-linecap: round; transition: stroke-dasharray var(--t-slow) var(--ease-out), stroke-dashoffset var(--t-slow) var(--ease-out), opacity var(--t); }
  .dn.bg { stroke: color-mix(in srgb, var(--text) 7%, transparent); }
  .dn.dim { opacity: 0.22; }
  .core { position: absolute; left: 50%; top: 50%; translate: -50% -50%; width: 21%; aspect-ratio: 1; display: grid; justify-items: center; place-content: center; gap: 0;
    border-radius: 50%; background: var(--surface); color: var(--accent); z-index: 1;
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 35%, var(--line)), var(--shadow-2); }
  .core b { font-size: 20px; font-weight: 720; letter-spacing: -0.03em; color: var(--text); line-height: 1.1; font-variant-numeric: tabular-nums; }
  .core span { font-size: 9.5px; color: var(--muted); }
  .core.ghost { background: var(--surface-2); animation: breath 1.6s var(--ease) infinite; }
  .node { position: absolute; translate: -50% -50%; display: grid; justify-items: center; gap: 3px; padding: 4px; border: 0; background: none; cursor: pointer;
    color: var(--text-2); font: 10.5px var(--font); z-index: 2; max-width: 92px; border-radius: 10px; animation: pop-node 0.5s var(--ease-out) both; animation-delay: calc(var(--i) * 45ms);
    transition: scale var(--t) var(--ease-out), color var(--t-fast); }
  .node:hover { scale: 1.08; color: var(--text); }
  .node:focus-visible { outline: none; box-shadow: var(--ring); }
  .node.on { color: var(--text); font-weight: 650; }
  .node.on :global(.av) { box-shadow: inset 0 0 0 1.5px var(--oc), 0 0 0 3px var(--surface), 0 0 0 5px color-mix(in srgb, var(--oc) 55%, transparent), 0 0 20px color-mix(in srgb, var(--oc) 55%, transparent); }
  .node .pv { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 50%; background: var(--surface-2); border: 1px solid var(--line-2); }
  .nl { max-width: 88px; }
  .aw { position: relative; display: grid; }
  .nl { padding: 0 4px; border-radius: 5px; background: color-mix(in srgb, var(--surface) 72%, transparent); }
  .ns { position: absolute; top: -5px; right: -9px; min-width: 15px; height: 15px; padding: 0 4px; border-radius: 99px; background: var(--oc); color: #fff; font: 700 9.5px/15px var(--font);
    box-shadow: 0 0 0 2px var(--surface); font-variant-numeric: tabular-nums; }
  .cap { display: flex; align-items: center; gap: 7px; min-height: 34px; padding: 0 12px; border-top: 1px solid var(--line); font-size: 11.5px; color: var(--text-2);
    background: color-mix(in srgb, var(--surface) 82%, transparent); }
  .cap > i { width: 8px; height: 8px; border-radius: 50%; background: var(--oc); flex: none; box-shadow: 0 0 0 3px color-mix(in srgb, var(--oc) 20%, transparent); }
  .cap b { font-weight: 650; color: var(--text); max-width: 40%; }
  .cap em { font-style: normal; color: color-mix(in srgb, var(--oc) 70%, var(--text)); font-weight: 600; }
  .cap .hint { color: var(--muted); font-size: 11px; white-space: nowrap; }

  .intel { display: grid; gap: 12px; align-content: start; min-width: 0; }
  .ih { display: flex; align-items: flex-start; gap: 10px; }
  .it { flex: 1; min-width: 0; }
  .it h3 { margin: 0; font-size: 17px; font-weight: 700; letter-spacing: -0.02em; color: var(--text); }
  .it p { margin: 3px 0 0; font-size: 12.5px; color: var(--text-2); line-height: 1.45; max-width: 70ch; }

  .spec { display: grid; gap: 8px; padding: 12px; border-radius: 12px; border: 1px solid var(--line); background: var(--surface); }
  .sbar { display: flex; gap: 3px; height: 10px; }
  .sg { flex: 0 1 0; min-width: 0; height: 100%; padding: 0; border: 0; border-radius: 4px; cursor: pointer; background: var(--sc);
    box-shadow: 0 0 12px -2px color-mix(in srgb, var(--sc) 55%, transparent);
    transition: flex-grow var(--t-slow) var(--ease-out), opacity var(--t), scale var(--t) var(--ease-out); }
  .sg.zero { display: none; }
  .sg:hover, .sg:focus-visible { scale: 1 1.5; outline: none; }
  .sg.dim { opacity: 0.25; box-shadow: none; }
  .slg { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; }
  .sl { display: inline-flex; align-items: center; gap: 6px; height: 26px; padding: 0 9px 0 8px; border-radius: 8px; border: 1px solid transparent; background: none; cursor: pointer;
    color: var(--text-2); font: 12px var(--font); max-width: 100%; transition: background var(--t-fast), border-color var(--t-fast), color var(--t-fast); }
  .sl i { width: 8px; height: 8px; border-radius: 3px; background: var(--sc); flex: none; }
  .sl b { font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
  .sl:hover:not(:disabled) { background: color-mix(in srgb, var(--sc) 10%, transparent); color: var(--text); }
  .sl.on { background: color-mix(in srgb, var(--sc) 14%, transparent); border-color: color-mix(in srgb, var(--sc) 40%, transparent); color: var(--text); }
  .sl.zero { opacity: 0.45; cursor: default; }
  .sl.zero i { background: var(--line-3); }
  .slg .lnk { font-size: 12px; margin-left: 4px; }

  .tips { display: grid; gap: 6px; }
  .tip { --tc: var(--accent); display: flex; align-items: center; gap: 10px; padding: 9px 10px 9px 10px; border-radius: 11px; border: 1px solid color-mix(in srgb, var(--tc) 20%, var(--line));
    background: color-mix(in srgb, var(--tc) 5%, var(--surface)); animation: rise 0.35s var(--ease-out) both; animation-delay: calc(var(--i) * 50ms);
    transition: border-color var(--t-fast), background var(--t-fast); }
  .tip:hover { border-color: color-mix(in srgb, var(--tc) 38%, var(--line)); background: color-mix(in srgb, var(--tc) 8%, var(--surface)); }
  .tip.warn { --tc: var(--warn); } .tip.bad { --tc: var(--bad); } .tip.good { --tc: var(--good); }
  .ti { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 9px; flex: none; color: var(--tc); background: color-mix(in srgb, var(--tc) 14%, transparent); }
  .tip.bad .ti { animation: alarm 2s var(--ease) infinite; }
  .tt { display: grid; gap: 1px; flex: 1; min-width: 0; }
  .tt b { font-size: 12.5px; font-weight: 650; }
  .tt span { font-size: 11.5px; color: var(--text-2); line-height: 1.35; }

  /* ---------------- barra de filtro */
  .bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; position: sticky; top: 0; z-index: 3; padding: 6px 0; background: var(--bg); scroll-margin-top: 0; }
  .search { display: flex; align-items: center; gap: 6px; height: 30px; padding: 0 8px; min-width: 200px; flex: 0 1 280px; border-radius: 9px; border: 1px solid var(--line-2);
    background: var(--surface); color: var(--muted); transition: border-color var(--t-fast), box-shadow var(--t-fast); }
  .search:focus-within { border-color: var(--accent); box-shadow: var(--ring); }
  .search input { flex: 1; min-width: 0; border: 0; background: none; outline: none; color: var(--text); font: 13px var(--font); }
  .search input::placeholder { color: var(--muted); }
  .search button { display: grid; place-items: center; border: 0; background: none; color: var(--muted); cursor: pointer; padding: 2px; }
  .chip { display: inline-flex; align-items: center; gap: 6px; height: 26px; padding: 0 8px; border-radius: 99px; cursor: pointer; font: 600 11.5px var(--font); color: var(--text);
    border: 1px solid color-mix(in srgb, var(--sc) 40%, transparent); background: color-mix(in srgb, var(--sc) 12%, transparent); animation: pop-in 0.25s var(--ease-out) both; }
  .chip i { width: 7px; height: 7px; border-radius: 50%; background: var(--sc); }
  .chip:hover { background: color-mix(in srgb, var(--sc) 20%, transparent); }

  /* ---------------- ponte */
  .bhead, .br { display: grid; grid-template-columns: minmax(180px, 1.5fr) 118px 96px 118px minmax(60px, 0.5fr) auto; align-items: center; gap: 10px; }
  .bhead { padding: 0 10px; font: 600 10.5px/1 var(--font); color: var(--muted); margin-bottom: -8px; }
  .bhead .hp, .bhead .ha { display: inline-flex; align-items: center; gap: 5px; justify-content: center; font-size: 11.5px; color: var(--text-2); }
  .bhead .hp { color: var(--accent); }
  .bhead .ha i { width: 8px; height: 8px; border-radius: 50%; background: var(--oc); }
  .bhead .hx { font-weight: 500; }
  .grp { display: grid; gap: 6px; scroll-margin-top: 50px; animation: fade 0.25s var(--ease-out) both; }
  .grp header { display: flex; align-items: center; gap: 8px; padding: 8px 4px 0; }
  .sd { width: 8px; height: 8px; border-radius: 3px; background: var(--sc); flex: none; box-shadow: 0 0 8px color-mix(in srgb, var(--sc) 60%, transparent); }
  .grp h4 { margin: 0; font-size: 13px; font-weight: 650; }
  .c { font: 650 10.5px/1 var(--font); padding: 2px 6px; border-radius: 99px; background: var(--surface-3); color: var(--text-2); font-variant-numeric: tabular-nums; }
  .h { font-size: 11.5px; color: var(--muted); }
  .rows { display: grid; border: 1px solid var(--line); border-radius: var(--r); background: var(--surface); overflow: hidden; box-shadow: var(--shadow-1); }
  .br { position: relative; padding: 8px 8px 8px 10px; border-top: 1px solid var(--line); animation: rise 0.3s var(--ease-out) both; animation-delay: calc(min(var(--i), 12) * 20ms);
    transition: background var(--t-fast); }
  .br:first-child { border-top: 0; }
  .br:hover, .br.open { background: color-mix(in srgb, var(--surface-2) 75%, transparent); }
  .br.landed { animation: land 1.8s var(--ease-out) both; }
  .bn { display: flex; align-items: center; gap: 10px; min-width: 0; padding: 0; border: 0; background: none; color: inherit; text-align: left; cursor: pointer; font: inherit; }
  .gl { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 9px; flex: none; transition: scale var(--t) var(--ease-out); }
  .gl.skill { color: var(--cat6); background: color-mix(in srgb, var(--cat6) 14%, transparent); }
  .gl.mcp { color: var(--cat3); background: color-mix(in srgb, var(--cat3) 14%, transparent); }
  .br:hover .gl, .mr:hover .gl { scale: 1.08; }
  .nm { display: grid; gap: 1px; min-width: 0; }
  .nm b { font-size: 13px; font-weight: 620; }
  .ds { font-size: 11.5px; color: var(--muted); }
  .side { display: flex; justify-content: center; }
  .has { --oc: var(--accent); display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 8px; border-radius: 99px; font: 600 11px var(--font); white-space: nowrap;
    color: color-mix(in srgb, var(--oc) 70%, var(--text)); background: color-mix(in srgb, var(--oc) 13%, transparent); border: 1px solid color-mix(in srgb, var(--oc) 26%, transparent); }
  .has.ha { --oc: var(--ac); }
  .br.landed .has { animation: pop 0.5s var(--ease-out) 0.1s; }
  .add { display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 9px; border-radius: 99px; border: 1px dashed var(--line-3); background: none; color: var(--muted);
    font: 550 11px var(--font); cursor: pointer; transition: border-color var(--t-fast), color var(--t-fast), background var(--t-fast); }
  .add:hover:not(:disabled), .add:focus-visible { border-style: solid; border-color: var(--accent); color: var(--accent); background: var(--accent-soft); outline: none; }
  .add.to-a:hover:not(:disabled), .add.to-a:focus-visible { border-color: var(--ac); color: color-mix(in srgb, var(--ac) 75%, var(--text)); background: color-mix(in srgb, var(--ac) 12%, transparent); }
  .add:disabled { opacity: 0.6; cursor: progress; }
  .na { color: var(--faint); font-size: 12px; }

  /* o conduíte entre projeto e conta: a cor diz o estado, o pacote corre na direção da cópia */
  .cd { position: relative; height: 22px; display: grid; place-items: center; }
  .cd .tr { position: absolute; left: 0; right: 0; top: 50%; height: 2px; margin-top: -1px; border-radius: 2px; background: var(--line-2); }
  .br.sync .tr { background: linear-gradient(90deg, var(--accent), var(--good) 50%, var(--ac)); opacity: 0.5; }
  .br.diff .tr { background: repeating-linear-gradient(90deg, var(--warn) 0 6px, transparent 6px 11px); background-size: 22px 2px; animation: slide 1.4s linear infinite; opacity: 0.75; }
  .br.acc .tr { background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--ac) 65%, transparent)); }
  .br.proj .tr, .br.other .tr, .br.cloud .tr { background: linear-gradient(90deg, color-mix(in srgb, var(--accent) 65%, transparent), transparent); }
  .br.other .tr, .br.cloud .tr { background: var(--line); }
  .cd .pk { position: absolute; left: 0; right: 0; top: 50%; height: 0; opacity: 0; pointer-events: none; }
  .cd .pk::before { content: ""; position: absolute; left: -3px; top: -3px; width: 6px; height: 6px; border-radius: 50%; background: var(--pc, var(--good));
    box-shadow: 0 0 8px 2px color-mix(in srgb, var(--pc, var(--good)) 55%, transparent); }
  .br.sync .pk { --pc: var(--good); animation: drift 3.8s var(--ease) infinite alternate; animation-delay: calc(var(--i) * -0.9s); }
  .br.diff .pk { --pc: var(--warn); opacity: 1; animation: clash 1.8s var(--ease) infinite; }
  .br.to-p .pk, .br:has(.add.to-p:hover:not(:disabled)) .pk { --pc: var(--ac); animation: go-l 0.95s var(--ease-out) infinite; }
  .br.to-a .pk, .br:has(.add.to-a:hover:not(:disabled)) .pk { --pc: var(--accent); animation: go-r 0.95s var(--ease-out) infinite; }
  .br.to-p .tr, .br.to-a .tr { opacity: 1; }
  .lb { position: relative; padding: 0 6px; border-radius: 99px; font: 600 10px/16px var(--font); color: var(--warn); background: var(--surface);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--warn) 30%, transparent); }
  .br:hover .lb, .br.open .lb { background: var(--surface-2); }
  .also { display: flex; align-items: center; gap: 0; min-width: 0; }
  .also > * { margin-left: -4px; } .also > :first-child { margin-left: 0; }
  .mini { display: inline-flex; border-radius: 50%; box-shadow: 0 0 0 2px var(--surface); transition: translate var(--t-fast) var(--ease-out); }
  .also:hover .mini { translate: 2px 0; }
  .dot.proj { display: grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; background: var(--accent-soft); color: var(--accent); box-shadow: 0 0 0 2px var(--surface); }
  .more { font-size: 10.5px; color: var(--muted); margin-left: 4px !important; }
  .act { display: flex; align-items: center; gap: 4px; justify-content: flex-end; }

  .det { display: grid; gap: 10px; padding: 10px 14px 14px 48px; border-top: 1px dashed var(--line); background: color-mix(in srgb, var(--surface-2) 50%, transparent); animation: fade 0.2s both; }
  .dd { margin: 0; font-size: 12.5px; color: var(--text-2); line-height: 1.5; max-width: 90ch; }
  .where { display: grid; gap: 4px; }
  .we { display: grid; grid-template-columns: minmax(130px, 200px) minmax(0, 1fr) auto auto; align-items: center; gap: 10px; padding: 5px 8px; border-radius: 8px; background: var(--surface);
    border: 1px solid var(--line); animation: rise 0.25s var(--ease-out) both; animation-delay: calc(var(--j) * 35ms); }
  .own { display: inline-flex; align-items: center; gap: 5px; min-width: 0; font: 600 11.5px var(--font); color: color-mix(in srgb, var(--oc) 65%, var(--text)); }
  .own i { width: 8px; height: 8px; border-radius: 50%; background: var(--oc); flex: none; }
  .own.local i { background: none; box-shadow: inset 0 0 0 2px var(--oc); }
  .meta { display: flex; align-items: center; gap: 8px; min-width: 0; font-size: 11.5px; color: var(--text-2); }
  .meta code, .mono { font: 11px var(--mono); color: var(--text-2); }
  .v { font-weight: 650; color: var(--text); }
  .tp { text-transform: uppercase; font: 650 9.5px/1 var(--font); letter-spacing: 0.06em; padding: 3px 5px; border-radius: 5px; background: var(--surface-3); }
  .off { color: var(--muted); font-style: italic; }
  .hsh { font-size: 10.5px; color: var(--muted); white-space: nowrap; }
  .hsh.solo { color: var(--warn); }
  .wa { display: flex; gap: 2px; }
  .keys { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 4px; padding-left: 13px; }
  .key { display: inline-flex; align-items: center; gap: 3px; height: 18px; padding: 0 6px; border-radius: 5px; font: 10.5px var(--mono); background: var(--surface-2); color: var(--text-2); }
  .key.sec { background: var(--warn-soft); color: color-mix(in srgb, var(--warn) 80%, var(--text)); }
  .pv { border: 1px solid var(--line); border-radius: 10px; overflow: hidden; background: var(--surface); animation: rise 0.25s var(--ease-out) both; }
  .pvh { display: flex; align-items: center; gap: 6px; padding: 4px 4px 4px 10px; font-size: 11.5px; color: var(--text-2); border-bottom: 1px solid var(--line); }
  .pv pre { margin: 0; padding: 10px 12px; max-height: 280px; overflow: auto; font: 11.5px/1.55 var(--mono); white-space: pre-wrap; color: var(--text-2); }
  .dact { display: flex; gap: 6px; }

  .fold { display: flex; align-items: center; gap: 7px; padding: 6px 4px; border: 0; background: none; color: var(--text); font: 600 13px var(--font); cursor: pointer; text-align: left; }
  .fold :global(.rot) { transform: rotate(-90deg); }
  .fold :global(svg) { transition: transform var(--t-fast); }
  .fold .h { font-weight: 400; }

  /* ---------------- matriz: cada item é uma linha de metrô ligando os lugares onde está */
  .mx { display: grid; border: 1px solid var(--line); border-radius: var(--r); background: var(--surface); overflow: auto; max-width: 100%; box-shadow: var(--shadow-1); outline: none; }
  .mh, .mr { display: grid; grid-template-columns: minmax(200px, 1fr) repeat(var(--n), 68px) 36px; align-items: center; min-width: max-content; }
  .mh > *, .mr > * { grid-row: 1; }
  .mh { position: sticky; top: 0; z-index: 2; background: var(--surface); border-bottom: 1px solid var(--line); }
  .mh .mc0 { padding: 0 12px 10px; font-size: 11.5px; color: var(--muted); align-self: end; }
  .lnk { border: 0; background: none; padding: 0; color: var(--accent); font: inherit; cursor: pointer; }
  .lnk:hover { text-decoration: underline; }
  .col { display: grid; justify-items: center; gap: 4px; height: 100%; padding: 10px 2px 8px; border: 0; background: none; cursor: pointer; color: var(--text-2); font: 10.5px var(--font);
    transition: background var(--t-fast), color var(--t-fast); }
  .col span.ell { max-width: 62px; }
  .col :global(.av) { transition: scale var(--t) var(--ease-out); }
  .col:hover :global(.av), .col.hc :global(.av) { scale: 1.08; }
  .col.on { color: var(--text); font-weight: 650; }
  .col.on :global(.av) { box-shadow: inset 0 0 0 1.5px var(--oc), 0 0 0 2px var(--surface), 0 0 0 4px color-mix(in srgb, var(--oc) 50%, transparent), 0 0 14px color-mix(in srgb, var(--oc) 45%, transparent); }
  .cn { width: 34px; height: 3px; border-radius: 2px; background: var(--line-2); overflow: hidden; }
  .cn i { display: block; height: 100%; border-radius: inherit; background: var(--oc); transition: width var(--t-slow) var(--ease-out); }
  .pj { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 50%; background: var(--accent-soft); color: var(--accent); }
  .col.hc, .cell.hc { background: color-mix(in srgb, var(--oc) 7%, transparent); }
  .mr { position: relative; border-top: 1px solid var(--line); min-height: 40px; animation: fade 0.25s both; animation-delay: calc(min(var(--i), 20) * 14ms); }
  .mh + .mr { border-top: 0; }
  .mr:hover, .mr.open { background: color-mix(in srgb, var(--surface-2) 70%, transparent); }
  .mr .mc0 { display: flex; align-items: center; gap: 9px; min-width: 0; height: 100%; padding: 4px 12px; border: 0; background: none; color: inherit; font: 13px var(--font); cursor: pointer; text-align: left; }
  .mr .mc0 b { font-weight: 600; }
  .mr .gl { width: 24px; height: 24px; border-radius: 7px; }
  .dif { font: 700 12px var(--font); color: var(--warn); }
  .thr { align-self: center; height: 2px; margin: 0 34px; border-radius: 2px; pointer-events: none; opacity: 0.32;
    background: linear-gradient(90deg, var(--c1), var(--c2)); transform-origin: left; animation: draw 0.5s var(--ease-out) both; animation-delay: calc(min(var(--i), 20) * 14ms + 80ms);
    transition: opacity var(--t); }
  .thr.odd { background: repeating-linear-gradient(90deg, var(--warn) 0 5px, transparent 5px 9px); opacity: 0.55; }
  .mr:hover .thr, .mr.open .thr { opacity: 0.75; }
  .cell { display: grid; place-items: center; height: 100%; position: relative; z-index: 1; transition: background var(--t-fast); }
  .pt { position: relative; width: 13px; height: 13px; border-radius: 50%; border: 0; padding: 0; cursor: pointer; background: var(--oc);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--oc) 18%, transparent), 0 0 10px color-mix(in srgb, var(--oc) 40%, transparent);
    animation: dot-in 0.4s var(--ease-out) both; animation-delay: calc(min(var(--i), 20) * 14ms + var(--j) * 22ms); transition: scale var(--t-fast) var(--ease-out); }
  .pt:hover, .pt:focus-visible { scale: 1.3; outline: none; }
  .pt.local { background: var(--surface); box-shadow: inset 0 0 0 3px var(--oc), 0 0 8px color-mix(in srgb, var(--oc) 35%, transparent); }
  .pt.ro { opacity: 0.55; }
  .pt.odd { box-shadow: 0 0 0 2px var(--surface), 0 0 0 4px var(--warn), 0 0 12px color-mix(in srgb, var(--warn) 50%, transparent); }
  .pt.new::after { content: ""; position: absolute; inset: -2px; border-radius: 50%; border: 2px solid var(--oc); animation: ripple 1.1s var(--ease-out) 2; }
  /* lugar vazio: um ponto apagado que vira "+" quando a linha está em foco */
  .pl { position: relative; display: grid; place-items: center; width: 22px; height: 22px; border-radius: 7px; border: 1px dashed transparent; background: none; color: transparent; cursor: pointer;
    transition: color var(--t-fast), border-color var(--t-fast), background var(--t-fast); }
  .pl::before { content: ""; position: absolute; width: 4px; height: 4px; border-radius: 50%; background: var(--line-3); transition: opacity var(--t-fast); }
  .mr:hover .pl, .pl:focus-visible { color: var(--muted); border-color: var(--line-3); outline: none; }
  .mr:hover .pl::before, .pl:focus-visible::before { opacity: 0; }
  .pl:hover:not(:disabled) { color: var(--oc); border-color: var(--oc); border-style: solid; background: color-mix(in srgb, var(--oc) 10%, transparent); }
  .pl:disabled { cursor: progress; }
  .pl.busy { color: var(--oc); border-color: var(--oc); animation: breath 0.9s var(--ease) infinite; }
  .pl.busy::before { opacity: 0; }
  .mm { display: grid; place-items: center; z-index: 1; }
  .mdet { border-top: 1px solid var(--line); }
  .mdet .det { padding-left: 14px; border-top: 0; }

  .empty { padding: 28px; text-align: center; color: var(--muted); font-size: 13px; }
  .err { color: var(--bad); padding: 10px; }
  .sk { display: grid; border: 1px solid var(--line); border-radius: var(--r); background: var(--surface); overflow: hidden; }
  .skr { display: grid; grid-template-columns: 28px minmax(0, 1fr) 120px; align-items: center; gap: 12px; padding: 12px; border-top: 1px solid var(--line); }
  .skr:first-child { border-top: 0; }
  .skr > * { height: 12px; border-radius: 6px; background: linear-gradient(90deg, var(--surface-2), var(--surface-3), var(--surface-2)); background-size: 200% 100%;
    animation: shimmer 1.4s linear infinite; animation-delay: calc(var(--i) * 0.1s); }
  .skr i { height: 28px; border-radius: 9px; }
  .skr span:nth-child(2) { width: calc(70% - var(--i) * 8%); }

  @container tools (max-width: 760px) {
    .hero { grid-template-columns: minmax(0, 1fr); }
    .const { max-width: 460px; width: 100%; justify-self: center; }
    .bhead { display: none; }
    .br { grid-template-columns: minmax(0, 1fr) auto; row-gap: 6px; }
    .br .side, .br .cd, .br .also { grid-row: 2; }
    .br .bn { grid-column: 1; } .br .act { grid-column: 2; grid-row: 1; }
    .br .side.p { grid-column: 1; justify-content: flex-start; padding-left: 38px; }
    .br .cd, .br .also { display: none; }
    .br .side.a { grid-column: 2; }
    .det { padding-left: 14px; }
    .we { grid-template-columns: minmax(0, 1fr) auto; }
    .we .meta { grid-column: 1 / -1; grid-row: 2; }
  }
  @keyframes slide { to { background-position: 22px 0; } }
  @keyframes breath { 0%, 100% { scale: 0.93; opacity: 0.8; } 50% { scale: 1.05; opacity: 1; } }
  @keyframes pop-node { from { opacity: 0; scale: 0.6; } }
  @keyframes pop-in { from { opacity: 0; scale: 0.85; } }
  @keyframes dot-in { from { opacity: 0; scale: 0; } }
  @keyframes draw { from { transform: scaleX(0); } }
  @keyframes ripple { from { opacity: 0.9; scale: 1; } to { opacity: 0; scale: 2.6; } }
  @keyframes alarm { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--bad) 40%, transparent); } 50% { box-shadow: 0 0 0 5px transparent; } }
  @keyframes drift { 0% { transform: translateX(0); opacity: 0; } 15%, 85% { opacity: 0.9; } 100% { transform: translateX(100%); opacity: 0; } }
  @keyframes clash { 0%, 100% { transform: translateX(32%); } 50% { transform: translateX(68%); } }
  @keyframes go-l { 0% { transform: translateX(100%); opacity: 0; } 20% { opacity: 1; } 100% { transform: translateX(0); opacity: 0; } }
  @keyframes go-r { 0% { transform: translateX(0); opacity: 0; } 20% { opacity: 1; } 100% { transform: translateX(100%); opacity: 0; } }
  @keyframes land {
    0% { background: color-mix(in srgb, var(--good) 20%, transparent); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--good) 55%, transparent); }
    100% { background: transparent; box-shadow: inset 0 0 0 1px transparent; }
  }
  @media (prefers-reduced-motion: reduce) {
    .sweep, .pkc, .cd .pk { display: none; }
    .breath, .core.ghost, .node, .br, .grp, .tip, .tip.bad .ti, .we, .pv, .mr, .thr, .pt, .pt.new::after, .pl.busy, .chip, .skr > *, .br.diff .tr { animation: none; }
    .br.landed { animation: none; background: color-mix(in srgb, var(--good) 10%, transparent); }
  }
</style>
