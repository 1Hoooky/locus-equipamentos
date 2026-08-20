"""
Usuário customizado com perfil (role) — especificação, seção 6 e 11.

Usamos um User próprio (em vez do padrão do Django) desde o primeiro
commit porque trocar o modelo de usuário depois que já existem migrations
aplicadas é doloroso. `AUTH_USER_MODEL = "accounts.User"` está configurado
em config/settings/base.py.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Administrador"
    ADMINISTRATIVO = "ADMINISTRATIVO", "Administrativo"
    OPERACIONAL = "OPERACIONAL", "Operacional/Técnico"
    CONSULTA = "CONSULTA", "Consulta"


class User(AbstractUser):
    """
    `is_active` já existe em AbstractUser (controla login), então não
    duplicamos SoftDeleteModel aqui — desativar um usuário é exatamente
    desmarcar esse campo, sem apagar o registro nem seu histórico de autoria.
    """

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CONSULTA)

    def has_role(self, *roles: str) -> bool:
        return self.role in roles

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_administrativo_ou_superior(self) -> bool:
        return self.role in (Role.ADMIN, Role.ADMINISTRATIVO)

    @property
    def is_operacional_ou_superior(self) -> bool:
        return self.role in (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL)

    def __str__(self) -> str:
        return self.get_full_name() or self.username
