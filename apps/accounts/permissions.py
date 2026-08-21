"""
Ponto único de verdade para "quem pode fazer o quê" — a matriz da seção 11
da especificação vira código aqui, não em cada view isoladamente.

Por que centralizar assim: a especificação é explícita em dizer que
permissão nunca pode depender só de esconder um botão no frontend. Ter um
decorator e um mixin únicos, usados em toda view sensível, é o que torna
possível testar a matriz inteira num único arquivo de testes
(apps/accounts/tests/test_permissions.py) em vez de confiar que cada view
"lembrou" de checar o perfil.
"""

from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied

from apps.accounts.models import Role


def roles_required(*allowed_roles: str):
    """Decorator para function-based views."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied("Login obrigatório.")
            if not request.user.is_superuser and request.user.role not in allowed_roles:
                raise PermissionDenied("Seu perfil não tem acesso a esta ação.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Mixin para class-based views. Defina `allowed_roles` na subclasse."""

    allowed_roles: tuple[str, ...] = ()

    def test_func(self) -> bool:
        user = self.request.user
        # Superusuário (Django is_superuser) sempre passa — é a válvula de
        # segurança operacional padrão do Django, independente do `role`
        # de negócio. `role` continua sendo a fonte da verdade para a
        # matriz de permissões da seção 11 no dia a dia da equipe.
        return user.is_superuser or user.role in self.allowed_roles

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        raise PermissionDenied("Seu perfil não tem acesso a esta ação.")


# Grupos de perfis reaproveitados nas views (espelham a matriz da seção 11)
CAN_MANAGE_USERS = (Role.ADMIN,)
CAN_MANAGE_CATALOG = (Role.ADMIN, Role.ADMINISTRATIVO)
CAN_EDIT_LOCKED_MODEL_CODE = (Role.ADMIN,)
CAN_RECLASSIFY_EQUIPMENT_MODEL = (Role.ADMIN,)
CAN_MANAGE_EQUIPMENT = (Role.ADMIN, Role.ADMINISTRATIVO)
CAN_VIEW_ACQUISITION_VALUE = (Role.ADMIN, Role.ADMINISTRATIVO)
CAN_REGISTER_OPERATIONS = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL)  # manutenção/higienização/movimentação — Fase 2
CAN_CHANGE_STATUS_CONDITION = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL)
CAN_ADD_PHOTOS = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL)
CAN_VIEW_EQUIPMENT = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA)
CAN_EXPORT_DATA = (Role.ADMIN, Role.ADMINISTRATIVO)
CAN_IMPORT_LEGACY_SPREADSHEET = (Role.ADMIN,)
CAN_SUPERSEDE_EQUIPMENT = (Role.ADMIN,)  # reemissão excepcional de patrimônio — mesma linha da matriz de CAN_EDIT_LOCKED_MODEL_CODE
