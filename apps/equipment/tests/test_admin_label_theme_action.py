"""
Action "Baixar etiquetas em PDF (lote)" do Django admin
(`apps/equipment/admin.py::EquipmentAdmin.download_labels_pdf`) — pedido
de 04/09/2026: intercepta esta MESMA action (seleção de equipamentos via
checkbox nativo do admin + "Ir") com um modal LIGHT/DARK, sem criar
nenhuma tela nova. O modal em si é JavaScript puro (não testável por
`manage.py test`, que não executa JS) — o que ESTE arquivo garante é a
metade que roda no servidor: a action aceita e repassa `tema` (com
"light" como padrão seguro quando o campo não vier, ex.: JS
desabilitado), e o destino real do redirect (`LabelBatchDownloadView`,
já coberto em `apps/qrcodes/tests/test_qr_and_labels.py`) é quem valida
de verdade.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()


class LabelThemeAdminActionTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Climatizador")
        model = EquipmentModel.objects.create(category=category, name="NI23 Big Tank", code="NI23BT")
        creator = User.objects.create_user(username="admin_action_criador", password="senha-forte-123")
        self.eq1 = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))
        self.eq2 = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))

        self.staff_user = User.objects.create_user(
            username="admin_action_staff", password="senha-forte-123", is_staff=True, is_superuser=True
        )
        self.changelist_url = reverse("admin:equipment_equipment_changelist")

    def _post_action(self, *, tema=None, selected_pks=None):
        data = {
            "action": "download_labels_pdf",
            "_selected_action": [str(pk) for pk in (selected_pks or [self.eq1.pk, self.eq2.pk])],
        }
        if tema is not None:
            data["tema"] = tema
        return self.client.post(self.changelist_url, data)

    def test_action_requires_staff_login(self):
        response = self._post_action(tema="dark")
        # Sem login, o admin redireciona para a tela de login dele, nunca executa a action.
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_redirect_includes_the_chosen_theme(self):
        self.client.login(username="admin_action_staff", password="senha-forte-123")
        response = self._post_action(tema="dark")
        self.assertEqual(response.status_code, 302)
        self.assertIn("tema=dark", response.url)
        self.assertIn(f"patrimonio={self.eq1.patrimonio}", response.url)
        self.assertIn(f"patrimonio={self.eq2.patrimonio}", response.url)

    def test_redirect_includes_light_theme_when_chosen(self):
        self.client.login(username="admin_action_staff", password="senha-forte-123")
        response = self._post_action(tema="light")
        self.assertEqual(response.status_code, 302)
        self.assertIn("tema=light", response.url)

    def test_missing_theme_field_defaults_to_light(self):
        """
        Simula o form sendo enviado sem o campo `tema` — JavaScript
        desabilitado, ou o modal nunca chegou a interceptar por algum
        motivo. A action não pode quebrar: cai no padrão "light", o
        mesmo comportamento de sempre desta action.
        """
        self.client.login(username="admin_action_staff", password="senha-forte-123")
        response = self._post_action(tema=None)
        self.assertEqual(response.status_code, 302)
        self.assertIn("tema=light", response.url)

    def test_redirect_target_actually_serves_a_pdf_for_the_chosen_theme(self):
        """Ponta a ponta: o redirect da action leva a um PDF de verdade — não só uma URL bem formada."""
        self.client.login(username="admin_action_staff", password="senha-forte-123")
        response = self._post_action(tema="dark")
        pdf_response = self.client.get(response.url)
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")

    def test_tampered_invalid_theme_is_rejected_downstream(self):
        """
        A action em si não valida (só repassa) — quem barra um tema
        inválido é o destino do redirect. Simula alguém adulterando o
        POST para mandar um valor fora de light/dark.
        """
        self.client.login(username="admin_action_staff", password="senha-forte-123")
        response = self._post_action(tema="sepia")
        self.assertEqual(response.status_code, 302)
        pdf_response = self.client.get(response.url)
        self.assertEqual(pdf_response.status_code, 400)

    def test_media_assets_are_declared_for_the_changelist(self):
        """
        O modal só existe se o JS/CSS realmente forem carregados na
        página de listagem — confirma que `EquipmentAdmin.Media` está
        registrado e a página os referencia (sem executar o JS em si,
        que exigiria um browser real).
        """
        self.client.login(username="admin_action_staff", password="senha-forte-123")
        response = self.client.get(self.changelist_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "qrcodes/admin/label_theme_modal.js")
        self.assertContains(response, "qrcodes/admin/label_theme_modal.css")
