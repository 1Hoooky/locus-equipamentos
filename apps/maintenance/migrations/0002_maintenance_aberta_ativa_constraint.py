"""
Ajuste de 27/08/2026 (revisão da fundação de apps.maintenance, decisões
4 e 5): a UniqueConstraint "no máximo uma Maintenance ABERTA por
equipamento" passa a exigir também `is_active=True` — `Maintenance` herda
`SoftDeleteModel`, e uma ficha inativada (cadastrada por engano, por
exemplo) nunca deveria prender o equipamento atrás de uma constraint de
banco para sempre. Nenhum dado é migrado aqui: como nenhuma Maintenance
foi soft-deletada até hoje (a fundação não expõe nenhuma operação que
faça isso), esta é uma troca de constraint pura, sem efeito em linhas
existentes.

`status_before.help_text` também foi esclarecido (decisão 5): o campo
representa o status no instante em que A FICHA foi aberta, não
necessariamente "o status antes de qualquer manutenção" — só é usado
para restauração quando `departure_movement` é nulo. Sem rename (não
havia necessidade — só a documentação do campo mudou).
"""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("equipment", "0005_alter_equipment_current_client_and_more"),
        ("maintenance", "0001_initial"),
        ("operations", "0005_deactivate_test_duplicate_locations"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="maintenance",
            name="uniq_maintenance_aberta_por_equipamento",
        ),
        migrations.AlterField(
            model_name="historicalmaintenance",
            name="status_before",
            field=models.CharField(
                blank=True,
                choices=[
                    ("DISPONIVEL", "Disponível"),
                    ("EM_OPERACAO", "Em operação"),
                    ("MANUTENCAO", "Manutenção"),
                    ("INATIVO", "Inativo"),
                ],
                help_text="Status do equipamento no instante em que ESTA FICHA foi aberta — usado para restaurar só quando departure_movement é nulo (esta ficha é dona da transição). Com departure_movement preenchido, este campo vale MANUTENCAO e é apenas informativo (o status genuinamente anterior, se precisar, está em StatusHistory/Movement).",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="maintenance",
            name="status_before",
            field=models.CharField(
                blank=True,
                choices=[
                    ("DISPONIVEL", "Disponível"),
                    ("EM_OPERACAO", "Em operação"),
                    ("MANUTENCAO", "Manutenção"),
                    ("INATIVO", "Inativo"),
                ],
                help_text="Status do equipamento no instante em que ESTA FICHA foi aberta — usado para restaurar só quando departure_movement é nulo (esta ficha é dona da transição). Com departure_movement preenchido, este campo vale MANUTENCAO e é apenas informativo (o status genuinamente anterior, se precisar, está em StatusHistory/Movement).",
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="maintenance",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True), ("status", "ABERTA")),
                fields=("equipment",),
                name="uniq_maintenance_aberta_ativa_por_equipamento",
            ),
        ),
    ]
