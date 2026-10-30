# Segurança

## Relatar uma vulnerabilidade

Não abra issue pública. Use **Security → Report a vulnerability** neste repositório (relato privado do GitHub) ou
escreva para contato@thomsoft.com.br. Respondemos em até 5 dias úteis e combinamos com você a divulgação depois da
correção.

## O que conta

Tudo que permita a outra pessoa, a um site ou a um repositório executar algo na máquina de quem usa o Codeck, ler
credenciais (PATs, tokens, senhas de banco), alterar um banco sem a confirmação que o app exige, ou fazer o app aceitar
uma atualização ou um plugin que não foi publicado pela ThomSoft.

## Como o app se protege

Resumo na seção **Segurança** do [README](README.md). Os pontos centrais:
- o backend só atende a janela do próprio app (chave por execução, Host/Origin conferidos, CSP);
- código vindo de um repositório só roda depois que você confia no projeto;
- atualizações só são aceitas com a assinatura da ThomSoft (`latest.json.sig`, ECDSA P-256) e o SHA-256 assinado.
- plugins de banco de dados só são instalados com o SHA-256 que vem no `latest.json` assinado, e conferidos de novo antes de rodar;
- senhas de banco ficam no cofre do sistema; produção abre somente leitura; agentes de IA só acessam bancos liberados por projeto, com aprovação.

## Versões com correção

Só a versão mais recente recebe correções — o app se atualiza sozinho, e a ThomSoft pode tornar uma atualização
obrigatória quando a correção for de segurança.
