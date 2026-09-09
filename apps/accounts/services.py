"""
Services de Cargo/Permissão — arquitetura aprovada em 09/09/2026. Único
caminho suportado para atribuir o cargo de um usuário e para
criar/editar/excluir um cargo — nunca `user.groups.add()`/`.set()` ou
`Group.objects.create()`/`group.permissions.set()` direto em view/form,
mesma disciplina já aplicada em `apps.clients.services`/
`apps.equipment.services` desde a Fase 1/2.

Por que "um cargo por usuário" vive aqui e não no banco
---------------------------------------------------------
`User.groups` é um `ManyToManyField` nativo do Django (herdado via
`PermissionsMixin`/`AbstractUser`) — tecnicamente permite vários grupos
por usuário. A especificação exige exatamente um cargo por usuário. Não
existe uma forma nativa e simples de expressar "no máximo 1" num M2M do
Django sem duplicar toda a autenticação num modelo `through` próprio (o
que a arquitetura aprovada explicitamente rejeitou — ver relatório de
aprovação). A garantia então é de APLICAÇÃO: `set_user_cargo()` é o
único ponto de escrita, e ele sempre SUBSTITUI o conjunto inteiro de
grupos do usuário (nunca adiciona a um conjunto existente), então depois
de qualquer chamada o usuário tem exatamente 0 ou 1 grupo — desde que
nenhum outro código chame `user.groups.add()`/`.set()` diretamente (é
por isso que só este módulo faz isso, e os testes de
`apps/accounts/tests/test_roles_services.py` cobrem a invariante).

Tela de gestão de cargos (`apps/accounts/views_roles.py`) e formulário de
usuário (`apps/accounts/forms.py`) usam exclusivamente estas funções.
"""

from dataclasses import dataclass
from functools import reduce
from operator import or_

from django.contrib.auth.models import Group, Permission
from django.db import transaction
from django.db.models import Q

from apps.accounts.models import RoleProfile, User
from apps.accounts.permission_catalog import PERMISSION_CATALOG


class CargoError(ValueError):
    """Erro de negócio ao criar/editar/excluir cargo ou atribuí-lo a um usuário."""


def set_user_cargo(user: User, group: Group | None) -> None:
    """
    Define o cargo do usuário, substituindo qualquer cargo anterior.

    `group=None` remove o usuário de qualquer cargo (fica sem
    permissões de cargo nenhuma — só `is_superuser`, se aplicável,
    continua valendo).
    """
    with transaction.atomic():
        if group is None:
            user.groups.clear()
        else:
            user.groups.set([group])


def _validate_codenames(codenames: list[str]) -> list[Permission]:
    """
    Só aceita codenames que estão no catálogo oficial (`PERMISSION_CATALOG`)
    — nunca os `add_`/`change_`/`delete_`/`view_` automáticos do Django
    nem qualquer Permission fora do catálogo. Isso é o que impede a tela
    de cargos de, por engano ou manipulação de formulário, conceder uma
    permissão que nenhuma view checa de verdade nesta rodada.
    """
    catalog_by_codename = {spec.codename: spec for spec in PERMISSION_CATALOG}
    unknown = sorted(set(codenames) - catalog_by_codename.keys())
    if unknown:
        raise CargoError(f"Permissão(ões) desconhecida(s) ou fora do catálogo: {', '.join(unknown)}.")

    specs = [catalog_by_codename[codename] for codename in codenames]
    if not specs:
        return []

    # Filtra por (app_label, model, codename) — não só `codename` — para
    # nunca depender de coincidência: a unicidade real de uma Permission
    # no Django é (content_type, codename), então é essa combinação que
    # precisamos espelhar aqui (mesmo raciocínio de
    # apps.accounts.forms.permission_catalog_queryset).
    filters = [
        Q(codename=spec.codename, content_type__app_label=spec.app_label, content_type__model=spec.model)
        for spec in specs
    ]
    permissions = list(Permission.objects.filter(reduce(or_, filters)))
    found_codenames = {p.codename for p in permissions}
    missing = sorted(set(codenames) - found_codenames)
    if missing:
        raise CargoError(
            f"Permissão(ões) do catálogo ainda não existem no banco (rode as migrations): {', '.join(missing)}."
        )
    return permissions


def _ensure_not_protected(group: Group, action: str) -> None:
    profile = getattr(group, "profile", None)
    if profile is not None and profile.is_protected:
        raise CargoError(f"O cargo \"{group.name}\" é protegido pelo sistema e não pode ser {action}.")


@dataclass
class CargoData:
    name: str
    description: str = ""
    permission_codenames: list[str] | None = None


def create_cargo(data: CargoData) -> Group:
    name = data.name.strip()
    if not name:
        raise CargoError("Nome do cargo é obrigatório.")
    if Group.objects.filter(name__iexact=name).exists():
        raise CargoError(f"Já existe um cargo chamado \"{name}\".")

    permissions = _validate_codenames(data.permission_codenames or [])

    with transaction.atomic():
        group = Group.objects.create(name=name)
        group.permissions.set(permissions)
        RoleProfile.objects.create(group=group, description=data.description.strip(), is_protected=False)
    return group


def update_cargo(group: Group, data: CargoData) -> Group:
    _ensure_not_protected(group, "editado")

    name = data.name.strip()
    if not name:
        raise CargoError("Nome do cargo é obrigatório.")
    if Group.objects.filter(name__iexact=name).exclude(pk=group.pk).exists():
        raise CargoError(f"Já existe um cargo chamado \"{name}\".")

    permissions = _validate_codenames(data.permission_codenames or [])

    with transaction.atomic():
        group.name = name
        group.save(update_fields=["name"])
        group.permissions.set(permissions)
        profile, _ = RoleProfile.objects.get_or_create(group=group)
        profile.description = data.description.strip()
        profile.save(update_fields=["description", "updated_at"])
    return group


def delete_cargo(group: Group) -> None:
    _ensure_not_protected(group, "excluído")

    users_count = group.user_set.count()
    if users_count:
        raise CargoError(
            f"O cargo \"{group.name}\" está atribuído a {users_count} usuário(s) — "
            "atribua outro cargo a eles antes de excluir este."
        )

    with transaction.atomic():
        group.delete()
