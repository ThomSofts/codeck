<script lang="ts">
  // Markdown renderizado (seguro: DOMPurify). Checkboxes de lista de tarefas são clicáveis — a N-ésima checkbox
  // corresponde à N-ésima linha de tarefa do código (scanTasks). Roteiros de teste: marque e ele salva.
  import { kbd, matches } from "../../lib/keys";
  import { renderMarkdown, scanTasks, slug } from "./md/render";

  let { text, path, ontoggle, onopen, onkey }:
    { text: string; path: string; ontoggle: (index: number, done: boolean) => void; onopen: (rel: string) => void; onkey?: (e: KeyboardEvent) => void } = $props();

  let el: HTMLDivElement | undefined = $state();
  let scroller: HTMLDivElement | undefined = $state();
  const tasks = $derived(scanTasks(text));
  const done = $derived(tasks.filter(t => t.done).length);
  const html = $derived(renderMarkdown(text));

  // troca o HTML preservando a rolagem (marcar uma tarefa não pode pular a tela)
  $effect(() => {
    const h = html;
    if (!el) return;
    const top = scroller?.scrollTop || 0;
    el.innerHTML = h;
    decorate(el);
    if (scroller) scroller.scrollTop = top;
  });

  const dir = $derived(path.includes("/") ? path.slice(0, path.lastIndexOf("/") + 1) : "");
  function resolve(href: string) {
    const parts = (dir + href).split("/"), out: string[] = [];
    for (const p of parts) { if (p === "..") out.pop(); else if (p && p !== ".") out.push(p); }
    return out.join("/");
  }
  const external = (h: string) => /^(https?:|mailto:)/i.test(h);

  function decorate(root: HTMLElement) {
    const seen = new Map<string, number>();
    for (const h of root.querySelectorAll<HTMLElement>("h1,h2,h3,h4,h5,h6")) {
      let id = slug(h.textContent || "");
      const n = seen.get(id) || 0;
      seen.set(id, n + 1);
      if (n) id += "-" + n;
      h.id = "md-" + id;
    }
    root.querySelectorAll<HTMLInputElement>("input[type=checkbox]").forEach((c, i) => {
      c.disabled = false;
      c.dataset.i = String(i);
      c.closest("li")?.classList.add("task", ...(c.checked ? ["done"] : []));
      c.closest("ul,ol")?.classList.add("tasks");
    });
    // imagem relativa precisa da chave da API (o <img> não manda cabeçalho): fica um marcador com o texto alternativo
    for (const img of root.querySelectorAll<HTMLImageElement>("img")) {
      const src = img.getAttribute("src") || "";
      if (external(src) || /^data:image\//i.test(src)) { img.loading = "lazy"; img.referrerPolicy = "no-referrer"; continue; }
      const ph = document.createElement("span");
      ph.className = "imgph";
      ph.textContent = `🖼 ${img.getAttribute("alt") || "imagem"} · ${resolve(src.split(/[?#]/)[0])}`;
      img.replaceWith(ph);
    }
  }

  function click(e: MouseEvent) {
    const t = e.target as HTMLElement;
    if (t instanceof HTMLInputElement && t.type === "checkbox") {
      const i = Number(t.dataset.i);
      t.closest("li")?.classList.toggle("done", t.checked);
      ontoggle(i, t.checked);
      return;
    }
    const a = t.closest("a");
    if (!a) return;
    e.preventDefault();
    const href = a.getAttribute("href") || "";
    if (!href) return;
    if (href.startsWith("#")) {
      const target = el?.querySelector("#md-" + CSS.escape(slug(decodeURIComponent(href.slice(1)))));
      target?.scrollIntoView({ behavior: "smooth", block: "start" });
    } else if (external(href)) window.open(href, "_blank");
    else if (!/^[a-z][\w+.-]*:/i.test(href)) {
      const rel = resolve(decodeURIComponent(href.split("#")[0].split("?")[0]));
      if (rel) onopen(rel);
    }
  }
  function key(e: KeyboardEvent) {
    if (matches(e, "mod+shift+v")) { e.preventDefault(); onkey?.(e); }
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div class="mdv" bind:this={scroller} tabindex="0" onkeydown={key} role="document" title={`${kbd("mod+shift+v")} alterna para o código`}>
  {#if tasks.length}
    <div class="prog" class:all={done === tasks.length}>
      <span><b>{done}</b> de {tasks.length} concluído{tasks.length > 1 ? "s" : ""}</span>
      <span class="bar"><span style="width:{(100 * done) / tasks.length}%"></span></span>
      <span class="pct">{Math.round((100 * done) / tasks.length)}%</span>
    </div>
  {/if}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="doc" bind:this={el} onclick={click}></div>
</div>

<style>
  .mdv { position: absolute; inset: 0; overflow: auto; background: var(--surface); outline: none; padding: 0 28px 48px; }
  .prog { position: sticky; top: 0; z-index: 2; display: flex; align-items: center; gap: 12px; max-width: 860px; margin: 0 auto; padding: 12px 2px 10px;
    background: var(--surface); border-bottom: 1px solid var(--line); font: 12.5px var(--font); color: var(--text-2); }
  .prog b { color: var(--text); }
  .bar { flex: 1; height: 5px; border-radius: 99px; background: var(--surface-3); overflow: hidden; }
  .bar span { display: block; height: 100%; border-radius: 99px; background: var(--accent); transition: width 0.35s var(--ease-out); }
  .prog.all .bar span { background: var(--good); }
  .prog.all .pct { color: var(--good); }
  .pct { font-variant-numeric: tabular-nums; color: var(--muted); min-width: 34px; text-align: right; }

  .doc { max-width: 860px; margin: 0 auto; padding-top: 18px; color: var(--text); font: 14.5px/1.65 var(--font); overflow-wrap: anywhere; }
  .doc :global(h1), .doc :global(h2), .doc :global(h3), .doc :global(h4), .doc :global(h5), .doc :global(h6) {
    margin: 1.5em 0 0.55em; line-height: 1.25; letter-spacing: -0.015em; font-weight: 650; scroll-margin-top: 56px; }
  .doc :global(h1) { font-size: 1.85em; padding-bottom: 0.3em; border-bottom: 1px solid var(--line); }
  .doc :global(h2) { font-size: 1.45em; padding-bottom: 0.25em; border-bottom: 1px solid var(--line); }
  .doc :global(h3) { font-size: 1.2em; }
  .doc :global(h4) { font-size: 1.05em; }
  .doc :global(h5), .doc :global(h6) { font-size: 0.95em; color: var(--text-2); }
  .doc :global(> :first-child) { margin-top: 0; }
  .doc :global(p) { margin: 0.7em 0; }
  .doc :global(a) { color: var(--accent); text-decoration: none; cursor: pointer; }
  .doc :global(a:hover) { text-decoration: underline; }
  .doc :global(ul), .doc :global(ol) { margin: 0.6em 0; padding-left: 1.6em; }
  .doc :global(li) { margin: 0.25em 0; }
  .doc :global(li > ul), .doc :global(li > ol) { margin: 0.2em 0; }
  .doc :global(ul.tasks) { list-style: none; padding-left: 0.4em; }
  .doc :global(li li) { padding-left: 0; }
  .doc :global(ul.tasks ul.tasks) { padding-left: 1.6em; }
  .doc :global(li.task) { display: block; padding: 3px 6px; margin: 1px 0 1px -6px; border-radius: 7px; transition: background 0.15s, color 0.2s; }
  .doc :global(li.task:hover) { background: var(--surface-2); }
  .doc :global(li.task > input[type="checkbox"]) { appearance: none; -webkit-appearance: none; display: inline-grid; place-content: center; vertical-align: -3px;
    width: 16px; height: 16px; margin: 0 9px 0 0; border: 1.5px solid var(--line-3); border-radius: 5px; background: var(--surface); cursor: pointer;
    transition: background 0.15s, border-color 0.15s, transform 0.12s; }
  .doc :global(li.task > input[type="checkbox"]:hover) { border-color: var(--accent); }
  .doc :global(li.task > input[type="checkbox"]:active) { transform: scale(0.88); }
  .doc :global(li.task > input[type="checkbox"]::after) { content: ""; width: 9px; height: 5px; margin-top: -2px; border-left: 2px solid #fff; border-bottom: 2px solid #fff;
    transform: rotate(-45deg) scale(0); transition: transform 0.15s var(--ease-out); }
  .doc :global(li.task > input[type="checkbox"]:checked) { background: var(--accent); border-color: var(--accent); }
  .doc :global(li.task > input[type="checkbox"]:checked::after) { transform: rotate(-45deg) scale(1); }
  .doc :global(li.task.done) { color: var(--muted); }
  .doc :global(li.task.done > p), .doc :global(li.task.done) { text-decoration: line-through; text-decoration-color: color-mix(in srgb, var(--muted) 55%, transparent); }
  .doc :global(li.task.done li) { text-decoration: none; }
  .doc :global(blockquote) { margin: 0.9em 0; padding: 0.2em 1em; border-left: 3px solid var(--accent-line, var(--line-2)); color: var(--text-2); background: var(--surface-2); border-radius: 0 8px 8px 0; }
  .doc :global(code) { font: 0.88em var(--mono); background: var(--surface-2); border: 1px solid var(--line); border-radius: 5px; padding: 0.1em 0.38em; }
  .doc :global(pre) { margin: 0.9em 0; padding: 12px 14px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 9px; overflow-x: auto; line-height: 1.5; }
  .doc :global(pre code) { background: none; border: 0; padding: 0; font-size: 12.5px; white-space: pre; }
  .doc :global(hr) { border: 0; border-top: 1px solid var(--line); margin: 1.6em 0; }
  .doc :global(table) { border-collapse: collapse; margin: 0.9em 0; display: block; overflow-x: auto; max-width: 100%; font-size: 13.5px; }
  .doc :global(th), .doc :global(td) { border: 1px solid var(--line-2); padding: 6px 12px; text-align: left; vertical-align: top; min-width: 5em; word-break: normal; overflow-wrap: anywhere; }
  .doc :global(td:first-child) { overflow-wrap: normal; }
  .doc :global(th) { background: var(--surface-2); font-weight: 650; }
  .doc :global(tr:nth-child(even) td) { background: color-mix(in srgb, var(--surface-2) 45%, transparent); }
  .doc :global(img) { max-width: 100%; border-radius: 6px; }
  .doc :global(.imgph) { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border: 1px dashed var(--line-2); border-radius: 8px;
    color: var(--muted); font: 12px var(--mono); background: var(--surface-2); }
  .doc :global(del) { color: var(--muted); }
</style>
