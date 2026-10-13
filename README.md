# Codeck

> Antes se chamava **Commitdeck** (e, antes, **PR Pilot**). Quem tem um deles instalado recebe o Codeck pela
> atualização automática: contas, regras, projetos e histórico vêm junto, e os PATs e tokens continuam no mesmo cofre.

A ferramenta de desktop (**macOS e Windows**) para programar com IA. Cada repositório abre como um projeto, com
agentes de IA (Claude Code, Codex, Cursor…) que mostram contexto, limites e quando resetam, terminais de verdade,
editor com servidor de linguagem, tarefas em git worktree, revisão do que o agente fez e a execução do projeto como no
VS Code. Em volta disso, o versionamento de **GitHub e Azure DevOps** numa fila só — PRs, builds/Actions, deploys,
issues e work items de várias contas, com regras de automação — e um cliente Git completo. Você não precisa trocar
de ferramenta.

## Instalar

| | |
|---|---|
| **Windows** | baixe `Codeck-<versão>-setup.exe` em `https://thomsoft.com.br/downloads/codeck/latest.json` (campo `windows.url`) e rode. Instala no seu perfil, sem administrador. |
| **macOS** | baixe o `.dmg` (campo `macos.url` do mesmo `latest.json`) e arraste o Codeck para Aplicativos. |

Os mesmos instaladores ficam em [Releases](https://github.com/LMThomaz/codeck/releases/latest).

Depois de instalado, o app **se atualiza sozinho**:
- Ele consulta o `latest.json`, mostra um aviso e o botão **Atualizar agora**.
- Antes de instalar, confere o SHA-256 do instalador baixado.
- Quando há uma versão obrigatória (`required`), ele bloqueia o uso até atualizar.

O app não é assinado por certificado comercial (decisão da ThomSoft):
- **Windows:** o SmartScreen pode avisar na primeira instalação. Clique em *Mais informações → Executar assim mesmo*.
- **macOS:** na primeira abertura, use *clique direito → Abrir*. As atualizações seguintes não pedem nada.

## O que faz

**Projetos (v3) — programar com IA sem sair do app**
- Projetos abertos em abas, quantos quiser. Em cada um: agentes de IA, terminais de verdade e arquivos lado a lado.
- **Hub de projetos:** todos os clones da máquina, com busca, filtros (abertos, com agente, com alterações, parados) e
  ordem por últimos acessados, mais/menos usados (seu tempo com o projeto e sessões de IA), último commit ou nome;
  agrupa por grupo, conta ou pasta.
- **Grupos de projetos** (como os grupos de abas do navegador): nome, cor, recolher/expandir nas abas, abrir/fechar
  todos. Arraste uma aba para o grupo ou use o clique direito.
- **Pedir à IA** (⌘⇧I / Ctrl+Shift+I): descreva a tarefa ou escolha uma issue e escolha o fluxo — só planejar,
  planejar → você aprova → implementar, ou implementar direto. Vira uma tarefa em worktree ou roda no checkout.
- **Tarefas em worktree:** "Nova tarefa" cria a branch, o worktree, copia os arquivos locais que o Git não leva
  (`workspace.local.json`, `nuget.config`, `.env`… — e garante que eles nunca entrem num commit), roda a preparação e
  abre o(s) agente(s) com o prompt. Vários agentes no mesmo pedido = cada um no seu worktree; **Comparar** mostra o que
  cada um mudou e **Ficar com este** descarta os outros.
- **Contas de IA:** Claude Code (cada `~/.claude-*` é uma conta), Codex (`CODEX_HOME`), Cursor Agent, Gemini CLI,
  OpenCode. O login é o da própria CLI; o app nunca lê token de IA.
- **Contexto, limite e reset:** por sessão, o modelo, o contexto usado, o custo e o estado (trabalhando, terminou,
  precisa de você — com notificação). Por conta, os limites de 5 h e semanal com a contagem para o reset, em qual
  projeto/tarefa ela está atuando e as sessões abertas fora do app. O limite do Claude Code também é lido sem abrir
  sessão ("Ler agora" ou automático, em Configurações): a própria CLI responde a um "ok" no Haiku em modo `-p` e
  devolve o limite — custa frações de centavo e o app continua sem ler token nenhum.
- A CLI é procurada no PATH do seu terminal (lendo o `.zprofile` e o `.zshrc`) e nas pastas de instalação comuns
  (`~/.local/bin`, npm, Homebrew, nvm…); no Windows, no PATH do usuário gravado no registro.
- **Editor** (Monaco, o do VS Code) que acompanha ao vivo o que o agente edita, ⌘P, busca no projeto, terminais (⌘T).
  Markdown abre renderizado (ou código, ou lado a lado): as checkboxes de um roteiro de testes marcam direto e salvam,
  com o progresso "N de M concluídos".
- **Quadro** (kanban) editável: colunas e cartões seus, com grupo, projetos (os que **mudam** — um worktree em cada,
  na mesma branch —, os de **consulta** e o **principal**, onde a IA roda), etiquetas, prioridade, prazo e item
  ligado. "Planejar"/"Implementar" no cartão abre a tarefa com o contexto do cartão, do grupo e das pastas; o cartão
  anda sozinho para "Em andamento" e "Revisão". A aba "Tarefas dos agentes" mostra as tarefas pelo estado do agente.
- Atalhos: "Revisar com IA" na PR, "Corrigir com IA" no build quebrado (com o log), "Pedir à IA"/"Começar tarefa"/
  "Adicionar ao quadro" na issue/work item.
- Os terminais não herdam a chave do app nem segredos: um agente não consegue chamar a API local nem ler os PATs.
- **Revisão** de cada tarefa: diff editável por arquivo (a seta da margem desfaz um trecho) e comentários em linhas
  que viram um prompt para o agente. Tarefas de revisão de PR publicam o resultado como comentário na PR.
- **Tarefa em vários repositórios** (ex.: entidades → infra → API): um worktree em cada, na mesma branch; o agente
  enxerga todos (`--add-dir` no Claude). Ajustes por projeto: arquivos copiados, preparação, pasta dos worktrees,
  pastas extras e shell.
- **Repositório = projeto:** abrir um repositório abre o projeto, com a aba **Git** (grafo, branches, alterações, commit,
  sync) e a aba **PRs** (pull requests e builds deste repositório, com o detalhe ao lado).
- **Executar** como no VS Code: configurações do `.vscode/launch.json` (com `compounds`, `preLaunchTask` e `envFile`, lido
  só na hora), scripts do `package.json` (npm/pnpm/yarn/bun), perfis do .NET (`launchSettings.json`), Go, Rust e Compose.
- Painéis laterais redimensionáveis arrastando a borda; tarefas abaixo dos arquivos.
- **Retomar** a conversa de um agente depois de fechar o app; dividir a tela (clique direito na aba → Abrir ao lado);
  abrir um projeto em **janela própria** (clique direito na aba do projeto).
- **Limites**: aviso ao passar de 80% e 95%, sugestão de outra conta ao criar tarefa e página de uso por dia,
  conta e projeto (Contas e ajustes → IA).
- **Servidores de linguagem** no editor (autocompletar, erros, hover, F12/⌘-clique): usa o que estiver instalado —
  typescript-language-server, pyright, csharp-ls, gopls, rust-analyzer…


**Revisão e entrega**
- **Fila**: tudo que espera você — PRs aguardando o seu voto (conflito e build em destaque), deploys aguardando
  aprovação (releases clássicas, environments YAML e *pending deployments* do GitHub) e pipelines travados em
  *"needs permission to access a resource"*.
- **Pull requests** dos dois provedores: para revisar, minhas (com o que as trava), todas e arquivadas. Aprovar,
  pedir mudança e comentar sem sair do app.
- **Builds e Actions**: execuções recentes com filtros; no que falhou, o job, as anotações e o trecho do log em volta
  do erro. *Tentar de novo* (só o que falhou), *Rodar de novo* e *Cancelar*.
- **Issues e tarefas**: issues do GitHub e work items do Azure atribuídos a você ou que mencionam você.
- **Automação**: regras por prioridade — PR (criador → branch → aprovar/arquivar/notificar), deploy (pipeline →
  estágio → branch, com *"só se eu já aprovei a PR de origem"*) e permissão (pipeline → recurso), com prévia do que
  cada regra pegaria.
- **Análise** (lead time, aprovações, criadores, repositórios) e **Histórico** de tudo que você e o piloto fizeram.

**Sem internet**: o app continua mostrando o que já tinha lido (PRs, builds, listas de repositórios) com um alerta
fixo, tenta reconectar a cada 10 s e atualiza tudo assim que a rede volta.

**Repositórios e Git**
- **Contas**: quem gere os repositórios é a conta. Cada conta conectada (organização do Azure ou conta do GitHub) lista
  todos os repositórios dela, com a quantidade e o logo do provedor, e guarda as **pastas base** dos clones — podem ser
  várias (…/apis, …/mobile). O app reconhece sozinho os clones dentro delas e as oferece primeiro na hora de clonar.
  **Catálogos** são só filtros/agrupamentos manuais. Filtre por clonado/não clonado e clone um ou todos de uma vez.
  A busca entra em repositórios dentro de outros (um workspace com as APIs dentro dele).
- **O que acompanhar:** por conta, todos os repositórios ou só os escolhidos; por repositório (o olho na lista), liga
  e desliga PRs, builds, deploys, issues e notificações. O painel do repositório mostra o que está acontecendo nele
  (PRs, builds, deploys, issues), a pasta local (abrir, **mover para…**, clonar, limpar), o grupo e as tags; o painel
  da conta, a conexão, os números, as pastas base e a conta de IA padrão.
- **Favoritos e tags**: favorite repositórios de qualquer conta (GitHub e Azure misturados) — pela estrela ou buscando
  em todas as contas — e organize com tags livres ("Open-Source", "Sustentação"…). Cada tag vira uma coleção; tag nova
  é criada digitando no próprio seletor.
- **Branches**: agrupadas em pastas (`feature/`, `fix/`…), com ações no "⋯" e no clique direito — checkout, atualizar
  sem checkout, publicar, merge, rebase, PR, nova branch a partir dela, renomear e apagar; tags (enviar, apagar no
  servidor) e stashes. Clique direito num commit do graph: branch/tag aqui, cherry-pick, revert, reset, copiar SHA.
- **Limpar repositório local** (manda para a Lixeira) — desabilitado quando há algo não commitado, stash, operação
  em andamento ou commit que não subiu.
- **Repositório**: graph de commits no estilo GitKraken (faixas coloridas, avatar do autor, branches e tags),
  alterações com diff, stage/unstage/descartar, commit/amend, pull/push/fetch, branches locais e remotas, merge,
  cherry-pick, revert, reset, stash, tags e **Criar PR** direto para o GitHub ou o Azure.
- Abrir no **VS Code/Cursor/Rider**, no **Finder/Explorer**, no terminal ou no navegador.
- **⌘K / Ctrl+K**: paleta de comandos para ir a qualquer tela, repositório ou ação. Os atalhos aparecem no formato do
  sistema (⌘ no macOS, Ctrl no Windows); a lista completa fica em Configurações → Atalhos.
- **Barra lateral recolhível** (⌘\ / Ctrl+\): só ícones, com os submenus em popover.

**No sistema**
- **Notificações nativas** (Central de Notificações no Mac, bandeja no Windows): clicar abre o item.
- **Contador** de pendências no Dock e na barra de menus (Mac) ou na bandeja e na barra de tarefas (Windows).

## Contas

| Provedor | Como conectar | O que usa |
|---|---|---|
| **Azure DevOps** | PAT por organização (Configurações → Azure DevOps), com teste de cada permissão | PRs, builds, releases, environments, work items, repositórios |
| **GitHub** | *Entrar com GitHub* (device flow), o login do `gh` CLI ou um token | contas pessoais, organizações e repositórios de terceiros a que o perfil tem acesso |

O *Entrar com GitHub* usa o OAuth App **Codeck** (device flow), cujo client id está em `backend/pilot/github.py`
(`GITHUB_CLIENT_ID`). Ele é público: o device flow não usa client secret. Quem distribuir outro build pode trocá-lo
pela variável `CODECK_GITHUB_CLIENT_ID` ou por `githubClientId` no `config.json`.

O Git local usa as mesmas credenciais (por variável de ambiente, nunca na linha de comando) para clonar, buscar e
enviar por HTTPS; remotos SSH usam as suas chaves.

## Segurança

- **O PAT nunca fica em texto.**
  - No macOS vai para o **Keychain**. A gravação é feita pelo stdin do `security`, então ele não aparece na lista de processos.
  - No Windows é cifrado com **DPAPI**: só a sua conta do Windows decifra.
  - O `config.json` guarda apenas a referência, e a tela nunca recebe o PAT de volta. Tokens do GitHub seguem o mesmo caminho.
- O backend atende só em `127.0.0.1:47821` e exige uma **chave nova a cada execução**, que só o app conhece. Outros programas da máquina não leem a fila nem agem por você.
- O backend encerra junto com o app (watchdog do processo-pai; no Windows também um Job Object).
- Dados por usuário, fora do repositório:
  - macOS: `~/Library/Application Support/Codeck`
  - Windows: `%APPDATA%\Codeck`

## Como é feito

```
backend/        server.py + pacote pilot/ (Python, só biblioteca padrão) — igual nas duas plataformas
  pilot/        http (rotas) · engine (leitura periódica) · azure · github · git · catalogs · rules · secrets · update
  static/       a interface compilada (gerada, não versionada)
ui/             interface do app em Svelte 5 + TypeScript, compilada com Vite (npm run build → backend/static)
brand/          make-logo.py gera logo.svg e icon.svg; make-icons.sh gera .icns e .ico
macos/          Codeck.swift — janela nativa (AppKit + WebKit), Dock, barra de menus, notificações, troca do .app
windows/        Codeck (C# .NET 8, WinForms + WebView2) — janela, bandeja, notificações, atualização pelo ThomSoft Setup
scripts/        build-macos.sh · release-macos.sh · set-required.sh
.github/        release-windows.yml — gera, testa e publica o instalador do Windows
VERSION         x.y.z+N — a versão das duas plataformas
```

O app nativo sobe o backend escondido e mostra a tela dele. Não é Electron: o macOS usa o WebKit do sistema e o
Windows usa o WebView2 (Edge). O instalador do Windows leva um Python embutido (com hash fixo); no Mac o app usa o
`python3` das Command Line Tools. O Git é o da máquina (`git` no PATH).

**Novo provedor** (GitLab, Bitbucket…): um módulo em `backend/pilot/` com a mesma forma de `github.py` — listar
repositórios, PRs, execuções e issues devolvendo itens com `provider` e `key` — registrado em `engine.py`, mais o
reconhecimento do remoto em `git.parse_remote`. A interface já trata os itens pelo `provider`.

## Desenvolver

O Codeck só existe como app de desktop (macOS e Windows) — não há versão web. No VS Code ou no Cursor, dê ▶ em
**Codeck (dev, macOS)** ou **Codeck (dev, Windows)**.

- O backend sobe em depuração (porta `47822`, dados em `data-sandbox/`) e o app nativo se conecta a ele.
- `cd ui && npm run check` confere os tipos; `npm run build` gera `backend/static/`.
- Não toca no app instalado nem nas suas contas reais.
- **Instalar o app no meu Mac** (`scripts/build-macos.sh`) compila o app universal (Apple Silicon e Intel) e o instala em `/Applications`.

Requisitos:
- **macOS:** Command Line Tools (`xcode-select --install`) e Node.js 20+.
- **Windows:** .NET 8 SDK, Python 3 e Node.js 20+.

## Testar o app de desktop

`scripts/test-desktop.sh` compila o app do Mac, monta repositórios Git de verdade numa pasta temporária e roda
`tests/desktop/selftest.js` **dentro da janela do app** (dados e porta próprios — não mexe na sua instalação):
navegação, tema e barra de título, repositórios, favoritos/tags, terminal (digitação real), editor e ⌘S, servidor de
linguagem, tarefas em worktree, revisão, tela dividida, quadro, ajustes, janela própria e remoção. Com
`AGENT_ACCOUNT=<conta> TRUSTED_DIR=<pasta>` inclui um agente Claude de verdade. No Windows, o mesmo roteiro roda no
`Codeck.exe` dentro do build do GitHub Actions, e o build só publica se todas as etapas passarem.

## Publicar uma versão

1. Suba o `+N` do arquivo `VERSION`, faça commit e push na `main`.
2. **Windows:** o GitHub Actions gera o instalador e testa: instala sem janela, abre o app, atualiza por cima e desinstala. Depois publica no site da ThomSoft (`downloads/codeck/`) e no GitHub Releases. Ele só roda quando o `VERSION` muda, para não gastar a cota.
3. **macOS:** no Mac, rode `scripts/release-macos.sh`. Ele gera o `.dmg` e publica no mesmo lugar.
4. Cada plataforma atualiza só a própria parte do `latest.json`. Para obrigar quem está abaixo do build N a atualizar, rode `scripts/set-required.sh N`, só depois de N estar publicado nas duas plataformas.

As credenciais do FTP do site são as mesmas do Chefinho.
- **Mac:** `~/.config/thomsoft/downloads.env` com a senha no Keychain (`thomsoft-downloads-ftp`).
- **GitHub:** secrets `DOWNLOADS_FTP_SERVER`, `DOWNLOADS_FTP_USER` e `DOWNLOADS_FTP_PASSWORD`.

## Licença

MIT — veja [LICENSE](LICENSE).
