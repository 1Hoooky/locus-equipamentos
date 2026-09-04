"""
Configurações de produção.

Usadas tanto pelo deploy atual (notebook Windows/WSL2 atrás de túnel
FRP + Oracle Cloud VPS — ver docs/deploy-oracle-frp-notebook.md) quanto,
por herança, pelo caminho alternativo Render+Neon
(config/settings/render.py) — nada aqui é específico de uma topologia de
rede em particular, só do fato de "produção real, atrás de um proxy de
confiança que termina TLS antes do Django".
"""

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

# Quem termina TLS de verdade, hoje, é o Nginx público da Oracle Cloud
# VPS — não o Nginx deste Compose. A cadeia completa é: Oracle (HTTPS,
# Let's Encrypt) → túnel reverso FRP → Nginx deste Compose (HTTP puro,
# ver docker/nginx.conf) → Gunicorn. O Nginx local só REPASSA o
# `X-Forwarded-Proto` que a Oracle já enviou
# (`proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;`), nunca
# recalcula esse valor a partir da própria conexão (que, da perspectiva
# dele, é sempre HTTP simples, mesmo para tráfego público que chegou por
# HTTPS na Oracle).
#
# Sem dizer ao Django para confiar nesse header, request.is_secure()
# sempre voltaria False mesmo para quem chegou por HTTPS de verdade — e
# SECURE_SSL_REDIRECT (acima) entraria em loop infinito de redirecionamento,
# porque toda requisição pareceria "insegura" e seria redirecionada de
# novo, para sempre. Seguro confiar neste header aqui porque o Gunicorn
# nunca é exposto diretamente à internet — só o Nginx local fala com ele,
# e é o próprio Nginx local (não o cliente) quem preenche este header a
# cada requisição.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
