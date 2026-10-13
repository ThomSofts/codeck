import { ui } from "./ui.svelte";

// Cliente da API local. A chave da execução vem do app nativo (window.CODECK_TOKEN); sem ela o backend recusa.
declare global {
  interface Window { CODECK_TOKEN?: string; CODECK_PLATFORM?: string; openTarget?: (t: string) => void; checkUpdate?: (m?: boolean) => void;
    __nativeResolve?: (id: string, value: string | null) => void; webkit?: any; chrome?: any }
}

const headers = () => ({ "X-Codeck-Token": window.CODECK_TOKEN || "" });

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function handle<T>(r: Response): Promise<T> {
  const text = await r.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* resposta não-JSON */ }
  if (!r.ok) throw new ApiError(data?.error || text || `HTTP ${r.status}`, r.status);
  return data as T;
}

export function get<T = any>(path: string, params?: Record<string, string | number | boolean | null | undefined>): Promise<T> {
  const qs = params ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => [k, String(v)])).toString() : "";
  return fetch(`/api/${path}${qs}`, { headers: headers() }).then(r => handle<T>(r));
}

// Rotas que criam terminal levam o tamanho do painel: o programa já nasce do tamanho certo (lib: Terminal.svelte)
const TERM_ROUTES = /^ws\/(agent|shell|task|run)$/;
let sizeHint: (() => { cols: number; rows: number } | null) | null = null;
export function setTermSizeHint(fn: typeof sizeHint) { sizeHint = fn; }

/** Envio de ação. Conta como "em andamento" até responder, o que acende a barra de progresso do topo. */
export function post<T = any>(path: string, body: unknown = {}): Promise<T> {
  if (sizeHint && TERM_ROUTES.test(path) && body && typeof body === "object" && !("cols" in body)) {
    const sz = sizeHint();
    if (sz) body = { ...body, ...sz };
  }
  ui.inflight++;
  return fetch(`/api/${path}`, {
    method: "POST", headers: { ...headers(), "Content-Type": "application/json", "X-Codeck": "1" }, body: JSON.stringify(body),
  }).then(r => handle<T>(r)).finally(() => ui.inflight--);
}
