import { ui } from "./ui.svelte";

// Cliente da API local. A chave da execução vem do app nativo (window.CODECK_TOKEN); sem ela o backend recusa.
declare global {
  interface Window { CODECK_TOKEN?: string; CODECK_PLATFORM?: string; openTarget?: (t: string) => void; checkUpdate?: (m?: boolean) => void;
    __nativeResolve?: (id: string, value: string | null) => void; webkit?: any; chrome?: any }
}

const headers = () => ({ "X-Codeck-Token": window.CODECK_TOKEN || "" });

export class ApiError extends Error {
  constructor(message: string, public status: number, public data: any = null) { super(message); }
}

async function handle<T>(r: Response): Promise<T> {
  const text = await r.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* resposta não-JSON */ }
  if (!r.ok) throw new ApiError(data?.error || text || `HTTP ${r.status}`, r.status, data);
  return data as T;
}

export function get<T = any>(path: string, params?: Record<string, string | number | boolean | null | undefined>): Promise<T> {
  const qs = params ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => [k, String(v)])).toString() : "";
  return fetch(`/api/${path}${qs}`, { headers: headers() }).then(r => handle<T>(r));
}

// Rotas que criam terminal levam o tamanho do painel: o programa já nasce do tamanho certo (lib: Terminal.svelte)
const TERM_ROUTES = /^(ws\/(agent|shell|task|run)|pr\/fix)$/;
let sizeHint: (() => { cols: number; rows: number } | null) | null = null;
export function setTermSizeHint(fn: typeof sizeHint) { sizeHint = fn; }

/** Envio de ação. Conta como "em andamento" até responder, o que acende a barra de progresso do topo — menos os envios
 *  de fundo (quiet: pulso de tempo de uso, preferências), que não são ação sua e não devem piscar o topo. */
export function post<T = any>(path: string, body: unknown = {}, opts: { quiet?: boolean } = {}): Promise<T> {
  return send<T>(path, body, opts).catch(async e => {
    if (!(e instanceof ApiError) || e.status !== 409 || !e.data?.trust) throw e;
    if (!(await askTrust(e.data.trust))) throw e;
    return send<T>(path, body, opts);   // confiou: repete o pedido uma vez
  });
}

/** Projeto ainda não confiável: o pedido rodaria algo do repositório (launch.json, build, preparação…). */
async function askTrust(t: { repoId: string; repoName: string; what: string }): Promise<boolean> {
  const r = await ui.ask({
    title: `Confiar no projeto ${t.repoName}?`,
    message: `Isto vai executar ${t.what}, que vem do repositório. Só confie se você conhece a origem do código — um clone ` +
      "novo ou a PR de outra pessoa pode trazer comandos maliciosos.",
    confirm: "Confiar e continuar", check: "Não perguntar novamente (confiar em todos os projetos)",
  });
  if (!r) return false;
  await send(r === "check" ? "trust/all" : "trust", r === "check" ? { all: true } : { repoId: t.repoId, trusted: true }, {});
  return true;
}

function send<T>(path: string, body: unknown, opts: { quiet?: boolean }): Promise<T> {
  if (sizeHint && TERM_ROUTES.test(path) && body && typeof body === "object" && !("cols" in body)) {
    const sz = sizeHint();
    if (sz) body = { ...body, ...sz };
  }
  if (!opts.quiet) ui.inflight++;
  return fetch(`/api/${path}`, {
    method: "POST", headers: { ...headers(), "Content-Type": "application/json", "X-Codeck": "1" }, body: JSON.stringify(body),
  }).then(r => handle<T>(r)).finally(() => { if (!opts.quiet) ui.inflight--; });
}
