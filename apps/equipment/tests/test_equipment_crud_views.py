"""
Testes das telas próprias de cadastro/edição de equipamento, alteração de
status/condição (com StatusHistory/ConditionHistory automáticos),
reclassificação e reemissão — fechamento da Fase 1: essas telas
substituem o Django admin como interface operacional, então precisam
validar permissão no backend exatamente como qualquer outra rota
sensível (especificação, seção 5/11).
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.models import ConditionHistory, Equipment, StatusHistory
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()


class EquipmentCreateViewTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        User.objects.create_user(username="cad_admin", password="senha-forte-123", role=Role.ADMIN)
        User.objects.create_user(username="cad_administrativo", password="senha-forte-123", role=Role.ADMINISTRATIVO)
        User.objects.create_user(username="cad_operacional", password="senha-forte-123", role=Role.OPERACIONAL)

    def test_administrativo_can_create_equipment_and_gets_atomic_patrimonio(self):
        self.client.login(username="cad_administrativo", password="senha-forte-123")
        response = self.client.post(
            "/equipamentos/novo/",
            {
                "model": self.model.pk,
                "serial_number": "SN-CRUD-1",
                "supplier": "Fornecedor Teste",
                "condition": "BOM",
                "notes": "cadastro via tela",
            },
        )
        self.assertEqual(response.status_code, 302)
        created = Equipment.objects.get(serial_number="SN-CRUD-1")
        self.assertEqual(created.patrimonio, "LOC-NI23BT-0001")
        self.assertEqual(created.status, "DISPONIVEL")

    def test_operacional_cannot_create_equipment(self):
        self.client.login(username="cad_operacional", password="senha-forte-123")
        response = self.client.get("/equipamentos/novo/")
        self.assertEqual(response.status_code, 403)

    def test_anonymous_is_redirected(self):
        response = self.client.get("/equipamentos/novo/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/contas/login/", response.url)


class EquipmentUpdateViewTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=category, name="NI23 Big Tank", code="NI23BT")
        self.creator = User.objects.create_user(username="upd_creator", password="senha-forte-123", role=Role.ADMIN)
        self.equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.creator))
        User.objects.create_user(username="upd_administrativo", password="senha-forte-123", role=Role.ADMINISTRATIVO)
        User.objects.create_user(username="upd_consulta", password="senha-forte-123", role=Role.CONSULTA)

    def test_administrativo_can_edit_non_immutable_fields(self):
        self.client.login(username="upd_administrativo", password="senha-forte-123")
        response = self.client.post(
            f"/equipamentos/{self.equipment.patrimonio}/editar/",
            {
                "serial_number": "SN-EDITADO",
                "legacy_code": "",
                "supplier": "Novo Fornecedor",
                "acquisition_date": "",
                "acquisition_value": "",
                "notes": "editado pela tela",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.serial_number, "SN-EDITADO")

    def test_edit_form_cannot_change_model_status_or_patrimonio(self):
        """O form de edição nem expõe esses campos — POST extra neles não deve ter efeito algum."""
        other_model = EquipmentModel.objects.create(
            category=self.model.category, name="NI23 Tanque Caixa", code="NI23TC"
        )
        self.client.login(username="upd_administrativo", password="senha-forte-123")
        original_patrimonio = self.equipment.patrimonio
        self.client.post(
            f"/equipamentos/{self.equipment.patrimonio}/editar/",
            {
                "serial_number": "SN-2",
                "supplier": "",
                "acquisition_date": "",
                "acquisition_value": "",
                "notes": "",
                "model": other_model.pk,
                "status": "INATIVO",
                "patrimonio": "LOC-FORJADO-0001",
            },
        )
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.patrimonio, original_patrimonio)
        self.assertEqual(self.equipment.model_id, self.model.pk)
        self.assertEqual(self.equipment.status, "DISPONIVEL")

    def test_consulta_cannot_edit(self):
        self.client.login(username="upd_consulta", password="senha-forte-123")
        response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/editar/")
        self.assertEqual(response.status_code, 403)


class EquipmentChangeStatusConditionViewTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Torre", code="AQCT")
        creator = User.objects.create_user(username="status_creator", password="senha-forte-123", role=Role.ADMIN)
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))
        self.operacional = User.objects.create_user(
            username="status_operacional", password="senha-forte-123", role=Role.OPERACIONAL
        )
        User.objects.create_user(username="status_consulta", password="senha-forte-123", role=Role.CONSULTA)

    def test_operacional_can_change_status_and_history_is_created(self):
        self.client.login(username="status_operacional", password="senha-forte-123")
        response = self.client.post(
            f"/equipamentos/{self.equipment.patrimonio}/status/",
            {"new_status": "MANUTENCAO", "reason": "Vazamento identificado na vistoria."},
        )
        self.assertEqual(response.status_code, 302)

        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, "MANUTENCAO")

        history = StatusHistory.objects.get(equipment=self.equipment)
        self.assertEqual(history.old_value, "DISPONIVEL")
        self.assertEqual(history.new_value, "MANUTENCAO")
        self.assertEqual(history.changed_by, self.operacional)
        self.assertEqual(history.reason, "Vazamento identificado na vistoria.")

    def test_operacional_can_change_condition_and_history_is_created(self):
        self.client.login(username="status_operacional", password="senha-forte-123")
        response = self.client.post(
            f"/equipamentos/{self.equipment.patrimonio}/condicao/",
            {"new_condition": "RUIM", "reason": "Amassado no transporte."},
        )
        self.assertEqual(response.status_code, 302)

        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.condition, "RUIM")

        history = ConditionHistory.objects.get(equipment=self.equipment)
        self.assertEqual(history.old_value, "BOM")
        self.assertEqual(history.new_value, "RUIM")
        self.assertEqual(history.reason, "Amassado no transporte.")

    def test_change_status_requires_reason(self):
        self.client.login(username="status_operacional", password="senha-forte-123")
        response = self.client.post(
            f"/equipamentos/{self.equipment.patrimonio}/status/", {"new_status": "MANUTENCAO", "reason": ""}
        )
        self.assertEqual(response.status_code, 200)  # re-renderiza com erro
        self.assertFalse(StatusHistory.objects.filter(equipment=self.equipment).exists())

    def test_consulta_cannot_change_status(self):
        self.client.login(username="status_consulta", password="senha-forte-123")
        response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/status/")
        self.assertEqual(response.status_code, 403)

    def test_multiple_changes_accumulate_history_without_overwriting(self):
        self.client.login(username="status_operacional", password="senha-forte-123")
        self.client.post(
            f"/equipamentos/{self.equipment.patrimonio}/status/", {"new_status": "EM_OPERACAO", "reason": "Locado."}
        )
        self.client.post(
            f"/equipamentos/{self.equipment.patrimonio}/status/",
            {"new_status": "MANUTENCAO", "reason": "Retornou com defeito."},
        )
        history = list(StatusHistory.objects.filter(equipment=self.equipment).order_by("changed_at"))
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].new_value, "EM_OPERACAO")
        self.assertEqual(history[1].old_value, "EM_OPERACAO")
        self.assertEqual(history[1].new_value, "MANUTENCAO")


class EquipmentReclassifyViewTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        self.other_model = EquipmentModel.objects.create(
            category=self.category, name="NI23 Tanque Caixa", code="NI23TC"
        )
        self.admin = User.objects.create_user(username="reclass_admin", password="senha-forte-123", role=Role.ADMIN)
        User.objects.create_user(username="reclass_administrativo", password="senha-forte-123", role=Role.ADMINISTRATIVO)
        self.equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))

    def test_admin_can_reclassify_and_patrimonio_is_kept(self):
        self.client.login(username="reclass_admin", password="senha-forte-123")
        original_patrimonio = self.equipment.patrimonio
        response = self.client.post(
            f"/equipamentos/{self.equipment.patrimonio}/reclassificar/",
            {"new_model": self.other_model.pk, "reason": "Cadastrado com o modelo errado na importação."},
        )
        self.assertEqual(response.status_code, 302)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.patrimonio, original_patrimonio)
        self.assertEqual(self.equipment.model_id, self.other_model.pk)

    def test_administrativo_cannot_reclassify(self):
        """Matriz seção 11: reclassificação é Administrador only, diferente de cadastro/edição comum."""
        self.client.login(username="reclass_administrativo", password="senha-forte-123")
        response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/reclassificar/")
        self.assertEqual(response.status_code, 403)


class EquipmentSupersedeViewTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        self.other_model = EquipmentModel.objects.create(
            category=self.category, name="NI23 Tanque Caixa", code="NI23TC"
        )
        self.admin = User.objects.create_user(username="supersede_admin", password="senha-forte-123", role=Role.ADMIN)
        User.objects.create_user(username="supersede_administrativo", password="senha-forte-123", role=Role.ADMINISTRATIVO)
        self.equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))

    def test_admin_can_supersede_with_confirmation(self):
        self.client.login(username="supersede_admin", password="senha-forte-123")
        old_patrimonio = self.equipment.patrimonio
        response = self.client.post(
            f"/equipamentos/{self.equipment.patrimonio}/reemitir/",
            {
                "new_model": self.other_model.pk,
                "reason": "Categoria errada, precisa reimprimir etiqueta.",
                "confirm_reprint": "on",
            },
        )
        self.assertEqual(response.status_code, 302)

        self.equipment.refresh_from_db()
        self.assertFalse(self.equipment.is_active)
        self.assertEqual(self.equipment.patrimonio, old_patrimonio)

        new_equipment = Equipment.objects.get(model=self.other_model)
        self.assertNotEqual(new_equipment.patrimonio, old_patrimonio)
        self.assertEqual(self.equipment.superseded_by, new_equipment)

    def test_supersede_without_confirmation_checkbox_fails(self):
        self.client.login(username="supersede_admin", password="senha-forte-123")
        response = self.client.post(
            f"/equipamentos/{self.equipment.patrimonio}/reemitir/",
            {"new_model": self.other_model.pk, "reason": "Motivo qualquer."},
        )
        self.assertEqual(response.status_code, 200)
        self.equipment.refresh_from_db()
        self.assertTrue(self.equipment.is_active)

    def test_administrativo_cannot_supersede(self):
        self.client.login(username="supersede_administrativo", password="senha-forte-123")
        response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/reemitir/")
        self.assertEqual(response.status_code, 403)


class EquipmentListFiltersTest(TestCase):
    def setUp(self):
        self.category_a = Category.objects.create(name="Climatizador")
        self.category_b = Category.objects.create(name="Aquecedor")
        self.model_a = EquipmentModel.objects.create(category=self.category_a, name="NI23 Big Tank", code="NI23BT")
        self.model_b = EquipmentModel.objects.create(category=self.category_b, name="Aquecedor Torre", code="AQCT")
        creator = User.objects.create_user(username="filter_creator", password="senha-forte-123", role=Role.ADMIN)

        self.eq_a = create_equipment(NewEquipmentData(model_id=self.model_a.pk, created_by=creator))
        self.eq_b = create_equipment(
            NewEquipmentData(model_id=self.model_b.pk, created_by=creator, condition="RUIM")
        )
        self.eq_b.status = "MANUTENCAO"
        self.eq_b.save(update_fields=["status"])

        User.objects.create_user(username="filter_consulta", password="senha-forte-123", role=Role.CONSULTA)
        self.client.login(username="filter_consulta", password="senha-forte-123")

    def test_filter_by_status(self):
        response = self.client.get("/equipamentos/?status=MANUTENCAO")
        equipment_list = list(response.context["equipment_list"])
        self.assertEqual(equipment_list, [self.eq_b])

    def test_filter_by_condition(self):
        response = self.client.get("/equipamentos/?condition=RUIM")
        equipment_list = list(response.context["equipment_list"])
        self.assertEqual(equipment_list, [self.eq_b])

    def test_filter_by_category(self):
        response = self.client.get(f"/equipamentos/?category={self.category_a.pk}")
        equipment_list = list(response.context["equipment_list"])
        self.assertEqual(equipment_list, [self.eq_a])

    def test_filter_by_model(self):
        response = self.client.get(f"/equipamentos/?model={self.model_b.pk}")
        equipment_list = list(response.context["equipment_list"])
        self.assertEqual(equipment_list, [self.eq_b])

    def test_list_context_has_filter_options(self):
        response = self.client.get("/equipamentos/")
        self.assertIn(self.category_a, list(response.context["categories"]))

    def test_non_numeric_category_filter_is_ignored_not_500(self):
        """Regressão (auditoria final da Fase 1, 2026-08-25): category/model
        são filtros por PK (FK) — um valor não numérico levantava ValueError
        dentro do ORM (500) em vez de ser ignorado como um filtro inválido."""
        response = self.client.get("/equipamentos/?category=abc")
        self.assertEqual(response.status_code, 200)
        equipment_list = list(response.context["equipment_list"])
        self.assertCountEqual(equipment_list, [self.eq_a, self.eq_b])

    def test_non_numeric_model_filter_is_ignored_not_500(self):
        response = self.client.get("/equipamentos/?model=xyz")
        self.assertEqual(response.status_code, 200)
        equipment_list = list(response.context["equipment_list"])
        self.assertCountEqual(equipment_list, [self.eq_a, self.eq_b])
        self.assertIn(self.model_a, list(response.context["models"]))
        self.assertEqual(dict(response.context["status_choices"]).keys().__len__(), 4)
