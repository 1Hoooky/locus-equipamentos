# Deploy de produção — Oracle Cloud VPS + túnel FRP + notebook (Docker)

**Substitui, como procedimento corrente**, a hospedagem HostGator VPS
descrita em `docs/deploy-fase1.md` (mantido como registro histórico —
ver o aviso no topo daquele arquivo). Atualizado em 04/09/2026. Domínio
público: `https://estoque.locuslocacoes.com.br`.

Este documento descreve só a parte deste repositório (Dockerfile,
`docker-compose.yml`, `docker/nginx.conf`, `config/settings/prod.py`).
A configuração da Oracle Cloud VPS (Nginx público, certificado Let's
Encrypt, renovação) e do túnel FRP (cliente no notebook, servidor na
Oracle) **não fazem parte deste repositório** e não são alteradas por
este documento — são operadas separadamente.

## 1. Arquitetura

```
Internet
    ↓ HTTPS
Oracle Cloud VPS
    ↓ Nginx público + Let's Encrypt (HTTPS, certificado, renovação,
    ↓ redirecionamento HTTP→HTTPS — tudo isso só aqui, fora deste repo)
Túnel reverso FRP
    ↓
Notebook Windows / WSL2
    ↓ HTTP local
Docker Nginx (docker-compose.yml, serviço `nginx` — só porta 80)
    ↓
Django/Gunicorn (serviço `web`)
    ↓
PostgreSQL local em Docker (serviço `db`, sem porta publicada ao host)
```

A Oracle é o único ponto responsável por HTTPS público, certificado
Let's Encrypt, renovação do certificado e redirecionamento HTTP→HTTPS.
**O notebook não é mais responsável por nenhum desses três itens** — não
tem porta 443 aberta em lugar nenhum do Compose, não monta certificado,
não roda `certbot`.

## 2. O que mudou em relação à arquitetura anterior (VPS HostGator)

| Item | Antes (`docs/deploy-fase1.md`) | Agora |
|---|---|---|
| Quem termina TLS | O próprio Nginx do Compose, na porta 443 | Nginx público da Oracle |
| Certificado Let's Encrypt | Serviço `certbot` neste Compose + cron de renovação no host | Só na Oracle, fora deste repositório |
| Porta 443 no Compose | Publicada (`443:443`) | Removida — só `80:80` |
| `docker/nginx.conf` | 2 blocos `server` (80 redireciona + ACME; 443 com `ssl_certificate`) | 1 bloco `server`, só porta 80, sem TLS |
| `X-Forwarded-Proto` | Gerado localmente (`$scheme`, correto porque o TLS terminava ali) | Repassado do que a Oracle já enviou (`$http_x_forwarded_proto`) |
| DNS | Registro `A` apontando para o IP do VPS | Aponta para a Oracle (fora do escopo deste repo) |
| `config/settings/prod.py` | Mesmo código | Sem mudança de comportamento — só o comentário, que descrevia "Nginx do VPS termina TLS", foi corrigido |

Nenhuma variável de ambiente mudou de valor — `DJANGO_ALLOWED_HOSTS`,
`DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_BASE_URL`, `DJANGO_SECURE_SSL_REDIRECT`
já apontavam para `estoque.locuslocacoes.com.br` desde antes (ver
`.env.example`).

## 3. Por que o header `X-Forwarded-Proto` precisa ser repassado, não recalculado

Do ponto de vista do Nginx que roda no Docker do notebook, **toda**
conexão que ele recebe é HTTP puro — inclusive as que, na internet, o
público acessou via HTTPS — porque quem terminou o TLS foi a Oracle, lá
na borda, antes de encaminhar pelo túnel FRP. Se este Nginx local
calculasse o header a partir da própria conexão (`$scheme`, ou pior,
fixando o literal `http`), ele diria ao Django "esta requisição chegou
por HTTP" mesmo para tráfego público que era HTTPS de ponta a ponta.

Isso quebraria duas coisas em `config/settings/prod.py`:

- `SECURE_SSL_REDIRECT = True` entraria em loop de redirecionamento (o
  Django redireciona pra HTTPS, a requisição volta pela mesma cadeia,
  continua "parecendo" HTTP, redireciona de novo — infinito).
- `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE = True` fariam o navegador
  descartar os cookies (só são enviados de volta em conexões que o
  navegador considera HTTPS — e o navegador está certo, a conexão dele
  É HTTPS; é só a perna interna Oracle→FRP→notebook que não é).

Por isso `docker/nginx.conf` faz:

```nginx
proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
```

— ou seja, repassa adiante o valor que a Oracle já escreveu nesse header
antes de encaminhar pelo túnel, em vez de sobrescrevê-lo. Confiar nisso é
seguro porque o Gunicorn nunca é exposto diretamente à internet: só este
Nginx fala com ele (`docker-compose.yml`), e é o próprio Nginx — não um
cliente externo — quem preenche o header a cada requisição que chega
pelo túnel.

Em `config/settings/prod.py`, `SECURE_PROXY_SSL_HEADER =
("HTTP_X_FORWARDED_PROTO", "https")` é o que diz ao Django para confiar
nesse header como sinal de "esta requisição é HTTPS de verdade" — esse
código já existia e não precisou mudar, só o comentário ao lado dele.

## 4. Variáveis de ambiente (`.env` real, só no notebook — nunca no Git)

| Variável | Valor em produção | Observação |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` | O mais importante — confirmar sempre no teste pós-deploy. |
| `DJANGO_ALLOWED_HOSTS` | `estoque.locuslocacoes.com.br` | Sem `localhost`/IP interno em produção. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://estoque.locuslocacoes.com.br` | Com o esquema `https://` explícito. |
| `DJANGO_SECURE_COOKIES` | `True` | `prod.py` já força isso incondicionalmente; mantenha `True` por clareza. |
| `DJANGO_SECURE_SSL_REDIRECT` | `True` | Depende do `X-Forwarded-Proto` correto (seção 3 acima) para não virar loop. |
| `SITE_BASE_URL` | `https://estoque.locuslocacoes.com.br` | Usado para montar a URL permanente dos QR Codes. |
| `DB_HOST` | `db` | Nome do serviço no Compose — Postgres roda no mesmo Compose, sem porta publicada ao host. |

O restante (`DJANGO_SECRET_KEY`, `DB_NAME`/`DB_USER`/`DB_PASSWORD`,
`AXES_FAILURE_LIMIT`/`AXES_COOLOFF_MINUTES`, URLs comerciais da landing)
segue exatamente como documentado em `.env.example` — nenhuma delas
muda por causa desta arquitetura.

## 5. Deploy inicial (primeira vez nesta arquitetura)

Pré-requisitos fora deste repositório, já assumidos como prontos: Oracle
Cloud VPS com Nginx público + certificado Let's Encrypt válido para
`estoque.locuslocacoes.com.br`, túnel FRP conectando essa VPS ao
notebook e encaminhando para a porta 80 local.

```bash
git clone <repositório> && cd locus-equipamentos
cp .env.example .env
# editar o .env com os valores reais de produção (seção 4 acima +
# SECRET_KEY/senha do banco próprios — nunca reaproveitar os de dev)

docker compose up -d db
# esperar o healthcheck do Postgres ficar "healthy" (docker compose ps)

docker compose up -d --build web
# migrate + collectstatic + bootstrap_admin rodam automaticamente
# (docker/entrypoint.sh) a cada subida deste container

docker compose up -d nginx
```

Criação do primeiro Administrador: mesmo procedimento de sempre
(`docs/deploy-fase1.md`, seção 10 — `createsuperuser` seguido do ajuste
de `role` via shell), inalterado por esta mudança de arquitetura.

## 6. Redeploys seguintes (o caso comum)

Com o `.env` e o túnel já configurados, um redeploy depois de um `git
push` é sempre a mesma sequência, sem editar nenhum arquivo versionado
na máquina de produção:

```bash
git pull
docker compose up -d --build
```

`docker compose up -d --build` reconstrói a imagem `web` só se o código
mudou (o Dockerfile copia o repositório para dentro da imagem — não há
volume de código montado em produção, diferente do
`docker-compose.dev.yml`), recria os containers que mudaram e deixa os
demais como estavam. `migrate`/`collectstatic` rodam automaticamente
dentro do container `web` a cada subida (`docker/entrypoint.sh`) — não é
um passo manual à parte.

Depois do `git pull`, `git status` deve voltar limpo: nenhum arquivo
versionado (em particular `docker/nginx.conf`) precisa ser editado à mão
na máquina de produção para esta arquitetura funcionar — é exatamente
isso que esta rodada de mudança resolveu (antes havia uma alteração
local não versionada em `docker/nginx.conf` para o túnel funcionar).

Se só o `docker/nginx.conf` mudou (sem mudança em código Python/
Dockerfile): `docker compose up -d nginx` recarrega a configuração sem
precisar reconstruir a imagem `web`.

## 7. Teste pós-deploy

```bash
docker compose ps
# db, web, nginx "healthy"/"running" — sem 0.0.0.0:5432 nem 0.0.0.0:443
# em nenhuma linha (só 0.0.0.0:80, encaminhado pelo túnel FRP)

docker compose exec web python manage.py shell -c "from django.conf import settings; print(settings.DEBUG, settings.SETTINGS_MODULE)"
# precisa imprimir: False config.settings.prod
```

No navegador (de fora da rede do notebook, ex.: dados móveis):
`https://estoque.locuslocacoes.com.br/` carrega com cadeado válido
(certificado da Oracle), sem redirecionamento em loop e sem aviso de
cookie/sessão perdida ao logar — esses dois sintomas específicos
apareceriam exatamente se o `X-Forwarded-Proto` estivesse sendo
recalculado incorretamente (seção 3 acima).

## 8. O que continua igual (não repetido aqui — ver `docs/deploy-fase1.md`)

Backup (`pg_dump` + cópia externa), procedimento de rollback,
checklist de validação real no celular e a ressalva sobre e-mail
transacional ainda não configurado seguem exatamente como documentados
em `docs/deploy-fase1.md` (seções 10 a 15) — nada disso depende de qual
proxy termina o TLS na borda.
