<script lang="ts">
  // Issue do GitHub ou work item do Azure aberto no app: descrição renderizada (Markdown ou o HTML do Azure, sempre
  // sanitizado), etiquetas, responsável, itens ligados e a discussão — com comentar e "Implementar" direto, num projeto
  // local escolhido aqui (o work item do Azure não diz o repositório: sugere os clones do mesmo projeto do Azure).
  import { Bot, ExternalLink, KanbanSquare, Link2, MessageSquare, Paperclip, Send, Sparkles } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { get, post } from "../../lib/api";
  import { ago } from "../../lib/format";
  import { repos } from "../../lib/repos.svelte";
  import { go } from "../../lib/router.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { work } from "../../lib/work.svelte";
  import Drawer from "../Drawer.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import { htmlText, renderMarkdown, safeHtml } from "./md/render";

  type Comment = { author: string; created: string; markdown?: string; html?: string };
  type Detail = { provider: "github" | "azure"; number: number; title: string; state: string; type: string; project: string; author: string;
    assignee: string; created: string; updated: string; labels: string[]; markdown?: string; sections?: { label: string; html: string }[];
    comments: Comment[]; relations: { kind: string; name: string; id?: number; url?: string }[]; url: string;
    iteration?: string; area?: string; priority?: number; effort?: number; milestone?: string };

  let { item, onclose, onboard }: { item: any; onclose: () => void; onboard?: (i: any) => void } = $props();
  let d = $state<Detail | null>(null);
  let err = $state("");
  let reply = $state("");
  let sending = $state(false);

  async function load() {
    try {
      d = await get<Detail>("issue", { provider: item.provider, account: item.account || undefined, org: item.org, repo: item.repo, number: item.number });
      err = "";
    } catch (e: any) { err = e.message || String(e); }
  }
  $effect(() => { void item.key; untrack(load); });
  $effect(() => { if (!repos.loaded) untrack(() => repos.load(false)); });

  // ------------------------------------------------------------ onde implementar
  const azOrg = $derived(item.provider === "azure" ? (item.url.match(/dev\.azure\.com\/([^/]+)/)?.[1] || item.url.match(/\/\/([^.]+)\.visualstudio/)?.[1] || "") : "");
  const candidates = $derived.by(() => {
    const n = (s?: string | null) => (s || "").toLowerCase();
    const pool = repos.local.filter(r => r.exists);
    const fit = item.provider === "github"
      ? pool.filter(r => r.provider === "github" && n(r.slug) === n(item.repo))
      : pool.filter(r => r.provider === "azure" && n(r.slug).startsWith(`${n(azOrg)}/${n(item.repo)}/`));
    const openIds = new Set(work.projects.map(p => p.id));
    const rank = (id: string) => (id === work.active ? 0 : openIds.has(id) ? 1 : 2);
    return [...fit].sort((a, b) => rank(a.id) - rank(b.id) || a.name.localeCompare(b.name));
  });
  let target = $state("");
  $effect(() => {
    const c = candidates;
    if (!c.some(r => r.id === target)) untrack(() => (target = c[0]?.id || (item.provider === "azure" ? work.active || "" : "")));
  });
  const others = $derived(repos.local.filter(r => r.exists && !candidates.some(c => c.id === r.id)).sort((a, b) => a.name.localeCompare(b.name)));

  /** O pedido para o agente: o conteúdo inteiro (descrição e discussão), não só o link. */
  function promptOf() {
    const kind = item.provider === "github" ? "a issue" : `o work item (${d?.type || item.type || "item"})`;
    const head = `Implemente ${kind} #${item.number}: ${item.title}\n${item.url}`;
    if (!d) return `${head}\n\nLeia a descrição completa no link antes de começar.`;
    const body = d.provider === "github" ? (d.markdown || "").trim() : (d.sections || []).map(s => `## ${s.label}\n${htmlText(s.html)}`).join("\n\n");
    const talk = d.comments.slice(-15).map(c => `- ${c.author} (${c.created?.slice(0, 10)}): ${(c.markdown ?? htmlText(c.html || "")).trim().slice(0, 1500)}`).join("\n");
    return [head, d.labels.length ? `Etiquetas: ${d.labels.join(", ")}` : "", body ? `\n${body.slice(0, 12000)}` : "", talk ? `\n## Discussão\n${talk}` : ""].filter(Boolean).join("\n");
  }
  async function into(kind: "ask" | "task", flow?: string) {
    if (!target) return ui.toast("Escolha o projeto onde implementar", "info");
    try {
      const projectId = await work.open(target);
      if (!projectId) return;
      const text = promptOf();
      if (kind === "ask") work.pendingAsk = { projectId, preset: { title: item.title, text, workItem: item, flow } };
      else work.pendingTask = { projectId, preset: { title: item.title, prompt: text, workItem: item,
        kind: /bug|defeito|defect/i.test(item.type || "") || item.labels?.some((l: any) => /bug/i.test(l.name)) ? "fix" : "feature" } };
      go("/work/" + projectId);
      onclose();
    } catch (e) { ui.error(e); }
  }
  async function send() {
    const text = reply.trim();
    if (!text) return;
    sending = true;
    try {
      await post("issue/comment", { provider: item.provider, account: item.account, org: item.org, repo: item.repo, number: item.number, text });
      reply = "";
      ui.toast("Comentário enviado", "ok");
      await load();
    } catch (e) { ui.error(e); }
    sending = false;
  }
</script>

<Drawer title={`${item.provider === "github" ? "Issue" : item.type || "Work item"} #${item.number}`} subtitle={item.repo} {onclose} width={760}>
  <div class="id">
    <h3 class="ttl">{d?.title || item.title}</h3>
    <div class="meta small">
      <ProviderIcon provider={item.provider} size={13} />
      <span class="pill info">{d?.state || item.state}</span>
      {#if d?.assignee}<span>com <b>{d.assignee}</b></span>{/if}
      {#if d?.author}<span class="muted">aberta por {d.author}{d.created ? ` há ${ago(d.created)}` : ""}</span>{/if}
      {#if d?.updated}<span class="muted">· atualizada há {ago(d.updated)}</span>{/if}
      <a class="lnk" href={item.url} target="_blank" rel="noopener"><ExternalLink size={12} /> Abrir no {item.provider === "github" ? "GitHub" : "Azure"}</a>
    </div>
    {#if d && (d.labels.length || d.iteration || d.priority || d.milestone)}
      <div class="meta small">
        {#each d.labels as l (l)}<span class="chip">{l}</span>{/each}
        {#if d.milestone}<span class="muted">marco: {d.milestone}</span>{/if}
        {#if d.iteration && d.iteration !== d.project}<span class="muted">sprint: {d.iteration.split("\\").pop()}</span>{/if}
        {#if d.priority}<span class="muted">prioridade {d.priority}</span>{/if}
        {#if d.effort}<span class="muted">esforço {d.effort}</span>{/if}
      </div>
    {/if}

    <div class="impl card">
      <span class="small muted">Implementar em</span>
      <select class="input sm" bind:value={target}>
        {#if !candidates.length && !target}<option value="">Escolha o projeto…</option>{/if}
        {#if candidates.length}<optgroup label="Deste {item.provider === 'github' ? 'repositório' : 'projeto do Azure'}">{#each candidates as r (r.id)}<option value={r.id}>{r.name}{r.slug ? ` — ${r.slug}` : ""}</option>{/each}</optgroup>{/if}
        <optgroup label="Outros projetos">{#each others as r (r.id)}<option value={r.id}>{r.name}</option>{/each}</optgroup>
      </select>
      <button class="btn sm primary" disabled={!target} title="Manda a issue inteira (descrição e discussão) para o agente implementar" onclick={() => into("ask", "implement")}><Sparkles size={13} /> Implementar com IA</button>
      <button class="btn sm" disabled={!target} onclick={() => into("ask", "plan-implement")}>Planejar e implementar</button>
      <button class="btn sm ghost" disabled={!target} title="Branch + worktree + agente, com o formulário completo" onclick={() => into("task")}><Bot size={13} /> Nova tarefa</button>
      {#if onboard}<button class="btn sm ghost" onclick={() => onboard!(item)}><KanbanSquare size={13} /> Quadro</button>{/if}
    </div>

    {#if err}<p class="small err">Não consegui ler: {err}</p>
    {:else if !d}<div class="shimw"><span class="shim"></span><span class="shim"></span><span class="shim"></span></div>
    {:else}
      {#if d.provider === "github"}
        {#if d.markdown?.trim()}<div class="doc">{@html renderMarkdown(d.markdown)}</div>{:else}<p class="muted small">Sem descrição.</p>{/if}
      {:else}
        {#each d.sections || [] as s (s.label)}<h4 class="sec">{s.label}</h4><div class="doc">{@html safeHtml(s.html)}</div>
        {:else}<p class="muted small">Sem descrição.</p>{/each}
      {/if}

      {#if d.relations.length}
        <h4 class="sec">Ligados</h4>
        <div class="rels small">
          {#each d.relations as r, i (i)}
            {#if r.kind === "item"}<span class="chip"><Link2 size={11} /> {r.name} #{r.id}</span>
            {:else}<a class="chip" href={r.url} target="_blank" rel="noopener">{#if r.kind === "file"}<Paperclip size={11} />{:else}<Link2 size={11} />{/if} {r.name}</a>{/if}
          {/each}
        </div>
      {/if}

      <h4 class="sec"><MessageSquare size={13} /> Discussão {d.comments.length ? `(${d.comments.length})` : ""}</h4>
      {#each d.comments as c, i (i)}
        <div class="cm">
          <div class="small"><b>{c.author}</b> <span class="muted">há {ago(c.created)}</span></div>
          <div class="doc">{@html c.markdown !== undefined ? renderMarkdown(c.markdown) : safeHtml(c.html || "")}</div>
        </div>
      {:else}<p class="muted small">Nenhum comentário.</p>{/each}
      <div class="reply">
        <textarea class="input" rows="3" bind:value={reply} placeholder="Comentar…" onkeydown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); } }}></textarea>
        <button class="btn sm" disabled={!reply.trim() || sending} onclick={send}><Send size={13} /> Comentar</button>
      </div>
    {/if}
  </div>
</Drawer>

<style>
  .id { display: flex; flex-direction: column; gap: 10px; }
  .ttl { margin: 0; font-size: 17px; line-height: 1.35; }
  .meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .lnk { display: inline-flex; align-items: center; gap: 4px; color: var(--accent); text-decoration: none; margin-left: auto; }
  .chip { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 99px; border: 1px solid var(--line-2); color: var(--text-2);
    font-size: 11.5px; text-decoration: none; }
  a.chip:hover { color: var(--text); border-color: var(--line-3); }
  .impl { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 10px; }
  .impl select { min-width: 200px; flex: 1; }
  .sec { display: flex; align-items: center; gap: 6px; margin: 10px 0 0; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
  .rels { display: flex; flex-wrap: wrap; gap: 6px; }
  .doc { font-size: 13.5px; line-height: 1.6; color: var(--text); overflow-wrap: anywhere; }
  .doc :global(img) { max-width: 100%; }
  .doc :global(pre) { overflow: auto; padding: 10px; border-radius: 8px; background: var(--bg-2); }
  .doc :global(code) { font-family: var(--mono); font-size: 12.5px; }
  .doc :global(a) { color: var(--accent); }
  .doc :global(table) { border-collapse: collapse; }
  .doc :global(td), .doc :global(th) { border: 1px solid var(--line); padding: 4px 8px; }
  .doc :global(> :first-child) { margin-top: 0; }
  .cm { padding: 10px 12px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface-2); display: grid; gap: 4px; }
  .reply { display: grid; gap: 6px; justify-items: end; }
  .reply textarea { width: 100%; resize: vertical; }
  .err { color: var(--bad); }
  .shimw { display: grid; gap: 10px; }
  .shimw .shim { height: 12px; }
  .shimw .shim:nth-child(2) { width: 70%; }
</style>
