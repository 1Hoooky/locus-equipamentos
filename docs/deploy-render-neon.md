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
| `DATABASE_URL` | a *direct connection string* da Neon (seção 2, passo 3) | **Única variável de banco necessária.** `config/settings/render.py` faz o parse desta URL e injeta host/porta/nome/usuário/senha no processo antes mesmo de `base.py` carregar — então tanto o Django quanto o teste de conexão TCP do `docker/entrypoint.sh` (que também passou a ler `DATABASE_URL` quando ela existe) leem os mesmos valores, derivados de um único lugar. Não é mais preciso definir `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` separadamente (ver seção 4.1 — isto mudou depois de uma revisão desta configuração). |
| `AXES_FAILURE_LIMIT` / `AXES_COOLOFF_MINUTES` | `5` / `30` (ou o que a Locus decidir) | Mesmos valores do VPS. |

Depois de criar o serviço, a Render builda a imagem (mesmo `Dockerfile`) e sobe o container — `docker/entrypoint.sh` roda `migrate`/`collectstatic`/Gunicorn automaticamente, exatamente como no VPS.

### 4.1. Por que só `DATABASE_URL`, e não também `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`

Uma revisão anterior deste documento listava as cinco variáveis separadas como obrigatórias, além de `DATABASE_URL`. Isso era redundante e tinha um risco real: nada impedia `DATABASE_URL` e as cinco variáveis avulsas de divergirem entre si depois de uma rotação de credencial na Neon, por exemplo, se só uma das duas fosse atualizada.

A causa raiz era técnica, não só de documentação: `config/settings/base.py` (herdado por `render.py` via `prod.py`) monta `DATABASES` lendo `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT` do ambiente, e precisa que essas variáveis existam para não quebrar ao carregar — mesmo sabendo que `render.py` ia sobrescrever o resultado logo em seguida. E o teste de conexão TCP em `docker/entrypoint.sh` roda como um processo Python separado, antes de qualquer configuração do Django ser carregada, então também precisava de `DB_HOST`/`DB_PORT` próprios.

A correção: `config/settings/render.py` agora faz o parse de `DATABASE_URL` **antes** de herdar de `prod.py`/`base.py`, e injeta os cinco campos no ambiente do processo a partir desse parse — então quando `base.py` os lê um instante depois, já está lendo valores derivados da mesma `DATABASE_URL`, nunca um valor suprido à parte. `docker/entrypoint.sh` também passou a preferir `DATABASE_URL` para o teste de conexão, com `DB_HOST`/`DB_PORT` só como alternativa (usada no VPS, onde `DATABASE_URL` nunca é definida). Resultado: `DATABASE_URL` é a única fonte de verdade de ponta a ponta — não sobra nenhum lugar onde um valor divergente possa ser digitado.

SSL: a Neon exige conexão criptografada. `render.py` adiciona `OPTIONS: {"sslmode": "require"}` ao `DATABASES` depois que `base.py` o monta — isto fica exclusivamente em `render.py`, nunca em `base.py`/`prod.py`, porque o Postgres do VPS (mesma rede interna do Docker Compose) não usa SSL entre os containers `web` e `db`; forçar `sslmode=require` ali quebraria o VPS. Confirmado lendo o `DATABASES` resultante num teste local com uma `DATABASE_URL` de teste: `OPTIONS` chega com `sslmode: require` como esperado, e nenhuma outra variável de banco precisou ser definida para o carregamento funcionar.

## 5. Limitações conhecidas deste caminho (ler antes de validar)

Nenhuma delas é um problema do código do projeto — são características da camada gratuita das duas plataformas:

- **A Render Free "dorme" depois de 15 minutos sem tráfego, e leva cerca de 1 minuto para acordar** na próxima requisição. Isso significa que o critério de aceite 10 da especificação (QR abrindo em menos de 2 segundos numa 4G comum) **vai falhar** sempre que o serviço tiver ficado ocioso por mais de 15 minutos antes do teste — não por causa de nenhum código deste projeto, é o comportamento documentado do Free tier da Render. Para validar esse critério de fato, é preciso testar logo depois de uma requisição recente (serviço já "acordado"), ou aceitar que este critério específico só é validável de verdade no VPS (que não dorme).
- **750 horas grátis por mês, por workspace, compartilhadas entre todos os serviços Free daquele workspace** — soma o tempo em que o serviço fica realmente rodando (o tempo dormindo não conta). Um único serviço rodando o mês inteiro sem dormir já usa perto do limite sozinho.
- **Disco efêmero — não há disco persistente no Free tier.** Qualquer arquivo gravado localmente pelo container (inclusive `MEDIA_ROOT`) some no próximo deploy ou reinício. Não é um problema hoje (fotos/anexos ainda são um esqueleto vazio na Fase 1), mas é um bloqueador real para quando essa funcionalidade for implementada — nesse momento, mídia precisará de armazenamento externo (S3-compatible, já previsto na especificação seção 15) antes de usar fotos neste ambiente.
- **O compute da Neon Free entra em suspensão depois de 5 minutos de inatividade**, mas volta em algumas centenas de milissegundos na primeira consulta seguinte — bem mais rápido que o "acordar" da Render, praticamente imperceptível na prática.
- **Janela de restore da Neon Free: 6 horas** (Neon guarda o WAL para permitir "instant restore"/branching a partir de um ponto no tempo dentro dessa janela). Útil para desfazer um erro recente sem precisar de um backup manual — mas não substitui um backup externo para prazos maiores; o mesmo hábito de `pg_dump` regular do runbook do VPS vale aqui também, se este ambiente for usado por mais que alguns dias.
- **E-mail transacional segue sem provedor configurado** — mesma pendência já registrada para o VPS; a recuperação de senha não funciona aqui também, pelo mesmo motivo. **Além disso, e diferente do VPS:** a Render bloqueia tráfego de saída para as portas SMTP tradicionais (25, 465, 587) em serviços web do plano Free (mudança de plataforma confirmada no changelog oficial da Render, "Free web services will no longer allow outbound traffic to SMTP ports" — só afeta o plano Free, planos pagos não são bloqueados). Isso significa que, quando a recuperação de senha por e-mail for implementada de verdade, o `EMAIL_BACKEND` SMTP padrão do Django (que é o que `config/settings/prod.py`/`render.py` usariam por omissão, sem nenhum provedor configurado) **não vai funcionar neste ambiente**, mesmo com credenciais corretas — vai falhar silenciosamente ou dar timeout de conexão, não um erro óbvio de autenticação. Quando essa etapa chegar, o provedor de e-mail transacional (seção 10 da especificação já cita Mailgun/Resend/SES como opções) precisa ser integrado pela **API HTTPS** dele, não por SMTP — todos os três oferecem SDK/endpoint HTTP para isso. Nenhuma mudança de código foi feita agora para isto — é só o registro do porquê, para quando a Locus decidir implementar.

Nenhuma dessas limitações impede validar o resto da Fase 1 (login, cadastro, permissões, geração de patrimônio, exportação, etc.) — só o critério de aceite 10 especificamente fica sujeito ao estado de "sono" da Render no momento do teste.

## 6. Criar o primeiro usuário administrador

**Correção importante em relação a uma versão anterior deste documento:** o Free tier da Render não oferece Shell/SSH nem "one-off jobs" gratuitos — os dois são recursos exclusivos de planos pagos. O procedimento anterior (job avulso disparado pela API) não funciona no Free tier. O que segue substitui aquele procedimento.

**Estratégia:** um passo de bootstrap **executado automaticamente durante a inicialização do container** (a mesma sequência que já roda `migrate`/`collectstatic` a cada subida, `docker/entrypoint.sh`) — o único ponto de execução de código disponível no Free tier sem Shell, sem SSH e sem job avulso, já que o container inicializa normalmente independente do plano. Controlado exclusivamente por três variáveis de ambiente temporárias:

- **Sem credencial hardcoded** — usuário/e-mail/senha vêm só das variáveis de ambiente que você define no painel da Render; nada fica fixo no código.
- **Sem endpoint HTTP, permanente ou temporário** — é um `management command` (`python manage.py bootstrap_admin`), chamado só durante o boot do container, nunca registrado em nenhuma rota (`apps/accounts/management/commands/bootstrap_admin.py`).
- **Nunca promove um usuário já existente a Administrador** — se já existe alguém com o username informado, o comando só registra isso no log e não toca em nada. O único caminho que este mecanismo tem é *criar uma conta nova* com o username exato que você informar; não existe cenário em que ele altere uma conta pré-existente.
- **Idempotente** — rodar de novo (com as mesmas variáveis, ou já sem elas) nunca duplica nem reseta nada.
- **Reversível sem mudança de código** — "desativar" é simplesmente remover as três variáveis do serviço; no próximo boot, o comando não encontra o que precisa e não faz nada, permanentemente, até (e a menos que) alguém as defina de novo.
- **Sem alterar a arquitetura de autenticação normal** — não mexe em `RoleRequiredMixin`, `permissions.py`, nas views de login, nem em nenhuma regra de permissão já existente; é só uma forma alternativa de criar a PRIMEIRA linha na tabela de usuários, para plataformas onde não há outra forma de fazer isso.

**Passo a passo:**

1. No painel do serviço na Render, adicionar temporariamente três variáveis de ambiente:
   - `BOOTSTRAP_ADMIN_USERNAME` — o username do primeiro administrador.
   - `BOOTSTRAP_ADMIN_EMAIL` — o e-mail dele.
   - `BOOTSTRAP_ADMIN_PASSWORD` — uma senha forte (validada contra a mesma política do resto do sistema — `AUTH_PASSWORD_VALIDATORS`, mínimo 10 caracteres — na hora do boot; se a senha for fraca, a inicialização do container falha alto, com uma mensagem clara, em vez de criar silenciosamente uma conta com senha fraca).
2. Salvar — a Render reinicia o serviço automaticamente ao mudar variáveis de ambiente. No próximo boot, `docker/entrypoint.sh` chama `python manage.py bootstrap_admin` (depois do `migrate`, antes do `collectstatic`) — o comando encontra as três variáveis, cria o usuário com `role=ADMIN` e `is_superuser=True` (o mesmo par que o VPS precisa ajustar manualmente na sua seção 10 de `docs/deploy-fase1.md` — aqui já sai correto de fábrica) e imprime uma confirmação nos logs de deploy do serviço.
3. Conferir nos logs do deploy (aba "Logs" do serviço) a linha `bootstrap_admin: Administrador '...' criado (role=ADMIN, is_superuser=True)`.
4. **Remover as três variáveis `BOOTSTRAP_ADMIN_*`** do serviço imediatamente depois de confirmar — isto é o que "desativa" o mecanismo; elas guardam a senha inicial em texto simples na configuração do ambiente enquanto estiverem lá, sem necessidade de continuar depois do primeiro uso. A Render reinicia de novo ao salvar; esse boot seguinte já roda com as variáveis ausentes, e `bootstrap_admin` vira no-op (confirmado por teste automatizado local: ver nota abaixo).
5. Logar com o administrador criado e trocar a senha pela própria interface, se preferir não confiar na que foi passada por variável de ambiente.

Depois do primeiro administrador criado, o resto da equipe é cadastrado pela tela própria (`/contas/usuarios/`), como no VPS — não precisa mais deste mecanismo para ninguém depois do primeiro.

**Nota de verificação:** o comando foi testado localmente (fora deste ambiente Render) nos quatro cenários relevantes — sem as variáveis definidas (no-op), com as variáveis definidas criando corretamente `role=ADMIN`/`is_superuser=True`, rodando de novo com as mesmas variáveis (idempotente, não duplica), e com uma senha fraca (falha alto, não cria nada). O comportamento *dentro* de um container real da Render ainda não foi observado nesta sessão — é o primeiro item do teste pós-deploy (seção 8).

## 7. Bug real corrigido (afeta os dois caminhos de deploy)

Preparar este documento revelou um problema em `config/settings/prod.py` que **já afetava o VPS antes de qualquer mudança relacionada à Render** — não foi introduzido agora, só descoberto agora: o Nginx do VPS termina TLS na borda e repassa a requisição para o Gunicorn por HTTP simples internamente (`docker/nginx.conf` já define `X-Forwarded-Proto` corretamente), mas `prod.py` nunca dizia ao Django para confiar nesse cabeçalho. Sem isso, `SECURE_SSL_REDIRECT = True` (já configurado) causaria um **loop infinito de redirecionamento** assim que alguém acessasse o site pelo HTTPS de verdade através do Nginx — toda requisição pareceria "insegura" aos olhos do Django e seria redirecionada de novo, para sempre. Corrigido com uma linha (`SECURE_PROXY_SSL_HEADER`) em `prod.py`, seguro especificamente porque o Gunicorn nunca é exposto diretamente à internet no `docker-compose.yml` — só o Nginx fala com ele. `render.py` herda a mesma correção automaticamente, necessária ali pelo mesmo motivo (a Render também termina TLS na borda e repassa por HTTP internamente).

Isto não foi pego antes porque a suíte de testes automatizados usa o `Client` de teste do Django, que nunca passa por Nginx/Gunicorn de verdade — só apareceria no primeiro acesso HTTPS real através do proxy, exatamente o tipo de coisa que o teste pós-deploy do runbook do VPS (`docs/deploy-fase1.md`, seção 13, item 4: `curl -I https://...`) seria o primeiro a pegar, antes de qualquer usuário real notar.

## 8. Teste pós-deploy

Mesmo espírito do runbook do VPS (`docs/deploy-fase1.md`, seção 13), adaptado:

1. Conferir nos logs de deploy a linha `bootstrap_admin: Administrador '...' criado` (seção 6) — é a primeira confirmação de que o boot rodou com `DJANGO_SETTINGS_MODULE=config.settings.render` de fato ativo (se estivesse caindo em `config.settings.dev` por engano, `AUTH_PASSWORD_VALIDATORS` ainda seria o mesmo, mas vale conferir também a linha de log do próprio Django/Gunicorn subindo sem erro de configuração).
2. Acessar a URL pública (`https://SEU-SERVICO.onrender.com`) — se o serviço estava dormindo, esperar o "acordar" (a Render mostra uma página de carregamento própria nesse meio-tempo).
3. `/contas/login/` carrega, certificado válido (a Render gerencia o TLS automaticamente, sem passo de certbot como no VPS).
4. Logar com o administrador criado na seção 6, confirmar que a interface mostra os links de Categorias/Modelos/Importar planilha/Usuários (confirma o `role=ADMIN` aplicado corretamente).
5. Cadastrar um equipamento de teste, confirmar o formato do patrimônio, baixar o QR.
6. Repetir o teste do QR em conexão móvel (mesma checklist de `docs/deploy-fase1.md`, seção 15) — **logo depois de uma requisição recente**, para não medir o tempo de "acordar" do Free tier junto com o tempo real de carregamento da página (ver seção 5 acima).

## 9. Rollback

Mais simples que no VPS: a Render mantém o histórico de deploys de cada serviço, e "Manual Deploy" → escolher um deploy anterior (ou um commit/tag específico) reverte o código com um clique, sem precisar de acesso SSH ao servidor. Para o banco, a Neon permite restaurar um branch para um ponto no tempo dentro da janela de 6 horas (seção 5) direto pelo painel — mais rápido que restaurar um `pg_dump` manual, mas com janela bem mais curta; para qualquer coisa além dessas 6 horas, o mesmo procedimento de backup/restore de `docs/deploy-fase1.md` (seção 11/12) se aplica igual, trocando só o `pg_dump`/`psql` para apontar para o host da Neon em vez do serviço `db` do Compose.

## 10. O que foi tocado no repositório para isto existir

Só para deixar explícito, em resposta direta ao pedido de não mexer no que já existia:

- **Novos, sem afetar nada existente:** `config/settings/render.py`, `render.yaml`, `.dockerignore`, `apps/accounts/management/commands/bootstrap_admin.py` (e os `__init__.py` do pacote), este documento.
- **Alterados:**
  - `config/settings/prod.py` — só a correção do `SECURE_PROXY_SSL_HEADER` (seção 7), que é uma correção de bug real do próprio caminho VPS, não uma mudança de comportamento pretendido nem uma funcionalidade nova.
  - `docker/entrypoint.sh` — ganhou uma linha (`python manage.py bootstrap_admin`) entre o `migrate` e o `collectstatic`. **Sem efeito no VPS**: o comando só age se `BOOTSTRAP_ADMIN_USERNAME`/`PASSWORD` estiverem definidas, e o `.env` do VPS nunca as define — testado localmente confirmando que, sem essas variáveis, o comando não faz nada e retorna sucesso (não trava o `set -e` do script). O procedimento de criação do primeiro admin no VPS (`docs/deploy-fase1.md`, seção 10) continua exatamente o mesmo, sem depender disto. Depois, na rodada de simplificação do banco (seção 4.1), o laço de espera do banco também passou a preferir `DATABASE_URL` quando ela existir, em vez de exigir `DB_HOST`/`DB_PORT` como cópia separada da mesma informação — no VPS, onde `DATABASE_URL` nunca é definida, o comportamento é exatamente o de antes (lê `DB_HOST`/`DB_PORT` do `.env`), testado nos dois ramos contra Postgres real.
  - `docs/deploy-fase1.md` — uma nota de uma frase avisando sobre a linha nova em `entrypoint.sh`, para o documento continuar preciso; nenhuma instrução do procedimento do VPS foi alterada.
  - `config/settings/render.py` — na rodada de simplificação do banco (seção 4.1), reescrito para fazer o parse de `DATABASE_URL` e injetar `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` no ambiente antes de herdar de `prod.py`/`base.py`, em vez de exigir essas cinco variáveis preenchidas à parte. Nenhuma mudança de comportamento fora do caminho Render — `base.py`/`prod.py` continuam exatamente iguais, e o VPS não importa `render.py`.
  - `render.yaml` — mesma rodada: removidas as cinco entradas `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` de `envVars`, que ficaram redundantes; `DATABASE_URL` passou a ser a única variável de banco pedida no Blueprint.

  `docker-compose.yml`, `docker-compose.dev.yml`, `docker/nginx.conf`, `Dockerfile` **não foram tocados** — o `Dockerfile` é reaproveitado sem alteração também pela Render (ver seção 3).
