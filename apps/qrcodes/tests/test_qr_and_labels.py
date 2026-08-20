"""
Testes de QR Code e etiqueta — especificação, seção 14.

O ponto mais importante aqui não é "o PNG/PDF foi gerado" — é que a URL
codificada no QR é a URL permanente correta (`SITE_BASE_URL +
/equipamentos/{patrimonio}/`), e que o download dessas rotas respeita a
matriz de permissões (seção 11: Administrador/Administrativo).
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.qrcodes.services import equipment_url, generate_label_pdf, generate_qr_png

User = get_user_model()


class QRServiceTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Torre", code="AQCT")
        user = User.objects.create_user(username="cadastrador", password="senha-forte-123")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=user))

    def test_equipment_url_is_permanent_and_uses_site_base_url(self):
        url = equipment_url(self.equipment)
        self.assertEqual(url, f"{settings.SITE_BASE_URL}/equipamentos/{self.equipment.patrimonio}/")

    def test_generate_qr_png_returns_valid_png(self):
        png_bytes = generate_qr_png(self.equipment)
        self.assertTrue(png_bytes.startswith(b"\x89PNG"), "Não parece um PNG válido.")

    def test_qr_decodes_to_the_permanent_equipment_url(self):
        """
        Não basta o PNG ser válido — o conteúdo do QR precisa ser
        exatamente a URL permanente do patrimônio (seção 14: "O QR NÃO
        armazenará informações adicionais. A URL identifica o
        equipamento."). Decodificamos de verdade em vez de confiar que
        `generate_qr_png` fez a coisa certa.
        """
        import io

        from PIL import Image
        from pyzbar.pyzbar import decode

        png_bytes = generate_qr_png(self.equipment)
        decoded = decode(Image.open(io.BytesIO(png_bytes)))

        self.assertEqual(len(decoded), 1, "QR deveria conter exatamente um código.")
        self.assertEqual(decoded[0].data.decode(), equipment_url(self.equipment))

    def test_generate_label_pdf_returns_valid_pdf(self):
        pdf_bytes = generate_label_pdf(self.equipment)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"), "Não parece um PDF válido.")


class QRDownloadPermissionTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Torre", code="AQCT")
        creator = User.objects.create_user(username="cadastrador2", password="senha-forte-123")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))

        for role in (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA):
            User.objects.create_user(username=f"qr_{role.lower()}", password="senha-forte-123", role=role)

    def _qr_url(self):
        return f"/qrcodes/{self.equipment.patrimonio}/qr.png"

    def _label_url(self):
        return f"/qrcodes/{self.equipment.patrimonio}/etiqueta.pdf"

    def test_admin_and_administrativo_can_download(self):
        for role in (Role.ADMIN, Role.ADMINISTRATIVO):
            with self.subTest(role=role):
                self.client.login(username=f"qr_{role.lower()}", password="senha-forte-123")
                response = self.client.get(self._qr_url())
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "image/png")
                self.client.logout()

    def test_operacional_and_consulta_are_forbidden(self):
        for role in (Role.OPERACIONAL, Role.CONSULTA):
            with self.subTest(role=role):
                self.client.login(username=f"qr_{role.lower()}", password="senha-forte-123")
                response = self.client.get(self._qr_url())
                self.assertEqual(response.status_code, 403)
                self.client.logout()

    def test_label_pdf_download(self):
        self.client.login(username="qr_admin", password="senha-forte-123")
        response = self.client.get(self._label_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
