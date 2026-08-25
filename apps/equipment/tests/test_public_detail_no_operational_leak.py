"""
Validação obrigatória #16 (fundação Fase 2 — Operação): a ficha pública do
QR continua sem expor cliente, unidade ou movimentações, mesmo depois que
o equipamento já foi instalado/movimentado. Complementa (não substitui)
`test_public_detail_view.py`, que já cobre o mesmo risco para os campos da
Fase 1 (cliente/fornecedor/valor).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import LocationType, MovementType
from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

User = get_user_model()


class PublicDetailNoOperationalLeakTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Sigiloso", code="AQSG")
        self.admin = User.objects.create_user(username="leak_admin", password="senha-forte-123", role="ADMIN")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))

        self.client_record = Client.objects.create(company_name="Cliente Segredo Operacional LTDA")
        self.location = create_location(
            NewLocationData(name="Unidade Ultra Secreta", type=LocationType.CLIENTE, client=self.client_record)
        )
        create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.admin,
                destination_location=self.location,
                reason="",
            )
        )

    def test_public_page_never_mentions_client_location_or_movement(self):
        response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "equipment/detail_public.html")

        content = response.content.decode()
        self.assertNotIn("Cliente Segredo Operacional", content)
        self.assertNotIn("Unidade Ultra Secreta", content)
        self.assertNotIn("Instalação", content)
        self.assertNotIn("Instalacao", content)
        self.assertNotIn("EM_OPERACAO", content)

    def test_public_page_context_has_no_history_events_key(self):
        """
        A view pública nunca recebe `history_events` no contexto — nem por
        engano ficaria disponível para o template renderizar (ver
        apps/equipment/views.py::EquipmentDetailView).
        """
        response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")
        self.assertNotIn("history_events", response.context)

    def test_authenticated_page_does_show_the_movement(self):
        """Contraste: confirma que a proteção é específica da rota pública, não um bug escondendo o dado de todo mundo."""
        self.client.login(username="leak_admin", password="senha-forte-123")
        response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")
        content = response.content.decode()
        self.assertIn("Cliente Segredo Operacional", content)
        self.assertIn("Unidade Ultra Secreta", content)
