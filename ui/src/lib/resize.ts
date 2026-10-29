// Divisórias que se arrastam (lista × detalhe da PR, gaveta do diff): o tamanho fica guardado por chave no navegador.
// O mesmo jeito do Work.svelte: pointermove na janela e body.resizing enquanto arrasta (sem selecionar texto e sem o
// Monaco/terminal roubarem o ponteiro).
const PREFIX = "codeck.size.";

export function loadSize(key: string): number | null {
  try { const v = Number(localStorage.getItem(PREFIX + key)); return Number.isFinite(v) && v > 0 ? v : null; } catch { return null; }
}
export function saveSize(key: string, v: number) {
  try { localStorage.setItem(PREFIX + key, String(Math.round(v * 1000) / 1000)); } catch { /* sem armazenamento */ }
}
export function clearSize(key: string) {
  try { localStorage.removeItem(PREFIX + key); } catch { /* sem armazenamento */ }
}

/** Acompanha o arraste a partir do pointerdown: `onmove` recebe o X do ponteiro; `onend` quando solta. */
export function dragX(e: PointerEvent, onmove: (x: number) => void, onend: () => void) {
  if (e.button !== 0) return;
  e.preventDefault();
  const move = (ev: PointerEvent) => onmove(ev.clientX);
  const up = () => {
    window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
    document.body.classList.remove("resizing");
    onend();
  };
  document.body.classList.add("resizing");
  window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
}
