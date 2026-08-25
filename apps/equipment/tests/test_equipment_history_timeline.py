"""
Seção "Histórico do equipamento" da ficha autenticada — linha do tempo
somente leitura que funde `StatusHistory` + `ConditionHistory` (já
gravados por `change_status()`/`change_condition()`, com motivo
obrigatório; ver apps/equipment/services.py). Este arquivo testa só a
APRESENTAÇÃO desses dados já existentes: nenhum campo, tabela ou evento
novo é criado por esta funcionalidade — os testes de que o motivo é
obrigatório e de que o histórico é gravado corretamente já existem em
test_equipment_crud_views.py::EquipmentChangeStatusConditionViewTest.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import (
    NewEquipmentData,
    change_condition,
    change_status,
    create_equipment,
)

User = get_user_model()


class EquipmentHistoryTimelineTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Climatizador")
        model = EquipmentModel.objects.create(category=category, name="NI23 Big Tank", code="NI23BT")
        self.admin = User.objects.create_user(username="hist_admin", password="senha-forte-123", role=Role.ADMIN)
        self.consulta = User.objects.create_user(
            username="hist_consulta", password="senha-forte-123", role=Role.CONSULTA
        )
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))
        self.url = f"/equipamentos/{self.equipment.patrimonio}/"

    def test_no_events_shows_empty_message(self):
        self.client.login(username="hist_admin", password="senha-forte-123")
        response = self.client.get(self.url)
        self.assertContains(response, "Histórico do equipamento")
        self.assertContains(response, "Nenhuma alteração registrada ainda.")

    def test_status_change_appears_in_timeline_with_reason_and_user(self):
        change_status(
            equipment=self.equipment,
            new_status="MANUTENCAO",
            reason="Climatizador com problemas na inversora",
            changed_by=self.admin,
        )
        self.client.login(username="hist_admin", password="senha-forte-123")
        response = self.client.get(self.url)
        content = response.content.decode()

        self.assertContains(response, "Status")
        self.assertContains(response, "Disponível")
        self.assertContains(response, "Manutenção")
        self.assertContains(response, "Climatizador com problemas na inversora")
        self.assertIn(str(self.admin), content)

    def test_condition_change_appears_in_timeline_with_reason_and_user(self):
        change_condition(
            equipment=self.equipment,
            new_condition="RUIM",
            reason="Equipamento apresentou falha durante operação",
            changed_by=self.admin,
        )
        self.client.login(username="hist_admin", password="senha-forte-123")
        response = self.client.get(self.url)

        self.assertContains(response, "Condição")
        self.assertContains(response, "Bom")
        self.assertContains(response, "Ruim")
        self.assertContains(response, "Equipamento apresentou falha durante operação")

    def test_status_and_condition_events_are_merged_and_ordered_most_recent_first(self):
        # Três eventos intercalados, em ordem de criação: status, condição, status.
        change_status(
            equipment=self.equipment, new_status="EM_OPERACAO", reason="Primeiro evento.", changed_by=self.admin
        )
        change_condition(
            equipment=self.equipment, new_condition="MEDIO", reason="Segundo evento.", changed_by=self.admin
        )
        change_status(
            equipment=self.equipment, new_status="MANUTENCAO", reason="Terceiro evento.", changed_by=self.admin
        )

        self.client.login(username="hist_admin", password="senha-forte-123")
        response = self.client.get(self.url)
        content = response.content.decode()

        pos_first = content.index("Primeiro evento.")
        pos_second = content.index("Segundo evento.")
        pos_third = content.index("Terceiro evento.")

        # Mais recente primeiro: "Terceiro" (por último criado) deve
        # aparecer ANTES de "Segundo", que deve aparecer ANTES de "Primeiro".
        self.assertLess(pos_third, pos_second)
        self.assertLess(pos_second, pos_first)

    def test_public_page_does_not_show_history(self):
        change_status(
            equipment=self.equipment,
            new_status="MANUTENCAO",
            reason="Motivo confidencial de manutenção.",
            changed_by=self.admin,
        )
        response = self.client.get(self.url)  # sem login

        self.assertTemplateUsed(response, "equipment/detail_public.html")
        self.assertNotContains(response, "Histórico do equipamento")
        self.assertNotContains(response, "Motivo confidencial de manutenção.")

    def test_authenticated_authorized_user_can_view_history(self):
        """Todos os 4 perfis podem consultar a ficha (matriz da seção 11) — inclusive Consulta."""
        change_status(
            equipment=self.equipment,
            new_status="MANUTENCAO",
            reason="Visível para consulta.",
            changed_by=self.admin,
        )
        self.client.login(username="hist_consulta", password="senha-forte-123")
        response = self.client.get(self.url)

        self.assertTemplateUsed(response, "equipment/detail_private.html")
        self.assertContains(response, "Histórico do equipamento")
        self.assertContains(response, "Visível para consulta.")
