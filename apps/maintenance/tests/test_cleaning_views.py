"""
Fluxos de UI de Cleaning — sempre via create_cleaning()/cancel_cleaning().
Cobre: com/sem Movement, Movement de outro equipamento manipulado (sem
500), double-submit em criar/cancelar, cancelamento nunca é hard delete
nem cria ciclo ABERTA/CONCLUIDA.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.maintenance.models import Cleaning
from apps.maintenance.services import NewCleaningData, create_cleaning
from apps.operations.models import LocationType, MovementType
from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

User = get_user_model()


class CleaningViewsTestBase(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Categoria UI Higienização")
        model = EquipmentModel.objects.create(category=category, name="Modelo UI Higienização", code="UIHG")
        self.tecnico = User.objects.create_user(username="ui_hig_tecnico", password="senha-forte-123", role=Role.OPERACIONAL)
        self.admin = User.objects.create_user(username="ui_hig_admin", password="senha-forte-123", role=Role.ADMIN)
        self.estoque = create_location(NewLocationData(name="Estoque UI Higienização", type=LocationType.ESTOQUE))
        self.cliente = Client.objects.create(company_name="Cliente UI Higienização LTDA")
        self.unidade = create_location(
            NewLocationData(name="Unidade UI Higienização A", type=LocationType.CLIENTE, client=self.cliente)
        )

        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))
        self.client.login(username="ui_hig_admin", password="senha-forte-123")

    def _create_token(self):
        response = self.client.get("/manutencao/higienizacoes/registrar/")
        self.assertEqual(response.status_code, 200)
        return response.context["submission_token"]


class RegistrarHigienizacaoViewTest(CleaningViewsTestBase):
    def test_registrar_sem_movement(self):
        token = self._create_token()
        response = self.client.post(
            "/manutencao/higienizacoes/registrar/",
            {
                "equipment": self.equipment.pk,
                "responsible": self.tecnico.pk,
                "notes": "Higienização de rotina.",
                "submission_token": token,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        cleaning = Cleaning.objects.get(equipment=self.equipment)
        self.assertIsNone(cleaning.movement)

    def test_registrar_com_movement_do_mesmo_equipamento(self):
        movimento = create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.admin,
                destination_location=self.unidade,
            )
        )
        token = self._create_token()
        response = self.client.post(
            "/manutencao/higienizacoes/registrar/",
            {"equipment": self.equipment.pk, "responsible": self.tecnico.pk, "movement": movimento.pk, "submission_token": token},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        cleaning = Cleaning.objects.get(equipment=self.equipment)
        self.assertEqual(cleaning.movement, movimento)

    def test_movement_de_outro_equipamento_manipulado_e_rejeitado_sem_500(self):
        outro = create_equipment(NewEquipmentData(model_id=self.equipment.model_id, created_by=self.admin))
        movimento_outro = create_movement(
            NewMovementData(
                equipment_id=outro.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.admin,
                destination_location=self.unidade,
            )
        )
        token = self._create_token()
        response = self.client.post(
            "/manutencao/higienizacoes/registrar/",
            {"equipment": self.equipment.pk, "responsible": self.tecnico.pk, "movement": movimento_outro.pk, "submission_token": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Cleaning.objects.filter(equipment=self.equipment).count(), 0)

    def test_pre_selecao_via_query_param_da_ficha(self):
        response = self.client.get(f"/manutencao/higienizacoes/registrar/?equipment={self.equipment.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial.get("equipment"), self.equipment.pk)

    def test_double_submit_nao_cria_dois_registros(self):
        token = self._create_token()
        data = {"equipment": self.equipment.pk, "responsible": self.tecnico.pk, "submission_token": token}

        first = self.client.post("/manutencao/higienizacoes/registrar/", data, follow=True)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(Cleaning.objects.filter(equipment=self.equipment).count(), 1)

        second = self.client.post("/manutencao/higienizacoes/registrar/", data, follow=True)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(Cleaning.objects.filter(equipment=self.equipment).count(), 1)


class CancelarHigienizacaoViewTest(CleaningViewsTestBase):
    def _create(self):
        return create_cleaning(NewCleaningData(equipment_id=self.equipment.pk, responsible=self.tecnico, created_by=self.admin))

    def _cancel_token(self, pk):
        response = self.client.get(f"/manutencao/higienizacoes/{pk}/cancelar/")
        self.assertEqual(response.status_code, 200)
        return response.context["submission_token"]

    def test_cancelar_exige_confirmacao(self):
        cleaning = self._create()
        token = self._cancel_token(cleaning.pk)
        response = self.client.post(f"/manutencao/higienizacoes/{cleaning.pk}/cancelar/", {"submission_token": token})
        self.assertEqual(response.status_code, 200)
        cleaning.refresh_from_db()
        self.assertTrue(cleaning.is_active)

    def test_cancelar_confirmado_inativa_sem_hard_delete(self):
        cleaning = self._create()
        token = self._cancel_token(cleaning.pk)
        response = self.client.post(
            f"/manutencao/higienizacoes/{cleaning.pk}/cancelar/", {"confirm": "on", "submission_token": token}, follow=True
        )
        self.assertEqual(response.status_code, 200)
        cleaning.refresh_from_db()
        self.assertFalse(cleaning.is_active)
        self.assertTrue(Cleaning.objects.filter(pk=cleaning.pk).exists())

    def test_double_submit_nao_cancela_duas_vezes(self):
        cleaning = self._create()
        token = self._cancel_token(cleaning.pk)
        data = {"confirm": "on", "submission_token": token}

        first = self.client.post(f"/manutencao/higienizacoes/{cleaning.pk}/cancelar/", data, follow=True)
        self.assertEqual(first.status_code, 200)
        cleaning.refresh_from_db()
        self.assertFalse(cleaning.is_active)

        second = self.client.post(f"/manutencao/higienizacoes/{cleaning.pk}/cancelar/", data, follow=True)
        self.assertEqual(second.status_code, 200)
        cleaning.refresh_from_db()
        self.assertFalse(cleaning.is_active)
