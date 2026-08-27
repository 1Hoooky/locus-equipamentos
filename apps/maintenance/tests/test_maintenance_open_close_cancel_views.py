"""
Fluxos de UI de abrir/concluir/cancelar Maintenance — sempre via
open_maintenance()/close_maintenance()/cancel_maintenance() (nunca
Maintenance.objects.create()/.save() na view). Cobre também: erro de
domínio virando mensagem de formulário (nunca HTTP 500), e proteção
contra reenvio (double-submit) reaproveitando `SubmissionGuard`.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.models import Status
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.maintenance.models import Maintenance, MaintenanceStatus
from apps.maintenance.services import NewMaintenanceData, open_maintenance
from apps.operations.models import LocationType, MovementType
from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

User = get_user_model()


class MaintenanceViewsTestBase(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Categoria UI Manutenção")
        model = EquipmentModel.objects.create(category=category, name="Modelo UI Manutenção", code="UIMN")
        self.tecnico = User.objects.create_user(username="ui_tecnico", password="senha-forte-123", role=Role.OPERACIONAL)
        self.admin = User.objects.create_user(username="ui_admin", password="senha-forte-123", role=Role.ADMIN)

        self.oficina = create_location(NewLocationData(name="Oficina UI", type=LocationType.MANUTENCAO))
        self.estoque = create_location(NewLocationData(name="Estoque UI", type=LocationType.ESTOQUE))
        self.cliente = Client.objects.create(company_name="Cliente UI LTDA")
        self.unidade = create_location(NewLocationData(name="Unidade UI A", type=LocationType.CLIENTE, client=self.cliente))

        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))
        self.client.login(username="ui_admin", password="senha-forte-123")

    def _move(self, movement_type, destination, equipment=None):
        return create_movement(
            NewMovementData(
                equipment_id=(equipment or self.equipment).pk,
                movement_type=movement_type,
                created_by=self.admin,
                destination_location=destination,
            )
        )

    def _open_token(self):
        response = self.client.get("/manutencao/manutencoes/abrir/")
        self.assertEqual(response.status_code, 200)
        return response.context["submission_token"]


class AbrirManutencaoViewTest(MaintenanceViewsTestBase):
    def test_abrir_sem_movement(self):
        token = self._open_token()
        response = self.client.post(
            "/manutencao/manutencoes/abrir/",
            {
                "equipment": self.equipment.pk,
                "maintenance_type": "CORRETIVA",
                "diagnosis": "Barulho estranho.",
                "responsible": self.tecnico.pk,
                "notes": "",
                "submission_token": token,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        maintenance = Maintenance.objects.get(equipment=self.equipment)
        self.assertEqual(maintenance.status, MaintenanceStatus.ABERTA)
        self.assertIsNone(maintenance.departure_movement)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.MANUTENCAO)

    def test_abrir_com_departure_movement_valido(self):
        movimento = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina)
        token = self._open_token()
        response = self.client.post(
            "/manutencao/manutencoes/abrir/",
            {
                "equipment": self.equipment.pk,
                "maintenance_type": "CORRETIVA",
                "responsible": self.tecnico.pk,
                "departure_movement": movimento.pk,
                "submission_token": token,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        maintenance = Maintenance.objects.get(equipment=self.equipment)
        self.assertEqual(maintenance.departure_movement, movimento)

    def test_abrir_com_departure_movement_de_outro_equipamento_manipulado_e_rejeitado_sem_500(self):
        """POST manipulado — o Movement de outro equipamento não aparece na queryset do form, mas o service é a autoridade final."""
        outro = create_equipment(NewEquipmentData(model_id=self.equipment.model_id, created_by=self.admin))
        movimento_outro = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina, equipment=outro)
        token = self._open_token()
        response = self.client.post(
            "/manutencao/manutencoes/abrir/",
            {
                "equipment": self.equipment.pk,
                "maintenance_type": "CORRETIVA",
                "responsible": self.tecnico.pk,
                "departure_movement": movimento_outro.pk,
                "submission_token": token,
            },
        )
        # Rejeitado no FORM (ModelChoiceField — não está na queryset
        # filtrada por equipamento) — nunca 500, nunca cria nada.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Maintenance.objects.filter(equipment=self.equipment).count(), 0)

    def test_abrir_para_equipamento_ja_com_manutencao_aberta_mostra_erro_sem_500(self):
        open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin
            )
        )
        # Força o POST com o equipamento mesmo fora da queryset filtrada
        # (que já o exclui por UX) — simulando um POST manipulado.
        token = self._open_token()
        response = self.client.post(
            "/manutencao/manutencoes/abrir/",
            {
                "equipment": self.equipment.pk,
                "maintenance_type": "CORRETIVA",
                "responsible": self.tecnico.pk,
                "submission_token": token,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Maintenance.objects.filter(equipment=self.equipment, status=MaintenanceStatus.ABERTA).count(), 1)

    def test_pre_selecao_via_query_param_da_ficha(self):
        response = self.client.get(f"/manutencao/manutencoes/abrir/?equipment={self.equipment.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial.get("equipment"), self.equipment.pk)

    def test_double_submit_nao_cria_duas_manutencoes(self):
        token = self._open_token()
        data = {
            "equipment": self.equipment.pk,
            "maintenance_type": "CORRETIVA",
            "responsible": self.tecnico.pk,
            "submission_token": token,
        }
        first = self.client.post("/manutencao/manutencoes/abrir/", data, follow=True)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(Maintenance.objects.filter(equipment=self.equipment).count(), 1)

        second = self.client.post("/manutencao/manutencoes/abrir/", data, follow=True)
        self.assertEqual(second.status_code, 200)
        # Reenvio — nenhuma segunda Maintenance criada.
        self.assertEqual(Maintenance.objects.filter(equipment=self.equipment).count(), 1)


class ConcluirManutencaoViewTest(MaintenanceViewsTestBase):
    def _open(self, **overrides):
        data = dict(
            equipment_id=self.equipment.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin
        )
        data.update(overrides)
        return open_maintenance(NewMaintenanceData(**data))

    def _close_token(self, pk):
        response = self.client.get(f"/manutencao/manutencoes/{pk}/concluir/")
        self.assertEqual(response.status_code, 200)
        return response.context["submission_token"]

    def test_concluir_sem_return_movement(self):
        maintenance = self._open()
        token = self._close_token(maintenance.pk)
        response = self.client.post(
            f"/manutencao/manutencoes/{maintenance.pk}/concluir/",
            {"service_performed": "Troca de peça.", "condition_after": "", "submission_token": token},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        maintenance.refresh_from_db()
        self.assertEqual(maintenance.status, MaintenanceStatus.CONCLUIDA)
        self.assertIsNotNone(maintenance.closed_at)

    def test_concluir_com_return_movement(self):
        movimento_envio = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina)
        maintenance = self._open(departure_movement=movimento_envio)
        movimento_retorno = self._move(MovementType.RETORNO_MANUTENCAO, self.estoque)
        token = self._close_token(maintenance.pk)
        response = self.client.post(
            f"/manutencao/manutencoes/{maintenance.pk}/concluir/",
            {
                "service_performed": "Serviço concluído na oficina.",
                "condition_after": "",
                "return_movement": movimento_retorno.pk,
                "submission_token": token,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        maintenance.refresh_from_db()
        self.assertEqual(maintenance.return_movement, movimento_retorno)

    def test_concluir_com_movement_incompativel_manipulado_e_rejeitado_sem_500(self):
        maintenance = self._open()
        # OUTRO — não bloqueado pela "manutenção aberta" (diferente de
        # INSTALACAO/RETIRADA/TRANSFERENCIA/ENVIO_MANUTENCAO), mas
        # continua sendo um tipo INVÁLIDO como return_movement (só
        # RETORNO_MANUTENCAO/RETORNO_ESTOQUE são aceitos) — mesmo Movement
        # real usado em `test_return_movement_tipo_errado_rejeitado`.
        movimento_errado = create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=MovementType.OUTRO,
                created_by=self.admin,
                reason="Anotação qualquer, sem efeito de status.",
            )
        )
        token = self._close_token(maintenance.pk)
        response = self.client.post(
            f"/manutencao/manutencoes/{maintenance.pk}/concluir/",
            {"service_performed": "Concluído.", "condition_after": "", "return_movement": movimento_errado.pk, "submission_token": token},
        )
        self.assertEqual(response.status_code, 200)
        maintenance.refresh_from_db()
        self.assertEqual(maintenance.status, MaintenanceStatus.ABERTA)

    def test_double_submit_conclui_uma_unica_vez(self):
        maintenance = self._open()
        token = self._close_token(maintenance.pk)
        data = {"service_performed": "Concluído.", "condition_after": "", "submission_token": token}

        first = self.client.post(f"/manutencao/manutencoes/{maintenance.pk}/concluir/", data, follow=True)
        self.assertEqual(first.status_code, 200)
        maintenance.refresh_from_db()
        closed_at_first = maintenance.closed_at
        self.assertEqual(maintenance.status, MaintenanceStatus.CONCLUIDA)

        second = self.client.post(f"/manutencao/manutencoes/{maintenance.pk}/concluir/", data, follow=True)
        self.assertEqual(second.status_code, 200)
        maintenance.refresh_from_db()
        self.assertEqual(maintenance.closed_at, closed_at_first)


class CancelarManutencaoViewTest(MaintenanceViewsTestBase):
    def _open(self):
        return open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin
            )
        )

    def _cancel_token(self, pk):
        response = self.client.get(f"/manutencao/manutencoes/{pk}/cancelar/")
        self.assertEqual(response.status_code, 200)
        return response.context["submission_token"]

    def test_get_confirmation_page(self):
        maintenance = self._open()
        response = self.client.get(f"/manutencao/manutencoes/{maintenance.pk}/cancelar/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("form", response.context)

    def test_cancelar_exige_motivo_e_confirmacao(self):
        maintenance = self._open()
        token = self._cancel_token(maintenance.pk)
        response = self.client.post(
            f"/manutencao/manutencoes/{maintenance.pk}/cancelar/", {"reason": "", "submission_token": token}
        )
        self.assertEqual(response.status_code, 200)
        maintenance.refresh_from_db()
        self.assertEqual(maintenance.status, MaintenanceStatus.ABERTA)

    def test_cancelar_post_only_muda_status_e_restaura(self):
        maintenance = self._open()
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.MANUTENCAO)

        token = self._cancel_token(maintenance.pk)
        response = self.client.post(
            f"/manutencao/manutencoes/{maintenance.pk}/cancelar/",
            {"reason": "Aberta por engano.", "confirm": "on", "submission_token": token},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        maintenance.refresh_from_db()
        self.assertEqual(maintenance.status, MaintenanceStatus.CANCELADA)
        self.assertIn("Aberta por engano.", maintenance.notes)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)

    def test_cancelamento_nunca_e_hard_delete(self):
        maintenance = self._open()
        token = self._cancel_token(maintenance.pk)
        self.client.post(
            f"/manutencao/manutencoes/{maintenance.pk}/cancelar/",
            {"reason": "Teste.", "confirm": "on", "submission_token": token},
        )
        # A linha continua existindo no banco (soft, nunca DELETE).
        self.assertTrue(Maintenance.objects.filter(pk=maintenance.pk).exists())

    def test_double_submit_nao_cancela_duas_vezes(self):
        maintenance = self._open()
        token = self._cancel_token(maintenance.pk)
        data = {"reason": "Teste de reenvio.", "confirm": "on", "submission_token": token}

        first = self.client.post(f"/manutencao/manutencoes/{maintenance.pk}/cancelar/", data, follow=True)
        self.assertEqual(first.status_code, 200)

        second = self.client.post(f"/manutencao/manutencoes/{maintenance.pk}/cancelar/", data, follow=True)
        self.assertEqual(second.status_code, 200)
        # cancel_maintenance() já rejeitaria uma segunda vez (não está mais
        # ABERTA); a proteção de reenvio garante que a 2ª tentativa nem
        # chega no service com token repetido — de qualquer forma, o
        # resultado observável é o mesmo: só uma transição ocorreu.
        maintenance.refresh_from_db()
        self.assertEqual(maintenance.status, MaintenanceStatus.CANCELADA)
