# Deploy

> Este documento substitui o antigo `docs/deploy-oracle-frp-notebook.md`, `docs/deploy-render-neon.md` e `docs/deploy-fase1.md`, removidos na limpeza de 14/09/2026 por serem relatórios pontuais de uma etapa já concluída (ver histórico de decisão dessa remoção no commit "Limpeza..."). Alguns comentários dentro de `docker-compose.yml`/`config/settings/*.py`/`render.yaml` ainda citam esses caminhos antigos — o conteúdo relevante deles foi absorvido aqui.

## Dois caminhos de deploy, em paralelo

O projeto suporta dois caminhos de produção, que **não se excluem** — o VPS é o principal, a Render é uma via de validação alternativa. Nenhum dos dois altera o comportamento do outro.

### 1. Principal — Oracle Cloud VPS + túnel FRP + notebook

```
Internet → HTTPS → Oracle Cloud VPS (Nginx público + Let's Encrypt)
  → túnel reverso FRP
    → notebook Windows/WSL2 → Docker Compose:
        Nginx (docker/nginx.conf, só porta 80, HTTP puro)
          → Gunicorn (serviço web, config.wsgi:application, 3 workers)
            → PostgreSQL 16 (serviço db, volume nomeado)
```

- A **Oracle Cloud VPS** é o único ponto responsável por HTTPS público: termina TLS, emite/renova o certificado Let's Encrypt, e redireciona HTTP→HTTPS. Isso acontece inteiramente do lado da Oracle, fora deste repositório.
- O **Nginx local** (`docker/nginx.conf`, dentro do Compose do notebook) só escuta na porta 80 (HTTP puro) — nunca a 443, nenhum certificado é montado ou servido por ele. Ele **repassa** o header `X-Forwarded-Proto` que a Oracle já enviou (`$http_x_forwarded_proto`), em vez de recalculá-lo com `$scheme` — recalcular seria sempre "http" (a conexão que chega via FRP é sempre HTTP puro, mesmo quando o público acessou via HTTPS na Oracle), e isso faria o Django (`SECURE_PROXY_SSL_HEADER`, `config/settings/prod.py`) achar que toda requisição pública é insegura, entrando em loop de redirecionamento.
- `server_name estoque.locuslocacoes.com.br` (`docker/nginx.conf`); `/static/` e `/media/` servidos direto pelo Nginx via `alias` para os volumes nomeados `static_volume`/`media_volume`, compartilhados com o container `web`.
- Substitui uma hospedagem VPS HostGator anterior (decisão histórica de 04/09/2026, quando a arquitetura mudou para Oracle+FRP).

**Uso**: `docker compose up -d --build`, com um `.env` real na raiz (nunca commitado — ver `.env.example`) com `DJANGO_SETTINGS_MODULE=config.settings.prod`.

Primeiro admin: `docker compose exec web python manage.py createsuperuser` (o `bootstrap_admin` automático do entrypoint não tem efeito aqui, pois `BOOTSTRAP_ADMIN_USERNAME`/`PASSWORD` nunca são definidas no `.env` do VPS).

### 2. Alternativo — Render (Free) + Neon (Postgres serverless)

Via de **validação**, em paralelo ao VPS — não substitui nem altera o caminho principal. Reaproveita o mesmo `Dockerfile` (nenhuma duplicação de build), só troca `DJANGO_SETTINGS_MODULE` para `config.settings.render`.

Blueprint em `render.yaml` — no dashboard da Render, "New +" → "Blueprint" apontando para este repositório.

**Particularidades de `config/settings/render.py`** (herda de `prod.py`, que herda de `base.py`):

- **`DATABASE_URL` é a única fonte de verdade do banco.** O módulo faz o parse dela (`urlsplit`) e injeta `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` no `os.environ` **antes** de importar `prod`/`base` — elimina a possibilidade de uma segunda cópia dessas 5 variáveis divergir da `DATABASE_URL`.
- **Neon exige SSL** — `DATABASES["default"]["OPTIONS"] = {"sslmode": "require"}`, aplicado só aqui (o Postgres do VPS, na mesma rede interna do Compose, não precisa).
- **Use a "Direct connection" da Neon, não a pooled** — a pooled do Neon usa PgBouncer em modo transação, incompatível com os prepared statements que `psycopg[binary]` 3.x usa para a geração atômica de patrimônio (`SELECT ... FOR UPDATE` dentro de transação).
- **Sem Nginx dedicado** no Free tier — WhiteNoise (`whitenoise.middleware.WhiteNoiseMiddleware`, inserido logo após `SecurityMiddleware`) serve os estáticos direto do processo Gunicorn. `STORAGES["staticfiles"]` usa `CompressedStaticFilesStorage`.
- **`django-axes` atrás de um proxy único**: sem `AXES_IPWARE_PROXY_COUNT=1` e `AXES_IPWARE_META_PRECEDENCE_ORDER=("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")`, todo login que passa pelo proxy da Render apareceria vir do mesmo IP interno, e o bloqueio por IP passaria a valer para todo mundo de uma vez.
- **`PORT` dinâmica** — a Render atribui a porta via variável de ambiente `PORT`, que muda a cada deploy; `docker/entrypoint.sh` usa `${PORT:-8000}` no `gunicorn --bind`. No VPS, `PORT` nunca é definida, cai no valor de sempre (8000).
- **Mídia é efêmera** no Free tier (não sobrevive a redeploys). Não é problema hoje porque `apps.attachments` (fotos/anexos) ainda é um esqueleto vazio — mas quando essa funcionalidade for implementada, `MEDIA` precisará migrar para armazenamento externo S3-compatible antes de usar fotos em produção na Render.
- **Bootstrap do primeiro Administrador**: `docker/entrypoint.sh` sempre chama `python manage.py bootstrap_admin` — na Render (sem shell/SSH no Free tier), preencher `BOOTSTRAP_ADMIN_USERNAME`/`EMAIL`/`PASSWORD` nas env vars faz o comando criar o primeiro Admin no boot; no VPS essas variáveis nunca são definidas, então o comando não faz nada (idempotente — ver `docs/apps/accounts.md`).

## `Dockerfile`

`python:3.12-slim`. Dependências de sistema para `psycopg` e Pillow/WeasyPrint (etiquetas em PDF): `libpq-dev`, `gcc`, `libpango-1.0-0`, `libpangocairo-1.0-0`, `libcairo2`, `libgdk-pixbuf-2.0-0`, `libffi-dev`, `fonts-liberation`, `shared-mime-info`, `libzbar0`. `ARG REQUIREMENTS_FILE=requirements/prod.txt` (trocado para `requirements/dev.txt` no compose de dev). Roda como usuário não-root (`appuser`). `RUN sed -i 's/\r$//' docker/entrypoint.sh && chmod +x ...` — normaliza CRLF→LF e garante o bit de execução independentemente de como o arquivo chegou ao contexto de build (Windows/`.zip` costumam quebrar os dois).

## `docker/entrypoint.sh`

1. Espera o banco responder (parseia `DATABASE_URL` se definida — Render — senão usa `DB_HOST`/`DB_PORT` do `.env` — VPS).
2. `python manage.py migrate --noinput`.
3. `python manage.py bootstrap_admin` (sem efeito se as env vars não estiverem definidas).
4. `python manage.py collectstatic --noinput`.
5. `exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 3`.

## Desenvolvimento local

```bash
cp .env.example .env
# editar o .env com uma SECRET_KEY própria

docker compose -f docker-compose.dev.yml up --build
```

`docker-compose.dev.yml` monta o código como volume (hot reload via `runserver`), expõe Postgres na porta 5432 do host, e usa `requirements/dev.txt`. Depois:

```bash
docker compose -f docker-compose.dev.yml exec web python manage.py createsuperuser
docker compose -f docker-compose.dev.yml exec web python manage.py seed_catalog
```

Sem Docker: qualquer ambiente Python 3.12 + Postgres 16 real acessível funciona (ver `docs/architecture.md` sobre por que Postgres é obrigatório mesmo em dev). `requirements/dev.txt` inclui as mesmas libs de sistema do `Dockerfile`, que precisam estar instaladas no host.

## E-mail

Sem provedor de e-mail transacional configurado ainda (decisão de produção pendente — Mailgun/Resend/SES). `dev.py` usa `EMAIL_BACKEND` de console (imprime o e-mail, incluindo o link de redefinição de senha, no terminal do `runserver`). Produção (`prod.py`/`render.py`) não sobrescreve isso — configurar antes de depender do fluxo de "esqueci minha senha" em produção real.

## Variáveis de ambiente relevantes

Ver `.env.example` na raiz do repositório para a lista completa. As mais específicas de arquitetura:

- `SITE_BASE_URL` — fixa a URL que todo QR Code impresso aponta; nunca derivada do `Host` da requisição.
- `DJANGO_ALLOWED_HOSTS`/`DJANGO_CSRF_TRUSTED_ORIGINS` — obrigatórias em produção (`prod.py` recusa subir com `ALLOWED_HOSTS` vazio).
- `AXES_FAILURE_LIMIT`/`AXES_COOLOFF_MINUTES` — ajustáveis sem mudança de código.
- `COMPANY_LOOKUP_PROVIDER` — provider da consulta de CNPJ (default `"brasilapi"`).
- `LOCUS_INSTAGRAM_URL`/`LOCUS_SITE_URL`/`LOCUS_WHATSAPP_URL`/`LOCUS_ORCAMENTO_URL`/`LOCUS_EQUIPAMENTOS_URL` — CTAs da landing pública; vazios são seguros (o CTA correspondente simplesmente não renderiza).
- `BOOTSTRAP_ADMIN_USERNAME`/`EMAIL`/`PASSWORD` — só relevantes em plataformas sem shell (Render); remover do ambiente após o primeiro boot.
- `DATABASE_URL` — só na Render; em todo o resto usa-se `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT` separados.
