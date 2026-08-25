"""
Testes de `Address` — Fase 2 (Operação, v1.1 delta seção 5): auditoria
própria (django-simple-history), e a garantia de que editar um `Address`
referenciado por um `Client`/`Location` NÃO altera a linha do
`Client`/`Location` em si (histórico de cada um é independente — mesmo
padrão já validado em `EquipmentModel`/`Equipment` na Fase 1).
"""

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.clients.models import Client
from apps.core.models import Address
from apps.core.services import AddressData, create_address, update_address
from apps.operations.models import Location, LocationType


class AddressHistoryTest(TestCase):
    """Validação obrigatória #15: auditoria de Address."""

    def test_editing_address_creates_history_entry(self):
        address = create_address(AddressData(cep="80000-000", logradouro="Rua Um", cidade="Curitiba", uf="PR"))
        self.assertEqual(address.history.count(), 1)

        update_address(address=address, data=AddressData(cep="80000-000", logradouro="Rua Dois", cidade="Curitiba", uf="PR"))
        address.refresh_from_db()

        self.assertEqual(address.logradouro, "Rua Dois")
        self.assertEqual(address.history.count(), 2)

    def test_editing_address_via_client_fiscal_address_does_not_touch_client_history(self):
        """
        Confirma a decisão registrada no delta v1.1 (seção 5): editar só o
        Address relacionado NÃO gera entrada no histórico do Client, porque
        a linha do Client não muda (a FK continua igual) — por isso Address
        precisa do próprio `HistoricalRecords()`.
        """
        client = Client.objects.create(company_name="Cliente Endereço LTDA")
        address = create_address(AddressData(cep="80000-000", cidade="Curitiba", uf="PR"))
        client.fiscal_address = address
        client._change_reason = "Vínculo de endereço fiscal (setup de teste)."
        client.save()

        client_history_count_before = client.history.count()

        update_address(address=address, data=AddressData(cep="80000-000", cidade="Curitiba Nova", uf="PR"))

        self.assertEqual(client.history.count(), client_history_count_before)
        self.assertEqual(address.history.count(), 2)


class AddressProtectOnDeleteTest(TestCase):
    """Validação obrigatória #12 (parcial) / v1.1 delta seção 5: PROTECT em Address referenciado."""

    def test_deleting_fiscal_address_referenced_by_client_is_blocked(self):
        address = create_address(AddressData(cep="80000-000", cidade="Curitiba", uf="PR"))
        Client.objects.create(company_name="Cliente Protegido LTDA", fiscal_address=address)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                address.delete()

    def test_deleting_operational_address_referenced_by_location_is_blocked(self):
        address = create_address(AddressData(cep="80000-000", cidade="Curitiba", uf="PR"))
        Location.objects.create(name="Estoque Central", type=LocationType.ESTOQUE, address=address)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                address.delete()


class AddressCreateHelperTest(TestCase):
    def test_blank_address_data_creates_nothing(self):
        self.assertIsNone(create_address(None))
        self.assertIsNone(create_address(AddressData()))

    def test_non_blank_creates_independent_rows_even_with_identical_values(self):
        """v1.0, seção 6: 'usar fiscal como entrega' nunca compartilha a mesma linha."""
        data = AddressData(cep="80000-000", logradouro="Rua Igual", cidade="Curitiba", uf="PR")
        first = create_address(data)
        second = create_address(data)

        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(Address.objects.filter(logradouro="Rua Igual").count(), 2)
