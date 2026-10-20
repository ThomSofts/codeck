<script lang="ts">
  // Pessoas: a mesma pessoa com nomes diferentes em cada conta ("Leonardo" = "Leonardo Thomaz" na Cifal e
  // "leonardo.thomaz" na Dematec). O filtro de responsável das Issues junta todos os nomes dela. Sugere juntar os nomes
  // que começam igual e aparecem em contas diferentes.
  import { Plus, Trash2, Users, X } from "@lucide/svelte";
  import { people, savePeople } from "../../lib/people";
  import { store } from "../../lib/store.svelte";

  const list = $derived(Object.entries(people()));
  // nomes vistos (responsáveis e autores das issues/work items) e em qual conta
  const seen = $derived.by(() => {
    const m = new Map<string, Set<string>>();
    for (const i of store.s?.issues || []) {
      for (const a of i.assignees || []) { if (a.login) m.set(a.login, (m.get(a.login) || new Set()).add(i.org)); if (a.email) m.set(a.email, (m.get(a.email) || new Set()).add(i.org)); }
      if (i.author) m.set(i.author, (m.get(i.author) || new Set()).add(i.org));
    }
    return m;
  });
  const used = $derived(new Set(list.flatMap(([, v]) => v.map(x => x.toLowerCase()))));
  const first = (n: string) => n.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().split(/[\s._@-]+/)[0];
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  const suggestions = $derived.by(() => {
    const g = new Map<string, { names: string[]; orgs: Set<string> }>();
    for (const [n, orgs] of seen) {
      if (used.has(n.toLowerCase()) || n.includes("@") || first(n).length < 3) continue;
      const k = first(n), x = g.get(k) || { names: [], orgs: new Set() };
      x.names.push(n); for (const o of orgs) x.orgs.add(o); g.set(k, x);
    }
    return [...g.entries()].filter(([, x]) => x.names.length > 1 && x.orgs.size > 1).map(([k, x]) => ({ name: cap(k), names: x.names }));
  });

  let draft = $state<Record<string, string>>({});
  function set(name: string, aliases: string[], rename?: string) {
    const next = { ...people() };
    if (rename !== undefined && rename !== name) delete next[name];
    next[rename ?? name] = aliases;
    savePeople(next);
  }
  function add(name: string) {
    const v = (draft[name] || "").trim();
    if (!v) return;
    set(name, [...(people()[name] || []).filter(x => x !== "?"), v]);
    draft = { ...draft, [name]: "" };
  }
  function remove(name: string) { const next = { ...people() }; delete next[name]; savePeople(next); }
  function newPerson() {
    let n = "Nova pessoa", i = 2;
    while (people()[n]) n = `Nova pessoa ${i++}`;
    savePeople({ ...people(), [n]: ["?"] });
  }
</script>

<div class="card org" id="people">
  <div class="row" style="gap:8px"><Users size={16} /><b>Pessoas</b><span class="spacer"></span>
    <button class="btn sm ghost" onclick={newPerson}><Plus size={14} /> Pessoa</button></div>
  <p class="small muted">A mesma pessoa com nomes diferentes em cada conta — por exemplo, “Leonardo” = <i>Leonardo Thomaz</i> na Cifal e <i>leonardo.thomaz</i> na Dematec. No filtro de responsável das Issues, escolher a pessoa traz os itens de todos os nomes dela. Vale nome, login ou e-mail.</p>
  {#each suggestions as sg (sg.name)}
    <div class="sug small"><span>Parecem a mesma pessoa: <b>{sg.names.join(", ")}</b></span>
      <button class="btn sm" onclick={() => set(sg.name, sg.names)}>Juntar como “{sg.name}”</button></div>
  {/each}
  {#each list as [name, aliases] (name)}
    <div class="person">
      <input class="input nm" value={name} aria-label="Nome da pessoa" onchange={(e) => { const v = (e.target as HTMLInputElement).value.trim(); if (v && v !== name) set(name, aliases, v); }} />
      <div class="al">
        {#each aliases.filter(a => a !== "?") as a (a)}
          <span class="chip">{a}{#if seen.get(a)}<span class="tiny muted"> · {[...seen.get(a)!].join(", ")}</span>{/if}
            <button title="Tirar" onclick={() => set(name, aliases.filter(x => x !== a))}><X size={10} /></button></span>
        {/each}
        <input class="input sm add" list="people-names" placeholder="nome, login ou e-mail em outra conta" bind:value={draft[name]}
          onkeydown={(e) => e.key === "Enter" && add(name)} onblur={() => add(name)} />
      </div>
      <button class="btn sm ghost danger" title="Apagar a pessoa" onclick={() => remove(name)}><Trash2 size={14} /></button>
    </div>
  {:else}
    <div class="tiny muted">Nenhuma pessoa ainda.</div>
  {/each}
  <datalist id="people-names">{#each [...seen.keys()].filter(n => !used.has(n.toLowerCase())).sort() as n (n)}<option value={n}></option>{/each}</datalist>
</div>

<style>
  .person { display: grid; grid-template-columns: 180px minmax(0, 1fr) auto; gap: 10px; align-items: start; padding: 8px 0; border-top: 1px solid var(--line); }
  .nm { height: 30px; font-weight: 600; }
  .al { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .chip { display: inline-flex; align-items: center; gap: 4px; height: 26px; padding: 0 4px 0 10px; border-radius: 99px; border: 1px solid var(--line-2); font-size: 12.5px; }
  .chip button { display: grid; place-items: center; width: 18px; height: 18px; border: 0; border-radius: 50%; background: none; color: var(--muted); cursor: pointer; }
  .chip button:hover { background: var(--surface-3); color: var(--text); }
  .add { flex: 1; min-width: 200px; height: 28px; }
  .sug { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 7px 10px; border-radius: 8px; background: var(--accent-soft); }
  .sug span { flex: 1; }
</style>
