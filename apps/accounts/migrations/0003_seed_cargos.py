"""
Seed dos Cargos iniciais — arquitetura de Cargos/Permissões aprovada em
09/09/2026.

Cria 9 `Group` ("Cargo"): 4 espelhando exatamente os 4 `Role` legados
(Administrador, Administrativo, Operacional, Consulta) — com as MESMAS
Permissions que os CAN_* de `apps/accounts/permissions.py` já concedem a
cada `Role` hoje, calculadas programaticamente a partir do próprio
`PERMISSION_CATALOG`/CAN_* (não uma lista copiada à mão, para nunca
divergir do que as views realmente checam) — mais 5 cargos vazios (sem
nenhuma Permission), reservados para uso futuro sem exigir nova migração
quando alguém precisar deles: Financeiro, Marketing, TI, Backoffice,
Comercial.

Esta migração é aditiva e não altera nenhum comportamento de
autorização: os `CAN_*`/`RoleRequiredMixin` continuam sendo a
autorização de fato em toda view existente nesta rodada. Os `Group`
criados aqui só passam a valer alguma coisa quando (e se) uma view for
migrada para `PermissionRequiredMixin`, em uma etapa futura e separada.

Depende das migrations que declaram `Meta.permissions` nos modelos
referenciados por `PERMISSION_CATALOG` (accounts, catalog, equipment,
operations, clients, maintenance) — precisa rodar depois delas para que
as Permissions já existam no banco a essa altura.
"""

from django.apps import apps as global_apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.db import migrations


INITIAL_ROLE_MIRRORED_CARGOS = ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA")
CARGO_NAME_BY_ROLE = {
    "ADMIN": "Administrador",
    "ADMINISTRATIVO": "Administrativo",
    "OPERACIONAL": "Operacional",
    "CONSULTA": "Consulta",
}
EMPTY_CARGOS = ("Financeiro", "Marketing", "TI", "Backoffice", "Comercial")
EMPTY_CARGO_DESCRIPTION = (
    "Cargo reservado para uso futuro — criado sem permissões na fundação da arquitetura "
    "de Cargos/Permissões (09/09/2026). Edite as permissões pela tela de gestão de cargos "
    "quando este cargo passar a ser usado."
)


def _ensure_contenttypes_and_permissions_exist():
    """
    `ContentType`/`Permission` são criados normalmente pelo sinal
    `post_migrate` — que só dispara depois que TODAS as migrations do
    comando `migrate` em execução terminam, ou seja, depois desta própria
    migração de dados. Sem isto, o `Permission.objects.get(...)` abaixo
    falharia com `DoesNotExist` na primeira vez que este conjunto de
    migrations for aplicado num banco. Este é o contorno documentado para
    esse problema conhecido do Django: disparar manualmente a mesma
    criação que o `post_migrate` faria, usando o app registry REAL
    (`django.apps.apps`, não o `apps` histórico injetado pelo
    `RunPython`) — só assim os helpers enxergam as classes de modelo de
    verdade, com o `Meta.permissions` já declarado no código atual.
    Rodar de novo depois (via `post_migrate`) é inofensivo — ambos os
    helpers são idempotentes (`get_or_create` por dentro).
    """
    for app_config in global_apps.get_app_configs():
        app_config.models_module = True
        create_contenttypes(app_config, verbosity=0)
        create_permissions(app_config, verbosity=0)
        app_config.models_module = None


def seed_cargos(apps, schema_editor):
    _ensure_contenttypes_and_permissions_exist()

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    RoleProfile = apps.get_model("accounts", "RoleProfile")

    # Import tardio e só de módulos Python puros (não modelos) — seguro
    # dentro de uma migração porque `permission_catalog`/`permissions` não
    # têm estado de banco, só constantes; é o mesmo raciocínio de por que
    # `Role` (um `TextChoices`) pode ser importado aqui sem passar pelo
    # `apps` histórico.
    from apps.accounts import permissions as legacy_permissions
    from apps.accounts.permission_catalog import PERMISSION_CATALOG

    def codenames_for_role(role_value: str) -> list[str]:
        codenames = []
        for spec in PERMISSION_CATALOG:
            # Entradas sem CAN_* legado correspondente (ex.: catálogo do
            # CRM, nascido 100% na arquitetura nova — ver
            # apps/crm/models.py) nunca são espelhadas para nenhum Cargo
            # legado aqui: não existe "allowed_roles" para comparar, e
            # espelhar seria inventar uma concessão que ninguém pediu.
            # Essas permissões só passam a valer para um Cargo quando um
            # Administrador marcar explicitamente pela tela de gestão de
            # cargos.
            if spec.legacy_constant is None:
                continue
            allowed_roles = getattr(legacy_permissions, spec.legacy_constant)
            if role_value in allowed_roles:
                codenames.append(spec.codename)
        return codenames

    for role_value in INITIAL_ROLE_MIRRORED_CARGOS:
        cargo_name = CARGO_NAME_BY_ROLE[role_value]
        group, _ = Group.objects.get_or_create(name=cargo_name)
        codenames = codenames_for_role(role_value)
        permissions = list(Permission.objects.filter(codename__in=codenames))
        group.permissions.set(permissions)
        RoleProfile.objects.update_or_create(
            group=group,
            defaults={
                "description": f"Cargo inicial espelhando o perfil legado \"{cargo_name}\" (Role.{role_value}).",
                "is_protected": role_value == "ADMIN",
            },
        )

    for cargo_name in EMPTY_CARGOS:
        group, _ = Group.objects.get_or_create(name=cargo_name)
        RoleProfile.objects.update_or_create(
            group=group,
            defaults={"description": EMPTY_CARGO_DESCRIPTION, "is_protected": False},
        )


def unseed_cargos(apps, schema_editor):
    # Reverso deliberadamente um no-op: os Cargos criados aqui são só
    # dados de configuração aditivos. Removê-los num rollback poderia
    # apagar silenciosamente atribuições/edições feitas depois pela
    # tela de gestão de cargos (ex.: alguém já editou permissões do
    # Operacional). Reverter esta migração deixa os Groups/RoleProfile
    # no banco — inofensivo, já que nenhuma view depende da AUSÊNCIA
    # deles nesta rodada.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_seed_cargo_architecture_base"),
        ("catalog", "0003_seed_cargo_architecture_base"),
        ("equipment", "0006_seed_cargo_architecture_base"),
        ("operations", "0006_seed_cargo_architecture_base"),
        ("clients", "0005_seed_cargo_architecture_base"),
        ("maintenance", "0004_seed_cargo_architecture_base"),
    ]

    operations = [
        migrations.RunPython(seed_cargos, unseed_cargos),
    ]
