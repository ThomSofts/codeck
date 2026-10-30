# Segurança

## Relatar uma vulnerabilidade

Não abra issue pública. Use **Security → Report a vulnerability** neste repositório (relato privado do GitHub) ou
escreva para contato@thomsoft.com.br. Respondemos em até 5 dias úteis e combinamos com você a divulgação depois da
correção.

## O que conta

Tudo que permita a outra pessoa, a um site ou a um repositório executar algo na máquina de quem usa o Codeck, ler
credenciais (PATs, tokens), ou fazer o app aceitar uma atualização que não foi publicada pela ThomSoft.

## Como o app se protege

Resumo na seção **Segurança** do [README](README.md). Os pontos centrais:
- o backend só atende a janela do próprio app (chave por execução, Host/Origin conferidos, CSP);
- código vindo de um repositório só roda depois que você confia no projeto;
- atualizações só são aceitas com a assinatura da ThomSoft (`latest.json.sig`, ECDSA P-256) e o SHA-256 assinado.

## Versões com correção

Só a versão mais recente recebe correções — o app se atualiza sozinho, e a ThomSoft pode tornar uma atualização
obrigatória quando a correção for de segurança.
