"""
Listagens de Manutenção/Higienização: filtros, paginação preservando
filtros ao trocar de página (mesmo mecanismo genérico de
`apps.core.templatetags.pagination_tags.url_replace`, já usado por
`equipment/list.html`), e ausência de N+1 em Equipment/Modelo/Responsável
— query count não pode CRESCER com mais registros (mesmo raciocínio de
`apps.operations.tests.test_duplicate_locations_report`: comparar a
contagem entre poucos e muitos registros, nunca fixar um número mágico
sensível a mudanças de middleware/autenticação).
"""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.maintenance.models import MaintenanceStatus, MaintenanceType
from apps.maintenance.services import NewCleaningData, NewMaintenanceData, create_cleaning, open_maintenance

User = get_user_model()


class ListingsTestBase(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Categoria Listagem")
        self.model = EquipmentModel.objects.create(category=self.category, name="Modelo Listagem", code="LIST")
        self.tecnico = User.objects.create_user(username="list_tecnico", password="senha-forte-123", role=Role.OPERACIONAL)
        self.admin = User.objects.create_user(username="list_admin", password="senha-forte-123", role=Role.ADMIN)
        self.client.login(username="list_admin", password="senha-forte-123")
        self._equipment_counter = 0

    def _equipment(self, suffix):
        # Contador crescente (nunca reiniciado entre chamadas) — evita
        # colisão de `code` quando o MESMO teste chama `_equipment()`
        # várias vezes com o mesmo prefixo (ex.: duas rodadas de
        # `_make_n()` para provar ausência de N+1).
        self._equipment_counter += 1
        model = EquipmentModel.objects.create(
            category=self.category, name=f"Modelo {suffix}", code=f"M{self._equipment_counter}{suffix}"[:20]
        )
        return create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))


class MaintenanceFiltersTest(ListingsTestBase):
    def test_filtro_por_status(self):
        aberta_eq = self._equipment("A")
        concluida_eq = self._equipment("B")
        open_maintenance(
            NewMaintenanceData(equipment_id=aberta_eq.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin)
        )
        from apps.maintenance.services import CloseMaintenanceData, close_maintenance

        concluida = open_maintenance(
            NewMaintenanceData(equipment_id=concluida_eq.pk, maintenance_type="PREVENTIVA", responsible=self.tecnico, created_by=self.admin)
        )
        close_maintenance(maintenance=concluida, data=CloseMaintenanceData(service_performed="Feito.", closed_by=self.tecnico))

        response = self.client.get("/manutencao/manutencoes/?status=ABERTA")
        self.assertEqual(response.status_code, 200)
        patrimonios = [m.equipment.patrimonio for m in response.context["maintenances"]]
        self.assertIn(aberta_eq.patrimonio, patrimonios)
        self.assertNotIn(concluida_eq.patrimonio, patrimonios)

    def test_filtro_por_tipo(self):
        preventiva_eq = self._equipment("C")
        corretiva_eq = self._equipment("D")
        open_maintenance(
            NewMaintenanceData(equipment_id=preventiva_eq.pk, maintenance_type="PREVENTIVA", responsible=self.tecnico, created_by=self.admin)
        )
        open_maintenance(
            NewMaintenanceData(equipment_id=corretiva_eq.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin)
        )
        response = self.client.get("/manutencao/manutencoes/?maintenance_type=PREVENTIVA")
        patrimonios = [m.equipment.patrimonio for m in response.context["maintenances"]]
        self.assertIn(preventiva_eq.patrimonio, patrimonios)
        self.assertNotIn(corretiva_eq.patrimonio, patrimonios)

    def test_busca_por_patrimonio(self):
        alvo = self._equipment("E")
        outro = self._equipment("F")
        open_maintenance(
            NewMaintenanceData(equipment_id=alvo.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin)
        )
        open_maintenance(
            NewMaintenanceData(equipment_id=outro.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin)
        )
        response = self.client.get(f"/manutencao/manutencoes/?q={alvo.patrimonio}")
        patrimonios = [m.equipment.patrimonio for m in response.context["maintenances"]]
        self.assertEqual(patrimonios, [alvo.patrimonio])


class MaintenancePaginationTest(ListingsTestBase):
    def test_paginacao_preserva_filtro_ao_trocar_de_pagina(self):
        for i in range(55):
            eq = self._equipment(f"P{i}")
            open_maintenance(
                NewMaintenanceData(equipment_id=eq.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin)
            )

        response = self.client.get("/manutencao/manutencoes/?status=ABERTA")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_paginated"])
        self.assertContains(response, 'name="status"')

        # O link "Próxima" (montado via url_replace, mesmo mecanismo já
        # corrigido para equipment/list.html) precisa preservar o filtro.
        self.assertContains(response, "status=ABERTA")

        page2 = self.client.get("/manutencao/manutencoes/?status=ABERTA&page=2")
        self.assertEqual(page2.status_code, 200)
        self.assertEqual(page2.context["selected_status"], "ABERTA")
        for m in page2.context["maintenances"]:
            self.assertEqual(m.status, MaintenanceStatus.ABERTA)


class MaintenanceListQueryCountTest(ListingsTestBase):
    def _make_n(self, n):
        for i in range(n):
            eq = self._equipment(f"Q{i}")
            open_maintenance(
                NewMaintenanceData(equipment_id=eq.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin)
            )

    def test_query_count_nao_cresce_com_mais_manutencoes(self):
        self._make_n(3)
        with CaptureQueriesContext(connection) as small:
            self.client.get("/manutencao/manutencoes/")
        small_count = len(small.captured_queries)

        self._make_n(20)
        with CaptureQueriesContext(connection) as large:
            self.client.get("/manutencao/manutencoes/")
        large_count = len(large.captured_queries)

        self.assertEqual(small_count, large_count)


class CleaningListQueryCountTest(ListingsTestBase):
    def _make_n(self, n):
        for i in range(n):
            eq = self._equipment(f"C{i}")
            create_cleaning(NewCleaningData(equipment_id=eq.pk, responsible=self.tecnico, created_by=self.admin))

    def test_query_count_nao_cresce_com_mais_higienizacoes(self):
        self._make_n(3)
        with CaptureQueriesContext(connection) as small:
            self.client.get("/manutencao/higienizacoes/")
        small_count = len(small.captured_queries)

        self._make_n(20)
        with CaptureQueriesContext(connection) as large:
            self.client.get("/manutencao/higienizacoes/")
        large_count = len(large.captured_queries)

        self.assertEqual(small_count, large_count)


class EquipmentFichaSummaryQueryCountTest(ListingsTestBase):
    """A seção resumida da ficha (`get_equipment_maintenance_summary`) usa duas queries fixas, sem N+1."""

    def test_query_count_nao_cresce_com_mais_eventos_no_mesmo_equipamento(self):
        equipment = self._equipment("SUMMARY")

        def _add_events(n):
            for _ in range(n):
                create_cleaning(NewCleaningData(equipment_id=equipment.pk, responsible=self.tecnico, created_by=self.admin))

        _add_events(2)
        with CaptureQueriesContext(connection) as small:
            self.client.get(f"/equipamentos/{equipment.patrimonio}/")
        small_count = len(small.captured_queries)

        _add_events(10)
        with CaptureQueriesContext(connection) as large:
            self.client.get(f"/equipamentos/{equipment.patrimonio}/")
        large_count = len(large.captured_queries)

        self.assertEqual(small_count, large_count)
