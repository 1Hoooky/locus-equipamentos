"""
Testes de `apps.operations.services.create_location()`/`update_location()`
— invariante `type=CLIENTE ⟺ client is not null`, tanto via service
(rejeição amigável) quanto via `CheckConstraint` real no banco (validação
obrigatória #11, parte "Location"), múltiplas unidades (#10) e auditoria
(#15).
"""

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.clients.models import Client
from apps.operations.models import Location, LocationType
from apps.operations.services import LocationUpdateData, NewLocationData, create_location, update_location


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
