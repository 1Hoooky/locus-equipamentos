"""
Testes do backfill do 3º reteste manual
(`0004_backfill_principal_locations`): clientes anteriores à criação
automática da Location principal não apareciam no seletor de instalação
(o seletor lista Locations, e eles não tinham nenhuma
`Location(type=CLIENTE)` ativa).

Os clientes "legados" são simulados com `Client.objects.create()` direto
(exatamente como os cadastros antigos ficaram no banco: sem Location) —
`create_client()` atual não consegue mais produzir esse estado, o que é
justamente o ponto: o service novo protege os cadastros novos, e o
backfill conserta os antigos.
"""

import importlib

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.clients.models import Client
from apps.core.models import Address
from apps.operations.models import Location, LocationType

User = get_user_model()

_migration = importlib.import_module("apps.operations.migrations.0004_backfill_principal_locations")


class _FakeAppsRegistry:
    """Mímica mínima do `apps` de migration — mesma técnica de test_seed_internal_locations."""

    def get_model(self, app_label, model_name):
        from django.apps import apps as real_apps

        return real_apps.get_model(app_label, model_name)


def _run_backfill():
    _migration.backfill_principal_locations(apps=_FakeAppsRegistry(), schema_editor=None)


class BackfillPrincipalLocationsTest(TestCase):
    def test_legacy_client_without_location_gains_exactly_one_principal(self):
        legacy = Client.objects.create(company_name="Cliente Legado LTDA")
        self.assertFalse(Location.objects.filter(client=legacy).exists())

        _run_backfill()

        locations = Location.objects.filter(client=legacy)
        self.assertEqual(locations.count(), 1)
        principal = locations.get()
        self.assertEqual(principal.name, "Unidade principal")
        self.assertEqual(principal.type, LocationType.CLIENTE)
        self.assertTrue(principal.is_active)

    def test_fiscal_address_values_are_copied_into_an_independent_row(self):
        fiscal = Address.objects.create(cep="80000-000", logradouro="Rua Fiscal Legada", numero="10", cidade="Curitiba", uf="PR")
        legacy = Client.objects.create(company_name="Cliente Legado Com Fiscal LTDA", fiscal_address=fiscal)

        _run_backfill()

        principal = Location.objects.get(client=legacy)
        self.assertIsNotNone(principal.address_id)
        self.assertNotEqual(principal.address_id, fiscal.pk)  # linha NOVA, nunca a mesma FK
        self.assertEqual(principal.address.logradouro, "Rua Fiscal Legada")

        # Independência preservada: editar o fiscal depois não altera o operacional...
        fiscal.logradouro = "Rua Fiscal Editada Depois"
        fiscal.save()
        principal.address.refresh_from_db()
        self.assertEqual(principal.address.logradouro, "Rua Fiscal Legada")

        # ...e vice-versa.
        principal.address.logradouro = "Rua Operacional Editada"
        principal.address.save()
        fiscal.refresh_from_db()
        self.assertEqual(fiscal.logradouro, "Rua Fiscal Editada Depois")

    def test_existing_inactive_unit_address_is_preferred_over_fiscal(self):
        """"Use o endereço operacional existente quando houver" — a unidade inativa com endereço é a fonte preferida."""
        fiscal = Address.objects.create(logradouro="Rua Fiscal")
        operational = Address.objects.create(logradouro="Rua Operacional Antiga", reference_notes="portão azul")
        legacy = Client.objects.create(company_name="Cliente Com Unidade Inativa LTDA", fiscal_address=fiscal)
        Location.objects.create(
            name="Unidade Desativada", type=LocationType.CLIENTE, client=legacy, address=operational, is_active=False
        )

        _run_backfill()

        principal = Location.objects.get(client=legacy, is_active=True)
        self.assertEqual(principal.address.logradouro, "Rua Operacional Antiga")
        self.assertEqual(principal.address.reference_notes, "portão azul")
        self.assertNotEqual(principal.address_id, operational.pk)  # cópia, não reaproveitamento
        # A unidade inativa continua exatamente como estava.
        self.assertTrue(Location.objects.filter(pk__in=[principal.pk]).exists())
        self.assertFalse(Location.objects.get(name="Unidade Desativada").is_active)

    def test_client_with_active_location_is_untouched(self):
        ok_client = Client.objects.create(company_name="Cliente Já Migrado LTDA")
        existing = Location.objects.create(
            name="Matriz", type=LocationType.CLIENTE, client=ok_client, is_active=True
        )

        _run_backfill()

        self.assertEqual(Location.objects.filter(client=ok_client).count(), 1)
        self.assertEqual(Location.objects.get(client=ok_client).pk, existing.pk)

    def test_inactive_client_is_untouched(self):
        inactive = Client.objects.create(company_name="Cliente Inativo LTDA", is_active=False)

        _run_backfill()

        self.assertFalse(Location.objects.filter(client=inactive).exists())

    def test_backfill_is_idempotent(self):
        legacy = Client.objects.create(company_name="Cliente Idempotência LTDA")

        _run_backfill()
        _run_backfill()

        self.assertEqual(Location.objects.filter(client=legacy).count(), 1)


class LegacyClientAppearsInInstallationSelectorTest(TestCase):
    """Depois do backfill, o cliente antigo aparece como destino de instalação — o sintoma exato do reteste."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="instalador_legado", password="senha-forte-123", role="OPERACIONAL"
        )
        self.client.login(username="instalador_legado", password="senha-forte-123")

        from apps.catalog.models import Category, EquipmentModel
        from apps.equipment.services import NewEquipmentData, create_equipment

        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Legado", code="AQLG")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.user))

    def test_legacy_client_becomes_selectable_after_backfill(self):
        legacy = Client.objects.create(company_name="Empresa Antiga LTDA", trade_name="Empresa Antiga")

        # Antes do backfill: invisível (o sintoma relatado).
        response = self.client.get(f"/operacao/movimentar/{self.equipment.patrimonio}/")
        self.assertNotIn("Empresa Antiga", response.content.decode())

        _run_backfill()

        # Depois: aparece — e, por ter UMA unidade, como "Empresa Antiga"
        # puro, sem sufixo artificial.
        response = self.client.get(f"/operacao/movimentar/{self.equipment.patrimonio}/")
        content = response.content.decode()
        self.assertIn(">Empresa Antiga<", content)
        self.assertNotIn("Empresa Antiga — Unidade principal", content)

    def test_new_clients_keep_appearing_normally(self):
        from apps.clients.services import NewClientData, create_client

        create_client(
            NewClientData(
                client_type="PJ", company_name="Empresa Nova LTDA", trade_name="Empresa Nova",
                document="11.222.333/0001-81",
            )
        )
        response = self.client.get(f"/operacao/movimentar/{self.equipment.patrimonio}/")
        self.assertIn(">Empresa Nova<", response.content.decode())
