// Ícones de arquivo e pasta do explorador, das abas e do controle de código-fonte.
// Sem tema de ícones: um conjunto embutido (ícone por tipo, colorido pela linguagem). Com um tema de ícones de uma
// extensão do VS Code (Material Icon Theme, vscode-icons, Seti…): segue as regras do próprio tema — fileNames,
// fileExtensions (a mais longa primeiro: "d.ts" antes de "ts"), languageIds, folderNames e o padrão — com ícones SVG
// ou glifos de fonte. Os arquivos do tema vêm do backend (com a chave da execução) e viram blob: URLs na hora.
import { Braces, Database, File, FileArchive, FileCode2, FileCog, FileDiff, FileImage, FileKey, FileLock, FileSpreadsheet, FileTerminal,
  FileText, FileType, FileVideo, Folder, FolderCog, FolderGit2, FolderOpen, FolderRoot, Package, TestTube2 } from "@lucide/svelte";

export type IconRes = { kind: "builtin"; icon: any; color: string } | { kind: "img"; url: string } | { kind: "glyph"; char: string; color?: string; font: string; size?: string };

// ------------------------------------------------------------ embutido
const LANG_COLOR: Record<string, string> = {
  ts: "#3178c6", tsx: "#3178c6", mts: "#3178c6", cts: "#3178c6", js: "#e8c547", jsx: "#e8c547", mjs: "#e8c547", cjs: "#e8c547",
  cs: "#9b6bdf", csx: "#9b6bdf", vb: "#5f7fdb", fs: "#4fa6d9", cshtml: "#9b6bdf", razor: "#9b6bdf", xaml: "#5ea2e8",
  py: "#4b8bbe", go: "#29beb0", rs: "#e2703a", java: "#e76f00", kt: "#a97bff", swift: "#f05138", rb: "#d9443a", php: "#8892bf",
  c: "#5c8dbc", h: "#a074c4", cpp: "#f34b7d", hpp: "#a074c4", dart: "#40c4ff", lua: "#5f7fdb", r: "#4a90d9", scala: "#dc322f",
  html: "#e5532d", htm: "#e5532d", css: "#4b8bd6", scss: "#cd6799", sass: "#cd6799", less: "#5a7fc0", svelte: "#ff3e00", vue: "#41b883", astro: "#ff5d01",
  sh: "#89e051", bash: "#89e051", zsh: "#89e051", ps1: "#5391fe", psm1: "#5391fe", bat: "#c1f12e", cmd: "#c1f12e",
  sql: "#e38c00", graphql: "#e535ab", gql: "#e535ab", proto: "#6aa84f",
};
const BY_EXT: Record<string, [any, string]> = {
  json: [Braces, "#e8c547"], jsonc: [Braces, "#e8c547"], json5: [Braces, "#e8c547"],
  md: [FileText, "#4fa6d9"], mdx: [FileText, "#4fa6d9"], markdown: [FileText, "#4fa6d9"], txt: [FileText, "#9aa4b2"], rst: [FileText, "#9aa4b2"], log: [FileText, "#7d869b"],
  png: [FileImage, "#b07cff"], jpg: [FileImage, "#b07cff"], jpeg: [FileImage, "#b07cff"], gif: [FileImage, "#b07cff"], svg: [FileImage, "#ffb13b"],
  webp: [FileImage, "#b07cff"], ico: [FileImage, "#b07cff"], bmp: [FileImage, "#b07cff"], icns: [FileImage, "#b07cff"],
  mp4: [FileVideo, "#ff6b7d"], mov: [FileVideo, "#ff6b7d"], webm: [FileVideo, "#ff6b7d"],
  zip: [FileArchive, "#c9a26b"], gz: [FileArchive, "#c9a26b"], tgz: [FileArchive, "#c9a26b"], rar: [FileArchive, "#c9a26b"], "7z": [FileArchive, "#c9a26b"], nupkg: [Package, "#5f7fdb"],
  csv: [FileSpreadsheet, "#3ccf91"], tsv: [FileSpreadsheet, "#3ccf91"], xlsx: [FileSpreadsheet, "#21a366"], xls: [FileSpreadsheet, "#21a366"],
  ttf: [FileType, "#ff8a50"], otf: [FileType, "#ff8a50"], woff: [FileType, "#ff8a50"], woff2: [FileType, "#ff8a50"],
  lock: [FileLock, "#7d869b"], pem: [FileKey, "#e8c547"], key: [FileKey, "#e8c547"], pfx: [FileKey, "#e8c547"], snk: [FileKey, "#e8c547"],
  patch: [FileDiff, "#3ccf91"], diff: [FileDiff, "#3ccf91"],
  yml: [FileCog, "#cb5b7b"], yaml: [FileCog, "#cb5b7b"], toml: [FileCog, "#9c4221"], ini: [FileCog, "#9aa4b2"], cfg: [FileCog, "#9aa4b2"], conf: [FileCog, "#9aa4b2"],
  xml: [FileCode2, "#e5532d"], config: [FileCog, "#9b6bdf"], props: [FileCog, "#9b6bdf"], targets: [FileCog, "#9b6bdf"], editorconfig: [FileCog, "#9aa4b2"],
  sln: [FileCog, "#9b6bdf"], slnx: [FileCog, "#9b6bdf"], csproj: [FileCog, "#9b6bdf"], vbproj: [FileCog, "#5f7fdb"], fsproj: [FileCog, "#4fa6d9"],
  sqlproj: [Database, "#e38c00"], db: [Database, "#e38c00"], sqlite: [Database, "#e38c00"], sql: [Database, "#e38c00"],
  sh: [FileTerminal, "#89e051"], bash: [FileTerminal, "#89e051"], zsh: [FileTerminal, "#89e051"], ps1: [FileTerminal, "#5391fe"], bat: [FileTerminal, "#c1f12e"], cmd: [FileTerminal, "#c1f12e"],
  exe: [FileCog, "#7d869b"], dll: [FileCog, "#7d869b"], pdb: [FileCog, "#7d869b"],
};
const BY_NAME: Record<string, [any, string]> = {
  "package.json": [Package, "#3ccf91"], "package-lock.json": [FileLock, "#7d869b"], "pnpm-lock.yaml": [FileLock, "#7d869b"], "yarn.lock": [FileLock, "#7d869b"],
  dockerfile: [FileCog, "#2496ed"], "docker-compose.yml": [FileCog, "#2496ed"], "docker-compose.yaml": [FileCog, "#2496ed"], "compose.yml": [FileCog, "#2496ed"],
  ".gitignore": [FileCog, "#f05033"], ".gitattributes": [FileCog, "#f05033"], ".gitmodules": [FileCog, "#f05033"], ".dockerignore": [FileCog, "#2496ed"],
  ".env": [FileKey, "#e8c547"], ".env.local": [FileKey, "#e8c547"], ".env.example": [FileKey, "#9aa4b2"], ".npmrc": [FileCog, "#cb3837"], ".nvmrc": [FileCog, "#3ccf91"],
  license: [FileText, "#e8c547"], "license.md": [FileText, "#e8c547"], "readme.md": [FileText, "#4fa6d9"], makefile: [FileTerminal, "#e38c00"],
  "tsconfig.json": [FileCog, "#3178c6"], "jsconfig.json": [FileCog, "#e8c547"], "nuget.config": [Package, "#5f7fdb"], "global.json": [FileCog, "#9b6bdf"],
  "launchsettings.json": [FileCog, "#9b6bdf"], "appsettings.json": [FileCog, "#9b6bdf"], "web.config": [FileCog, "#9b6bdf"], "app.config": [FileCog, "#9b6bdf"],
  "packages.config": [Package, "#5f7fdb"], "vite.config.ts": [FileCog, "#a47bff"], "svelte.config.js": [FileCog, "#ff3e00"],
};
const FOLDER: Record<string, [any, string]> = {
  ".git": [FolderGit2, "#f05033"], ".github": [FolderGit2, "#9aa4b2"], ".vscode": [FolderCog, "#3b99d4"], ".idea": [FolderCog, "#9aa4b2"], ".vs": [FolderCog, "#9b6bdf"],
  node_modules: [Package, "#3ccf91"], packages: [Package, "#5f7fdb"], src: [FolderRoot, "#6f8cff"], test: [TestTube2, "#3ccf91"], tests: [TestTube2, "#3ccf91"],
  __tests__: [TestTube2, "#3ccf91"], spec: [TestTube2, "#3ccf91"], properties: [FolderCog, "#9b6bdf"], scripts: [FolderCog, "#89e051"],
};

function builtin(name: string, dir: boolean, open: boolean): IconRes {
  const n = name.toLowerCase();
  if (dir) {
    const f = FOLDER[n];
    if (f) return { kind: "builtin", icon: f[0], color: f[1] };
    return { kind: "builtin", icon: open ? FolderOpen : Folder, color: "#8a94a8" };
  }
  const byName = BY_NAME[n];
  if (byName) return { kind: "builtin", icon: byName[0], color: byName[1] };
  if (n.startsWith(".env")) return { kind: "builtin", icon: FileKey, color: "#e8c547" };
  if (n.startsWith("dockerfile")) return { kind: "builtin", icon: FileCog, color: "#2496ed" };
  const ext = n.includes(".") ? n.slice(n.lastIndexOf(".") + 1) : "";
  if (n.endsWith(".d.ts")) return { kind: "builtin", icon: FileCode2, color: "#5a9bd5" };
  if (/\.(test|spec)\.[jt]sx?$/.test(n)) return { kind: "builtin", icon: TestTube2, color: "#3ccf91" };
  const byExt = BY_EXT[ext];
  if (byExt) return { kind: "builtin", icon: byExt[0], color: byExt[1] };
  const lc = LANG_COLOR[ext];
  if (lc) return { kind: "builtin", icon: FileCode2, color: lc };
  return { kind: "builtin", icon: File, color: "#7d869b" };
}

// ------------------------------------------------------------ tema de ícones de extensão do VS Code
type Def = { iconPath?: string; fontCharacter?: string; fontColor?: string; fontSize?: string; fontId?: string };
type Section = { file?: string; folder?: string; folderExpanded?: string; fileExtensions?: Record<string, string>; fileNames?: Record<string, string>;
  folderNames?: Record<string, string>; folderNamesExpanded?: Record<string, string>; languageIds?: Record<string, string> };
type ThemeJson = Section & { iconDefinitions: Record<string, Def>; fonts?: { id: string; src: { path: string; format: string }[]; size?: string; weight?: string; style?: string }[];
  light?: Section; hidesExplorerArrows?: boolean };

export interface IconSource {
  id: string; label: string;
  /** lê um arquivo do tema (relativo à pasta do JSON) — texto ou binário */
  blob(rel: string): Promise<Blob>;
}

/** extensão → languageId do VS Code (para os temas que mapeiam por linguagem) */
const LANG_OF: Record<string, string> = {
  ts: "typescript", tsx: "typescriptreact", js: "javascript", jsx: "javascriptreact", mjs: "javascript", cjs: "javascript", cs: "csharp",
  py: "python", go: "go", rs: "rust", java: "java", json: "json", jsonc: "jsonc", md: "markdown", html: "html", css: "css", scss: "scss",
  less: "less", yml: "yaml", yaml: "yaml", xml: "xml", sql: "sql", sh: "shellscript", ps1: "powershell", php: "php", rb: "ruby",
  c: "c", h: "c", cpp: "cpp", hpp: "cpp", vb: "vb", fs: "fsharp", swift: "swift", kt: "kotlin", dart: "dart", lua: "lua", r: "r",
  svelte: "svelte", vue: "vue", bat: "bat", dockerfile: "dockerfile", razor: "aspnetcorerazor", cshtml: "aspnetcorerazor", xaml: "xml",
};

class IconTheme {
  private urls = new Map<string, string>();
  private loading = new Set<string>();
  fontFamily: Record<string, string> = {};
  constructor(public src: IconSource, public json: ThemeJson, public light: boolean) {}

  private section(): Section {
    const j = this.json, l = this.light ? j.light || {} : {};
    return {
      file: l.file || j.file, folder: l.folder || j.folder, folderExpanded: l.folderExpanded || j.folderExpanded,
      fileExtensions: { ...(j.fileExtensions || {}), ...(l.fileExtensions || {}) }, fileNames: { ...(j.fileNames || {}), ...(l.fileNames || {}) },
      folderNames: { ...(j.folderNames || {}), ...(l.folderNames || {}) }, folderNamesExpanded: { ...(j.folderNamesExpanded || {}), ...(l.folderNamesExpanded || {}) },
      languageIds: { ...(j.languageIds || {}), ...(l.languageIds || {}) },
    };
  }
  private sec: Section | null = null;
  idFor(name: string, dir: boolean, open: boolean): string | undefined {
    const s = (this.sec ||= this.section());
    const n = name.toLowerCase();
    if (dir) return (open ? s.folderNamesExpanded?.[n] || s.folderNamesExpanded?.[name] : undefined) || s.folderNames?.[n] || s.folderNames?.[name]
      || (open ? s.folderExpanded || s.folder : s.folder);
    const byName = s.fileNames?.[n] ?? s.fileNames?.[name];
    if (byName) return byName;
    const parts = n.split(".");
    for (let i = 1; i < parts.length; i++) {
      const ext = parts.slice(i).join(".");
      const id = s.fileExtensions?.[ext];
      if (id) return id;
    }
    const lang = LANG_OF[parts.length > 1 ? parts[parts.length - 1] : n];
    return (lang && s.languageIds?.[lang]) || s.file;
  }
  resolve(name: string, dir: boolean, open: boolean): IconRes | null {
    const id = this.idFor(name, dir, open);
    const d = id ? this.json.iconDefinitions?.[id] : undefined;
    if (!d) return null;
    if (d.iconPath) {
      const u = this.urls.get(d.iconPath);
      if (u) return { kind: "img", url: u };
      this.fetch(d.iconPath);
      return null;   // enquanto carrega, o embutido aparece; o tema troca assim que chegar
    }
    if (d.fontCharacter) {
      const fid = d.fontId || this.json.fonts?.[0]?.id || "";
      const fam = this.fontFamily[fid];
      if (!fam) return null;
      const ch = d.fontCharacter.startsWith("\\") ? String.fromCodePoint(parseInt(d.fontCharacter.slice(1), 16)) : d.fontCharacter;
      return { kind: "glyph", char: ch, color: d.fontColor, font: fam, size: d.fontSize || this.json.fonts?.find(f => f.id === fid)?.size };
    }
    return null;
  }
  private fetch(rel: string) {
    if (this.loading.has(rel)) return;
    this.loading.add(rel);
    this.src.blob(rel).then(b => {
      // SVG sem tipo vira imagem quebrada: garante o MIME
      const blob = rel.toLowerCase().endsWith(".svg") && b.type !== "image/svg+xml" ? new Blob([b], { type: "image/svg+xml" }) : b;
      this.urls.set(rel, URL.createObjectURL(blob));
      icons.bump();
    }).catch(() => { /* ícone faltando no tema: fica o embutido */ });
  }
  async loadFonts() {
    for (const f of this.json.fonts || []) {
      const s = f.src?.[0];
      if (!s) continue;
      try {
        const buf = await (await this.src.blob(s.path)).arrayBuffer();
        const fam = `cdicon-${this.src.id}-${f.id}`.replace(/[^\w-]/g, "_");
        const face = new FontFace(fam, buf, { weight: f.weight || "normal", style: f.style || "normal" });
        await face.load();
        (document as any).fonts.add(face);
        this.fontFamily[f.id] = fam;
      } catch { /* fonte do tema não carregou: ícones de glifo caem no embutido */ }
    }
  }
  dispose() { for (const u of this.urls.values()) URL.revokeObjectURL(u); }
}

class Icons {
  /** muda quando um ícone do tema termina de carregar: quem desenha relê */
  version = $state(0);
  theme = $state<IconTheme | null>(null);
  hidesArrows = $state(false);
  private pending = false;
  bump() { if (this.pending) return; this.pending = true; requestAnimationFrame(() => { this.pending = false; this.version++; }); }

  async use(src: IconSource | null, json?: ThemeJson) {
    this.theme?.dispose();
    if (!src || !json) { this.theme = null; this.hidesArrows = false; this.version++; return; }
    const light = document.documentElement.dataset.theme === "light";
    const t = new IconTheme(src, json, light);
    await t.loadFonts();
    this.theme = t;
    this.hidesArrows = !!json.hidesExplorerArrows;
    this.version++;
  }
  resolve(name: string, dir = false, open = false): IconRes {
    void this.version;
    return this.theme?.resolve(name, dir, open) || builtin(name, dir, open);
  }
}

export const icons = new Icons();
