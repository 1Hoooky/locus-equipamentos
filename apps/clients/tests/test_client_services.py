"""
Testes de `apps.clients.services` — `create_client()`/`update_client()`.
Cobre: normalização/duplicidade de documento (inclusive contra cliente
inativo), independência entre endereço fiscal e endereço de entrega
(validação obrigatória #9), unidade inicial (#10), e auditoria (#15).

Decisão revista a pedido do usuário: o CNPJ/CPF passou a ser o campo
OBRIGATÓRIO do cadastro (a razão social virou opcional) — o inverso do
que valia antes. `document` é exigido em `create_client()`/`update_client()`
independentemente de `company_name` estar preenchido.
"""

from django.test import TestCase

from apps.clients.models import Client, ClientType
from apps.clients.services import (
    ClientUpdateData,
    NewClientData,
    create_client,
    update_client,
)
from apps.core.services import AddressData
from apps.operations.models import Location, LocationType

VALID_CNPJ = "11.222.333/0001-81"
OTHER_VALID_CNPJ = "11.444.777/0001-61"


class CreateClientTest(TestCase):
    def test_creates_client_with_normalized_document(self):
        client = create_client(NewClientData(client_type=ClientType.PJ, company_name="Locus Cliente LTDA", document=VALID_CNPJ))
        self.assertEqual(client.document, "11222333000181")
        self.assertEqual(client.pk is not None, True)

    def test_company_name_is_optional(self):
        """Razão social virou opcional — o CNPJ é que é obrigatório agora."""
        client = create_client(NewClientData(client_type=ClientType.PJ, company_name="", document=VALID_CNPJ))
        self.assertEqual(client.company_name, "")
        self.assertEqual(client.document, "11222333000181")

    def test_document_is_required(self):
        with self.assertRaises(ValueError):
            create_client(NewClientData(client_type=ClientType.PJ, company_name="Cliente Sem CNPJ LTDA", document=""))

    def test_document_with_only_non_digit_characters_is_still_rejected_as_required(self):
        """Documento que normaliza para vazio (só caracteres não numéricos) também conta como ausente."""
        with self.assertRaises(ValueError):
            create_client(NewClientData(client_type=ClientType.PJ, company_name="Cliente X", document="--/."))

    def test_invalid_document_checksum_is_rejected(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            create_client(NewClientData(client_type=ClientType.PJ, company_name="Cliente X", document="11222333000180"))

    def test_duplicate_document_is_rejected(self):
        create_client(NewClientData(client_type=ClientType.PJ, company_name="Cliente Um", document=VALID_CNPJ))
        with self.assertRaises(ValueError):
            create_client(NewClientData(client_type=ClientType.PJ, company_name="Cliente Dois (mesmo CNPJ)", document=VALID_CNPJ))

    def test_duplicate_document_rejected_even_against_inactive_client(self):
        """v1.0, seção 12: duplicidade checada 'inclusive contra cliente inativo'."""
        existing = create_client(NewClientData(client_type=ClientType.PJ, company_name="Cliente Inativo", document=VALID_CNPJ))
        existing.is_active = False
        existing.save(update_fields=["is_active"])

        with self.assertRaises(ValueError):
            create_client(NewClientData(client_type=ClientType.PJ, company_name="Cliente Novo", document=VALID_CNPJ))

    def test_legacy_clients_without_document_do_not_collide_at_db_level(self):
        """
        `document` passou a ser exigido por `create_client()`, mas a
        constraint do model (`uniq_client_document_when_present`) continua
        condicionada a "não vazio" — clientes legados/criados fora do
        service (ex.: import antigo) sem documento continuam podendo
        coexistir sem colidir.
        """
        Client.objects.create(company_name="Sem Documento Um")
        Client.objects.create(company_name="Sem Documento Dois")
        self.assertEqual(Client.objects.filter(document="").count(), 2)

    def test_creation_is_recorded_in_history(self):
        client = create_client(
            NewClientData(client_type=ClientType.PJ, company_name="Cliente Auditado LTDA", document=VALID_CNPJ)
        )
        self.assertEqual(client.history.count(), 1)
        self.assertEqual(client.history.first().history_type, "+")


class FiscalAndOperationalAddressIndependenceTest(TestCase):
    """Validação obrigatória #9: endereço fiscal e operacional são registros `Address` distintos."""

    def test_fiscal_and_initial_location_addresses_are_distinct_rows_even_with_same_values(self):
        same_values = AddressData(cep="80000-000", logradouro="Rua Comum", numero="100", cidade="Curitiba", uf="PR")

        client = create_client(
            NewClientData(
                client_type=ClientType.PJ,
                company_name="Cliente Endereço Único LTDA",
                document=VALID_CNPJ,
                fiscal_address=same_values,
                initial_location_name="Unidade Matriz",
                initial_location_address=same_values,
            )
        )

        location = Location.objects.get(client=client)
        self.assertIsNotNone(client.fiscal_address_id)
        self.assertIsNotNone(location.address_id)
        self.assertNotEqual(client.fiscal_address_id, location.address_id)

        # Editar um não pode alterar o outro.
        client.fiscal_address.logradouro = "Rua Só Do Fiscal"
        client.fiscal_address.save()
        location.address.refresh_from_db()
        self.assertEqual(location.address.logradouro, "Rua Comum")

    def test_initial_location_created_as_client_type_and_linked(self):
        """Validação obrigatória #10 (parte 1): unidade inicial criada junto com o cliente."""
        client = create_client(
            NewClientData(
                client_type=ClientType.PJ,
                company_name="Cliente Com Unidade LTDA",
                document=VALID_CNPJ,
                initial_location_name="Unidade Inicial",
            )
        )
        location = Location.objects.get(client=client)
        self.assertEqual(location.type, LocationType.CLIENTE)
        self.assertEqual(location.name, "Unidade Inicial")

    def test_no_initial_location_created_when_not_requested(self):
        client = create_client(
            NewClientData(client_type=ClientType.PJ, company_name="Cliente Sem Unidade LTDA", document=VALID_CNPJ)
        )
        self.assertFalse(Location.objects.filter(client=client).exists())


class UpdateClientTest(TestCase):
    def setUp(self):
        self.client_record = create_client(
            NewClientData(client_type=ClientType.PJ, company_name="Cliente Original LTDA", document=VALID_CNPJ)
        )

    def test_document_is_editable_after_creation(self):
        """Decisão v1.0 seção 15.5 / confirmada v1.1: document pode ser editado depois."""
        update_client(
            client=self.client_record,
            data=ClientUpdateData(
                client_type=ClientType.PJ, company_name="Cliente Original LTDA", document=OTHER_VALID_CNPJ
            ),
        )
        self.client_record.refresh_from_db()
        self.assertEqual(self.client_record.document, "11444777000161")

    def test_updating_to_duplicate_document_is_rejected(self):
        create_client(NewClientData(client_type=ClientType.PJ, company_name="Outro Cliente LTDA", document=OTHER_VALID_CNPJ))
        with self.assertRaises(ValueError):
            update_client(
                client=self.client_record,
                data=ClientUpdateData(
                    client_type=ClientType.PJ, company_name="Cliente Original LTDA", document=OTHER_VALID_CNPJ
                ),
            )

    def test_update_is_recorded_in_history_with_reason(self):
        history_count_before = self.client_record.history.count()
        update_client(
            client=self.client_record,
            data=ClientUpdateData(
                client_type=ClientType.PJ,
                company_name="Cliente Original LTDA",
                document=VALID_CNPJ,
                phone="41999999999",
                change_reason="Correção de telefone.",
            ),
        )
        self.client_record.refresh_from_db()
        self.assertEqual(self.client_record.history.count(), history_count_before + 1)
        self.assertEqual(self.client_record.history.first().history_change_reason, "Correção de telefone.")

    def test_document_is_required_on_update_too(self):
        with self.assertRaises(ValueError):
            update_client(
                client=self.client_record,
                data=ClientUpdateData(client_type=ClientType.PJ, company_name="Cliente Original LTDA", document=""),
            )

    def test_company_name_is_optional_on_update(self):
        update_client(
            client=self.client_record,
            data=ClientUpdateData(client_type=ClientType.PJ, company_name="", document=VALID_CNPJ),
        )
        self.client_record.refresh_from_db()
        self.assertEqual(self.client_record.company_name, "")
