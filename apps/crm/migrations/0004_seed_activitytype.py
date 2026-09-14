# RODADA 3 DE REFINAMENTOS DO HUB DA OPORTUNIDADE (14/09/2026).
#
# Semeia os 8 tipos de atividade que hoje existem como `TextChoices`
# fixo, preservando EXATAMENTE os mesmos valores (código técnico/nome/
# ordem) — nenhum tipo novo é inventado aqui, só migrado. Lista
# hardcoded no PRÓPRIO arquivo de migration (nunca importando o model
# "ao vivo" — o model pode mudar no futuro, esta migration precisa
# continuar reproduzindo fielmente o estado histórico), mesma prática já
# usada em `apps/operations/migrations/0003_seed_internal_locations.py`.
#
# Idempotente (`get_or_create` por `code`) e com `reverse_code` — reverter
# remove só as linhas que esta migration criou (por `code`), nunca um
# `DeleteModel` (isso já é feito por trás pela migration anterior).

from django.db import migrations

ORIGINAL_ACTIVITY_TYPES = [
    ("LIGACAO", "Ligação", 0),
    ("WHATSAPP", "WhatsApp", 1),
    ("EMAIL", "E-mail", 2),
    ("REUNIAO", "Reunião", 3),
    ("VISITA", "Visita", 4),
    ("OBSERVACAO", "Observação", 5),
    ("FOLLOW_UP", "Follow-up", 6),
    ("OUTRO", "Outro", 7),
]


def seed_activity_types(apps, schema_editor):
    ActivityType = apps.get_model("crm", "ActivityType")
    for code, name, order in ORIGINAL_ACTIVITY_TYPES:
        ActivityType.objects.get_or_create(code=code, defaults={"name": name, "order": order, "is_active": True})


def unseed_activity_types(apps, schema_editor):
    ActivityType = apps.get_model("crm", "ActivityType")
    codes = [code for code, _name, _order in ORIGINAL_ACTIVITY_TYPES]
    ActivityType.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0003_activitytype"),
    ]

    operations = [
        migrations.RunPython(seed_activity_types, unseed_activity_types),
    ]
