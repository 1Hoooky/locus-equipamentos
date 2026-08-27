"""
Integração com a ficha do equipamento (revisão de 27/08/2026, item 7) e
com a timeline unificada (item 8): pré-seleção vinda da ficha, seção
resumida "Manutenção e higienização" (sem duplicar a timeline inteira), e
os quatro eventos novos (manutenção aberta/concluída/cancelada,
higienização realizada) aparecendo em
`apps.equipment.services.get_equipment_history_timeline()` sem alterar os
eventos de Status/Condição/Movimentação já existentes.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import NewEquipmentData, create_equipment, get_equipment_history_timeline
from apps.maintenance.services import (
    CloseMaintenanceData,
    NewCleaningData,
    NewMaintenanceData,
    cancel_maintenance,
    close_maintenance,
    create_cleaning,
    open_maintenance,
)

User = get_user_model()


class FichaEquipamentoTestBase(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Categoria Ficha")
        model = EquipmentModel.objects.create(category=category, name="Modelo Ficha", code="FICH")
        self.tecnico = User.objects.create_user(username="ficha_tecnico", password="senha-forte-123", role=Role.OPERACIONAL)
        self.admin = User.objects.create_user(username="ficha_admin", password="senha-forte-123", role=Role.ADMIN)
        self.consulta = User.objects.create_user(username="ficha_consulta", password="senha-forte-123", role=Role.CONSULTA)
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))


class FichaEquipamentoLinksETest(FichaEquipamentoTestBase):
    def test_ficha_mostra_links_de_abrir_manutencao_e_registrar_higienizacao(self):
        self.client.login(username="ficha_admin", password="senha-forte-123")
        response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/manutencao/manutencoes/abrir/?equipment=")
        self.assertContains(response, "/manutencao/higienizacoes/registrar/?equipment=")

    def test_ficha_esconde_abrir_manutencao_quando_ja_existe_uma_aberta(self):
        open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin
            )
        )
        self.client.login(username="ficha_admin", password="senha-forte-123")
        response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "/manutencao/manutencoes/abrir/?equipment=")
        # A informação de "manutenção em aberto" aparece na seção resumida.
        self.assertContains(response, "Manutenção em aberto desde")

    def test_consulta_ve_secao_mas_nao_ve_links_de_acao(self):
        self.client.login(username="ficha_consulta", password="senha-forte-123")
        response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")
        self.assertEqual(response.status_code, 200)
        # Consulta tem CAN_VIEW_MAINTENANCE — a seção aparece.
        self.assertContains(response, "Manutenção e higienização")
        # Mas não tem CAN_REGISTER_OPERATIONS — sem link de ação.
        self.assertNotContains(response, "/manutencao/manutencoes/abrir/?equipment=")
        self.assertNotContains(response, "/manutencao/higienizacoes/registrar/?equipment=")

    def test_secao_resumida_lista_eventos_recentes_com_link_para_detalhe(self):
        maintenance = open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin
            )
        )
        close_maintenance(maintenance=maintenance, data=CloseMaintenanceData(service_performed="Concluído.", closed_by=self.tecnico))
        cleaning = create_cleaning(NewCleaningData(equipment_id=self.equipment.pk, responsible=self.tecnico, created_by=self.admin))

        self.client.login(username="ficha_admin", password="senha-forte-123")
        response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")
        self.assertContains(response, f"/manutencao/manutencoes/{maintenance.pk}/")
        self.assertContains(response, f"/manutencao/higienizacoes/{cleaning.pk}/")


class MaintenanceOpenPreSelectionTest(FichaEquipamentoTestBase):
    def test_link_da_ficha_pre_seleciona_equipamento_no_form_de_abertura(self):
        self.client.login(username="ficha_admin", password="senha-forte-123")
        response = self.client.get(f"/manutencao/manutencoes/abrir/?equipment={self.equipment.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial.get("equipment"), self.equipment.pk)

    def test_link_da_ficha_pre_seleciona_equipamento_no_form_de_higienizacao(self):
        self.client.login(username="ficha_admin", password="senha-forte-123")
        response = self.client.get(f"/manutencao/higienizacoes/registrar/?equipment={self.equipment.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial.get("equipment"), self.equipment.pk)


class TimelineIntegrationTest(FichaEquipamentoTestBase):
    def test_timeline_inclui_manutencao_aberta_e_concluida(self):
        maintenance = open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin
            )
        )
        close_maintenance(maintenance=maintenance, data=CloseMaintenanceData(service_performed="Concluído.", closed_by=self.tecnico))

        events = get_equipment_history_timeline(self.equipment)
        event_types = [e["event_type"] for e in events]
        self.assertIn("manutencao_aberta", event_types)
        self.assertIn("manutencao_concluida", event_types)

    def test_timeline_inclui_manutencao_cancelada(self):
        maintenance = open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin
            )
        )
        cancel_maintenance(maintenance=maintenance, cancelled_by=self.tecnico, reason="Teste.")

        events = get_equipment_history_timeline(self.equipment)
        event_types = [e["event_type"] for e in events]
        self.assertIn("manutencao_aberta", event_types)
        self.assertIn("manutencao_cancelada", event_types)
        self.assertNotIn("manutencao_concluida", event_types)

    def test_timeline_inclui_higienizacao(self):
        create_cleaning(NewCleaningData(equipment_id=self.equipment.pk, responsible=self.tecnico, created_by=self.admin))
        events = get_equipment_history_timeline(self.equipment)
        self.assertIn("higienizacao", [e["event_type"] for e in events])

    def test_timeline_preserva_eventos_existentes_de_status_condicao_movimentacao(self):
        from apps.equipment.services import change_condition, change_status
        from apps.equipment.models import Condition, Status
        from apps.operations.models import LocationType, MovementType
        from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

        change_status(equipment=self.equipment, new_status=Status.INATIVO, reason="Teste.", changed_by=self.admin)
        change_status(equipment=self.equipment, new_status=Status.DISPONIVEL, reason="Teste.", changed_by=self.admin)
        change_condition(equipment=self.equipment, new_condition=Condition.MEDIO, reason="Teste.", changed_by=self.admin)
        estoque = create_location(NewLocationData(name="Estoque Timeline", type=LocationType.ESTOQUE))
        create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk, movement_type=MovementType.OUTRO, created_by=self.admin, reason="Anotação."
            )
        )

        events = get_equipment_history_timeline(self.equipment)
        event_types = [e["event_type"] for e in events]
        self.assertIn("status", event_types)
        self.assertIn("condicao", event_types)
        self.assertIn("movimentacao", event_types)

    def test_timeline_esta_ordenada_do_mais_recente_para_o_mais_antigo(self):
        create_cleaning(NewCleaningData(equipment_id=self.equipment.pk, responsible=self.tecnico, created_by=self.admin))
        maintenance = open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin
            )
        )
        events = get_equipment_history_timeline(self.equipment)
        timestamps = [e["changed_at"] for e in events]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))
