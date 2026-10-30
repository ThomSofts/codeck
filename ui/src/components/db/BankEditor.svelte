<script lang="ts">
  // Cadastro de um banco: nome, pasta, tipo, ambientes (dev/hml/prod, cada um com servidor, usuário, senha e TLS) e os
  // projetos que o usam. A senha vai direto para o cofre do sistema; aqui só se sabe se existe.
  import { CheckCircle2, KeyRound, Plus, Search, ShieldAlert, ShieldCheck, Trash2, Zap } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { ApiError, post } from "../../lib/api";
  import { db, ENGINE_LABEL, type DbBank, type DbEnv, type Engine, type EnvKind } from "../../lib/db.svelte";
  import { repos } from "../../lib/repos.svelte";
  import { ui } from "../../lib/ui.svelte";
  import Drawer from "../Drawer.svelte";
  import Segmented from "../Segmented.svelte";
  import Switch from "../Switch.svelte";

  let { bank = null, folder = "", onclose, onsaved = undefined }: { bank?: DbBank | null; folder?: string; onclose: () => void; onsaved?: (b: DbBank) => void } = $props();

  type FormEnv = Omit<DbEnv, "port" | "timeoutSec" | "ssh"> & { port: string; password: string; clearPassword: boolean; test?: { ok: boolean; text: string } | null; testing?: boolean;
    ssh: { on: boolean; host: string; port: string; user: string; key: string } };
  const COLORS = ["#6F8CFF", "#3CCF91", "#F5B84F", "#FF6B7D", "#B07CFF", "#4FC3F7", "#FF8A50", "#9AA4B2"];
  const toForm = (e: DbEnv): FormEnv => ({ ...e, tls: { ...e.tls }, port: e.port ? String(e.port) : "", password: "", clearPassword: false, test: null,
    ssh: { on: !!e.ssh?.host, host: e.ssh?.host || "", port: e.ssh?.port ? String(e.ssh.port) : "", user: e.ssh?.user || "", key: e.ssh?.key || "" } });
  const blankEnv = (kind: EnvKind): FormEnv => ({ id: "", kind, label: "", host: "", port: "", database: "", user: "", file: "", password: "", clearPassword: false,
    tls: { mode: "verify", pin: "", legacy: false }, readOnly: kind === "prod", hasPassword: false, test: null,
    ssh: { on: false, host: "", port: "", user: "", key: "" } });

  const init = untrack(() => bank);
  let name = $state(init?.name || "");
  let fold = $state(init?.folder || untrack(() => folder));
  let engine = $state<Engine>(init?.engine || "sqlserver");
  let color = $state(init?.color || "");
  let notes = $state(init?.notes || "");
  let envs = $state<FormEnv[]>(init?.envs.length ? init.envs.map(toForm) : [blankEnv("dev")]);
  let linked = $state<Set<string>>(new Set(init?.projects.map(p => p.repo) || []));
  let q = $state("");
  let saving = $state(false);

  const projects = $derived(repos.local.filter(r => r.exists && !/[\\/]\.worktrees[\\/]/.test(r.path)).sort((a, b) => a.name.localeCompare(b.name)));
  const shown = $derived(projects.filter(r => !q || r.name.toLowerCase().includes(q.toLowerCase()) || r.path.toLowerCase().includes(q.toLowerCase())));
  $effect(() => { if (!repos.loaded) untrack(() => repos.load(false)); });

  function payloadEnv(e: FormEnv) {
    return { id: e.id || undefined, kind: e.kind, label: e.label, host: e.host.trim(), port: e.port ? Number(e.port) : null, database: e.database.trim(), user: e.user.trim(),
      file: e.file.trim(), tls: e.tls, readOnly: e.readOnly, password: e.password || undefined, clearPassword: e.clearPassword || undefined,
      ssh: e.ssh.on && e.ssh.host.trim() ? { host: e.ssh.host.trim(), port: e.ssh.port ? Number(e.ssh.port) : 22, user: e.ssh.user.trim(), key: e.ssh.key.trim() } : null };
  }

  async function test(e: FormEnv) {
    e.testing = true; e.test = null;
    try {
      const r = await post("db/test", { engine, env: payloadEnv(e), bank: bank?.id, envId: e.id || undefined });
      e.test = { ok: true, text: `${r.server}${r.tls ? ` · ${r.tls.version}` : engine === "sqlite" || engine === "firebase" ? "" : " · sem criptografia"}${r.ssh ? " · pelo túnel SSH" : ""}` };
    } catch (err) {
      const code = err instanceof ApiError ? err.data?.code : null;
      if (code && String(code).startsWith("cert-")) {
        const c = err instanceof ApiError ? err.data.data : null;
        const ok = await ui.ask({ title: "Certificado do servidor", message: "O servidor apresentou um certificado que o sistema não reconhece. Confira a impressão digital com quem administra o servidor e fixe — daqui em diante só ele é aceito.",
          detail: [`SHA-256: ${c.sha256.replace(/(..)(?!$)/g, "$1:")}`, `Emitido para: ${c.subject || "—"}`, `Válido até: ${c.notAfter?.slice(0, 10)}`, `Protocolo: ${c.version} · ${c.cipher}`],
          confirm: "Fixar este certificado" });
        if (ok) { e.tls = { ...e.tls, mode: "pin", pin: c.sha256 }; return test(e); }
      }
      e.test = { ok: false, text: (err as any)?.message || String(err) };
    } finally { e.testing = false; }
  }

  async function save() {
    if (!name.trim()) return ui.toast("Dê um nome ao banco", "error");
    saving = true;
    try {
      const r = await post("db/bank", { id: bank?.id, name, folder: fold, engine, color: color || undefined, notes, envs: envs.map(payloadEnv) });
      db.set(r);
      const before = new Set(bank?.projects.map(p => p.repo) || []);
      const add = [...linked].filter(x => !before.has(x)), remove = [...before].filter(x => !linked.has(x));
      if (add.length || remove.length) db.set(await post("db/links", { bank: r.bank.id, add, remove }));
      db.project = {};   // as abas Banco dos projetos releem
      ui.toast(bank ? "Banco atualizado" : "Banco cadastrado");
      onsaved?.(db.bank(r.bank.id)!);
      onclose();
    } catch (e) { ui.error(e); } finally { saving = false; }
  }

  async function remove() {
    if (!bank) return;
    const ok = await ui.ask({ title: `Apagar ${bank.name}?`, message: "Sai do Codeck com os ambientes, as senhas guardadas no cofre e os vínculos com projetos. O banco de dados em si não é tocado.",
      confirm: "Apagar", danger: true });
    if (!ok) return;
    try { db.set(await post("db/bank/delete", { id: bank.id })); db.project = {}; onclose(); } catch (e) { ui.error(e); }
  }
  const sqlite = $derived(engine === "sqlite");
</script>

<Drawer title={bank ? `Banco · ${bank.name}` : "Novo banco"} subtitle="Senhas ficam no cofre do sistema e nunca voltam para a tela" {onclose} width={760} resizeKey="dbbank">
  <div class="form">
    <div class="g2">
      <label class="label">Nome <input class="input" bind:value={name} placeholder="Ex.: Cifal · Atual" /></label>
      <label class="label">Pasta <input class="input" bind:value={fold} list="db-folders" placeholder="Ex.: Cifal (opcional)" />
        <datalist id="db-folders">{#each db.data?.folders || [] as f (f)}<option value={f}></option>{/each}</datalist></label>
    </div>
    <div class="g2">
      <label class="label">Tipo
        <select class="select" bind:value={engine} disabled={!!bank && bank.envs.length > 0}>
          {#each db.data?.plugins || [] as p (p.engine)}<option value={p.engine}>{ENGINE_LABEL[p.engine]}{p.installed ? "" : " (plugin não instalado)"}</option>{/each}
        </select>
      </label>
      <div class="label">Cor
        <div class="colors">{#each COLORS as c (c)}<button class="sw" class:on={(color || bank?.color) === c} style="--c:{c}" aria-label={c} onclick={() => (color = c)}></button>{/each}</div>
      </div>
    </div>

    {#if db.plugin(engine) && !db.plugin(engine)!.installed}
      <div class="plugbox"><span>O plugin de <b>{ENGINE_LABEL[engine]}</b> ainda não está instalado neste computador.</span><span class="grow"></span>
        <button class="btn sm primary" onclick={() => db.installPlugin(engine)}>Instalar plugin</button></div>
    {/if}
    <div class="sect"><span>Ambientes</span><span class="grow"></span>
      {#each (["dev", "hml", "prod"] as EnvKind[]).filter(k => !envs.some(e => e.kind === k)) as k (k)}
        <button class="btn sm ghost" onclick={() => (envs = [...envs, blankEnv(k)])}><Plus size={13} /> {k === "prod" ? "PROD" : k}</button>
      {/each}
    </div>
    {#each envs as e, i (i)}
      <div class="env" class:prod={e.kind === "prod"}>
        <div class="eh">
          <Segmented size="sm" bind:value={e.kind} options={[{ value: "dev", label: "dev" }, { value: "hml", label: "hml" }, { value: "prod", label: "PROD" }]}
            onchange={(k) => (e.readOnly = k === "prod" ? true : e.readOnly)} />
          <input class="input lbl" bind:value={e.label} placeholder="apelido (opcional)" />
          <span class="grow"></span>
          {#if envs.length > 1}<button class="btn sm ghost icon" title="Remover ambiente" onclick={() => (envs = envs.filter((_, j) => j !== i))}><Trash2 size={13} /></button>{/if}
        </div>
        {#if sqlite}
          <label class="label">Arquivo <input class="input mono" bind:value={e.file} placeholder="/caminho/do/banco.db" /></label>
        {:else if engine === "libsql"}
          <label class="label">URL do banco <input class="input mono" bind:value={e.host} placeholder="libsql://meu-banco-org.turso.io" /></label>
          <label class="label">Token de acesso
            <input class="input" type="password" bind:value={e.password} autocomplete="new-password" placeholder={e.hasPassword && !e.clearPassword ? "•••••• (guardado no cofre)" : "turso db tokens create meu-banco"} /></label>
        {:else if engine === "firebase"}
          <div class="g2">
            <label class="label">Projeto (Firestore) ou URL do Realtime Database
              <input class="input" bind:value={e.host} placeholder="meu-projeto  ·  ou https://meu-projeto-default-rtdb.firebaseio.com" /></label>
            <label class="label">Banco do Firestore <input class="input" bind:value={e.database} placeholder="(default)" disabled={e.host.startsWith("https://")} /></label>
          </div>
          <label class="label">JSON da conta de serviço
            <textarea class="textarea mono sa" rows="3" bind:value={e.password} spellcheck="false"
              placeholder={e.hasPassword && !e.clearPassword ? "•••••• (guardado no cofre) — cole outro para trocar" : "Firebase → Configurações do projeto → Contas de serviço → Gerar nova chave privada → cole o conteúdo aqui"}></textarea>
            <span class="tiny muted">Vai direto para o cofre do sistema. Dê à conta só o acesso que você precisa (ex.: leitura no banco de produção).</span>
          </label>
        {:else}
          <div class="g3">
            <label class="label">Servidor <input class="input" bind:value={e.host} placeholder={engine === "mongodb" ? "host ou mongodb+srv://cluster.x.mongodb.net" : "177.66.233.212 ou db.empresa.com"} /></label>
            <label class="label">Porta <input class="input" bind:value={e.port} inputmode="numeric" placeholder={String(db.data?.plugins.find(p => p.engine === engine) ? ({ sqlserver: 1433, postgres: 5432, mysql: 3306, mongodb: 27017, redis: 6379 } as any)[engine] ?? "" : "")} /></label>
            <label class="label">Banco <input class="input" bind:value={e.database} placeholder={engine === "redis" ? "0 (número)" : "DB_BELAFLOR"} /></label>
          </div>
          <div class="g2">
            <label class="label">Usuário <input class="input" bind:value={e.user} autocomplete="off" /></label>
            <label class="label">Senha
              <input class="input" type="password" bind:value={e.password} autocomplete="new-password" placeholder={e.hasPassword && !e.clearPassword ? "•••••• (guardada no cofre)" : ""} />
              {#if e.hasPassword && !e.password}<button class="link tiny" onclick={() => (e.clearPassword = !e.clearPassword)}>{e.clearPassword ? "manter a senha guardada" : "apagar a senha guardada"}</button>{/if}
            </label>
          </div>
          <div class="tls">
            <label class="label">Criptografia
              <select class="select" bind:value={e.tls.mode}>
                <option value="verify">Verificar certificado (padrão)</option>
                <option value="pin">Fixar certificado do servidor</option>
                <option value="off">Sem criptografia</option>
              </select>
            </label>
            {#if e.tls.mode !== "off"}
              <Switch bind:checked={e.tls.legacy} label="Servidor antigo" hint="Aceita TLS 1.0/1.1 — SQL Server 2008/2012 sem atualização" />
            {/if}
          </div>
          {#if e.tls.mode === "pin"}
            <p class="tiny muted pin"><KeyRound size={12} /> {e.tls.pin ? `Fixado: ${e.tls.pin.slice(0, 16)}…${e.tls.pin.slice(-8)}` : "Ao testar ou conectar, o Codeck mostra a impressão digital para você conferir e fixar."}
              {#if e.tls.pin}<button class="link" onclick={() => (e.tls.pin = "")}>esquecer</button>{/if}</p>
          {:else if e.tls.mode === "off"}
            <div class="warnbox">
              <ShieldAlert size={15} />
              <div>
                <b>Sem criptografia, usuário, senha e dados trafegam legíveis.</b>
                <label class="ck"><input type="checkbox" bind:checked={e.tls.offAck} /> Entendo o risco (rede local ou VPN)</label>
                <label class="ck"><input type="checkbox" bind:checked={e.tls.offPublicAck} disabled={!e.tls.offAck} /> Mesmo em endereço público — a senha iria legível pela internet</label>
              </div>
            </div>
          {/if}
        {/if}
        {#if !sqlite && engine !== "firebase" && engine !== "libsql"}
          <Switch bind:checked={e.ssh.on} label="Túnel SSH" hint="Para bancos que só se alcançam por um servidor intermediário (bastion)" />
          {#if e.ssh.on}
            <div class="g3">
              <label class="label">Servidor SSH <input class="input" bind:value={e.ssh.host} placeholder="bastion.empresa.com" /></label>
              <label class="label">Porta <input class="input" bind:value={e.ssh.port} inputmode="numeric" placeholder="22" /></label>
              <label class="label">Usuário <input class="input" bind:value={e.ssh.user} placeholder="deploy" /></label>
            </div>
            <label class="label">Chave (opcional) <input class="input mono" bind:value={e.ssh.key} placeholder="~/.ssh/id_ed25519 — vazio usa o ssh-agent e as chaves padrão" /></label>
            <p class="tiny muted">Usa o ssh do sistema, só com chave (nunca senha). O servidor precisa estar no seu known_hosts: na primeira vez, rode <code>ssh {e.ssh.user ? e.ssh.user + "@" : ""}{e.ssh.host || "servidor"}</code> no terminal e confira a impressão digital.</p>
          {/if}
        {/if}
        {#if e.kind === "prod"}<Switch bind:checked={e.readOnly} label="Abrir somente leitura" hint="Para alterar, destrava a conexão; cada alteração pede Confirmar/Desfazer" />{/if}
        <div class="tr">
          <button class="btn sm" disabled={e.testing} onclick={() => test(e)}><Zap size={13} /> {e.testing ? "Testando…" : "Testar conexão"}</button>
          {#if e.test}<span class="tiny" class:ok={e.test.ok} class:bad={!e.test.ok}>{#if e.test.ok}<CheckCircle2 size={12} /> {/if}{e.test.text}</span>{/if}
        </div>
      </div>
    {/each}

    <div class="sect"><span>Projetos que usam este banco</span><span class="tiny muted">{linked.size} vinculado{linked.size === 1 ? "" : "s"}</span><span class="grow"></span></div>
    <div class="pj">
      <div class="ps"><Search size={13} /><input class="input" bind:value={q} placeholder="Buscar projeto…" />
        {#if q && shown.length}<button class="btn sm ghost" onclick={() => { for (const r of shown) linked.add(r.id); linked = new Set(linked); }}>Marcar {shown.length}</button>{/if}
      </div>
      <div class="plist">
        {#each shown.slice(0, 400) as r (r.id)}
          <label class="pr"><input type="checkbox" checked={linked.has(r.id)} onchange={(ev) => { const s = new Set(linked); if ((ev.target as HTMLInputElement).checked) s.add(r.id); else s.delete(r.id); linked = s; }} />
            <span class="ell">{r.name}</span><span class="tiny muted ell">{r.path.replace(/^\/Users\/[^/]+/, "~")}</span></label>
        {/each}
      </div>
    </div>
    <label class="label">Notas <textarea class="textarea" rows="2" bind:value={notes} placeholder="Ex.: quem administra, VPN necessária…"></textarea></label>
  </div>
  {#snippet footer()}
    {#if bank}<button class="btn danger" onclick={remove}><Trash2 size={14} /> Apagar</button>{/if}
    <span class="grow"></span>
    <button class="btn ghost" onclick={onclose}>Cancelar</button>
    <button class="btn primary" disabled={saving} onclick={save}><ShieldCheck size={14} /> Salvar</button>
  {/snippet}
</Drawer>

<style>
  .form { display: flex; flex-direction: column; gap: 14px; }
  .g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .g3 { display: grid; grid-template-columns: 2fr 90px 1.4fr; gap: 12px; }
  .colors { display: flex; gap: 6px; align-items: center; height: 32px; }
  .sw { width: 20px; height: 20px; border-radius: 50%; border: 2px solid transparent; background: var(--c); cursor: pointer; }
  .sw.on { border-color: var(--text); }
  .sect { display: flex; align-items: center; gap: 8px; font-weight: 680; font-size: 13px; margin-top: 6px; }
  .plugbox { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: var(--r-sm); background: var(--info-soft); font-size: 13px; }
  .env { border: 1px solid var(--line-2); border-radius: var(--r); padding: 12px; display: flex; flex-direction: column; gap: 10px; background: var(--surface-2); }
  .env.prod { border-color: color-mix(in srgb, var(--bad) 45%, transparent); }
  .eh { display: flex; align-items: center; gap: 8px; }
  .lbl { max-width: 200px; height: 27px; }
  .tls { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: end; }
  .pin { display: flex; align-items: center; gap: 6px; margin: 0; }
  .warnbox { display: flex; gap: 10px; padding: 10px; border-radius: var(--r-sm); background: var(--bad-soft); color: var(--text); font-size: 12.5px; }
  .warnbox :global(svg) { color: var(--bad); flex: none; margin-top: 1px; }
  .ck { display: flex; gap: 6px; align-items: center; margin-top: 6px; }
  .tr { display: flex; align-items: center; gap: 10px; }
  .ok { color: var(--good); display: inline-flex; align-items: center; gap: 4px; }
  .bad { color: var(--bad); }
  .link { background: none; border: 0; color: var(--accent); cursor: pointer; padding: 0; font: inherit; text-align: left; }
  .mono { font-family: var(--mono); }
  .sa { font-size: 11.5px; }
  .pj { border: 1px solid var(--line-2); border-radius: var(--r); overflow: hidden; }
  .ps { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-bottom: 1px solid var(--line); color: var(--muted); }
  .ps .input { height: 28px; }
  .plist { max-height: 240px; overflow: auto; padding: 4px; }
  .pr { display: grid; grid-template-columns: auto minmax(0, 1fr) minmax(0, 1.2fr); gap: 8px; align-items: center; padding: 4px 6px; border-radius: 6px; font-size: 13px; cursor: pointer; }
  .pr:hover { background: var(--surface-2); }
</style>
