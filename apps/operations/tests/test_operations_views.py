"""
Testes HTTP de `Location`/`Movement` — matriz de permissões (v1.0, seção
11) e integração da movimentação com a timeline existente do equipamento
(`apps.equipment.services.get_equipment_history_timeline`).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import Location, LocationType
from apps.operations.services import NewLocationData, create_location

User = get_user_model()


class LocationViewPermissionTest(TestCase):
    def setUp(self):
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            User.objects.create_user(username=f"loc_{role.lower()}", password="senha-forte-123", role=role)
        self.location = create_location(NewLocationData(name="Estoque Views", type=LocationType.ESTOQUE))

    def test_all_roles_can_view_location_list_and_detail(self):
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            with self.subTest(role=role):
                self.client.login(username=f"loc_{role.lower()}", password="senha-forte-123")
                self.assertEqual(self.client.get("/operacao/unidades/").status_code, 200)
                self.assertEqual(self.client.get(f"/operacao/unidades/{self.location.pk}/").status_code, 200)
                self.client.logout()

    def test_only_admin_and_administrativo_can_create_location(self):
        for role, expected in (("ADMIN", 200), ("ADMINISTRATIVO", 200), ("OPERACIONAL", 403), ("CONSULTA", 403)):
            with self.subTest(role=role):
                self.client.login(username=f"loc_{role.lower()}", password="senha-forte-123")
                response = self.client.get("/operacao/unidades/novo/")
                self.assertEqual(response.status_code, expected)
                self.client.logout()

    def test_creating_location_via_http(self):
        self.client.login(username="loc_admin", password="senha-forte-123")
        response = self.client.post(
            "/operacao/unidades/novo/",
            {
                "name": "Nova Unidade HTTP",
                "type": LocationType.ESTOQUE,
                "client": "",
                "cep": "",
                "logradouro": "",
                "numero": "",
                "complemento": "",
                "bairro": "",
                "cidade": "",
                "uf": "",
                "reference_notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Location.objects.filter(name="Nova Unidade HTTP").exists())


class MovementCreatePermissionTest(TestCase):
    """CAN_REGISTER_OPERATIONS (já existente desde a Fase 1) — Admin/Administrativo/Operacional, não Consulta."""

    def setUp(self):
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            User.objects.create_user(username=f"mov_{role.lower()}", password="senha-forte-123", role=role)

        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor HTTP", code="AQHT")
        creator = User.objects.get(username="mov_admin")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))

    def test_permission_matrix_for_movement_form_access(self):
        for role, expected in (("ADMIN", 200), ("ADMINISTRATIVO", 200), ("OPERACIONAL", 200), ("CONSULTA", 403)):
            with self.subTest(role=role):
                self.client.login(username=f"mov_{role.lower()}", password="senha-forte-123")
                response = self.client.get(f"/operacao/movimentar/{self.equipment.patrimonio}/")
                self.assertEqual(response.status_code, expected)
                self.client.logout()


class MovementTimelineIntegrationTest(TestCase):
    """A movimentação registrada aparece na timeline autenticada do equipamento, sem tocar o template."""

    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Timeline", code="AQTL")
        self.admin = User.objects.create_user(username="timeline_admin", password="senha-forte-123", role="ADMIN")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))

        self.cliente = Client.objects.create(company_name="Cliente Timeline LTDA")
        self.unidade = create_location(NewLocationData(name="Unidade Timeline", type=LocationType.CLIENTE, client=self.cliente))

    def test_movement_appears_in_authenticated_timeline(self):
        self.client.login(username="timeline_admin", password="senha-forte-123")
        response = self.client.post(
            f"/operacao/movimentar/{self.equipment.patrimonio}/",
            {"movement_type": "INSTALACAO", "destination_location": self.unidade.pk, "reason": ""},
        )
        self.assertEqual(response.status_code, 302)

        detail_response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")
        self.assertEqual(detail_response.status_code, 200)
        content = detail_response.content.decode()
        self.assertIn("Instalação", content)
        self.assertIn("Unidade Timeline", content)
        self.assertIn("Cliente Timeline LTDA", content)

        events = detail_response.context["history_events"]
        self.assertTrue(any(e["event_type"] == "movimentacao" for e in events))
