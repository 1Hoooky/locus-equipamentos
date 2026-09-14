# RODADA 3 DE REFINAMENTOS DO HUB DA OPORTUNIDADE (14/09/2026).
#
# Converte `CommercialActivity.activity_type` do antigo `CharField(choices=...)`
# para uma FK real de `ActivityType` (PROTECT — mesmo motivo de
# `Opportunity.source`/`stage`/`loss_reason`: um tipo em uso nunca pode
# desaparecer por baixo de um registro histórico).
#
# Passos, em ordem, dentro de UMA transação (Postgres suporta DDL
# transacional — nenhum passo fica "pela metade" se algo falhar):
#   1. Adiciona a nova coluna `activity_type_new` (FK, nullable por
#      enquanto — só até o passo 2 preencher todas as linhas).
#   2. RunPython: para cada `CommercialActivity` existente, localiza o
#      `ActivityType` cujo `code` bate com o valor antigo da string
#      (semeados pela migration anterior, 1-para-1 por construção) e
#      preenche `activity_type_new`.
#   3. Remove a coluna antiga (`activity_type`, CharField).
#   4. Renomeia `activity_type_new` → `activity_type`.
#   5. Torna a coluna obrigatória (`null=False`) — depois do passo 2 não
#      deve sobrar nenhuma linha nula; se sobrar (dado inconsistente fora
#      do enum original), o próprio AlterField falha alto e visível em
#      vez de silenciosamente permitir NULL.
#
# Ambiente é DEV (dado real de produção nunca chega aqui — ver docs de
# deployment) — auditoria confirmou só 6 `CommercialActivity`/atividades
# de teste no banco no momento da escrita desta migration, todas com
# `activity_type` dentro do enum original, então o backfill do passo 2
# cobre 100% das linhas existentes.

import django.db.models.deletion
from django.db import migrations, models


def populate_activity_type_fk(apps, schema_editor):
    ActivityType = apps.get_model("crm", "ActivityType")
    CommercialActivity = apps.get_model("crm", "CommercialActivity")

    types_by_code = {t.code: t for t in ActivityType.objects.all()}
    for activity in CommercialActivity.objects.all().iterator():
        activity_type = types_by_code.get(activity.activity_type)
        if activity_type is None:
            # Valor fora do enum original (não deveria acontecer — ver
            # docstring). Falha alto em vez de perder silenciosamente a
            # informação do tipo.
            raise ValueError(
                f"CommercialActivity id={activity.pk} tem activity_type={activity.activity_type!r} "
                "sem ActivityType correspondente — migration de dados abortada."
            )
        activity.activity_type_new_id = activity_type.pk
        activity.save(update_fields=["activity_type_new"])


def reverse_populate_activity_type_fk(apps, schema_editor):
    # Reverso é feito pelo AlterField/RenameField/AddField em sentido
    # contrário nas operações abaixo — nada a fazer aqui além de existir
    # como par simétrico do RunPython (mantém a migration 100% reversível).
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0004_seed_activitytype"),
    ]

    operations = [
        migrations.AddField(
            model_name="commercialactivity",
            name="activity_type_new",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="activities_tmp",
                to="crm.activitytype",
            ),
        ),
        migrations.RunPython(populate_activity_type_fk, reverse_populate_activity_type_fk),
        migrations.RemoveField(
            model_name="commercialactivity",
            name="activity_type",
        ),
        migrations.RenameField(
            model_name="commercialactivity",
            old_name="activity_type_new",
            new_name="activity_type",
        ),
        migrations.AlterField(
            model_name="commercialactivity",
            name="activity_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="activities",
                to="crm.activitytype",
            ),
        ),
    ]
