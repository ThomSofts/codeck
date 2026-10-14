// Diff de linhas (Myers, O(ND)) entre o arquivo no último commit e o que está no editor — vira as marcas da margem
// (verde = linhas novas, azul = alteradas, triângulo vermelho = linhas apagadas), como o "dirty diff" do VS Code.

export type Hunk = { kind: "add" | "mod" | "del"; start: number; end: number };   // linhas 1-based no texto NOVO (del: start=end=linha após a remoção)

/** Edições mínimas entre a e b (como pares [i, j] alinhados), ou null se passar do limite de esforço. */
function lcsPairs(a: string[], b: string[], maxD = 4000): [number, number][] | null {
  const n = a.length, m = b.length, max = n + m;
  const off = max + 1;
  const v = new Int32Array(2 * max + 3);
  const trace: Int32Array[] = [];
  for (let d = 0; d <= Math.min(max, maxD); d++) {
    trace.push(v.slice());
    for (let k = -d; k <= d; k += 2) {
      let x = k === -d || (k !== d && v[off + k - 1] < v[off + k + 1]) ? v[off + k + 1] : v[off + k - 1] + 1;
      let y = x - k;
      while (x < n && y < m && a[x] === b[y]) { x++; y++; }
      v[off + k] = x;
      if (x >= n && y >= m) {
        // reconstrói o caminho
        const pairs: [number, number][] = [];
        let cx = n, cy = m;
        for (let dd = d; dd > 0; dd--) {
          const vv = trace[dd];
          const kk = cx - cy;
          const prevK = kk === -dd || (kk !== dd && vv[off + kk - 1] < vv[off + kk + 1]) ? kk + 1 : kk - 1;
          const px = vv[off + prevK], py = px - prevK;
          while (cx > px && cy > py) { pairs.push([cx - 1, cy - 1]); cx--; cy--; }
          cx = px; cy = py;
        }
        while (cx > 0 && cy > 0) { pairs.push([cx - 1, cy - 1]); cx--; cy--; }
        return pairs.reverse();
      }
    }
  }
  return null;
}

export function lineHunks(oldText: string, newText: string): Hunk[] {
  if (oldText === newText) return [];
  const a = oldText.split(/\r?\n/), b = newText.split(/\r?\n/);
  if (a.length + b.length > 60000) return [];
  // corta o começo e o fim iguais (o caso comum: poucas linhas mudadas num arquivo grande)
  let pre = 0;
  while (pre < a.length && pre < b.length && a[pre] === b[pre]) pre++;
  let suf = 0;
  while (suf < a.length - pre && suf < b.length - pre && a[a.length - 1 - suf] === b[b.length - 1 - suf]) suf++;
  const am = a.slice(pre, a.length - suf), bm = b.slice(pre, b.length - suf);
  const pairs = lcsPairs(am, bm);
  if (!pairs) return [{ kind: "mod", start: pre + 1, end: Math.max(pre + 1, b.length - suf) }];
  const out: Hunk[] = [];
  let i = 0, j = 0;
  const flush = (ai: number, aj: number) => {
    const delN = ai - i, addN = aj - j;
    if (delN && addN) out.push({ kind: "mod", start: pre + j + 1, end: pre + aj });
    else if (addN) out.push({ kind: "add", start: pre + j + 1, end: pre + aj });
    else if (delN) out.push({ kind: "del", start: pre + j + 1, end: pre + j + 1 });
  };
  for (const [pi, pj] of pairs) { if (pi > i || pj > j) flush(pi, pj); i = pi + 1; j = pj + 1; }
  if (i < am.length || j < bm.length) flush(am.length, bm.length);
  return out;
}
