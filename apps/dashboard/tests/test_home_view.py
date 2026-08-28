"""
Home operacional — etapa de UX/UI, 28/08/2026 (ver
AUDITORIA_UX_HOME_NAVEGACAO_QR.md, itens [26]-[29]).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.models import Condition, Status
from apps.equipment.services import (
    NewEquipmentData,
    change_condition,
    change_status,
    create_equipment,
)
from apps.maintenance.services import NewMaintenanceData, open_maintenance
from apps.operations.models import LocationType, MovementType
from apps.operations.services import (
    NewLocationData,
    NewMovementData,
    create_location,
    create_movement,
)

User = get_user_model()


class DashboardHomeAccessTest(TestCase):
    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/contas/login/", response["Location"])

    def test_any_authenticated_role_can_see_the_home(self):
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            User.objects.create_user(username=f"home_{role.lower()}", password="senha-forte-123", role=role)
            self.client.login(username=f"home_{role.lower()}", password="senha-forte-123")
            response = self.client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, "dashboard/home.html")
            self.client.logout()


class DashboardHomeContentTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="Climatizador 9PRO", code="9PRO")
        self.admin = User.objects.create_user(username="home_content_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="home_content_admin", password="senha-forte-123")

    def test_status_cards_reflect_real_counts(self):
        create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))
        create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))
        em_operacao = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))
        change_status(equipment=em_operacao, new_status=Status.EM_OPERACAO, reason="Instalado em cliente", changed_by=self.admin)

        response = self.client.get("/")
        self.assertEqual(response.context["status_counts"].disponiveis, 2)
        self.assertEqual(response.context["status_counts"].em_operacao, 1)
        content = response.content.decode()
        self.assertIn(">2<", content)
        self.assertIn(">1<", content)

    def test_open_maintenance_card_and_list(self):
        equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))
        open_maintenance(
            NewMaintenanceData(
                equipment_id=equipment.pk,
                maintenance_type="CORRETIVA",
                diagnosis="Não liga",
                responsible=self.admin,
                created_by=self.admin,
            )
        )

        response = self.client.get("/")
        self.assertEqual(response.context["open_maintenance_count"], 1)
        content = response.content.decode()
        self.assertIn(equipment.patrimonio, content)
        self.assertIn("Manutenções abertas", content)

    def test_recent_movements_list(self):
        equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))
        client_record = Client.objects.create(company_name="Cliente Home Movimentação LTDA")
        location = create_location(
            NewLocationData(name="Unidade Home Movimentação", type=LocationType.CLIENTE, client=client_record)
        )
        create_movement(
            NewMovementData(
                equipment_id=equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.admin,
                destination_location=location,
                reason="",
            )
        )

        response = self.client.get("/")
        self.assertEqual(len(response.context["recent_movements"]), 1)
        self.assertIn(equipment.patrimonio, response.content.decode())

    def test_equipment_needing_attention_list(self):
        bad_equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))
        change_condition(equipment=bad_equipment, new_condition=Condition.RUIM, reason="Vazamento", changed_by=self.admin)
        good_equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))

        response = self.client.get("/")
        attention_list = list(response.context["equipment_needing_attention"])
        self.assertIn(bad_equipment, attention_list)
        self.assertNotIn(good_equipment, attention_list)

    def test_home_has_no_charts_and_no_out_of_scope_metrics(self):
        """Decisão aprovada (item 15/17 do briefing): sem gráficos, sem métricas não listadas."""
        response = self.client.get("/")
        content = response.content.decode()
        for forbidden in ("<canvas", "chart.js", "Higienizações recentes", "Total de clientes", "Total de unidades"):
            self.assertNotIn(forbidden, content)
            self.assertNotIn(forbidden.lower(), content.lower())


class DashboardHomeQueryBudgetTest(TestCase):
    """
    Item [18]/[28] do briefing: agregações + slices limitados, zero
    `.count()` em loop, zero N+1 — e a contagem de queries não pode
    crescer com o volume de dados.
    """

    def setUp(self):
        category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=category, name="Climatizador 6PRO", code="6PRO")
        self.admin = User.objects.create_user(username="home_budget_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="home_budget_admin", password="senha-forte-123")

    def _seed(self, n):
        client_record = Client.objects.create(company_name=f"Cliente Budget {n} LTDA")
        location = create_location(
            NewLocationData(name=f"Unidade Budget {n}", type=LocationType.CLIENTE, client=client_record)
        )
        for _ in range(n):
            equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))
            change_condition(equipment=equipment, new_condition=Condition.RUIM, reason="Teste", changed_by=self.admin)
            create_movement(
                NewMovementData(
                    equipment_id=equipment.pk,
                    movement_type=MovementType.INSTALACAO,
                    created_by=self.admin,
                    destination_location=location,
                    reason="",
                )
            )
            open_maintenance(
                NewMaintenanceData(
                    equipment_id=equipment.pk,
                    maintenance_type="CORRETIVA",
                    diagnosis="Teste",
                    responsible=self.admin,
                    created_by=self.admin,
                )
            )

    def test_query_count_does_not_grow_with_more_records(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self._seed(3)
        with CaptureQueriesContext(connection) as small:
            self.client.get("/")

        self._seed(12)
        with CaptureQueriesContext(connection) as large:
            self.client.get("/")

        self.assertEqual(len(small.captured_queries), len(large.captured_queries))
