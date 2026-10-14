// Tema de cores de extensão ativo, no que outras partes precisam sem importar o carregador inteiro (o terminal lê as
// cores terminal.* dele). Quem troca o tema marca data-ext-theme no <html> para todo mundo repintar.
export type TermTheme = Record<string, string>;
let terminal: TermTheme | null = null;
export const extTerminal = () => terminal;
export function setExtTerminal(t: TermTheme | null) { terminal = t; }
