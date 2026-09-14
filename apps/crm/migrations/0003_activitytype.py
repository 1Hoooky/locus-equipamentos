# RODADA 3 DE REFINAMENTOS DO HUB DA OPORTUNIDADE (14/09/2026).
#
# Cria o novo model `ActivityType` — migração de `TextChoices` fixo para
# entidade configurável, mesmo padrão já usado por `CommercialSource`/
# `OpportunityStage`/`LossReason` (ver docstring do model). Esta migration
# só cria a TABELA — o seed dos 8 tipos originais e a conversão do FK de
# `CommercialActivity.activity_type` vêm nas duas migrations seguintes,
# em passos pequenos e reversíveis, nunca tudo numa operação só.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0002_numberingcounter_proposal_proposalversion_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ActivityType",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True)),
                ("name", models.CharField(max_length=50, unique=True)),
                (
                    "order",
                    models.PositiveIntegerField(
                        default=0, help_text="Ordem de exibição nos seletores."
                    ),
                ),
                ("code", models.CharField(blank=True, editable=False, max_length=20)),
            ],
            options={
                "verbose_name": "tipo de atividade",
                "verbose_name_plural": "tipos de atividade",
                "ordering": ["order", "name"],
            },
        ),
        migrations.AddConstraint(
            model_name="activitytype",
            constraint=models.UniqueConstraint(
                condition=models.Q(("code", ""), _negated=True),
                fields=("code",),
                name="uniq_activitytype_code_when_present",
            ),
        ),
    ]
