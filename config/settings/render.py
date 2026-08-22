"""
Configurações para o deploy ALTERNATIVO de validação em Render (Free) +
Neon (Postgres serverless).

Isto é um SEGUNDO caminho de deploy, em paralelo ao VPS/Docker Compose
(config/settings/prod.py, docker-compose.yml, docker/nginx.conf) — não
substitui, não remove e não altera o comportamento do caminho VPS, que
continua funcionando exatamente como antes. Ver docs/deploy-render-neon.md
para o procedimento completo.

Herda de `prod.py` (não de `base.py` direto) para reaproveitar todo o
endurecimento de produção já existente e já testado (DEBUG=False, HSTS,
cookies seguros, `SECURE_PROXY_SSL_HEADER`, validação de ALLOWED_HOSTS) —
só sobrescreve o que é especificamente diferente na Render:

- banco: `DATABASE_URL` (a connection string da Neon) é a ÚNICA fonte de
  verdade — ver a nota logo abaixo sobre como isso é garantido, não só
  pretendido;
- hosts: domínio da Render (`*.onrender.com`) além do domínio próprio;
- estáticos: o Free tier da Render não roda um Nginx dedicado ao lado do
  container `web` — o WhiteNoise serve os estáticos direto do Gunicorn;
- django-axes atrás de um proxy único (o edge da Render), para não
  bloquear por IP todo mundo que loga através dele.

Sobre `DATABASE_URL` ser realmente a ÚNICA fonte de verdade do banco:
`config/settings/base.py` (herdado via `prod.py`) monta `DATABASES` a
partir de `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT` — e
precisa que essas variáveis existam no ambiente, mesmo aqui, só para não
quebrar com um erro de configuração ausente antes deste módulo terminar
de carregar. Em vez de exigir que alguém preencha essas cinco variáveis
a parte (arriscando divergir do que está em `DATABASE_URL` se só uma das
duas for atualizada depois), este módulo faz o parse de `DATABASE_URL`
ANTES de herdar de `prod.py`/`base.py` e injeta os cinco campos no
processo — então quando `base.py` lê `DB_NAME`/etc. um instante depois,
já está lendo valores derivados desta mesma `DATABASE_URL`, nunca um
valor suprido à parte. Não sobra nenhuma variável independente para
divergir: só existe uma leitura da connection string, feita uma vez,
aqui.
"""

import os
from urllib.parse import unquote, urlsplit

from decouple import config

# --------------------------------------------------------------------------
# Banco — precisa rodar ANTES de "from .prod import *": é o próprio
# carregamento de base.py (disparado por essa importação, um instante
# depois) que lê DB_NAME/DB_USER/DB_PASSWORD/DB_HOST/DB_PORT do ambiente
# para montar DATABASES. Injetando os cinco aqui, derivados só de
# DATABASE_URL, garantimos que não existe um segundo lugar de onde esses
# valores possam vir — elimina a redundância, não só documenta que ela
# "não deveria" divergir.
# --------------------------------------------------------------------------

_database_url = config("DATABASE_URL", default="")
if _database_url:
    _parsed = urlsplit(_database_url)
    os.environ["DB_HOST"] = _parsed.hostname or ""
    os.environ["DB_PORT"] = str(_parsed.port or 5432)
    os.environ["DB_NAME"] = _parsed.path.lstrip("/")
    os.environ["DB_USER"] = unquote(_parsed.username or "")
    os.environ["DB_PASSWORD"] = unquote(_parsed.password or "")
# Se DATABASE_URL não estiver definida, base.py cai no comportamento
# padrão dela (lê DB_NAME/DB_USER/... diretamente do ambiente) — só serve
# para depuração local deste módulo; em produção real na Render,
# DATABASE_URL é obrigatória (ver docs/deploy-render-neon.md).

from .prod import *

# --------------------------------------------------------------------------
# Hosts — DJANGO_ALLOWED_HOSTS continua obrigatório (herdado de prod.py,
# que já recusa subir se vier vazio — a checagem roda ANTES destas linhas,
# então isto aqui é um complemento, não um substituto: sempre configurar
# DJANGO_ALLOWED_HOSTS no Render também, pelo menos com o hostname que a
# Render atribuir ao serviço). RENDER_EXTERNAL_HOSTNAME é definida
# automaticamente pela própria Render em tempo de execução.
# --------------------------------------------------------------------------

_render_hostname = config("RENDER_EXTERNAL_HOSTNAME", default="")
ALLOWED_HOSTS = [*ALLOWED_HOSTS, ".onrender.com"]
if _render_hostname:
    ALLOWED_HOSTS.append(_render_hostname)

CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, "https://*.onrender.com"]
if _render_hostname:
    CSRF_TRUSTED_ORIGINS.append(f"https://{_render_hostname}")

# Neon exige SSL; o Postgres do VPS (mesma rede interna do Compose) não —
# por isso isto fica só aqui, nunca em base.py/prod.py. DATABASES já
# existe neste ponto, montado por base.py com os valores injetados acima.
if _database_url:
    DATABASES["default"]["OPTIONS"] = {"sslmode": "require"}

# --------------------------------------------------------------------------
# Estáticos — sem Nginx dedicado no Free tier da Render, o WhiteNoise
# serve os estáticos a partir do próprio processo Gunicorn. `whitenoise`
# já está em requirements/prod.txt desde o primeiro commit (instalado,
# mas sem uso até agora — pensado para este cenário). Ativado só aqui:
# base.py e prod.py continuam sem ele, então o VPS não muda em nada (lá
# quem serve /static/ é o Nginx, direto do volume compartilhado).
# --------------------------------------------------------------------------

MIDDLEWARE = MIDDLEWARE[:1] + ["whitenoise.middleware.WhiteNoiseMiddleware"] + MIDDLEWARE[1:]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# --------------------------------------------------------------------------
# django-axes atrás de proxy — sem isto, toda tentativa de login que passa
# pelo proxy da Render aparentaria vir do mesmo IP interno, e o bloqueio
# por IP (AXES_LOCKOUT_PARAMETERS já inclui "ip_address", ver base.py)
# passaria a valer para todo mundo de uma vez, não por rede/usuário real.
# Ajuste de melhor esforço para um único proxy reverso na frente — mesma
# ressalva documentada em docs/deploy-render-neon.md, porque não há como
# validar isto sem um deploy real na Render para testar contra.
# --------------------------------------------------------------------------

AXES_IPWARE_PROXY_COUNT = 1
AXES_IPWARE_META_PRECEDENCE_ORDER = ("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")

# --------------------------------------------------------------------------
# Mídia — o disco do Free tier da Render é efêmero (não sobrevive a
# redeploys/reinícios). Não é um problema HOJE porque `apps/attachments`
# (fotos/anexos) ainda é um esqueleto vazio na Fase 1 — mas fica registrado
# aqui para não ser esquecido quando essa funcionalidade for implementada:
# nesse momento, MEDIA precisa migrar para armazenamento externo
# (S3-compatible, já previsto na especificação seção 15) antes de usar
# fotos em produção na Render. Nenhuma mudança feita agora — é só o aviso
# no lugar certo para quem for implementar fotos depois.
# --------------------------------------------------------------------------
