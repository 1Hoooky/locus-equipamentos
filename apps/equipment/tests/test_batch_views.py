"""
Telas do cadastro em lote (formulário → confirmação → resultado) —
melhoria operacional da Fase 1, pedida em 25/08/2026.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.models import Equipment, EquipmentBatch
from apps.equipment.services import (
    MAX_BATCH_QUANTITY,
    NewEquipmentData,
    create_equipment,
)

User = get_user_model()


class EquipmentBatchCreateViewPermissionTest(TestCase):
    """Mesma matriz de permissão do cadastro individual (CAN_MANAGE_EQUIPMENT) — nenhum privilégio novo."""

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        User.objects.create_user(username="lote_admin", password="senha-forte-123", role=Role.ADMIN)
        User.objects.create_user(username="lote_administrativo", password="senha-forte-123", role=Role.ADMINISTRATIVO)
        User.objects.create_user(username="lote_operacional", password="senha-forte-123", role=Role.OPERACIONAL)
        User.objects.create_user(username="lote_consulta", password="senha-forte-123", role=Role.CONSULTA)

    def test_admin_can_access_the_form(self):
        self.client.login(username="lote_admin", password="senha-forte-123")
        response = self.client.get("/equipamentos/lote/novo/")
        self.assertEqual(response.status_code, 200)

    def test_administrativo_can_access_the_form(self):
        self.client.login(username="lote_administrativo", password="senha-forte-123")
        response = self.client.get("/equipamentos/lote/novo/")
        self.assertEqual(response.status_code, 200)

    def test_operacional_cannot_access_the_form(self):
        self.client.login(username="lote_operacional", password="senha-forte-123")
        response = self.client.get("/equipamentos/lote/novo/")
        self.assertEqual(response.status_code, 403)

    def test_consulta_cannot_access_the_form(self):
        self.client.login(username="lote_consulta", password="senha-forte-123")
        response = self.client.get("/equipamentos/lote/novo/")
        self.assertEqual(response.status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get("/equipamentos/lote/novo/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/contas/login/", response.url)

    def test_operacional_cannot_post_directly(self):
        self.client.login(username="lote_operacional", password="senha-forte-123")
        response = self.client.post("/equipamentos/lote/novo/", {"model": self.model.pk, "quantity": 5, "condition": "BOM"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Equipment.objects.count(), 0)


class EquipmentBatchFormValidationTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        self.inactive_model = EquipmentModel.objects.create(
            category=self.category, name="Modelo Descontinuado", code="DESC1", is_active=False
        )
        User.objects.create_user(username="lote_form_admin", password="senha-forte-123", role=Role.ADMIN)
        self.client.login(username="lote_form_admin", password="senha-forte-123")

    def _post(self, **overrides):
        data = {"model": self.model.pk, "quantity": 5, "condition": "BOM"}
        data.update(overrides)
        return self.client.post("/equipamentos/lote/novo/", data)

    def test_valid_submission_redirects_to_confirmation(self):
        response = self._post()
        self.assertRedirects(response, "/equipamentos/lote/confirmar/")
        self.assertIn("equipment_batch_pending", self.client.session)

    def test_zero_quantity_is_rejected_by_the_form(self):
        response = self._post(quantity=0)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())
        self.assertNotIn("equipment_batch_pending", self.client.session)

    def test_negative_quantity_is_rejected_by_the_form(self):
        response = self._post(quantity=-10)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())

    def test_non_numeric_quantity_is_rejected_by_the_form(self):
        response = self._post(quantity="oitenta")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())

    def test_quantity_above_limit_is_rejected_by_the_form(self):
        response = self._post(quantity=MAX_BATCH_QUANTITY + 1)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())

    def test_inactive_model_is_not_a_valid_choice(self):
        response = self._post(model=self.inactive_model.pk)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())

    def test_invalid_model_id_is_rejected(self):
        response = self._post(model=999999)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())

    def test_form_does_not_expose_serial_or_legacy_code_fields(self):
        response = self.client.get("/equipamentos/lote/novo/")
        self.assertNotIn("serial_number", response.context["form"].fields)
        self.assertNotIn("legacy_code", response.context["form"].fields)


class EquipmentBatchConfirmAndResultFlowTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        User.objects.create_user(username="lote_fluxo_admin", password="senha-forte-123", role=Role.ADMIN)
        self.client.login(username="lote_fluxo_admin", password="senha-forte-123")

    def test_confirm_page_shows_pending_batch_summary(self):
        self.client.post("/equipamentos/lote/novo/", {"model": self.model.pk, "quantity": 87, "condition": "BOM"})
        response = self.client.get("/equipamentos/lote/confirmar/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("87", content)
        self.assertIn("NI23BT", content)

    def test_confirm_get_without_pending_batch_redirects_to_form(self):
        response = self.client.get("/equipamentos/lote/confirmar/")
        self.assertRedirects(response, "/equipamentos/lote/novo/")

    def test_confirm_post_creates_the_batch_and_redirects_to_result(self):
        self.client.post("/equipamentos/lote/novo/", {"model": self.model.pk, "quantity": 10, "condition": "BOM"})
        response = self.client.post("/equipamentos/lote/confirmar/")

        self.assertEqual(response.status_code, 302)
        batch = EquipmentBatch.objects.get()
        self.assertEqual(batch.quantity, 10)
        self.assertEqual(response.url, f"/equipamentos/lote/{batch.id}/")
        self.assertEqual(Equipment.objects.filter(batch=batch).count(), 10)

    def test_double_submit_of_confirmation_does_not_create_a_second_batch(self):
        """
        Reenvio do POST de confirmação (F5, voltar+reenviar) não pode criar
        um segundo lote — a chave de sessão é consumida (uso único) no
        primeiro POST.
        """
        self.client.post("/equipamentos/lote/novo/", {"model": self.model.pk, "quantity": 5, "condition": "BOM"})
        first_response = self.client.post("/equipamentos/lote/confirmar/")
        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(EquipmentBatch.objects.count(), 1)

        second_response = self.client.post("/equipamentos/lote/confirmar/")
        self.assertRedirects(second_response, "/equipamentos/lote/novo/")
        self.assertEqual(EquipmentBatch.objects.count(), 1, "Reenvio da confirmação criou um segundo lote.")
        self.assertEqual(Equipment.objects.count(), 5, "Reenvio da confirmação criou equipamentos duplicados.")

    def test_result_page_shows_batch_summary_and_action_links(self):
        self.client.post("/equipamentos/lote/novo/", {"model": self.model.pk, "quantity": 3, "condition": "BOM"})
        self.client.post("/equipamentos/lote/confirmar/")
        batch = EquipmentBatch.objects.get()

        response = self.client.get(f"/equipamentos/lote/{batch.id}/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(batch.first_patrimonio, content)
        self.assertIn(batch.last_patrimonio, content)
        self.assertIn(f"/equipamentos/?batch={batch.id}", content)
        self.assertIn(f"batch={batch.id}", content)  # links de exportação de QR/etiqueta do lote


class EquipmentBatchExportAndListFilterTest(TestCase):
    """
    "Ver equipamentos criados" e "Exportar etiquetas/QR deste lote"
    (pedido do usuário) — reaproveitam a listagem e os geradores de QR/
    etiqueta já existentes, filtrando por `?batch=<uuid>`.
    """

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        creator = User.objects.create_user(username="lote_export_creator", password="senha-forte-123", role=Role.ADMIN)
        User.objects.create_user(username="lote_export_admin", password="senha-forte-123", role=Role.ADMIN)

        # Um equipamento cadastrado individualmente ANTES do lote — não pode aparecer no filtro do lote.
        self.individual = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=creator))

        self.client.login(username="lote_export_admin", password="senha-forte-123")
        self.client.post("/equipamentos/lote/novo/", {"model": self.model.pk, "quantity": 5, "condition": "BOM"})
        self.client.post("/equipamentos/lote/confirmar/")
        self.batch = EquipmentBatch.objects.get()

    def test_list_view_filtered_by_batch_shows_only_batch_equipment(self):
        response = self.client.get(f"/equipamentos/?batch={self.batch.id}")
        equipment_list = list(response.context["equipment_list"])
        self.assertEqual(len(equipment_list), 5)
        self.assertNotIn(self.individual, equipment_list)
        for equipment in equipment_list:
            self.assertEqual(equipment.batch_id, self.batch.id)

    def test_qr_zip_export_filtered_by_batch_only_includes_batch_equipment(self):
        import zipfile
        from io import BytesIO

        response = self.client.get(f"/qrcodes/lote/qr.zip?batch={self.batch.id}")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(BytesIO(response.content)) as zf:
            names = zf.namelist()
        self.assertEqual(len(names), 5)
        self.assertNotIn(self.individual.patrimonio, "".join(names))

    def test_label_zip_export_filtered_by_batch_only_includes_batch_equipment(self):
        import zipfile
        from io import BytesIO

        response = self.client.get(f"/qrcodes/lote/etiquetas.zip?batch={self.batch.id}")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(BytesIO(response.content)) as zf:
            names = zf.namelist()
        self.assertEqual(len(names), 5)

    def test_export_without_batch_param_still_includes_everything_active(self):
        """Comportamento existente (exportar tudo) precisa continuar intacto quando `batch` não é informado."""
        import zipfile
        from io import BytesIO

        response = self.client.get("/qrcodes/lote/qr.zip")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(BytesIO(response.content)) as zf:
            names = zf.namelist()
        # 5 do lote + 1 individual criado no setUp = 6
        self.assertEqual(len(names), 6)

    def test_invalid_batch_param_is_ignored_not_500(self):
        response = self.client.get("/equipamentos/?batch=not-a-valid-uuid")
        self.assertEqual(response.status_code, 200)
