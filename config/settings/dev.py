"""Configurações de desenvolvimento local."""

from .base import *  # noqa: F401,F403

DEBUG = True

# Sem provedor de e-mail transacional configurado ainda (seção 10/23 da
# especificação — Mailgun/Resend/SES é decisão de produção, pendente).
# Sem isto, o backend padrão do Django tenta SMTP real em localhost:25 e
# a tela de "esqueci minha senha" trava/falha em qualquer ambiente de
# desenvolvimento. Console backend imprime o e-mail (com o link de
# redefinição) no terminal do `runserver` — só para dev.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
