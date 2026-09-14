# Locus Equipamentos — Relatório de Status (24/08/2026)

## Onde paramos

A Fase 1 ("Patrimônio Digital") está tecnicamente congelada e aprovada. O código está travado na tag `fase-1-concluida`, apontando para o commit `e93abd3`: 96 testes automatizados passando contra PostgreSQL real, as 13 telas da especificação implementadas e com cobertura de teste dedicada, e a matriz de permissões coberta em código e em teste de autorização para todas as ações ativas. Uma auditoria final de arquitetura (`docs/auditoria-arquitetura-fase1.md`) revisou o sistema inteiro contra a especificação técnica v1.0 e encontrou apenas duas lacunas pontuais de cobertura de teste, ambas já fechadas nessa mesma rodada — inclusive um bug real de `NoReverseMatch` na recuperação de senha, descoberto ao escrever o teste que faltava.

Depois do congelamento, o trabalho passou a ser exclusivamente preparação de deploy, sem tocar em regra de negócio nenhuma. Isso resultou em quatro commits adicionais em cima da tag: um runbook completo de deploy de validação para VPS com Docker Compose (`docs/deploy-fase1.md`, cobrindo desde variáveis de ambiente até teste de QR em conexão móvel), um caminho alternativo de deploy gratuito em Render + Neon que reaproveita o mesmo `Dockerfile` sem alterar o caminho VPS (`config/settings/render.py`, `render.yaml`, `docs/deploy-render-neon.md`), a correção de duas premissas erradas desse segundo caminho — Render Free não tem Shell/SSH nem jobs avulsos, então o primeiro Administrador passou a ser criado por um management command idempotente e sem credencial hardcoded (`apps/accounts/management/commands/bootstrap_admin.py`), executado automaticamente no boot do container — e, mais recentemente, uma simplificação da configuração de banco desse caminho Render: `DATABASE_URL` virou a única variável de banco necessária de fato (antes exigia também cinco variáveis separadas, por uma limitação de como `base.py` lê configuração, o que criava risco real de divergência). Essa simplificação foi testada de ponta a ponta — inclusive com o `.env` local removido do ambiente para simular um container vazio de verdade — e está no commit mais recente, `f33b685`.

Nenhum deploy real foi executado até agora, nem no VPS nem na Render — toda essa rodada foi propositalmente parada antes desse passo, a seu pedido. A árvore de trabalho está limpa (`git status` sem pendências) e a suíte de testes, o `makemigrations --check` e o `manage.py check` foram todos reconfirmados depois da última mudança.

## O que existe no repositório hoje

Quatro documentos em `docs/` sustentam o estado atual: a especificação técnica v1.0 que define o escopo aprovado da Fase 1, a auditoria de arquitetura que valida o código contra essa especificação, o runbook de deploy VPS/Docker Compose (caminho principal) e o runbook de deploy Render Free + Neon (caminho alternativo gratuito de validação). Os dois runbooks de deploy são passo a passo operacional completo — variáveis de ambiente, banco, HTTPS, criação do primeiro administrador, backup, rollback e teste pós-deploy incluindo QR em celular — prontos para execução, mas ainda não executados.

## Pra onde vamos agora

A partir daqui existem, na prática, dois caminhos possíveis e independentes, e a escolha entre eles é sua.

O primeiro é seguir para o primeiro deploy real de validação, usando um dos dois runbooks já prontos. Render + Neon tem a vantagem de ser gratuito e mais rápido para validar (sem precisar de servidor próprio), mas com as limitações já documentadas — disco efêmero, sem SMTP tradicional, cold start depois de 15 minutos sem uso. O VPS com Docker Compose é o caminho mais próximo do que provavelmente será a operação real de produção, mas exige um servidor provisionado. Qualquer um dos dois pode ser executado agora sem nenhum trabalho adicional de preparação.

O segundo caminho é começar a planejar o escopo da Fase 2, deixando o primeiro deploy de validação para depois ou para acontecer em paralelo. Isso exigiria antes definir o que entra na Fase 2 — o Phase 1 audit e a especificação técnica têm pistas (fotos/anexos, e-mail de produção via API HTTPS em vez de SMTP, refinamento visual foram citados como itens explicitamente fora da Fase 1), mas o escopo formal da Fase 2 ainda não foi definido nesta conversa.

Não executei nenhum dos dois sem confirmação sua, e recomendo decidirmos juntos por qual seguir antes de eu continuar.
