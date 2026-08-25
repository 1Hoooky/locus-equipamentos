"""
Regressão do bug relatado (#6): não existia nenhuma `Location` interna do
tipo Estoque/Manutenção para usar em "Retirada"/"Retorno ao
estoque"/"Envio para manutenção" — a regra de compatibilidade
destino×tipo já estava correta (`_REQUIRED_DESTINATION_TYPE`), só faltava
o dado. Corrigido por uma migration de dados idempotente
(`0003_seed_internal_locations`), reaproveitando o `Location` já
existente — sem módulo novo de estoque/manutenção.

Como o teste roda contra o banco de teste (migrado do zero a cada run —
`manage.py test` aplica todas as migrations, inclusive esta), a simples
existência dos registros já prova que a migration funciona e é aplicada
automaticamente; os testes abaixo cobrem as garantias explícitas pedidas:
tipo certo, sem cliente, ativa, utilizável normalmente em movimentações, e
que rodar a função da migration de novo não duplica nada.
"""

from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import Location, LocationType, MovementType
from apps.operations.services import NewMovementData, create_movement
from django.contrib.auth import get_user_model

User = get_user_model()


class SeedInternalLocationsTest(TestCase):
    def test_at_least_one_estoque_location_exists(self):
        self.assertTrue(Location.objects.filter(type=LocationType.ESTOQUE, is_active=True).exists())

    def test_at_least_one_manutencao_location_exists(self):
        self.assertTrue(Location.objects.filter(type=LocationType.MANUTENCAO, is_active=True).exists())

    def test_seeded_locations_have_no_client(self):
        for location in Location.objects.filter(name__in=["Estoque Locus", "Manutenção Locus"]):
            self.assertIsNone(location.client_id)

    def test_seeded_locations_keep_their_expected_types(self):
        estoque = Location.objects.get(name="Estoque Locus")
        manutencao = Location.objects.get(name="Manutenção Locus")
        self.assertEqual(estoque.type, LocationType.ESTOQUE)
        self.assertEqual(manutencao.type, LocationType.MANUTENCAO)

    def test_running_seed_function_again_does_not_duplicate(self):
        """A função da migration é chamada de novo diretamente — precisa continuar idempotente."""
        import importlib

        migration_module = importlib.import_module("apps.operations.migrations.0003_seed_internal_locations")

        count_before = Location.objects.filter(type__in=[LocationType.ESTOQUE, LocationType.MANUTENCAO]).count()
        migration_module.seed_internal_locations(apps=_FakeAppsRegistry(), schema_editor=None)
        count_after = Location.objects.filter(type__in=[LocationType.ESTOQUE, LocationType.MANUTENCAO]).count()
        self.assertEqual(count_before, count_after)

    def test_seeded_estoque_location_can_be_used_normally_in_a_movement(self):
        """"Utilizáveis normalmente em movimentações" — usa a Location semeada como destino real de uma Retirada."""
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Seed", code="AQSD")
        user = User.objects.create_user(username="seed_operador", password="senha-forte-123", role="OPERACIONAL")
        equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=user))

        cliente_unidade = Location.objects.filter(type=LocationType.CLIENTE).first()
        if cliente_unidade is None:
            from apps.clients.models import Client
            from apps.operations.services import NewLocationData, create_location

            cliente = Client.objects.create(company_name="Cliente Seed LTDA")
            cliente_unidade = create_location(
                NewLocationData(name="Unidade Seed", type=LocationType.CLIENTE, client=cliente)
            )

        estoque = Location.objects.get(name="Estoque Locus")

        create_movement(
            NewMovementData(
                equipment_id=equipment.pk, movement_type=MovementType.INSTALACAO,
                created_by=user, destination_location=cliente_unidade,
            )
        )
        movement = create_movement(
            NewMovementData(
                equipment_id=equipment.pk, movement_type=MovementType.RETIRADA,
                created_by=user, destination_location=estoque,
            )
        )
        equipment.refresh_from_db()
        self.assertEqual(equipment.current_location, estoque)
        self.assertEqual(movement.destination_location, estoque)


class _FakeAppsRegistry:
    """Mímica mínima do `apps` de migration (`apps.get_model(...)`) — só o suficiente para reusar `seed_internal_locations` fora do fluxo real de migração."""

    def get_model(self, app_label, model_name):
        from django.apps import apps as real_apps

        return real_apps.get_model(app_label, model_name)
