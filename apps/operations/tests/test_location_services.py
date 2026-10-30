"""
Testes de `apps.operations.services.create_location()`/`update_location()`
— invariante `type=CLIENTE ⟺ client is not null`, tanto via service
(rejeição amigável) quanto via `CheckConstraint` real no banco (validação
obrigatória #11, parte "Location"), múltiplas unidades (#10) e auditoria
(#15).
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.models import Status
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import Location, LocationType, MovementType
from apps.operations.services import (
    LocationUpdateData,
    NewLocationData,
    NewMovementData,
    create_location,
    create_movement,
    update_location,
)

User = get_user_model()


class CreateLocationTest(TestCase):
    def setUp(self):
        self.client_record = Client.objects.create(company_name="Cliente Unidades LTDA")

    def test_creates_estoque_location_without_client(self):
        location = create_location(NewLocationData(name="Estoque Central", type=LocationType.ESTOQUE))
        self.assertIsNone(location.client)
        self.assertEqual(location.type, LocationType.ESTOQUE)

    def test_creates_cliente_location_with_client(self):
        location = create_location(
            NewLocationData(name="Unidade Cliente", type=LocationType.CLIENTE, client=self.client_record)
        )
        self.assertEqual(location.client, self.client_record)

    def test_cliente_type_without_client_is_rejected_by_service(self):
        with self.assertRaises(ValueError):
            create_location(NewLocationData(name="Unidade Sem Cliente", type=LocationType.CLIENTE, client=None))

    def test_non_cliente_type_with_client_is_rejected_by_service(self):
        with self.assertRaises(ValueError):
            create_location(NewLocationData(name="Estoque Com Cliente", type=LocationType.ESTOQUE, client=self.client_record))

    def test_multiple_locations_for_same_client(self):
        """Validação obrigatória #10: múltiplas unidades para o mesmo cliente."""
        first = create_location(NewLocationData(name="Unidade A", type=LocationType.CLIENTE, client=self.client_record))
        second = create_location(NewLocationData(name="Unidade B", type=LocationType.CLIENTE, client=self.client_record))
        self.assertEqual(set(self.client_record.locations.values_list("pk", flat=True)), {first.pk, second.pk})

    def test_creation_recorded_in_history(self):
        location = create_location(NewLocationData(name="Estoque Auditado", type=LocationType.ESTOQUE))
        self.assertEqual(location.history.count(), 1)


class LocationCheckConstraintTest(TestCase):
    """A mesma regra tem que ser rejeitada pelo BANCO, não só pelo service (delta v1.1, seção 10/11)."""

    def test_database_rejects_cliente_type_without_client(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Location.objects.create(name="Direto Sem Cliente", type=LocationType.CLIENTE, client=None)

    def test_database_rejects_estoque_type_with_client(self):
        client_record = Client.objects.create(company_name="Cliente Direto LTDA")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Location.objects.create(name="Direto Com Cliente", type=LocationType.ESTOQUE, client=client_record)


class UpdateLocationTest(TestCase):
    def setUp(self):
        self.location = create_location(NewLocationData(name="Unidade Original", type=LocationType.ESTOQUE))

    def test_update_name_and_type(self):
        update_location(location=self.location, data=LocationUpdateData(name="Unidade Renomeada", type=LocationType.ESTOQUE))
        self.location.refresh_from_db()
        self.assertEqual(self.location.name, "Unidade Renomeada")

    def test_update_rejects_invalid_client_type_combination(self):
        with self.assertRaises(ValueError):
            update_location(
                location=self.location,
                data=LocationUpdateData(name="Unidade Original", type=LocationType.CLIENTE, client=None),
            )

    def test_update_changes_client_and_type_freely_when_no_equipment(self):
        """Location SEM Equipment: client/type continuam livremente editáveis (especificação, ponto 1)."""
        cliente = Client.objects.create(company_name="Cliente Sem Equipamento LTDA")
        update_location(
            location=self.location,
            data=LocationUpdateData(name=self.location.name, type=LocationType.CLIENTE, client=cliente),
        )
        self.location.refresh_from_db()
        self.assertEqual(self.location.type, LocationType.CLIENTE)
        self.assertEqual(self.location.client_id, cliente.pk)


class UpdateLocationWithEquipmentTest(TestCase):
    """
    P0-05/OPS-001 — especificação de implementação, pontos 1/2/3/8/11:
    uma Location com Equipment presente (`current_location` + ativo) não
    pode ter `client`/`type` alterado por `update_location()`; `name`
    continua livre; uma tentativa rejeitada não deixa nem a Location nem
    o Equipment em estado parcial; a proteção nunca depende de
    `Equipment.status`.
    """

    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor OPS-001", code="AQOP")
        self.operador = User.objects.create_user(username="ops_001_operador", password="senha-forte-123", role="OPERACIONAL")

        self.cliente_a = Client.objects.create(company_name="Cliente OPS-001 A LTDA")
        self.cliente_b = Client.objects.create(company_name="Cliente OPS-001 B LTDA")
        self.location = create_location(
            NewLocationData(name="Unidade OPS-001 A", type=LocationType.CLIENTE, client=self.cliente_a)
        )
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.operador))
        create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.operador,
                destination_location=self.location,
            )
        )
        self.equipment.refresh_from_db()

    def test_rejects_client_change_while_equipment_present(self):
        with self.assertRaises(ValueError) as ctx:
            update_location(
                location=self.location,
                data=LocationUpdateData(name=self.location.name, type=LocationType.CLIENTE, client=self.cliente_b),
            )
        self.assertIn("Movimente os equipamentos primeiro", str(ctx.exception))

    def test_rejects_type_change_while_equipment_present(self):
        # ESTOQUE não aceita client — então o teste muda type sem tentar
        # mudar client ao mesmo tempo, isolando exatamente qual dos dois
        # campos estruturais está sendo testado.
        with self.assertRaises(ValueError):
            update_location(
                location=self.location,
                data=LocationUpdateData(name=self.location.name, type=LocationType.ESTOQUE, client=None),
            )

    def test_allows_renaming_while_equipment_present(self):
        update_location(
            location=self.location,
            data=LocationUpdateData(name="Unidade OPS-001 Renomeada", type=LocationType.CLIENTE, client=self.cliente_a),
        )
        self.location.refresh_from_db()
        self.assertEqual(self.location.name, "Unidade OPS-001 Renomeada")
        # client/type continuam exatamente os mesmos.
        self.assertEqual(self.location.client_id, self.cliente_a.pk)
        self.assertEqual(self.location.type, LocationType.CLIENTE)

    def test_rejected_attempt_leaves_location_and_equipment_intact(self):
        original_client_id = self.location.client_id
        original_type = self.location.type
        original_equipment_client_id = self.equipment.current_client_id
        original_equipment_location_id = self.equipment.current_location_id

        with self.assertRaises(ValueError):
            update_location(
                location=self.location,
                data=LocationUpdateData(name=self.location.name, type=LocationType.CLIENTE, client=self.cliente_b),
            )

        self.location.refresh_from_db()
        self.equipment.refresh_from_db()
        self.assertEqual(self.location.client_id, original_client_id)
        self.assertEqual(self.location.type, original_type)
        self.assertEqual(self.equipment.current_client_id, original_equipment_client_id)
        self.assertEqual(self.equipment.current_location_id, original_equipment_location_id)
        # Nenhum Movement "fantasma" foi criado pela tentativa rejeitada —
        # a edição nunca se transforma em movimentação silenciosa (ponto 8).
        self.assertEqual(self.equipment.movements.count(), 1)

    def test_protection_never_depends_on_equipment_status(self):
        """
        Especificação, ponto 2: a proteção nunca usa `exclude(status=...)`
        nem "só equipamento ativo [operacionalmente]" — vale para
        DISPONIVEL/EM_OPERACAO/MANUTENCAO igualmente, sempre que
        `current_location` aponta para esta Location e o registro está
        `is_active=True` (soft-delete).
        """
        from apps.equipment.services import change_status

        for status in (Status.DISPONIVEL, Status.EM_OPERACAO, Status.MANUTENCAO):
            with self.subTest(status=status):
                change_status(equipment=self.equipment, new_status=status, reason="Ajuste de teste.", changed_by=self.operador)
                with self.assertRaises(ValueError):
                    update_location(
                        location=self.location,
                        data=LocationUpdateData(name=self.location.name, type=LocationType.CLIENTE, client=self.cliente_b),
                    )

    def test_soft_deleted_equipment_does_not_block_the_change(self):
        """
        Ponto 2 da especificação: só Equipment "corrente/visível pelo
        manager operacional normal" conta — um registro `is_active=False`
        (soft-delete) não deve, por si só, travar a edição estrutural.
        """
        self.equipment.is_active = False
        self.equipment.save(update_fields=["is_active"])

        update_location(
            location=self.location,
            data=LocationUpdateData(name=self.location.name, type=LocationType.CLIENTE, client=self.cliente_b),
        )
        self.location.refresh_from_db()
        self.assertEqual(self.location.client_id, self.cliente_b.pk)
