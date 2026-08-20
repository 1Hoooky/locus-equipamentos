"""
Seed dos códigos de modelo já definidos pela Locus (especificação, seção
22 — "Códigos de modelo iniciais (seed de dados, não hardcoded)").

Importante: isto é DADO, não lógica de aplicação. Os códigos vivem só
aqui, num fixture/seed script, exatamente como a especificação exige
("nunca ficam fixos no código-fonte da aplicação" refere-se à lógica de
geração de patrimônio, que nunca faz switch/if sobre um `code` — este
comando só popula a tabela, um administrador poderia ter cadastrado a
mesma coisa manualmente pela interface).

Uso: python manage.py seed_catalog
Idempotente — pode rodar de novo sem duplicar nada.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Category, EquipmentModel

SEED_DATA = {
    "Aquecedor": [
        ("AQCP", "Aquecedor Pirâmide"),
        ("AQCT", "Aquecedor Torre"),
        ("AQCH", "Aquecedor Híbrido"),
    ],
    "Climatizador": [
        ("NI23TC", "NI23 Tanque Caixa"),
        ("NI23BT", "NI23 Big Tank"),
        ("NI23TS", "NI23 Tanque Suporte"),
        ("9PRO", "9 Pro"),  # nome comercial definitivo pendente — spec seção 23
        ("9PRO2", "9 Pro 220V"),  # nome comercial definitivo pendente — spec seção 23
        ("6PRO", "6 Pro"),  # nome comercial definitivo pendente — spec seção 23
    ],
}


class Command(BaseCommand):
    help = "Popula categorias e modelos iniciais (Aquecedor/Climatizador) definidos na especificação v1.0."

    @transaction.atomic
    def handle(self, *args, **options):
        for category_name, models in SEED_DATA.items():
            category, created = Category.objects.get_or_create(name=category_name)
            if created:
                self.stdout.write(self.style.SUCCESS(f"Categoria criada: {category_name}"))

            for code, name in models:
                _, created = EquipmentModel.objects.get_or_create(
                    code=code,
                    defaults={"category": category, "name": name},
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"  Modelo criado: {code} — {name}"))
                else:
                    self.stdout.write(f"  Modelo já existia: {code}")

        self.stdout.write(self.style.SUCCESS("Seed do catálogo concluído."))
