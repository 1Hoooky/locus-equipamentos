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
CAN_RECLASSIFY_EQUIPMENT_MODEL = (Role.ADMIN,)
CAN_MANAGE_EQUIPMENT = (Role.ADMIN, Role.ADMINISTRATIVO)
CAN_VIEW_ACQUISITION_VALUE = (Role.ADMIN, Role.ADMINISTRATIVO)
CAN_REGISTER_OPERATIONS = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL)  # manutenção/higienização/movimentação — Fase 2
CAN_CHANGE_STATUS_CONDITION = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL)
CAN_ADD_PHOTOS = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL)  # fotos/anexos de equipamento — Fase 2/3 (apps.attachments ainda é esqueleto vazio)
CAN_EXPORT_DATA = (Role.ADMIN, Role.ADMINISTRATIVO)
CAN_IMPORT_LEGACY_SPREADSHEET = (Role.ADMIN,)
CAN_SUPERSEDE_EQUIPMENT = (Role.ADMIN,)  # reemissão excepcional de patrimônio (especificação, seção 8/13-C)

# Fase 2 — Operação (arquitetura aprovada v1.0, seção 11). `CAN_REGISTER_OPERATIONS`
# não é redefinida aqui — já existe acima desde a Fase 1, reservada exatamente
# para "manutenção/higienização/movimentação", e é reaproveitada tal como está
# para instalar/retirar/transferir equipamento (nenhuma constante nova para isso).
CAN_VIEW_CLIENTS = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA)
CAN_MANAGE_CLIENTS = (Role.ADMIN, Role.ADMINISTRATIVO)
CAN_MANAGE_LOCATIONS = (Role.ADMIN, Role.ADMINISTRATIVO)
CAN_VIEW_MOVEMENTS = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA)

# Revisão de 25/08/2026 (auditoria final da Fase 1 — fechamento de
# inconsistências): duas constantes foram removidas por não corresponderem
# a nenhum comportamento real do sistema.
#
# - CAN_EDIT_LOCKED_MODEL_CODE existia sugerindo que Administrador tinha um
#   caminho excepcional para editar `EquipmentModel.code` depois que o
#   modelo já tem equipamento vinculado. Não existe: o campo é travado
#   incondicionalmente para TODOS os perfis (inclusive Admin e
#   superusuário) em três camadas independentes — `EquipmentModelForm`
#   (apps/catalog/forms.py, desabilita o campo), `EquipmentModelAdmin`
#   (apps/catalog/admin.py, mesma trava no Django admin) e, na camada que
#   de fato garante a regra, `EquipmentModel.clean()`
#   (apps/catalog/models.py) — que levanta `ValidationError` para
#   qualquer tentativa de mudança de `code` com equipamento vinculado,
#   sem checar `role` nenhum. Corrigir um código errado depois desse
#   ponto é, por design (especificação, seção 8), um procedimento fora do
#   CRUD comum — não há e não deve ser inventado aqui um fluxo de
#   bypass só para "usar" a constante.
# - CAN_VIEW_EQUIPMENT existia para "consultar equipamento e histórico",
#   mas nunca foi referenciada em nenhuma view: `EquipmentListView` e o
#   ramo autenticado de `EquipmentDetailView` já usam apenas
#   `request.user.is_authenticated`, o que hoje é idêntico a
#   "todos os 4 perfis", já que não existe (ainda) nenhum perfil
#   autenticado sem acesso de consulta. Não há distinção de papel real
#   para essa ação hoje, então não há necessidade de uma constante
#   dedicada — se isso mudar no futuro (um 5º perfil sem acesso de
#   consulta, por exemplo), a constante volta a fazer sentido e pode ser
#   reintroduzida naquele momento.
