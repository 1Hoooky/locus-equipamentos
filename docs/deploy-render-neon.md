# Deploy alternativo de validação — Render (Free) + Neon

**Relação com o deploy VPS:** este é um **segundo caminho de deploy**, em paralelo ao VPS/Docker Compose já documentado em `docs/deploy-fase1.md`. Os dois convivem sem conflito — nenhum arquivo do caminho VPS foi removido ou teve seu comportamento alterado para isto existir (ver seção "O que foi tocado no repositório" no final deste documento). Use este caminho para uma validação rápida, sem VPS provisionado ainda, ou como ambiente de staging paralelo; o VPS continua sendo o destino de produção real planejado desde a especificação (seção 22).

**Antes de tudo — este caminho tem limitações reais que o VPS não tem.** Elas estão detalhadas na seção 5; a mais importante é que o critério de aceite 10 da especificação (QR abrindo em menos de 2 segundos) provavelmente **falha** aqui depois de qualquer período de inatividade, por causa de como o Free tier da Render funciona — não é um bug deste projeto, é uma característica da camada gratuita da plataforma.

---

## 1. Pré-requisitos

- O repositório precisa estar num provedor Git que a Render suporte (GitHub, GitLab ou Bitbucket) — a Render não faz deploy a partir de um diretório local, só a partir de um repositório conectado. Se o código só existe localmente até agora, primeiro precisa subir para um repositório remoto.
- Conta na Render (render.com) e conta na Neon (neon.tech) — ambas têm tier gratuito, sem cartão de crédito exigido para o Free tier de nenhuma das duas no momento em que este documento foi escrito.
- Mesma tag de partida do VPS: `fase-1-concluida`.

## 2. Criar o banco na Neon

1. Criar um projeto novo na Neon. Se a interface oferecer escolha de versão do Postgres, escolher **16** — mesma versão usada no VPS (`postgres:16` no `docker-compose.yml`), para manter paridade com tudo que já foi testado nesta engenharia.
2. No painel do projeto, a Neon mostra os "Connection Details" com duas variantes de connection string:
   - **Pooled connection** (via PgBouncer, porta ou host com sufixo `-pooler`).
   - **Direct connection** (sem pooler).

   **Usar a Direct connection para este projeto.** A geração atômica de patrimônio (`apps/equipment/services.py`) depende de `SELECT FOR UPDATE` dentro de uma transação — funciona corretamente sob pooling em modo transação na maioria dos casos, mas o driver deste projeto (`psycopg[binary]`, psycopg3) pode preparar statements no lado do servidor depois de execuções repetidas, o que é uma incompatibilidade conhecida do PgBouncer em modo transação (statements preparados "vazam" entre sessões diferentes multiplexadas na mesma conexão física). Não vale o risco para o volume de uso de uma validação — a conexão direta evita a questão inteiramente.
3. Copiar a connection string direta (formato `postgresql://usuario:senha@ep-xxxxx.regiao.aws.neon.tech/nome_do_banco?sslmode=require`) — vai virar a variável `DATABASE_URL` na Render (seção 4).
4. Anotar também, separadamente, os mesmos dados que já estão dentro dessa string (a Neon também os mostra em campos separados no painel): host, porta (sempre `5432`), nome do banco, usuário, senha. Vão virar `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` na Render — ver por quê na seção 4.

## 3. O que muda no código para isto funcionar

Nada que afete o caminho VPS. Três arquivos novos, um arquivo ajustado (correção de bug, detalhe na seção 7):

- **`config/settings/render.py`** (novo) — herda de `config/settings/prod.py` (reaproveita todo o endurecimento de produção já validado) e sobrescreve só o que é específico da Render: parse de `DATABASE_URL` da Neon (com `sslmode=require`, sem afetar o Postgres do VPS, que não usa SSL), hosts (`*.onrender.com` + domínio próprio), `WhiteNoise` para servir estáticos (o Free tier da Render não tem um Nginx dedicado ao lado do container, diferente do VPS), e ajuste de `django-axes` para reconhecer o IP real do usuário atrás do proxy único da Render (sem isso, o bloqueio por IP trataria todo mundo que loga pela Render como se viesse do mesmo lugar).
- **`render.yaml`** (novo) — Blueprint opcional da Render, só para agilizar a criação do serviço pelo painel (seção 4). Não é lido pelo Docker Compose nem pelo VPS.
- **`.dockerignore`** (novo) — corrige um problema real que afeta os DOIS caminhos de deploy, não só a Render: sem ele, `docker build` empacotava o `.env` real (se presente no diretório no momento do build) dentro da imagem Docker, vazando segredos de produção numa camada da imagem. Corrigido de forma puramente aditiva — exclui do contexto de build o que já era ignorado pelo Git, mais o próprio `.env`.

`config/settings/prod.py` recebeu uma correção de bug real (não uma mudança de comportamento pretendido) — ver seção 7.

## 4. Criar o serviço na Render

**Opção A — Blueprint (`render.yaml`), mais rápido:** no painel da Render, "New +" → "Blueprint", apontar para o repositório. A Render lê `render.yaml` (raiz do repositório) e propõe um serviço Docker no plano Free, usando o mesmo `Dockerfile` do VPS. Ela vai pedir, um a um, os valores marcados como segredo no arquivo — preencher com os valores da tabela abaixo.

**Opção B — manual, painel a painel:** "New +" → "Web Service" → conectar o repositório → **Runtime: Docker** (não "Python" — as dependências de sistema do WeasyPrint/Pillow/pyzbar, já resolvidas no `Dockerfile`, não são instaláveis de forma confiável pelo runtime nativo Python da Render) → **Plan: Free** → preencher as variáveis de ambiente abaixo manualmente.

| Variável | Valor | Observação |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.render` | O módulo novo desta seção — não `config.settings.prod` (esse continua exclusivo do VPS, embora `render.py` herde dele). |
| `DJANGO_SECRET_KEY` | gerar um novo | Na Opção A, `generateValue: true` já faz isso sozinho. Na Opção B, gerar com `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`. Nunca reaproveitar a chave do VPS nem a de dev. |
| `DJANGO_DEBUG` | `False` | `prod.py` (herdado por `render.py`) já força isto de qualquer forma. |
| `DJANGO_ALLOWED_HOSTS` | pelo menos o hostname que a Render atribuir ao serviço (ex.: `locus-equipamentos.onrender.com`), mais qualquer domínio próprio | **Obrigatório mesmo na Render** — `prod.py` recusa subir se vier vazio, e essa checagem roda antes de `render.py` conseguir completar a lista sozinho. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://` + o mesmo hostname | Idem, com esquema explícito. |
| `DJANGO_SECURE_SSL_REDIRECT` | `True` | |
| `SITE_BASE_URL` | a URL pública final (`https://locus-equipamentos.onrender.com` ou o domínio próprio) | Crítico para os QR Codes gerados neste ambiente — a URL de cada etiqueta gerada aqui é permanente e não muda sozinha se depois você trocar de domínio. |
| `DATABASE_URL` | a *direct connection string* da Neon (seção 2, passo 3) | |
| `DB_HOST` | o host da Neon (ex.: `ep-xxxxx.regiao.aws.neon.tech`) | **Precisa ser o valor real**, não um placeholder — `docker/entrypoint.sh` (o mesmo do VPS, reaproveitado sem alteração) faz um teste de conexão TCP direto contra `DB_HOST:DB_PORT` antes de rodar as migrations; um valor inválido trava a inicialização esperando para sempre. |
| `DB_PORT` | `5432` | Idem — valor real. |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | os mesmos da Neon (seção 2, passo 4) | Tecnicamente redundantes com `DATABASE_URL` (que é o que `render.py` de fato usa para montar a conexão do Django) — mas `config/settings/base.py` os lê incondicionalmente ao carregar (antes de `render.py` ter a chance de sobrescrever), então precisam existir com valores reais, não placeholders, senão a inicialização já falha nesse ponto. |
| `AXES_FAILURE_LIMIT` / `AXES_COOLOFF_MINUTES` | `5` / `30` (ou o que a Locus decidir) | Mesmos valores do VPS. |

Depois de criar o serviço, a Render builda a imagem (mesmo `Dockerfile`) e sobe o container — `docker/entrypoint.sh` roda `migrate`/`collectstatic`/Gunicorn automaticamente, exatamente como no VPS.

## 5. Limitações conhecidas deste caminho (ler antes de validar)

Nenhuma delas é um problema do código do projeto — são características da camada gratuita das duas plataformas:

- **A Render Free "dorme" depois de 15 minutos sem tráfego, e leva cerca de 1 minuto para acordar** na próxima requisição. Isso significa que o critério de aceite 10 da especificação (QR abrindo em menos de 2 segundos numa 4G comum) **vai falhar** sempre que o serviço tiver ficado ocioso por mais de 15 minutos antes do teste — não por causa de nenhum código deste projeto, é o comportamento documentado do Free tier da Render. Para validar esse critério de fato, é preciso testar logo depois de uma requisição recente (serviço já "acordado"), ou aceitar que este critério específico só é validável de verdade no VPS (que não dorme).
- **750 horas grátis por mês, por workspace, compartilhadas entre todos os serviços Free daquele workspace** — soma o tempo em que o serviço fica realmente rodando (o tempo dormindo não conta). Um único serviço rodando o mês inteiro sem dormir já usa perto do limite sozinho.
- **Disco efêmero — não há disco persistente no Free tier.** Qualquer arquivo gravado localmente pelo container (inclusive `MEDIA_ROOT`) some no próximo deploy ou reinício. Não é um problema hoje (fotos/anexos ainda são um esqueleto vazio na Fase 1), mas é um bloqueador real para quando essa funcionalidade for implementada — nesse momento, mídia precisará de armazenamento externo (S3-compatible, já previsto na especificação seção 15) antes de usar fotos neste ambiente.
- **O compute da Neon Free entra em suspensão depois de 5 minutos de inatividade**, mas volta em algumas centenas de milissegundos na primeira consulta seguinte — bem mais rápido que o "acordar" da Render, praticamente imperceptível na prática.
- **Janela de restore da Neon Free: 6 horas** (Neon guarda o WAL para permitir "instant restore"/branching a partir de um ponto no tempo dentro dessa janela). Útil para desfazer um erro recente sem precisar de um backup manual — mas não substitui um backup externo para prazos maiores; o mesmo hábito de `pg_dump` regular do runbook do VPS vale aqui também, se este ambiente for usado por mais que alguns dias.
- **E-mail transacional segue sem provedor configurado** — mesma pendência já registrada para o VPS; a recuperação de senha não funciona aqui também, pelo mesmo motivo.

Nenhuma dessas limitações impede validar o resto da Fase 1 (login, cadastro, permissões, geração de patrimônio, exportação, etc.) — só o critério de aceite 10 especificamente fica sujeito ao estado de "sono" da Render no momento do teste.

## 6. Criar o primeiro usuário administrador

Isto é mais trabalhoso na Render do que no VPS porque **o Free tier da Render não tem Shell/SSH interativo** (recurso exclusivo dos planos pagos) — não dá para simplesmente abrir um terminal no container rodando, como o `docker compose exec web ...` do VPS. A alternativa nativa da Render para rodar um comando avulso contra a mesma imagem já em produção é um **"one-off job"**, disparado pela API (não tem botão no painel):

1. Gerar uma API key em Account Settings → API Keys, no painel da Render.
2. Pegar o "Service ID" do serviço (aparece na URL do serviço no painel, algo como `srv-xxxxxxxx`).
3. Nas variáveis de ambiente do serviço, adicionar temporariamente `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL` e `DJANGO_SUPERUSER_PASSWORD` (o `createsuperuser --noinput` do Django lê essas três variáveis padrão — nenhum código novo precisou ser escrito para isto).
4. Disparar o job:

   ```bash
   curl --request POST 'https://api.render.com/v1/services/SEU_SERVICE_ID/jobs' \
     --header 'Authorization: Bearer SUA_API_KEY' \
     --header 'Content-Type: application/json' \
     --data-raw '{
       "startCommand": "python manage.py createsuperuser --noinput && python manage.py shell -c \"from apps.accounts.models import User, Role; u = User.objects.get(username='"'"'SEU_USERNAME'"'"'); u.role = Role.ADMIN; u.save(update_fields=['"'"'role'"'"'])\""
     }'
   ```

   (o segundo comando é o mesmo ajuste de `role=ADMIN` explicado no runbook do VPS, seção 10 de `docs/deploy-fase1.md` — necessário pelo mesmo motivo: `createsuperuser` sozinho não define o perfil de negócio, só `is_superuser`).
5. Acompanhar o resultado do job pela aba correspondente no painel do serviço.
6. **Remover as três variáveis `DJANGO_SUPERUSER_*`** das configurações do serviço depois de confirmar que o usuário foi criado — elas guardam a senha inicial em texto simples na configuração do ambiente, sem necessidade de continuar lá depois do primeiro uso.

Disponibilidade de "one-off jobs" no plano Free não está confirmada com certeza total na documentação pública da Render no momento em que este texto foi escrito — se a chamada acima for recusada por causa do plano, a alternativa mais simples é fazer upgrade temporário do serviço para o plano pago mais barato só pelos poucos minutos necessários para abrir o Shell do painel e rodar `python manage.py createsuperuser` interativamente (mais o ajuste de `role`, do mesmo jeito que no VPS), e depois voltar o serviço para o plano Free — Render cobra por segundo, então o custo de fazer isso por poucos minutos é irrisório.

Depois do primeiro administrador criado, o resto da equipe é cadastrado pela tela própria (`/contas/usuarios/`), como no VPS — não precisa mais de job avulso nem de Shell para ninguém depois do primeiro.

## 7. Bug real corrigido (afeta os dois caminhos de deploy)

Preparar este documento revelou um problema em `config/settings/prod.py` que **já afetava o VPS antes de qualquer mudança relacionada à Render** — não foi introduzido agora, só descoberto agora: o Nginx do VPS termina TLS na borda e repassa a requisição para o Gunicorn por HTTP simples internamente (`docker/nginx.conf` já define `X-Forwarded-Proto` corretamente), mas `prod.py` nunca dizia ao Django para confiar nesse cabeçalho. Sem isso, `SECURE_SSL_REDIRECT = True` (já configurado) causaria um **loop infinito de redirecionamento** assim que alguém acessasse o site pelo HTTPS de verdade através do Nginx — toda requisição pareceria "insegura" aos olhos do Django e seria redirecionada de novo, para sempre. Corrigido com uma linha (`SECURE_PROXY_SSL_HEADER`) em `prod.py`, seguro especificamente porque o Gunicorn nunca é exposto diretamente à internet no `docker-compose.yml` — só o Nginx fala com ele. `render.py` herda a mesma correção automaticamente, necessária ali pelo mesmo motivo (a Render também termina TLS na borda e repassa por HTTP internamente).

Isto não foi pego antes porque a suíte de testes automatizados usa o `Client` de teste do Django, que nunca passa por Nginx/Gunicorn de verdade — só apareceria no primeiro acesso HTTPS real através do proxy, exatamente o tipo de coisa que o teste pós-deploy do runbook do VPS (`docs/deploy-fase1.md`, seção 13, item 4: `curl -I https://...`) seria o primeiro a pegar, antes de qualquer usuário real notar.

## 8. Teste pós-deploy

Mesmo espírito do runbook do VPS (`docs/deploy-fase1.md`, seção 13), adaptado:

1. Confirmar que é `render`, não `dev`: usando o one-off job (seção 6) ou o Shell temporário, `python manage.py shell -c "from django.conf import settings; print(settings.DEBUG, settings.SETTINGS_MODULE)"` → precisa imprimir `False config.settings.render`.
2. Acessar a URL pública (`https://SEU-SERVICO.onrender.com`) — se o serviço estava dormindo, esperar o "acordar" (a Render mostra uma página de carregamento própria nesse meio-tempo).
3. `/contas/login/` carrega, certificado válido (a Render gerencia o TLS automaticamente, sem passo de certbot como no VPS).
4. Logar com o administrador criado na seção 6, confirmar que a interface mostra os links de Categorias/Modelos/Importar planilha/Usuários (confirma o `role=ADMIN` aplicado corretamente).
5. Cadastrar um equipamento de teste, confirmar o formato do patrimônio, baixar o QR.
6. Repetir o teste do QR em conexão móvel (mesma checklist de `docs/deploy-fase1.md`, seção 15) — **logo depois de uma requisição recente**, para não medir o tempo de "acordar" do Free tier junto com o tempo real de carregamento da página (ver seção 5 acima).

## 9. Rollback

Mais simples que no VPS: a Render mantém o histórico de deploys de cada serviço, e "Manual Deploy" → escolher um deploy anterior (ou um commit/tag específico) reverte o código com um clique, sem precisar de acesso SSH ao servidor. Para o banco, a Neon permite restaurar um branch para um ponto no tempo dentro da janela de 6 horas (seção 5) direto pelo painel — mais rápido que restaurar um `pg_dump` manual, mas com janela bem mais curta; para qualquer coisa além dessas 6 horas, o mesmo procedimento de backup/restore de `docs/deploy-fase1.md` (seção 11/12) se aplica igual, trocando só o `pg_dump`/`psql` para apontar para o host da Neon em vez do serviço `db` do Compose.

## 10. O que foi tocado no repositório para isto existir

Só para deixar explícito, em resposta direta ao pedido de não mexer no que já existia:

- **Novos, sem afetar nada existente:** `config/settings/render.py`, `render.yaml`, `.dockerignore`, este documento.
- **Alterado:** `config/settings/prod.py` — só a correção do `SECURE_PROXY_SSL_HEADER` (seção 7), que é uma correção de bug real do próprio caminho VPS, não uma mudança de comportamento pretendido nem uma funcionalidade nova. `docker-compose.yml`, `docker-compose.dev.yml`, `docker/nginx.conf`, `docker/entrypoint.sh`, `Dockerfile` e `docs/deploy-fase1.md` **não foram tocados** — o deploy VPS continua exatamente como estava, e o `Dockerfile`/`docker/entrypoint.sh` são reaproveitados sem alteração também pela Render (ver seção 3).
