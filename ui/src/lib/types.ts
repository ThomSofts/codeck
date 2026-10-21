// Formatos que o backend devolve (backend/pilot). Azure e GitHub usam os mesmos campos; `provider` diz a origem.
export type Provider = "azure" | "github";

export interface Reviewer { name: string; vote: number; required: boolean; id?: string }
export interface Policy { name: string; type: string; status: string; blocking: boolean }

export interface PR {
  key: string; provider: Provider; account?: string; org: string; project: string; repo: string; repoId: string;
  prId: number; title: string; description: string; creatorName: string; creatorUnique: string; creatorAvatar?: string;
  source: string; target: string; isDraft: boolean; created: string; mergeStatus?: string; commit?: string;
  autoComplete: boolean; reviewers: Reviewer[]; url: string; myVote: number; approvals: number; policies: Policy[];
  build: "ok" | "failed" | "running" | "pending" | "none"; archived?: boolean; rule?: number | null; ruleId?: string | null;
  waiting?: string | null; reviewRequested?: boolean; blockers?: { code: string; label: string }[]; repoKey?: string | null; quiet?: boolean;
}

export interface Build {
  key: string; provider: Provider; account?: string; org: string; project: string; id: number; number: string;
  pipeline: string; pipelineId: number; folder: string; branch: string; sourceBranch: string; sourceVersion?: string;
  status: string; result: string | null; reason: string; requestedFor: string; requestedForId?: string; requestedForAvatar?: string;
  queued: string; started?: string; finished?: string; message: string; prNumber?: number | null; repo?: string; url: string;
  waiting?: boolean; attempt?: number; repoKey?: string | null; quiet?: boolean;
  /** só em andamento: o que está acontecendo de verdade (timeline do Azure / jobs do GitHub) */
  phase?: { state: "failing" | "approval" | "check" | "agent" | "running"; label: string; stage?: string | null; job?: string | null; since?: string | null } | null;
}

export interface Deploy {
  key: string; provider: Provider; kind: "release" | "approval" | "permission"; org: string; project: string;
  title: string; pipeline: string; stage: string; branch?: string; version?: string; buildId?: number; message?: string;
  prNumber?: number | null; prUrl?: string | null; repo?: string; requestedFor?: string; approver?: string; mine: boolean;
  created: string; resources: { type: string; id: string; name: string }[]; url: string; ruleId?: string | null;
  ruleName?: string | null; waiting?: string | null; otherApprovers?: string[]; releaseName?: string; approvalType?: string; repoKey?: string | null; quiet?: boolean;
}

export interface Release {
  provider: Provider; org: string; id: number; name: string; pipeline: string; created: string; createdBy: string;
  branch: string; version: string; envs: { name: string; status: string }[]; url: string;
}

export interface Issue {
  key: string; provider: Provider; org: string; repo: string; number: number; title: string; state: string; type: string;
  updated: string; author: string; labels: { name: string; color: string | null }[]; assignees?: { login: string; avatar: string | null; email?: string }[];
  comments: number | null; reason: string; reasons?: string[]; url: string; repoKey?: string | null; account?: string | null;
  /** repositório (ou projeto do Azure, para work items) que liga/desliga este item no acompanhamento */
  scopeKey?: string | null;
}

export interface Activity {
  ts: string; by: string; action: string; vote?: number | null; detail?: string | null; kind?: string; provider?: string;
  org: string; title: string; prId?: number | null; key?: string; url?: string | null; creatorName?: string; target?: string;
  pipeline?: string; stage?: string; branch?: string; version?: string; prNumber?: number; ruleId?: string;
}

export interface Rule {
  id: string; name: string; enabled: boolean; action: "approve" | "archive" | "notify"; orgs: string[]; creators: string[];
  targets: string[]; repos: string[]; titleContains: string; requireBuild: boolean;
}
export interface DeployRule {
  id: string; name: string; enabled: boolean; kind: "release" | "permission"; action: "approve" | "notify"; orgs: string[];
  pipelines: string[]; stages: string[]; branches: string[]; resources: string[]; requirePrApproved: boolean;
}
export interface RulesCfg {
  protectedTargets: string[]; settings: Record<string, boolean>; rules: Rule[]; deployRules: DeployRule[];
}

export type Source = "prs" | "builds" | "deploys" | "issues";

/** Acompanhar em cascata (backend/pilot/cascade.py): PR aprovada → merge → build → deploy. */
export type CascadeStatus = "pending" | "waiting" | "running" | "done" | "failed" | "skipped";
export interface CascadeStep { status: CascadeStatus; label: string; url: string | null; at: string | null;
  parts: { name: string; status: CascadeStatus; url?: string | null }[] }
export interface CascadeItem {
  key: string; provider: Provider; org: string; project: string; repo: string; prId: number; title: string; url: string;
  source: string; target: string; by: "manual" | "approve" | "auto"; startedAt: string; updatedAt: string; finishedAt?: string;
  stage: "merge" | "build" | "deploy" | "finished"; result: null | "succeeded" | "failed" | "abandoned" | "timeout";
  commit: string | null; error: string | null; steps: Record<"approved" | "merge" | "build" | "deploy", CascadeStep>;
}
export interface AppState {
  prs: PR[]; myPrs: PR[]; builds: Build[]; deploys: Deploy[]; releases: Release[]; issues: Issue[];
  errors: Record<string, string>; buildErrors: Record<string, string>; deployErrors: Record<string, string>;
  issueErrors: Record<string, string>; lastPoll: string | null; lastDeployPoll: string | null; lastBuildPoll: string | null;
  lastIssuePoll: string | null; pollMs: number | null; me: Record<string, { id: string; name: string; email?: string; avatar?: string } | null>;
  orgs: string[]; githubAccounts: { id: string; login: string; avatar?: string }[]; sources: string[]; pollSeconds: number;
  editor: string; theme: "system" | "dark" | "light"; ui?: Record<string, any>; polling: string | null; offline: string | null;
  /** cada fonte lê no próprio ciclo: desde quando está lendo (null = parada) e quando terminou a última leitura */
  loading?: Partial<Record<Source, string | null>>; updated?: Partial<Record<Source, string | null>>;
  /** intervalo de cada fonte (s) e a próxima leitura agendada — com o motivo quando o app acelera ou espaça */
  pollIntervals?: Record<Source, number>;
  schedule?: Partial<Record<Source, { every: number; why: string; next: string }>> & {
    /** tempo real (local) — backend/pilot/watch.py: ritmo atual, repositórios vigiados, chamadas e 304 (grátis) no último minuto */
    live?: { on: boolean; every: number | null; why: string; repos: number; callsMin: number; freeMin: number; changes: number; lastChange: string | null } };
  cascade?: CascadeItem[]; rules: RulesCfg; archive: Record<string, any>; activity: Activity[]; creators: string[]; repos: string[];
  targets: string[]; ruleStats: Record<string, { count: number; last: string }>; configured: boolean;
  app: { version: string; build: number; platform: string; product: string };
  update: { available?: boolean; version?: string; build?: number; notes?: string; required?: boolean; disabled?: boolean; checkedAt?: string; error?: string; publishedAt?: string };
}

export interface RepoStatusShort { branch: string | null; upstream: string | null; ahead: number; behind: number; dirty: boolean;
  stashes: number; detached: boolean; operation: string | null; changes: number }
export interface LocalRepo {
  id: string; path: string; name: string; pinned: boolean; remoteUrl: string | null; remoteKey: string; provider?: Provider | null;
  slug?: string | null; webUrl?: string | null; exists: boolean; status?: RepoStatusShort; error?: string;
  lastCommit?: { sha: string; subject: string; author: string; date: string } | null;
}
export interface RemoteRepo {
  key: string; provider: Provider; account: string; owner: string; name: string; fullName: string; cloneUrl?: string;
  sshUrl?: string; webUrl?: string; defaultBranch?: string; private: boolean; archived?: boolean; fork?: boolean;
  description: string; updated?: string | null; language?: string | null; cloned: boolean; clonePath?: string | null;
  local: (Partial<LocalRepo> & { id: string; path: string }) | null; remoteKey?: string; favorite?: boolean; accountKey?: string;
}
/** Favorito: retrato do repositório (de qualquer conta) + tags livres. `key` = remoto normalizado, ou "local:<id>". */
export interface FavRepo extends Omit<RemoteRepo, "account" | "owner"> { account?: string; owner?: string; tags: string[]; addedAt?: string }
export interface Tag { name: string; color: string; baseDir: string | null; count: number }
export interface CatalogSource { provider: Provider; account: string; owner?: string | null; project?: string | null }
export interface Catalog {
  id: string; name: string; color: string; baseDir: string | null; sources: CatalogSource[]; extra: string[]; exclude: string[];
  description?: string; auto?: string; count?: number | null;
}
/** Conta conectada vista como coleção: todos os repositórios dela. key = "azure:<org>" | "github:<login>" */
export interface AccountColl { key: string; provider: Provider; name: string; count: number | null; dirs: string[] }
export interface CatalogView extends Catalog { repos: RemoteRepo[]; errors: Record<string, string>; counts: { total: number; cloned: number }; staleSince?: number | null; provider?: Provider; account?: boolean; dirs?: string[] }

export interface FileChange { path: string; status: string; from?: string | null; add?: number | null; del?: number | null }
export interface RepoStatus {
  branch: string | null; head: string | null; upstream: string | null; ahead: number; behind: number; staged: FileChange[];
  unstaged: FileChange[]; untracked: FileChange[]; conflicts: FileChange[]; stashes: number; dirty: boolean;
  operation: string | null; detached: boolean;
}
export interface Commit { sha: string; parents: string[]; author: string; email: string; date: string; committer?: string; refs: string[]; subject: string }
export interface CommitDetail extends Commit { message: string; committedAt: string; files: FileChange[] }
export interface Refs {
  local: { name: string; sha: string; upstream: string | null; ahead: number; behind: number; gone: boolean; date: string; author: string; subject: string }[];
  remote: { name: string; sha: string; date: string; author: string; subject: string }[];
  tags: { name: string; sha: string; date: string }[];
  stashes: { ref: string; sha: string; message: string; date: string }[];
  default: string | null; current: string | null;
}
