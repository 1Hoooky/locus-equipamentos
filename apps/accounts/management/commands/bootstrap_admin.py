"""
Bootstrap opcional do primeiro Administrador, para plataformas sem
Shell/SSH nem execução avulsa de comando disponível no plano gratuito
(caso concreto: Render Free — sem Shell, sem SSH, sem "one-off jobs"
gratuitos; ver docs/deploy-render-neon.md). No VPS isto nunca roda de
verdade — lá o primeiro admin continua sendo criado com
`docker compose exec web python manage.py createsuperuser`, que já
funciona normalmente (docs/deploy-fase1.md, seção 10).

Desenhado para ficar seguro por padrão e nunca alterar a arquitetura de
autenticação normal do projeto:

- SEM credencial hardcoded: usuário/e-mail/senha vêm só de variáveis de
  ambiente (BOOTSTRAP_ADMIN_USERNAME/EMAIL/PASSWORD), nunca de um valor
  fixo no código.
- SEM endpoint HTTP: isto é um management command, chamado durante o
  boot do container (docker/entrypoint.sh) — nunca fica exposto por
  nenhuma rota, nem temporária.
- NUNCA promove um usuário existente: se já existe alguém com o
  username informado, o comando só registra isso e não toca em nada —
  não há caminho, mesmo por engano, para elevar uma conta já existente
  a Administrador. Só cria uma conta NOVA, com o username exato
  informado.
- Idempotente: rodar de novo com as mesmas variáveis (ou sem elas) não
  duplica nem reseta nada.
- Controlado exclusivamente pelas variáveis de ambiente: sem
  BOOTSTRAP_ADMIN_USERNAME e BOOTSTRAP_ADMIN_PASSWORD definidas, o
  comando não faz nada — "desativar" é simplesmente remover essas
  variáveis do serviço (nenhuma mudança de código necessária).

Uso: python manage.py bootstrap_admin (chamado automaticamente pelo
entrypoint, não precisa ser rodado manualmente).
"""

from decouple import config
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Bootstrap opcional do primeiro Administrador a partir de variáveis de ambiente "
        "temporárias (BOOTSTRAP_ADMIN_USERNAME/EMAIL/PASSWORD). Sem elas, não faz nada. "
        "Idempotente: se o usuário já existe, também não faz nada."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        username = config("BOOTSTRAP_ADMIN_USERNAME", default="").strip()
        email = config("BOOTSTRAP_ADMIN_EMAIL", default="").strip()
        password = config("BOOTSTRAP_ADMIN_PASSWORD", default="")

        if not username or not password:
            self.stdout.write("bootstrap_admin: BOOTSTRAP_ADMIN_USERNAME/PASSWORD não definidas — nada a fazer.")
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(
                f"bootstrap_admin: usuário '{username}' já existe — nada a fazer "
                "(idempotente; esta rotina nunca altera uma conta já existente)."
            )
            return

        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(
                "bootstrap_admin: BOOTSTRAP_ADMIN_PASSWORD não atende à política de senha do sistema "
                f"(AUTH_PASSWORD_VALIDATORS): {'; '.join(exc.messages)}"
            ) from exc

        user = User.objects.create_user(username=username, email=email, password=password)
        user.is_staff = True
        user.is_superuser = True
        user.role = Role.ADMIN
        user.save(update_fields=["is_staff", "is_superuser", "role"])

        self.stdout.write(
            self.style.SUCCESS(
                f"bootstrap_admin: Administrador '{username}' criado (role=ADMIN, is_superuser=True). "
                "Remova BOOTSTRAP_ADMIN_USERNAME/EMAIL/PASSWORD das variáveis de ambiente do serviço agora "
                "— não precisam mais existir depois deste primeiro boot."
            )
        )
