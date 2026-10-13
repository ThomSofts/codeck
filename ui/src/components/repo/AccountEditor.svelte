<script lang="ts">
  // Detalhes e ajustes de uma conta conectada (organização do Azure ou conta do GitHub): conexão, números, quais
  // repositórios acompanhar (todos × só os escolhidos), pastas base dos clones e a conta de IA padrão dos projetos dela.
  // Pastas base: onde ficam os clones (várias — …/apis, …/mobile); o app reconhece os clones dentro delas.
  import { ArrowUp, Eye, Folder, FolderGit2, FolderPlus, FolderSearch, KeyRound, Settings2, Star, Trash2 } from "@lucide/svelte";
  import { get, post } from "../../lib/api";
  import { dateTime } from "../../lib/format";
  import { pickFolder } from "../../lib/native";
  import { repos } from "../../lib/repos.svelte";
  import { go } from "../../lib/router.svelte";
  import { store } from "../../lib/store.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { work } from "../../lib/work.svelte";
  import Avatar from "../Avatar.svelte";
  import Drawer from "../Drawer.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import Segmented from "../Segmented.svelte";
  import TestResult from "../TestResult.svelte";
  import AgentIcon from "../work/AgentIcon.svelte";

  const key = $derived(ui.editAccount!);
  const acc = $derived(repos.accounts.find(a => a.key === key));
  const prov = $derived(key.split(":")[0] as "azure" | "github");
  const name = $derived(key.slice(prov.length + 1));
  let dirs = $state<string[]>([]);
  let counts = $state<Record<string, number>>({});
  let suggestions = $state<{ path: string; count: number }[]>([]);
  let cfg = $state<any>(null);
  let test = $state<any>(null);
  let scanning = $state(false);
  let cat = $state<{ total: number; cloned: number } | null>(null);
  const home = (p: string) => p.replace(/^\/Users\/[^/]+|^C:\\Users\\[^\\]+/i, "~");

  $effect(() => {
    const k = key;
    dirs = [...(repos.accounts.find(a => a.key === k)?.dirs || [])];
    get<{ targets: { path: string; count: number; account: boolean }[] }>("clone-targets", { account: k }).then(r => {
      counts = Object.fromEntries(r.targets.map(t => [t.path, t.count]));
      suggestions = r.targets.filter(t => !t.account && t.count > 0);
    }).catch(() => {});
    get("config").then(c => (cfg = c)).catch(() => {});
    cat = null;
    get<any>("catalog", { id: "account:" + k }).then(v => (cat = v.counts)).catch(() => {});
  });
  const info = $derived(prov === "github" ? cfg?.github?.find((a: any) => a.login === name) : cfg?.orgs?.find((o: any) => o.name === name));
  const errKey = $derived(prov === "github" ? "gh:" + name : name);
  const errors = $derived(store.s ? [store.s.errors?.[errKey], store.s.buildErrors?.[errKey], store.s.deployErrors?.[errKey], store.s.issueErrors?.[errKey]].filter(Boolean) as string[] : []);
  const mineItem = (x: any) => (prov === "github" ? x.provider === "github" && x.account === name : x.provider !== "github" && x.org === name);
  const stats = $derived({
    prs: (store.s?.prs || []).filter(p => !p.archived && mineItem(p)).length + (store.s?.myPrs || []).filter(mineItem).length,
    builds: (store.s?.builds || []).filter(b => mineItem(b) && b.status !== "completed").length,
    failed: (store.s?.builds || []).filter(b => mineItem(b) && b.result === "failed").length,
    deploys: (store.s?.deploys || []).filter(mineItem).length,
    issues: (store.s?.issues || []).filter(i => (prov === "github" ? i.provider === "github" && (!i.account || i.account === name) : i.provider !== "github" && i.org === name)).length,
  });
  const mode = $derived(repos.trackMode(key));
  const explicit = $derived(Object.entries(repos.tracking.repos).filter(([k, v]) => v.track !== undefined && localKeyOk(k)));
  function localKeyOk(k: string) {
    if (prov === "github") return k.startsWith("github:");
    const slug = (info?.url || "").replace(/\/$/, "").split("/").pop()?.toLowerCase() || name.toLowerCase();
    return k.startsWith(`azure:${slug}/`);
  }
  const trackedN = $derived(explicit.filter(([, v]) => v.track).length);
  const untrackedN = $derived(explicit.filter(([, v]) => v.track === false).length);
  const scope = $derived(`${prov}:${name}`);
  const defaultAi = $derived(work.defaults[scope] || "");

  async function save(next: string[], msg: string) {
    try {
      const r = await post<{ dirs: string[] }>("accounts/dirs", { key, dirs: next });
      dirs = r.dirs;
      if (acc) acc.dirs = r.dirs;
      ui.toast(msg);
    } catch (e) { ui.error(e); }
  }
  async function add(path?: string) {
    const p = path || (await pickFolder(`Pasta base de ${name}`));
    if (p && !dirs.includes(p)) save([...dirs, p], "Pasta adicionada — os clones dentro dela já são reconhecidos");
  }
  async function scan() {
    scanning = true;
    try { const r = await post<{ found: number; new: number }>("repos/discover"); await repos.load(); ui.toast(r.new ? `${r.new} repositório(s) novo(s) encontrado(s)` : "Nenhum clone novo — tudo já estava na lista", r.new ? "ok" : "info"); }
    catch (e) { ui.error(e); }
    scanning = false;
  }
  async function setMode(m: string) {
    if (m === mode) return;
    if (m === "selected" && !trackedN && !(await ui.ask({ title: "Acompanhar só os escolhidos?", message: "Nenhum repositório desta conta está marcado ainda — PRs, builds, deploys e issues dela somem até você marcar os que quer (no olho de cada repositório).", confirm: "Mudar" }))) return;
    try { await repos.setTrackMode(key, m as any); store.refreshSoon(2500); ui.toast(m === "all" ? "Acompanhando todos os repositórios da conta" : "Acompanhando só os repositórios escolhidos"); }
    catch (e) { ui.error(e); }
  }
  async function runTest() {
    test = { running: true };
    try { test = prov === "github" ? await post("github/test", { id: info?.id }) : await post("config/test", { name, url: info?.url, pat: "", originalName: name }); }
    catch (e: any) { test = { error: e.message }; }
  }
  async function setAi(id: string) { if (!id) return; await post("ai/default", { scope, id }); await work.loadAi(); ui.toast("Conta de IA padrão salva"); }
</script>

<Drawer title={name} subtitle={prov === "azure" ? "Organização do Azure DevOps" : "Conta do GitHub"} onclose={() => (ui.editAccount = null)} width={600}>
  <div class="wrap">
    <!-- conta -->
    <div class="who card">
      {#if prov === "github" && info?.avatar}<Avatar name={name} src={info.avatar} size={42} />{:else}<span class="ic"><ProviderIcon provider={prov} size={22} /></span>{/if}
      <div class="grow">
        <b>{prov === "github" ? info?.name || name : name}</b>
        <span class="small muted">{prov === "github" ? "@" + name : info?.url || ""}{info?.me ? ` · ${info.me.displayName || info.me.name}` : ""}</span>
        <span class="tiny muted">{prov === "github" ? `${info?.store || "cofre"}${info?.connectedAt ? " · conectado " + dateTime(info.connectedAt) : ""}${info?.rate ? ` · API ${info.rate.remaining}/${info.rate.limit}` : ""}` : `PAT no ${info?.patStore || "cofre"}`}</span>
      </div>
      <div class="col">
        <button class="btn sm" onclick={runTest}><KeyRound size={13} /> Testar</button>
        <button class="btn sm ghost" onclick={() => { ui.editAccount = null; go(prov === "azure" ? "/settings/accounts" : "/settings/github"); }}><Settings2 size={13} /> Credencial</button>
      </div>
    </div>
    {#if test}<div class="card pad"><TestResult {test} /></div>{/if}
    {#each errors as e (e)}<div class="err small">{e}</div>{/each}

    <div class="nums">
      <div><b>{cat?.total ?? acc?.count ?? "…"}</b><span>repositórios</span></div>
      <div><b>{cat?.cloned ?? "…"}</b><span>clonados aqui</span></div>
      <div><b>{stats.prs}</b><span>PRs abertas</span></div>
      <div class:hot={stats.builds}><b>{stats.builds}</b><span>builds rodando</span></div>
      <div class:bad={stats.failed}><b>{stats.failed}</b><span>builds falhos</span></div>
      <div><b>{stats.deploys}</b><span>deploys esperando</span></div>
      <div><b>{stats.issues}</b><span>issues / tarefas</span></div>
    </div>

    <!-- acompanhamento -->
    <section>
      <h4><Eye size={13} /> O que acompanhar</h4>
      <p class="small muted">PRs, builds, deploys e issues desta conta entram nas listas e nas notificações conforme a escolha. Em cada repositório (o olho na lista, ou o painel dele) dá para ligar/desligar só uma parte.</p>
      <Segmented value={mode} onchange={setMode} options={[{ value: "all", label: "Todos os repositórios" }, { value: "selected", label: "Só os escolhidos" }]} />
      <div class="small muted">{mode === "all" ? `Todos${untrackedN ? `, menos ${untrackedN} que você desligou` : ""}.` : `${trackedN} repositório(s) escolhido(s).`}
        <button class="lnk" onclick={() => { ui.editAccount = null; go("/repos/account/" + encodeURIComponent(key), "soft"); }}>Escolher na lista →</button></div>
    </section>

    <!-- pastas base -->
    <section>
      <h4><FolderGit2 size={13} /> Pastas base dos clones</h4>
      <p class="small muted">Onde ficam os repositórios clonados de <b>{name}</b> — pode ter várias. O app reconhece sozinho os clones dentro delas (inclusive repositórios dentro de outro, como um workspace com as APIs) e as oferece primeiro na hora de clonar.</p>
      <div class="list">
        {#each dirs as d, i (d)}
          <div class="dir">
            <Folder size={15} />
            <div class="grow"><b>{d.split(/[\\/]/).pop()}</b><span class="small muted mono ell">{home(d)}</span></div>
            <span class="tiny muted">{counts[d] ? `${counts[d]} clone${counts[d] > 1 ? "s" : ""}` : "vazia"}</span>
            {#if i > 0}<button class="btn sm ghost icon" title="Usar como sugerida" onclick={() => save([d, ...dirs.filter(x => x !== d)], "Pasta sugerida alterada")}><ArrowUp size={13} /></button>
            {:else}<span class="pill accent">sugerida</span>{/if}
            <button class="btn sm ghost icon" title="Tirar da conta (a pasta continua no disco)" onclick={() => save(dirs.filter(x => x !== d), "Pasta removida da conta")}><Trash2 size={13} /></button>
          </div>
        {:else}
          <div class="empty small muted">Nenhuma pasta ainda — ao clonar, o app pergunta e pode guardar a escolha aqui.</div>
        {/each}
        <div class="row"><button class="btn" onclick={() => add()}><FolderPlus size={14} /> Adicionar pasta</button>
          <button class="btn ghost" onclick={scan} disabled={scanning}><FolderSearch size={14} class={scanning ? "spin" : ""} /> Procurar clones agora</button></div>
      </div>
      {#if suggestions.filter(s => !dirs.includes(s.path)).length}
        <div class="small muted">Pastas onde você já tem clones:</div>
        <div class="list">
          {#each suggestions.filter(s => !dirs.includes(s.path)) as s (s.path)}
            <button class="dir sug" onclick={() => add(s.path)}><Folder size={15} /><div class="grow"><b>{s.path.split(/[\\/]/).pop()}</b><span class="small muted mono ell">{home(s.path)}</span></div>
              <span class="tiny muted">{s.count} clone{s.count > 1 ? "s" : ""}</span><span class="pill neutral">+ usar</span></button>
          {/each}
        </div>
      {/if}
    </section>

    <!-- IA -->
    <section>
      <h4><Star size={13} /> Conta de IA padrão</h4>
      <p class="small muted">Sugerida ao abrir agentes e pedir à IA nos projetos de {name}.</p>
      <div class="ais">
        {#each work.ai.filter(a => a.installed) as a (a.id)}
          <button class="ai" class:on={defaultAi === a.id} onclick={() => setAi(a.id)}><AgentIcon provider={a.provider} size={14} /><span class="ell">{a.name}</span></button>
        {:else}<span class="small muted">Nenhuma CLI de IA encontrada.</span>{/each}
      </div>
    </section>
  </div>
</Drawer>

<style>
  .wrap { display: grid; gap: 16px; padding-top: 12px; }
  p { margin: 0; }
  h4 { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
  section { display: grid; gap: 8px; }
  .card { padding: 14px; }
  .pad { padding: 10px 14px; }
  .who { display: flex; align-items: center; gap: 12px; }
  .who .ic { width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; background: var(--surface-2); border: 1px solid var(--line-2); }
  .who .grow { flex: 1; min-width: 0; display: grid; gap: 1px; }
  .col { display: grid; gap: 4px; }
  .err { padding: 8px 12px; border-radius: 9px; background: var(--bad-soft); color: var(--bad); }
  .nums { display: grid; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap: 8px; }
  .nums div { display: grid; gap: 2px; padding: 10px 12px; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--line); }
  .nums b { font-size: 18px; font-variant-numeric: tabular-nums; }
  .nums span { font-size: 11.5px; color: var(--muted); }
  .nums .hot b { color: var(--accent); } .nums .bad b { color: var(--bad); }
  .lnk { border: 0; background: none; color: var(--accent); font: inherit; cursor: pointer; padding: 0 0 0 4px; }
  .list { display: grid; gap: 6px; justify-items: start; }
  .row { display: flex; gap: 6px; flex-wrap: wrap; }
  .dir { display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 8px 8px 12px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface-2);
    color: var(--text-2); font: 13px var(--font); text-align: left; animation: rise 0.25s var(--ease-out) both; }
  .dir .grow { flex: 1; min-width: 0; display: grid; }
  .dir b { color: var(--text); }
  .sug { cursor: pointer; border-style: dashed; background: none; transition: border-color var(--t); }
  .sug:hover { border-color: var(--accent); }
  .empty { padding: 10px 2px; }
  .ais { display: flex; flex-wrap: wrap; gap: 6px; }
  .ai { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 10px; border-radius: 99px; border: 1px solid var(--line-2); background: var(--surface-2);
    color: var(--text-2); font: 12.5px var(--font); cursor: pointer; max-width: 200px; }
  .ai.on { border-color: var(--accent); background: var(--accent-soft); color: var(--text); }
</style>
