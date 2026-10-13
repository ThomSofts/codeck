import { get, post } from "./api";
import type { AccountColl, Catalog, FavRepo, LocalRepo, RemoteRepo, Tag } from "./types";

export type TrackCat = "prs" | "builds" | "deploys" | "issues";
export interface TrackRepo { track?: boolean; prs?: boolean; builds?: boolean; deploys?: boolean; issues?: boolean; notify?: boolean; note?: string }
export interface Tracking { accounts: Record<string, { mode: "all" | "selected" }>; repos: Record<string, TrackRepo> }
/** Acompanhamento efetivo de um repositório (modo da conta + o que foi marcado nele). */
export interface TrackState { on: boolean; explicit: boolean; mode: "all" | "selected"; prs: boolean; builds: boolean; deploys: boolean; issues: boolean; notify: boolean; note: string }

// Repositórios locais, catálogos e favoritos: carregados à parte do /api/state (o status de cada repo custa um `git status`).
class Repos {
  local = $state<LocalRepo[]>([]);
  catalogs = $state<Catalog[]>([]);
  /** contas conectadas, cada uma com todos os repositórios dela */
  accounts = $state<AccountColl[]>([]);
  favorites = $state<FavRepo[]>([]);
  tags = $state<Tag[]>([]);
  loaded = $state(false);
  tracking = $state<Tracking>({ accounts: {}, repos: {} });
  /** pedido para abrir o "Criar PR" ao entrar na tela do repositório (vem da tarefa) */
  prIntent = $state<string | null>(null);
  private inflight: Promise<void> | null = null;

  get pinned() { return this.local.filter(r => r.pinned); }
  byId(id: string) { return this.local.find(r => r.id === id); }

  load(withStatus = true): Promise<void> {
    if (this.inflight) return this.inflight;
    this.inflight = Promise.all([get<{ repos: LocalRepo[] }>("repos", { status: withStatus ? 1 : 0 }), get<{ catalogs: Catalog[]; accounts: AccountColl[] }>("catalogs"),
      get<{ repos: FavRepo[]; tags: Tag[] }>("library"), get<Tracking>("tracking").catch(() => this.tracking)])
      .then(([r, c, l, t]) => { this.local = r.repos; this.catalogs = c.catalogs; this.accounts = c.accounts; this.favorites = l.repos; this.tags = l.tags; this.tracking = t; this.loaded = true; })
      .finally(() => (this.inflight = null));
    return this.inflight;
  }
  async loadLibrary() {
    const l = await get<{ repos: FavRepo[]; tags: Tag[] }>("library");
    this.favorites = l.repos;
    this.tags = l.tags;
  }

  // ---------------------------------------------------------------- acompanhamento (PRs, builds, deploys, issues)
  trackMode(accountKey?: string | null): "all" | "selected" { return (accountKey && this.tracking.accounts[accountKey]?.mode) || "all"; }
  /** Conta dona de um repositório local pelo remoto: "github:<login conectado>" ou "azure:<org conectada>". */
  accountOf(r: { provider?: string | null; slug?: string | null; accountKey?: string; owner?: string }): string | null {
    if ((r as any).accountKey) return (r as any).accountKey;
    if (!r.provider) return null;
    const owner = (r.slug || r.owner || "").split("/")[0].toLowerCase();
    const same = this.accounts.filter(a => a.provider === r.provider);
    return (same.find(a => a.name.toLowerCase() === owner) || same[0])?.key || null;
  }
  track(key: string | null | undefined, accountKey?: string | null): TrackState {
    const mode = this.trackMode(accountKey);
    const r = (key && this.tracking.repos[key.toLowerCase()]) || {};
    const on = r.track !== undefined ? r.track : mode === "all";
    return { on, explicit: r.track !== undefined, mode, prs: r.prs !== false, builds: r.builds !== false, deploys: r.deploys !== false,
      issues: r.issues !== false, notify: r.notify !== false, note: r.note || "" };
  }
  async setTrack(key: string, patch: Partial<TrackRepo> & { reset?: boolean }) {
    const k = key.toLowerCase(), before = this.tracking;
    const cur = { ...(this.tracking.repos[k] || {}), ...patch };
    delete (cur as any).reset;
    this.tracking = { ...this.tracking, repos: { ...this.tracking.repos, [k]: patch.reset ? {} : cur } };   // otimista
    try { await post("tracking/repo", { key: k, ...patch }); this.tracking = await get<Tracking>("tracking"); }
    catch (e) { this.tracking = before; throw e; }
  }
  async setTrackMany(keys: string[], track: boolean) {
    await post("tracking/many", { keys, track });
    this.tracking = await get<Tracking>("tracking");
  }
  async setTrackMode(accountKey: string, mode: "all" | "selected") {
    this.tracking = { ...this.tracking, accounts: { ...this.tracking.accounts, [accountKey]: { mode } } };
    await post("tracking/account", { key: accountKey, mode });
    this.tracking = await get<Tracking>("tracking");
  }

  // ---------------------------------------------------------------- favoritos
  /** Chave do favorito: a do remoto normalizado (casa catálogo, busca e clone local); sem remoto, "local:<id>". */
  keyOf(r: RemoteRepo | LocalRepo | FavRepo): string {
    if ("tags" in r && r.key) return r.key;
    if ("remoteKey" in r && r.remoteKey) return r.remoteKey;
    if ("path" in r) return "local:" + r.id;
    return (r as RemoteRepo).key;
  }
  fav(key: string) { return this.favorites.find(f => f.key === key); }
  tag(name: string) { return this.tags.find(t => t.name === name); }

  async setFavorite(r: RemoteRepo | LocalRepo | FavRepo, on: boolean, tags: string[] = []) {
    const key = this.keyOf(r);
    // otimista: a estrela acende na hora; a resposta do backend confirma (ou desfaz)
    const before = this.favorites;
    if (!on) this.favorites = this.favorites.filter(f => f.key !== key);
    else if (!this.fav(key)) this.favorites = [...this.favorites, { ...(r as any), key, tags, cloned: !!(r as any).cloned || "path" in r, local: (r as any).local ?? null } as FavRepo];
    try {
      const snap = "path" in r ? { key: r.remoteKey ? undefined : key, remoteKey: r.remoteKey || undefined, provider: r.provider, name: r.name,
        fullName: r.slug || r.name, remoteUrl: r.remoteUrl, webUrl: r.webUrl, owner: r.slug?.split("/").slice(0, -1).join("/") } : r;
      await post("library/favorite", { repo: snap, on, tags });
      await this.loadLibrary();
    } catch (e) { this.favorites = before; throw e; }
  }

  async setTags(key: string, tags: string[]) {
    const f = this.fav(key);
    if (f) f.tags = tags;   // otimista
    try { await post("library/tags", { key, tags }); }
    finally { await this.loadLibrary(); }
  }
}

export const repos = new Repos();
