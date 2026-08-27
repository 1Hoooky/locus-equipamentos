"""
Testes da data migration `0005_deactivate_test_duplicate_locations` —
encerramento definitivo da limpeza de dados de teste, substituindo a
ferramenta web temporária (removida) que passou a retornar 502 no Render
Free.

Mesma técnica de `test_backfill_principal_locations.py`/
`test_seed_internal_locations.py`: chama a função `RunPython` da migration
diretamente, com um `_FakeAppsRegistry.get_model()` que devolve os models
reais via `django.apps.apps` (o de sempre neste projeto para testar
migrations de dados sem rodar `migrate` de verdade a cada teste).

Cobre os 13 cenários pedidos explicitamente: os três grupos de teste sem
referência (desativados), Location referenciada como origem e como
destino (preservada em ambos os casos — é o caso real da "#2 TESTE"),
nome parecido mas não exato (intocado), Location legítima fora dos três
grupos (intocada), as duas Locations internas (intocadas), Location já
inativa (sem efeito colateral), Movements/Equipment/Client/Address
inalterados, e idempotência ao rodar duas vezes.
"""

import importlib

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import Location, LocationType, Movement, MovementType
from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

User = get_user_model()

_migration = importlib.import_module("apps.operations.migrations.0005_deactivate_test_duplicate_locations")


class _FakeAppsRegistry:
    """Mímica mínima do `apps` de migration — mesma técnica de test_backfill_principal_locations.py."""

    def get_model(self, app_label, model_name):
        from django.apps import apps as real_apps

        return real_apps.get_model(app_label, model_name)


def _run_migration():
    _migration.deactivate_test_duplicate_locations(apps=_FakeAppsRegistry(), schema_editor=None)


def _equipment(created_by):
    n = Category.objects.count()
    category = Category.objects.create(name=f"Categoria {n}")
    model = EquipmentModel.objects.create(category=category, name=f"Modelo {n}", code=f"MD{n}")
    return create_equipment(NewEquipmentData(model_id=model.pk, created_by=created_by))


def _test_location(name, type_=LocationType.ESTOQUE, client=None):
    return create_location(NewLocationData(name=name, type=type_, client=client))


class DeactivateTestDuplicateLocationsMigrationTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="mig_admin", password="senha-forte-123", role="ADMIN")

    # 1-3: os três grupos de teste, sem Movement, ficam is_active=False.
    def test_teste_without_movement_is_deactivated(self):
        location = _test_location("TESTE")
        _run_migration()
        location.refresh_from_db()
        self.assertFalse(location.is_active)

    def test_teste3_without_movement_is_deactivated(self):
        location = _test_location("TESTE3")
        _run_migration()
        location.refresh_from_db()
        self.assertFalse(location.is_active)

    def test_teste2_without_movement_is_deactivated(self):
        location = _test_location("teste2")
        _run_migration()
        location.refresh_from_db()
        self.assertFalse(location.is_active)

    def test_all_three_groups_together_deactivate_exactly_those_without_reference(self):
        """Quantas Locations os testes demonstram que seriam desativadas: 3 candidatas sem referência → 3 desativadas."""
        candidates = [_test_location("TESTE"), _test_location("TESTE3"), _test_location("teste2")]

        _run_migration()

        for location in candidates:
            location.refresh_from_db()
            self.assertFalse(location.is_active)

    # 4-5: referenciada como origem OU como destino → preservada (o caso real da "#2 TESTE").
    def test_teste_referenced_as_origin_stays_active(self):
        cliente = Client.objects.create(company_name="Cliente Origem LTDA")
        estoque = _test_location("Estoque de Teste Origem", type_=LocationType.ESTOQUE)
        referenced = _test_location("TESTE", type_=LocationType.CLIENTE, client=cliente)
        equipment = _equipment(self.admin)
        # Equipamento precisa estar EM_OPERACAO, vindo de `referenced`, para RETIRADA usá-la como origem.
        create_movement(
            NewMovementData(
                equipment_id=equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.admin,
                destination_location=referenced,
            )
        )
        create_movement(
            NewMovementData(
                equipment_id=equipment.pk,
                movement_type=MovementType.RETIRADA,
                created_by=self.admin,
                destination_location=estoque,
            )
        )
        self.assertTrue(Movement.objects.filter(origin_location_id=referenced.pk).exists())

        _run_migration()

        referenced.refresh_from_db()
        self.assertTrue(referenced.is_active)

    def test_teste_referenced_as_destination_stays_active(self):
        """Representa a Location "TESTE" #2 do caso real: tem Movement referenciando como destino, nunca é apagada."""
        cliente = Client.objects.create(company_name="Cliente Destino LTDA")
        referenced = _test_location("TESTE", type_=LocationType.CLIENTE, client=cliente)
        equipment = _equipment(self.admin)
        create_movement(
            NewMovementData(
                equipment_id=equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.admin,
                destination_location=referenced,
            )
        )
        self.assertTrue(Movement.objects.filter(destination_location_id=referenced.pk).exists())

        _run_migration()

        referenced.refresh_from_db()
        self.assertTrue(referenced.is_active)

    def test_referenced_and_unreferenced_teste_locations_together(self):
        """O cenário real completo: um grupo "TESTE" com uma preservada (referência) e uma desativada (sem referência)."""
        cliente = Client.objects.create(company_name="Cliente Misto LTDA")
        sem_ref = _test_location("TESTE", type_=LocationType.CLIENTE, client=cliente)
        com_ref = _test_location("TESTE", type_=LocationType.CLIENTE, client=cliente)
        equipment = _equipment(self.admin)
        create_movement(
            NewMovementData(
                equipment_id=equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.admin,
                destination_location=com_ref,
            )
        )

        _run_migration()

        sem_ref.refresh_from_db()
        com_ref.refresh_from_db()
        self.assertFalse(sem_ref.is_active)
        self.assertTrue(com_ref.is_active)

    # 6: nome parecido, mas não exato → intocado (correspondência exata, nunca icontains/fuzzy).
    def test_similar_but_not_exact_names_are_untouched(self):
        similar = [
            _test_location("teste"),  # minúsculo — não é "TESTE"
            _test_location("TESTE2"),  # não está no allowlist (só teste2 minúsculo está)
            _test_location("TESTE "),  # espaço extra — não é exatamente "TESTE"
            _test_location(" TESTE"),
            _test_location("Teste3"),  # capitalização diferente de "TESTE3"
            _test_location("TESTE33"),
        ]

        _run_migration()

        for location in similar:
            location.refresh_from_db()
            self.assertTrue(location.is_active, f"{location.name!r} não deveria ter sido tocada.")

    # 7: Location legítima fora dos três grupos → intocada.
    def test_legitimate_location_outside_target_groups_is_untouched(self):
        cliente = Client.objects.create(company_name="Cliente Legítimo LTDA")
        legitimate = _test_location("Unidade Legítima", type_=LocationType.CLIENTE, client=cliente)

        _run_migration()

        legitimate.refresh_from_db()
        self.assertTrue(legitimate.is_active)

    # 8-9: Locations internas legítimas (seed da migração 0003) → intocadas.
    def test_estoque_locus_is_untouched(self):
        estoque_interno = Location.objects.get(name="Estoque Locus")
        _run_migration()
        estoque_interno.refresh_from_db()
        self.assertTrue(estoque_interno.is_active)

    def test_manutencao_locus_is_untouched(self):
        manutencao_interna = Location.objects.get(name="Manutenção Locus")
        _run_migration()
        manutencao_interna.refresh_from_db()
        self.assertTrue(manutencao_interna.is_active)

    # 10: Location já inativa → permanece inativa, sem efeito colateral.
    def test_already_inactive_location_stays_inactive_without_side_effects(self):
        location = _test_location("TESTE3")
        location.is_active = False
        location.save(update_fields=["is_active"])
        updated_at_before = Location.objects.get(pk=location.pk).updated_at

        _run_migration()

        location.refresh_from_db()
        self.assertFalse(location.is_active)
        # Não era candidata (já não estava is_active=True) — a migration
        # nem deveria tê-la tocado, então updated_at não muda.
        self.assertEqual(location.updated_at, updated_at_before)

    # 11: Movements existentes permanecem inalterados.
    def test_movements_are_not_modified(self):
        cliente = Client.objects.create(company_name="Cliente Movement Intacto LTDA")
        referenced = _test_location("TESTE", type_=LocationType.CLIENTE, client=cliente)
        equipment = _equipment(self.admin)
        movement = create_movement(
            NewMovementData(
                equipment_id=equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.admin,
                destination_location=referenced,
                reason="Motivo original",
            )
        )
        before = Movement.objects.get(pk=movement.pk)
        before_snapshot = (
            before.movement_type,
            before.origin_location_id,
            before.destination_location_id,
            before.reason,
            before.created_at,
        )

        _run_migration()

        after = Movement.objects.get(pk=movement.pk)
        after_snapshot = (
            after.movement_type,
            after.origin_location_id,
            after.destination_location_id,
            after.reason,
            after.created_at,
        )
        self.assertEqual(before_snapshot, after_snapshot)
        self.assertEqual(Movement.objects.count(), 1)

    # 12: Equipment/Client/Address permanecem inalterados.
    def test_equipment_client_and_address_are_not_modified(self):
        from apps.core.models import Address

        address = Address.objects.create(logradouro="Rua Intocada", numero="100")
        cliente = Client.objects.create(company_name="Cliente Intacto LTDA")
        referenced = _test_location("TESTE", type_=LocationType.CLIENTE, client=cliente, )
        referenced.address = address
        referenced.save(update_fields=["address"])

        sem_ref = _test_location("TESTE3")

        equipment = _equipment(self.admin)
        create_movement(
            NewMovementData(
                equipment_id=equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.admin,
                destination_location=referenced,
            )
        )

        equipment.refresh_from_db()
        equipment_before = (equipment.status, equipment.current_location_id, equipment.current_client_id, equipment.updated_at)
        cliente_before = (cliente.company_name, cliente.is_active)
        cliente_updated_at_before = Client.objects.get(pk=cliente.pk).updated_at
        address_before = (address.logradouro, address.numero, address.updated_at)

        _run_migration()

        equipment.refresh_from_db()
        cliente.refresh_from_db()
        address.refresh_from_db()

        self.assertEqual(
            (equipment.status, equipment.current_location_id, equipment.current_client_id, equipment.updated_at),
            equipment_before,
        )
        self.assertEqual((cliente.company_name, cliente.is_active), cliente_before)
        self.assertEqual(Client.objects.get(pk=cliente.pk).updated_at, cliente_updated_at_before)
        self.assertEqual((address.logradouro, address.numero, address.updated_at), address_before)
        # A Location sem referência do MESMO cliente foi desativada — prova
        # que a migration mexeu em Location, mas não vazou nenhum efeito
        # para Equipment/Client/Address.
        sem_ref.refresh_from_db()
        self.assertFalse(sem_ref.is_active)

    # 13: rodar a lógica de novo produz resultado idempotente.
    def test_running_twice_is_idempotent(self):
        cliente = Client.objects.create(company_name="Cliente Idempotência Migration LTDA")
        sem_ref = _test_location("TESTE")
        com_ref = _test_location("TESTE3", type_=LocationType.CLIENTE, client=cliente)
        equipment = _equipment(self.admin)
        create_movement(
            NewMovementData(
                equipment_id=equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.admin,
                destination_location=com_ref,
            )
        )

        _run_migration()
        sem_ref.refresh_from_db()
        com_ref.refresh_from_db()
        self.assertFalse(sem_ref.is_active)
        self.assertTrue(com_ref.is_active)
        updated_at_after_first_run = Location.objects.get(pk=sem_ref.pk).updated_at

        _run_migration()  # segunda execução — não deve fazer nada a mais

        sem_ref.refresh_from_db()
        com_ref.refresh_from_db()
        self.assertFalse(sem_ref.is_active)
        self.assertTrue(com_ref.is_active)
        # A segunda execução nem tocou na linha (já não era mais candidata:
        # is_active já era False) — updated_at não muda de novo.
        self.assertEqual(Location.objects.get(pk=sem_ref.pk).updated_at, updated_at_after_first_run)

    def test_running_twice_with_nothing_new_deactivates_nothing_extra(self):
        _test_location("teste2")
        _run_migration()
        active_count_after_first = Location.objects.filter(is_active=True).count()

        _run_migration()

        self.assertEqual(Location.objects.filter(is_active=True).count(), active_count_after_first)
