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
A instalação oficial é pela ThomSoft: **[thomsoft.com.br/codeck](https://thomsoft.com.br/codeck/)**. A página
confere a assinatura da versão e o SHA-256 do instalador no seu navegador antes de salvar o arquivo.

| | |
|---|---|
| **Windows** | baixe o instalador (`.exe`) na página e rode. Instala no seu perfil, sem administrador. |
| **macOS** | baixe o `.dmg` na página e arraste o Codeck para Aplicativos. |

Os mesmos instaladores ficam em [Releases](https://github.com/ThomSofts/codeck/releases/latest); o SHA-256 de cada um
está no `latest.json` assinado.

Depois de instalado, o app **se atualiza sozinho**:
- Ele consulta o `latest.json`, mostra um aviso e o botão **Atualizar agora**.
- Antes de instalar, confere o que se perderia ao reabrir — arquivos sem salvar (com "Salvar tudo" ali mesmo), agentes
  trabalhando, processos rodando e projetos abertos — e só então baixa, mostrando o progresso.
- Só aceita uma versão nova se o `latest.json` vier com a **assinatura da ThomSoft** (`latest.json.sig`, ECDSA P-256),
  e só baixa do GitHub Releases da ThomSoft (com o site de espelho). Antes de instalar, confere o SHA-256 do
  instalador, que também está assinado.
- Na primeira abertura de cada versão nova, copia os dados locais (contas, quadro, projetos, regras, histórico) para
  `backups/` dentro da pasta de dados, antes de qualquer migração — guarda as 5 últimas cópias.
- Quando há uma versão obrigatória (`required`), ele bloqueia o uso até atualizar.

O app não é assinado por certificado comercial (decisão da ThomSoft):
- **Windows:** o SmartScreen pode avisar na primeira instalação. Clique em *Mais informações → Executar assim mesmo*.
- **macOS:** na primeira abertura, use *clique direito → Abrir*. As atualizações seguintes não pedem nada.

## O que faz

**Projetos (v3) — programar com IA sem sair do app**
- Projetos abertos em abas, quantos quiser. Em cada um: agentes de IA, terminais de verdade e arquivos lado a lado.
- **Hub de projetos:** "Abertos agora" no topo (estado ao vivo dos agentes, branch, alterações, fechar), fixados e
  recentes, e todos os clones numa lista densa (feita para centenas de repositórios) com busca, filtros (abertos, com
  agente, com alterações, parados, fixados), ordem por últimos acessados, mais/menos usados, último commit ou nome,
  seções recolhíveis por grupo, conta ou pasta, e teclado (digite para buscar, ↑↓, Enter abre, ⌘↩ abre sem sair).
  Na barra de abas, o botão de projetos abertos lista todos para trocar ou fechar.
- **Grupos de projetos** (como os grupos de abas do navegador): nome, cor, recolher/expandir nas abas, abrir/fechar
  todos. Arraste uma aba para o grupo ou use o clique direito.
- **Pedir à IA** (⌘⇧I / Ctrl+Shift+I): uma caixa no painel do projeto — escreva e Enter manda direto para o agente,
  na conta do projeto (lembrada por projeto), no checkout ou numa tarefa nova; dá para mandar para uma sessão já
  aberta. "Mais opções" abre o formulário completo (issue, só planejar, planejar → aprovar → implementar).
- **Pular permissões (bypass)** por projeto, em Ajustes do projeto (desligado por padrão): os agentes abrem sem pedir
  permissão (Claude, Codex, Gemini, Cursor). Um escudo na aba mostra os projetos com bypass.
- **Tarefas:** "Nova tarefa" abre o agente **no seu checkout** (com uma branch nova, se quiser — só com o checkout
  limpo) ou, se pedido, num **worktree separado**: cria a branch, o worktree, copia os arquivos locais que o Git não
  leva (`workspace.local.json`, `nuget.config`, `.env`… — e garante que eles nunca entrem num commit), roda a
  preparação e abre o(s) agente(s) com o prompt. Vários agentes no mesmo pedido = cada um no seu worktree;
  **Comparar** mostra o que cada um mudou e **Ficar com este** descarta os outros. **Limpar tarefas** (🧹) lista os
  worktrees com o estado (já na base, sem commit, agente aberto) e os órfãos, e remove de uma vez — já vêm marcados
  os que saem sem perder nada.
- **Fechar é encerrar:** fechar o terminal de um agente (ou o projeto) mata o processo **e os filhos** (servidores MCP,
  shells das ferramentas — no Windows, a árvore inteira) e limpa a sessão: contexto, estado e a oferta de retomar.
  Sair do app continua guardando as conversas para retomar.
- **Arquivos de referência no terminal:** arraste arquivos do Finder/Explorer (ou da árvore) para cima de um terminal
  ou agente — metade de cima = **temporário** (apagado ao fechar o terminal), metade de baixo = **fixo no projeto**
  (`.codeck/refs`). Ficam dentro da pasta (o agente lê sem pedir permissão), fora do Git, e o caminho é digitado no
  prompt; o 📎 no canto lista para reinserir ou apagar.
- **Contas de IA:** Claude Code (cada `~/.claude-*` é uma conta), Codex (`CODEX_HOME`), Cursor Agent, Gemini CLI,
  OpenCode. O login é o da própria CLI; o app nunca lê token de IA.
- **Contexto, limite e reset:** por sessão, o modelo, o contexto usado, o custo e o estado (trabalhando, terminou,
  precisa de você — com notificação). Por conta, os limites de 5 h e semanal com a contagem para o reset, em qual
  projeto/tarefa ela está atuando e as sessões abertas fora do app. O limite do Claude Code também é lido sem abrir
  sessão ("Ler agora" ou automático, em Configurações): a própria CLI responde a um "ok" no Haiku em modo `-p` e
  devolve o limite — custa frações de centavo e o app continua sem ler token nenhum.
- **Skills e MCPs por projeto e por conta** (aba **IA** do projeto, ou IA → Skills e MCPs): de quem é cada um — do
  projeto (`.claude/skills`, `.mcp.json`, `.agents/skills`, `.codex/config.toml`, Cursor, Gemini), da conta ou da conta
  só neste projeto. Uma constelação mostra o que o projeto tem em comum com cada conta; dá para trazer da conta para o
  projeto e levar do projeto para a conta com um clique, igualar versões diferentes e ver tudo numa matriz. MCP com
  segredo indo para o projeto vira `${VARIÁVEL}`; remover guarda uma cópia na lixeira do Codeck.
- **Página IA "Ao vivo":** os agentes trabalhando e esperando você, e um radar do que fazer agora — qual conta usar,
  semanal que vai zerar com sobra, conta perto do limite, leitura de limite antiga.
- **Acabou o limite? Continua em outra conta.** Quando o agente para porque a conta atingiu o limite (5 h, semanal,
  cota diária — o Codeck reconhece pelo hook do Claude e pela mensagem de qualquer CLI no terminal), aparece por cima
  do terminal a contagem para o reset e as suas outras contas, da mais livre para a mais apertada. Escolha uma e o
  Codeck abre um terminal novo nela, no mesmo checkout/tarefa, já continuando de onde parou — de qualquer CLI para
  qualquer CLI (Claude → Claude, Claude → Cursor, Codex → Gemini…). Para gastar poucos tokens, o agente novo recebe um
  **resumo enxuto** (pedido original, últimos passos e o estado do git) e o histórico completo fica num arquivo que ele
  só lê se precisar; na mesma CLI (Claude/Codex) dá para **retomar a conversa inteira**. Também dá para passar o
  trabalho sem esperar o limite: painel do agente → **Continuar em outra conta**.
- A CLI é procurada no PATH do seu terminal (lendo o `.zprofile` e o `.zshrc`) e nas pastas de instalação comuns
  (`~/.local/bin`, npm, Homebrew, nvm…); no Windows, no PATH do usuário gravado no registro.
- **Editor como o VS Code** (Monaco, o editor do VS Code), que acompanha ao vivo o que o agente edita:
  - barra de atividades: Explorador (⌘⇧E), Busca (⌘⇧F, com maiúsculas/regex), Controle de código-fonte (⌃⇧G, com a
    contagem de alterações), Gerenciador de Soluções (.NET) e Extensões (⌘⇧X);
  - explorador com **todos os arquivos**, como o VS Code: os ignorados pelo `.gitignore` aparecem apagados e os
    repositórios dentro do projeto (uma pasta "workspace" que reúne vários repos) entram inteiros; pastas pesadas
    (`bin/`, `obj/`, `node_modules/`) são lidas ao abrir;
  - explorador com as cores do Git (alterado, novo, apagado, conflito — a pasta herda a cor), guias de indentação,
    pastas compactas, novo arquivo/pasta, renomear (F2), recortar/copiar/colar/duplicar, excluir (vai para a
    Lixeira), copiar caminho, seleção múltipla, teclado ↑↓←→; arraste para mover (⌥ copia) e arraste arquivos e
    pastas do Finder/Explorer para dentro do projeto;
  - controle de código-fonte: alterações preparadas e não preparadas (lista ou árvore), commit (⌘↩, "commit e enviar",
    amend), sincronizar, stash, descartar; clique abre o **diff** (lado a lado ou em linha, editável, ⌘S salva);
  - abas de visualização (clique simples reaproveita a aba, duplo clique fixa), arrastar para reordenar, ⌘⇧T reabre a
    fechada, "fechar outras/à direita/salvas", breadcrumbs com os símbolos (`arquivo › Classe › método`, clique lista os
    irmãos), marcas do Git na margem, ⌘P com busca aproximada (`arquivo:42`, `:42`);
  - as cores do VS Code (Dark/Light Modern) e, com servidor de linguagem, **destaque semântico** (função, tipo,
    parâmetro, propriedade), ocorrências do símbolo, **lâmpada de correção rápida** (⌘.), **F2 renomeia** em todos os
    arquivos, referências (⇧F12), implementação, símbolos do arquivo (⌘⇧O), formatar, dicas de parâmetros e **dicas
    inline** (segurando ⌃⌥);
  - **⌘/Ctrl+clique e F12 navegam entre arquivos** (abre a aba no ponto exato); as referências abrem no peek com o
    trecho de cada arquivo, e "**N referências**" aparece em cima de classes, funções e métodos (desliga em
    Configurações → Editor). **Dart/Flutter** com o servidor de linguagem do SDK do projeto (FVM incluso);
  - **atalhos do VS Code** (cerca de 100: editor, abas, painéis, terminal ⌃\`, depuração F5/F10/F11, explorador),
    todos trocáveis em Configurações → Atalhos (busca por nome/tecla, acordes como ⌘K ⌘F, conflitos, voltar ao padrão);
    a paleta (⌘⇧P) lista os comandos com `>`;
  - painel **Problemas** (⌘⇧M) com os erros do servidor de linguagem e da compilação, e **barra de status** com branch,
    sincronizar, erros/avisos, linha e coluna, indentação, fim de linha (LF/CRLF) e linguagem — clicáveis;
  - fonte (qualquer uma instalada), ligaduras, tabulação, cursor, colchetes coloridos, formatar ao salvar e salvar
    automático em Configurações → Editor.
  Markdown abre renderizado (ou código, ou lado a lado): as checkboxes de um roteiro de testes marcam direto e salvam,
  com o progresso "N de M concluídos".
- **.NET como no Visual Studio**: solução (.sln/.slnx) com pastas e projetos (web, console, Windows, biblioteca,
  testes; .NET Framework clássico ou SDK), configuração (Debug/Release…), projeto(s) de inicialização, **F5** (compila e
  inicia — o .exe, o site no IIS Express com a URL do projeto, ou `dotnet run`), Shift+F5 para, ⌘⇧B/Ctrl+Shift+B compila,
  Recompilar/Limpar/Restaurar NuGet, e a Lista de Erros vinda da saída do MSBuild. No Windows usa o MSBuild do Visual
  Studio/Build Tools (achado pelo vswhere); no Mac, o `dotnet` (projetos SDK) ou o Mono. "Abrir no Visual Studio" no
  Gerenciador de Soluções, que mostra os arquivos de cada projeto com as mesmas ações do explorador (criar, renomear,
  excluir, arrastar, copiar/colar) e esconde `bin/`/`obj/` até "Mostrar todos os arquivos".
- **Extensões do VS Code**: usa as que você já tem no VS Code/Cursor (e os temas que vêm com o VS Code) e instala novas
  do Open VSX — **temas de cores** (pintam o editor, o terminal e, se quiser, o app inteiro), **temas de ícones**
  (Material Icon Theme, vscode-icons, Seti…), **snippets** e linguagens. Seletor de tema com prévia ao vivo e "usar a
  aparência do VS Code" (tema, ícones, fonte e ajustes do editor). Extensões que rodam código (depuradores, linters)
  continuam só no VS Code.
- **Quadro** (kanban) editável: colunas e cartões seus, com grupo, projetos (os que **mudam** — um worktree em cada,
  na mesma branch —, os de **consulta** e o **principal**, onde a IA roda), etiquetas, prioridade, prazo e item
  ligado, anexos (imagens e arquivos: cole, arraste ou anexe) e checklist. Cartão rápido só com título direto na
  coluna — a IA é opcional. "Planejar"/"Implementar" no cartão abre a tarefa com o contexto do cartão, do grupo, das
  pastas e dos anexos; o cartão anda sozinho para "Em andamento" e "Revisão", com aviso e histórico de quem moveu
  (você ou a IA). A aba "Tarefas dos agentes" mostra as tarefas pelo estado do agente.
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
  Flutter usa o SDK que o projeto fixa, como o VS Code (`dart.flutterSdkPath` do `.vscode/settings.json` ou o FVM:
  `.fvmrc`, `.fvm/`), avisa se a versão não está instalada e mostra o erro de compilação quando o app não sobe.
- Painéis laterais redimensionáveis arrastando a borda; tarefas abaixo dos arquivos.
- **Minimizar** um terminal em execução (o "−" na aba, o clique direito ou ao fechar): o processo continua e ele fica
  numa doca no canto de baixo — clique para voltar, × para parar.
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
  Na PR, **Histórico** (H) mostra tudo que aconteceu com ela e **Commits** (C) abre a branch no clone local.
- **Builds e Actions**: execuções recentes com filtros; no que está rodando, o que acontece de verdade (etapa atual,
  "falhando em…", aguardando aprovação, esperando agente, sem progresso — relido a cada 20 s); no que falhou, o job,
  as anotações e o trecho do log em volta do erro. *Tentar de novo* (só o que falhou), *Rodar de novo* e *Cancelar*.
- **Issues e tarefas**: issues do GitHub e work items do Azure — **todas** dos projetos/repositórios ou as suas
  (atribuídas, criadas por você, que mencionam você), abertas, fechadas ou ambas, com filtro de **responsável**. Em
  Configurações → Contas → **Pessoas**, a mesma pessoa com nomes diferentes em cada conta ("Leonardo" = *Leonardo
  Thomaz* na Cifal e *leonardo.thomaz* na Dematec) vira um filtro só (o app sugere juntar). Clicar num item abre a
  descrição, os campos, os ligados e a discussão (dá para comentar) e **Implementar com IA** no projeto certo, com o
  conteúdo inteiro no pedido. "Não acompanhar issues de…" num item desliga só as issues daquele repositório/projeto.
  **Editar ali mesmo**: título, estado (os do tipo, no Azure), responsáveis, labels/tags, descrição e, no Azure,
  sprint, área e prioridade — aparece na hora e volta se o servidor recusar.
- **Arquivos modificados** na PR: a lista com +/− e o diff lado a lado (↑↓ ou J/K trocam de arquivo).
- **Acompanhar até o deploy**: ao aprovar uma PR (ou em "Acompanhar"), o app segue merge → build → deploy a cada
  10–15 s, numa linha do tempo na PR e num painel no canto, com notificação em cada etapa e na falha.
- **Automação**: regras por prioridade — PR (criador → branch → aprovar/arquivar/notificar), deploy (pipeline →
  estágio → branch, com *"só se eu já aprovei a PR de origem"*) e permissão (pipeline → recurso), com prévia do que
  cada regra pegaria.
- **Análise** (lead time, aprovações, criadores, repositórios) e **Histórico** de tudo que você e o piloto fizeram.

**Leitura em tempo real, por fonte**: PRs, builds, deploys e issues são lidos cada um no próprio ciclo — o que chega
primeiro já aparece —, com o intervalo de cada um em Configurações → Leitura e automação (mais lento com a janela
escondida, pausa com a tela bloqueada, respeita o limite de chamadas). O **tempo real (local)** vigia os repositórios
ativos a cada ~10 s (GitHub, com ETag: "nada mudou" não gasta cota) e ~15 s (Azure) e relê só o que mudou — tudo na
sua máquina, com o seu PAT; nada passa por servidor nenhum além do GitHub e do Azure. Cada tela mostra "lendo…" ou "atualizado há X" no cabeçalho (com ↻ para reler só ela), a barra
lateral marca o item que está lendo, e o fio de progresso do topo fica só para as ações que você dispara.

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
- **Limpar branches locais**: busca e poda o remoto e recomenda (já marcadas) as branches mergeadas na principal
  (main/master, inclusive squash/rebase) e as de remoto apagado sem commit só seu; o resto fica "para avaliar" ou
  nunca é oferecido (atual, principal, protegidas, em worktree, com commits que não subiram).
- **Limpar repositório local** (manda para a Lixeira) — desabilitado quando há algo não commitado, stash, operação
  em andamento ou commit que não subiu.
- **Repositório**: graph de commits no estilo GitKraken (faixas coloridas, avatar do autor, branches e tags),
  alterações com diff, stage/unstage/descartar, commit/amend, pull/push/fetch, branches locais e remotas, merge,
  cherry-pick, revert, reset, stash, tags e **Criar PR** direto para o GitHub ou o Azure.
- Abrir no **VS Code/Cursor/Rider**, no **Finder/Explorer**, no terminal ou no navegador.
- **⌘⇧P / Ctrl+Shift+P** (ou ⌘K): paleta de comandos para ir a qualquer tela, repositório ou ação — com `>`, os comandos. Os atalhos aparecem no formato do
  sistema (⌘ no macOS, Ctrl no Windows); a lista completa fica em Configurações → Atalhos.
- **Barra lateral recolhível** (⌘\ / Ctrl+\): só ícones, com os submenus em popover.

**Dados — bancos de dados dos projetos**
- **SQL Server** (inclusive 2008/2012 antigos, com TLS 1.0 e certificado fixado), **PostgreSQL**, **MySQL/MariaDB**,
  **SQLite**, **libSQL/Turso**, **MongoDB**, **Firebase** (Firestore e Realtime Database) e **Redis**. Cada banco é um
  **plugin** (em Go, `db/`) que você instala só se usar, em Dados → Ajustes: o download vem da ThomSoft e o SHA-256 de
  cada plugin vai assinado no `latest.json`. O build local (`build-macos.sh`) já embute todos.
- **Banco → ambientes → projetos**: cada banco tem dev/hml/prod (servidor, usuário, senha no cofre, TLS, túnel SSH) e a
  lista de projetos que o usam — um banco pode servir 30 projetos e um projeto pode usar vários bancos. Duas visões em
  Dados (Bancos | Projetos), com vínculo em lote. No projeto, a aba **Banco** aparece quando há banco vinculado.
- **Editor** (Monaco) com autocompletar do catálogo: ⌘↩ roda o comando do cursor (ou a seleção), ⇧⌘↩ o script inteiro;
  vários resultados, mensagens e "N linhas afetadas", como no SSMS. Mongo e Firebase no estilo do shell
  (`db.clientes.find({…})`, `collection('x').where(…)`), Redis como no `redis-cli`.
- **Grade como planilha**: seleção retangular, ⌘C no formato padrão e o menu com JSON, CSV, Markdown, INSERT, UPDATE e
  lista para `IN (…)`; colar do Excel; soma e média da seleção; edição pendente (amarelo/verde/riscado) aplicada numa
  transação só e conferida pela chave; ⌘-clique na chave estrangeira abre o registro.
- **Imagem do resultado (PNG)**: o cartão com a marca e o ponto verde comentando; esconda colunas e **mascare** dados
  pessoais (CPF, e-mail e telefone já vêm marcados). Copia, salva ou os dois (Dados → Ajustes).
- **Produção travada**: abre somente leitura; destravar pede confirmação e cada alteração fica numa transação esperando
  **Confirmar/Desfazer** (desfeita sozinha em 5 min). UPDATE/DELETE sem WHERE, DROP e TRUNCATE sempre perguntam.
- **Consultas salvas** (do banco ou do projeto — neste computador ou no repositório em `.codeck-db/queries`) e
  **histórico** local, com produção fora por padrão.
- **Banco do app Flutter** (offline-first): o Codeck lê o `pubspec.yaml`, o id do app e o nome dos arquivos no código e
  abre o banco no simulador iOS, no macOS/Windows (direto no arquivo), no Android (`adb run-as`, build de debug) e no
  iPhone (`devicectl`, só leitura). sqflite/drift/floor em SQLite; **Hive** (com o nome dos campos lido do `@HiveField`),
  sembast e shared_preferences convertidos para consultar. **Ao vivo**: relê quando o app grava e destaca o que mudou.
  No Android, **Enviar ao aparelho** fecha o app, guarda backup, troca o banco e reabre (com Desfazer).
- **Importar** do DBeaver (inclusive a senha), do Tabularis (senhas pelo Keychain, com a sua permissão) e do Beekeeper.
- **Agentes de IA (MCP)**: libere um banco para os agentes de um projeto e o Claude/Codex aberto pelo Codeck ganha as
  ferramentas `list_databases`, `list_tables`, `describe_table` e `query` — só os bancos daquele projeto, no ambiente
  ativo. Leitura em produção e alterações pedem a sua aprovação na tela (em produção, sempre; sem resposta em 30 min,
  é negado).

**No sistema**
- **Notificações nativas** (Central de Notificações no Mac, bandeja no Windows): clicar abre o item. Em
  Configurações → Notificações e sons, liga cada tipo separado (IA fazendo uma pergunta, IA em espera, conta no limite, PR
  para revisar, build falhou, deploy esperando você…), cada um com o seu som.
- **Contador** de pendências no Dock e na barra de menus (Mac) ou na bandeja e na barra de tarefas (Windows).

## Contas

| Provedor | Como conectar | O que usa |
|---|---|---|
| **Azure DevOps** | PAT por organização (Configurações → Azure DevOps), com teste de cada permissão | PRs, builds, releases, environments, work items, repositórios |
| **GitHub** | *Entrar com GitHub* (device flow), o login do `gh` CLI ou um token | contas pessoais, organizações e repositórios de terceiros a que o perfil tem acesso |

Quando o GitHub entrega um token que expira (com refresh token), o app o renova sozinho antes de vencer; se um token
for recusado, ele tenta renovar (ou reler o do `gh` CLI) antes de dar a conta por desconectada — e, se não der, mostra
**Entrar de novo** em Configurações → GitHub, que reconecta a mesma conta sem perder ajustes.

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
  - Recusa pedidos com outro `Host` ou outra `Origin` (um site com DNS apontando para cá não passa) e manda uma CSP
    que só deixa rodar o script do próprio app.
  - A chave não fica no ambiente: git, editores e scripts dos repositórios não a herdam.
  - A janela só carrega a tela do app; links abrem fora só se forem `http(s)` ou `mailto`.
- **Confiança por projeto.** O que vem de um repositório e executa código — executar/depurar pelo `launch.json` e
  `tasks.json`, scripts do `package.json`, build/execução .NET, a preparação de tarefas e os servidores de linguagem
  de C#, Rust e do SDK do Dart dentro do repo — só roda depois que você confia no projeto. A pergunta aparece uma vez,
  com "não perguntar novamente" (confia em todos). Ajuste em Configurações → Dados e privacidade e nos Ajustes do projeto.
- **A revisão automática de PRs pela IA não roda nada da PR:** sem Bash, sem os hooks/configurações do `.claude/`
  do repositório e sem MCP do projeto; o diff vai pronto.
- O PAT do git vai só para o host do provedor (`github.com`, `dev.azure.com/<org>`), nunca para outro remoto ou
  submódulo; o do Azure não segue redirecionamento.
- **Bancos de dados**: senhas e chaves (inclusive o JSON da conta do Firebase) vão para o mesmo cofre; o
  `databases.json` só tem a referência. TLS verificado por padrão; certificado próprio (SQL Server) só fixando a
  impressão digital — se ela mudar, a conexão é recusada. TLS 1.0 só na conexão marcada como servidor antigo. Sem
  criptografia só com o seu aceite, e num IP público com um segundo aceite. Produção abre somente leitura (o banco
  desfaz qualquer escrita escondida; `COMMIT` no meio do script é barrado). Túnel SSH pelo `ssh` do sistema, só com
  chave e com o servidor no `known_hosts`. Os plugins rodam em processos separados, falando só pelo stdin/stdout, e
  são conferidos pelo SHA-256 assinado antes de cada execução. O MCP dos agentes usa um token por projeto que só vale
  na rota dele.
- O backend encerra junto com o app (watchdog do processo-pai; no Windows também um Job Object).
- Dados por usuário, fora do repositório:
  - macOS: `~/Library/Application Support/Codeck`
  - Windows: `%APPDATA%\Codeck`

## Como é feito

```
backend/        server.py + pacote pilot/ (Python, só biblioteca padrão) — igual nas duas plataformas; mcp_db.py (MCP de banco)
db/             plugins de banco de dados em Go (um executável por banco; protocolo JSON no stdin/stdout)
  pilot/        http (rotas) · engine (leitura periódica) · azure · github · git · catalogs · rules · secrets · update
  static/       a interface compilada (gerada, não versionada)
ui/             interface do app em Svelte 5 + TypeScript, compilada com Vite (npm run build → backend/static)
brand/          make-logo.py gera logo.svg e icon.svg; make-icons.sh gera .icns e .ico
macos/          Codeck.swift — janela nativa (AppKit + WebKit), Dock, barra de menus, notificações, troca do .app
windows/        Codeck (C# .NET 8, WinForms + WebView2) — janela, bandeja, notificações, atualização pelo ThomSoft Setup
scripts/        build-macos.sh · release-macos.sh · set-required.sh · build-db-plugins.sh
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
- **Assinatura:** o build assina com o certificado "Codeck Code Signing", guardado no Keychain (criado uma vez por
  `scripts/macos-signing-cert.sh`; backup com `--export`). Sempre o mesmo certificado mantém as permissões do macOS
  (Documentos, modificar apps…) depois de cada atualização; sem ele o build sai ad-hoc, e a release se recusa a publicar.

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

## Testar os bancos de dados

`scripts/test-db.sh` sobe os bancos de verdade no Docker (Postgres com TLS, MySQL, MariaDB, SQL Server, MongoDB, Redis,
libSQL e um bastion SSH), os emuladores do Firebase e do Android (com um app Flutter de teste — sqflite, Hive e
shared_preferences), e roda `tests/db/run_tests.py` pela API do backend, `go test` dos plugins (inclusive um servidor
que só fala TLS 1.0, como um SQL Server 2008 R2) e `tests/db/ui_test.mjs` na tela. `--rapido` roda só os testes sem
servidor; `--sem-android` e `--sem-ui` pulam as partes lentas. O relatório fica em `dist/test-db-relatorio.txt`.

No Windows: `scripts/windows/preparar-teste-windows.sh` (no Mac) gera `dist/codeck-teste-windows.zip` — o backend, o
mesmo runner e os plugins `.exe`. Extraia no PC e rode `powershell -ExecutionPolicy Bypass -File testar-bancos.ps1`
(com o Docker Desktop ligado, testa também Postgres, MySQL, MongoDB e Redis).

## Publicar uma versão

1. Suba o `+N` do arquivo `VERSION`, faça commit e push na `main`.
2. **Windows:** o GitHub Actions gera o instalador e testa: instala sem janela, abre o app, atualiza por cima e desinstala. Depois publica no GitHub Releases e no site da ThomSoft (`downloads/codeck/`), com o `latest.json` assinado. Ele só roda quando o `VERSION` muda, para não gastar a cota.
3. **macOS:** no Mac, rode `scripts/release-macos.sh`. Ele gera o `.dmg`, publica no mesmo lugar e confere a assinatura servida, como o app confere.
4. O app baixa do GitHub Releases, com o site de espelho: o site corta conexões longas por volta de 4 MB. A página do Codeck baixa do site, por partes, e confere a assinatura no navegador.
5. Cada plataforma atualiza só a própria parte do `latest.json` e o assina de novo. Para obrigar quem está abaixo do build N a atualizar, rode `scripts/set-required.sh N`, só depois de N estar publicado nas duas plataformas.

**A chave que assina o `latest.json`** (ECDSA P-256; a pública está em `backend/pilot/update.py` e na página do site):
- **Mac:** Keychain, serviço `codeck-update-signing` (o PEM em base64), com uma cópia em `~/.config/thomsoft/codeck-update-signing.pem` (0600). **Guarde uma cópia fora deste Mac:** sem ela, nenhuma atualização nova é aceita pelos apps instalados.
- **GitHub:** secret `CODECK_SIGNING_KEY`.

As credenciais do FTP do site são as mesmas do Chefinho.
- **Mac:** `~/.config/thomsoft/downloads.env` com a senha no Keychain (`thomsoft-downloads-ftp`).
- **GitHub:** secrets `DOWNLOADS_FTP_SERVER`, `DOWNLOADS_FTP_USER` e `DOWNLOADS_FTP_PASSWORD`.

## Licença

Codeck é um produto da [ThomSoft](https://thomsoft.com.br), de uso gratuito. Veja [LICENSE](LICENSE).
