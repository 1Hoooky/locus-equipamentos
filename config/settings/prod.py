"""Configurações de produção (VPS HostGator, seção 10 da especificação)."""

from decouple import config

from .base import *  # noqa: F401,F403

DEBUG = False

# Em produção, ALLOWED_HOSTS e CSRF_TRUSTED_ORIGINS vêm obrigatoriamente
# do .env — nunca deixamos "*" nem hosts hardcoded aqui.
if not ALLOWED_HOSTS:  # noqa: F405
    raise RuntimeError("DJANGO_ALLOWED_HOSTS precisa estar definido em produção.")

SECURE_SSL_REDIRECT = config("DJANGO_SECURE_SSL_REDIRECT", default=True, cast=bool)
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# O Nginx do VPS termina TLS na borda e repassa a requisição para o
# Gunicorn por HTTP simples dentro da rede interna do Compose (ver
# docker/nginx.conf: "proxy_set_header X-Forwarded-Proto $scheme;"). Sem
# dizer ao Django para confiar nesse header, request.is_secure() sempre
# voltaria False mesmo para quem chegou por HTTPS de verdade — e
# SECURE_SSL_REDIRECT (acima) entraria em loop infinito de redirecionamento,
# porque toda requisição pareceria "insegura" e seria redirecionada de
# novo, para sempre. Seguro confiar neste header aqui porque o Gunicorn
# nunca é exposto diretamente à internet no docker-compose.yml — só o
# Nginx fala com ele.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
