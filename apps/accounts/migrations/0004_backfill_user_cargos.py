"""
Backfill: atribui a cada `User` já existente o `Group` ("Cargo") que
espelha seu `role` legado — arquitetura de Cargos/Permissões aprovada em
09/09/2026.

Só toca nos 4 cargos espelhados de `Role` (Administrador/Administrativo/
Operacional/Consulta), criados na migração anterior
(`0003_seed_cargos`). Usa `user.groups.set([group])` — o mesmo
comportamento de substituição total que `apps.accounts.services.
set_user_cargo()` usa em runtime, então mesmo rodando esta migração mais
de uma vez (idempotente) nenhum usuário acumula mais de um cargo.

Não altera `User.role` nem nenhum comportamento de autorização — os
CAN_*/`RoleRequiredMixin` continuam sendo a autorização de fato em toda
view existente nesta rodada. Isto só faz a atribuição inicial do NOVO
sistema, para que ele já nasça consistente com o estado atual de cada
usuário.
"""

from django.db import migrations


CARGO_NAME_BY_ROLE = {
    "ADMIN": "Administrador",
    "ADMINISTRATIVO": "Administrativo",
    "OPERACIONAL": "Operacional",
    "CONSULTA": "Consulta",
}


def backfill_user_cargos(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Group = apps.get_model("auth", "Group")

    groups_by_name = {group.name: group for group in Group.objects.filter(name__in=CARGO_NAME_BY_ROLE.values())}

    for user in User.objects.all():
        cargo_name = CARGO_NAME_BY_ROLE.get(user.role)
        group = groups_by_name.get(cargo_name) if cargo_name else None
        if group is not None:
            user.groups.set([group])


def unbackfill_user_cargos(apps, schema_editor):
    # Reverso deliberadamente um no-op — ver raciocínio em
    # 0003_seed_cargos.unseed_cargos. Remover o cargo de cada usuário
    # num rollback não desfaz nada de útil (o Role legado, que é quem
    # de fato autoriza hoje, é independente e não é tocado aqui) e
    # arrisca apagar uma atribuição de cargo já editada manualmente
    # depois desta migração.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_seed_cargos"),
    ]

    operations = [
        migrations.RunPython(backfill_user_cargos, unbackfill_user_cargos),
    ]
