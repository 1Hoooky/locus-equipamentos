# RODADA 4 (REFINAMENTO DA COMPOSIÇÃO COMERCIAL, 15/09/2026, seção 21-22):
# "não cadastrar automaticamente" a lista de exemplos — semeia SOMENTE o
# item confirmado nesta rodada ("Hora técnica"). Idempotente
# (`get_or_create`), mesmo padrão de `0004_seed_activitytype.py`. reverse()
# remove só esta linha (nunca apaga um "Hora técnica" criado manualmente
# depois — identifica pelo nome exato, mesmo raciocínio de reversibilidade
# seletiva já usado nas migrations de seed anteriores do app).

from django.db import migrations


def seed_hora_tecnica(apps, schema_editor):
    ServiceCatalogItem = apps.get_model("crm", "ServiceCatalogItem")
    ServiceCatalogItem.objects.get_or_create(
        name="Hora técnica",
        defaults={"order": 0, "unit_label": "hora", "is_active": True},
    )


def remove_hora_tecnica(apps, schema_editor):
    ServiceCatalogItem = apps.get_model("crm", "ServiceCatalogItem")
    ServiceCatalogItem.objects.filter(name="Hora técnica").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0008_proposal_item_service_type"),
    ]

    operations = [
        migrations.RunPython(seed_hora_tecnica, remove_hora_tecnica),
    ]
