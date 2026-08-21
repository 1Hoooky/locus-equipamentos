"""
Testes das telas próprias de categoria/modelo — fechamento da Fase 1.
Cobrem a matriz de permissões (Administrador/Administrativo, seção 11) e
a trava de `code` assim que o modelo já tem equipamento vinculado
(especificação, seção 8), agora reforçada no formulário além do
`EquipmentModel.clean()`.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()


class CategoryViewsTest(TestCase):
    def setUp(self):
        User.objects.create_user(username="cat_administrativo", password="senha-forte-123", role=Role.ADMINISTRATIVO)
        User.objects.create_user(username="cat_operacional", password="senha-forte-123", role=Role.OPERACIONAL)

    def test_administrativo_can_create_category(self):
        self.client.login(username="cat_administrativo", password="senha-forte-123")
        response = self.client.post("/catalogo/categorias/nova/", {"name": "Ventilador", "is_active": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Category.objects.filter(name="Ventilador").exists())

    def test_administrativo_can_edit_category(self):
        category = Category.objects.create(name="Original")
        self.client.login(username="cat_administrativo", password="senha-forte-123")
        response = self.client.post(f"/catalogo/categorias/{category.pk}/editar/", {"name": "Original", "is_active": ""})
        self.assertEqual(response.status_code, 302)
        category.refresh_from_db()
        self.assertFalse(category.is_active)

    def test_operacional_cannot_manage_categories(self):
        self.client.login(username="cat_operacional", password="senha-forte-123")
        self.assertEqual(self.client.get("/catalogo/categorias/").status_code, 403)
        self.assertEqual(self.client.get("/catalogo/categorias/nova/").status_code, 403)

    def test_anonymous_is_redirected(self):
        response = self.client.get("/catalogo/categorias/")
        self.assertEqual(response.status_code, 302)


class EquipmentModelViewsTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        User.objects.create_user(username="model_administrativo", password="senha-forte-123", role=Role.ADMINISTRATIVO)
        User.objects.create_user(username="model_consulta", password="senha-forte-123", role=Role.CONSULTA)

    def test_administrativo_can_create_model(self):
        self.client.login(username="model_administrativo", password="senha-forte-123")
        response = self.client.post(
            "/catalogo/modelos/novo/",
            {"category": self.category.pk, "name": "Novo Modelo", "code": "NOVO1", "manufacturer": "", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(EquipmentModel.objects.filter(code="NOVO1").exists())

    def test_code_is_editable_before_any_equipment_exists(self):
        model = EquipmentModel.objects.create(category=self.category, name="Modelo Livre", code="LIVRE1")
        self.client.login(username="model_administrativo", password="senha-forte-123")
        response = self.client.post(
            f"/catalogo/modelos/{model.pk}/editar/",
            {"category": self.category.pk, "name": "Modelo Livre", "code": "LIVRE2", "manufacturer": "", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 302)
        model.refresh_from_db()
        self.assertEqual(model.code, "LIVRE2")

    def test_code_is_locked_in_the_form_once_equipment_exists(self):
        model = EquipmentModel.objects.create(category=self.category, name="Modelo Travado", code="TRAVA1")
        creator = User.objects.create_user(username="model_creator", password="senha-forte-123", role=Role.ADMIN)
        create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))

        self.client.login(username="model_administrativo", password="senha-forte-123")

        # mesmo tentando forçar um novo `code` no POST, o campo desabilitado
        # no form ignora o valor enviado e mantém o original.
        response = self.client.post(
            f"/catalogo/modelos/{model.pk}/editar/",
            {
                "category": self.category.pk,
                "name": "Modelo Travado",
                "code": "FORCADO",
                "manufacturer": "",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        model.refresh_from_db()
        self.assertEqual(model.code, "TRAVA1")

    def test_consulta_cannot_manage_models(self):
        self.client.login(username="model_consulta", password="senha-forte-123")
        self.assertEqual(self.client.get("/catalogo/modelos/").status_code, 403)
