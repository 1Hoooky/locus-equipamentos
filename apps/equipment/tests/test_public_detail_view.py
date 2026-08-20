"""
Teste do risco técnico mais citado na especificação (seções 5, 12, 16,
20): a ficha pública do QR nunca pode vazar cliente, valor de aquisição
ou dados de manutenção para quem não está logado.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client as HttpClient
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()


class PublicEquipmentDetailViewTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Híbrido", code="AQCH")
        user = User.objects.create_user(username="cadastrador", password="senha-forte-123")

        self.client_record = Client.objects.create(company_name="Cliente Sigiloso LTDA")

        self.equipment = create_equipment(
            NewEquipmentData(
                model_id=model.pk,
                created_by=user,
                supplier="Fornecedor Secreto",
                acquisition_value=Decimal("1999.90"),
                notes="Observação técnica interna sensível.",
            )
        )
        self.equipment.current_client = self.client_record
        self.equipment.save(update_fields=["current_client"])

        self.anon_client = HttpClient()

    def test_public_page_shows_only_minimal_data(self):
        response = self.anon_client.get(f"/equipamentos/{self.equipment.patrimonio}/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "equipment/detail_public.html")

        content = response.content.decode()
        self.assertIn(self.equipment.patrimonio, content)
        self.assertIn("Aquecedor", content)

        # Nada sensível pode vazar para quem não está logado.
        self.assertNotIn("Cliente Sigiloso", content)
        self.assertNotIn("Fornecedor Secreto", content)
        self.assertNotIn("1999.90", content)
        self.assertNotIn("Observação técnica interna sensível", content)

    def test_authenticated_page_shows_full_data(self):
        User.objects.create_user(username="viewer", password="senha-forte-123", role="ADMIN")
        self.anon_client.login(username="viewer", password="senha-forte-123")

        response = self.anon_client.get(f"/equipamentos/{self.equipment.patrimonio}/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "equipment/detail_private.html")
        self.assertIn("Cliente Sigiloso", response.content.decode())
