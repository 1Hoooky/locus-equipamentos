"""
Matriz de permissões da UI de Manutenção/Higienização (revisão de
27/08/2026, item 9): leitura via `CAN_VIEW_MAINTENANCE` (4 perfis),
escrita via `CAN_REGISTER_OPERATIONS` (Admin/Administrativo/Operacional —
Consulta NUNCA alcança nenhuma view de escrita, mesmo manipulando a
URL/POST diretamente). A proteção testada aqui é sempre no BACKEND
(`RoleRequiredMixin`), nunca "o botão não aparece".
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.maintenance.services import CloseMaintenanceData, NewCleaningData, NewMaintenanceData, close_maintenance, create_cleaning, open_maintenance

User = get_user_model()

ALL_ROLES = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA)
WRITE_ROLES = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL)
READ_ONLY_ROLES = (Role.CONSULTA,)


class MaintenancePermissionsTestBase(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Categoria Permissões")
        model = EquipmentModel.objects.create(category=category, name="Modelo Permissões", code="PERM")
        self.admin = User.objects.create_user(username="perm_creator_admin", password="senha-forte-123", role=Role.ADMIN)
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))

        for role in ALL_ROLES:
            User.objects.create_user(username=f"perm_{role.lower()}", password="senha-forte-123", role=role)

    def _login(self, role):
        self.client.login(username=f"perm_{role.lower()}", password="senha-forte-123")

    def _user(self, role):
        return User.objects.get(username=f"perm_{role.lower()}")


class ReadViewsAllRolesTest(MaintenancePermissionsTestBase):
    def test_all_four_roles_can_view_maintenance_list(self):
        for role in ALL_ROLES:
            with self.subTest(role=role):
                self._login(role)
                response = self.client.get("/manutencao/manutencoes/")
                self.assertEqual(response.status_code, 200)
                self.client.logout()

    def test_all_four_roles_can_view_cleaning_list(self):
        for role in ALL_ROLES:
            with self.subTest(role=role):
                self._login(role)
                response = self.client.get("/manutencao/higienizacoes/")
                self.assertEqual(response.status_code, 200)
                self.client.logout()

    def test_all_four_roles_can_view_maintenance_detail(self):
        maintenance = open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type="CORRETIVA",
                responsible=self.admin,
                created_by=self.admin,
            )
        )
        for role in ALL_ROLES:
            with self.subTest(role=role):
                self._login(role)
                response = self.client.get(f"/manutencao/manutencoes/{maintenance.pk}/")
                self.assertEqual(response.status_code, 200)
                self.client.logout()

    def test_all_four_roles_can_view_cleaning_detail(self):
        cleaning = create_cleaning(
            NewCleaningData(equipment_id=self.equipment.pk, responsible=self.admin, created_by=self.admin)
        )
        for role in ALL_ROLES:
            with self.subTest(role=role):
                self._login(role)
                response = self.client.get(f"/manutencao/higienizacoes/{cleaning.pk}/")
                self.assertEqual(response.status_code, 200)
                self.client.logout()

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get("/manutencao/manutencoes/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/contas/login/", response.url)


class WriteViewsRoleMatrixTest(MaintenancePermissionsTestBase):
    def test_open_maintenance_get(self):
        for role in WRITE_ROLES:
            with self.subTest(role=role):
                self._login(role)
                response = self.client.get("/manutencao/manutencoes/abrir/")
                self.assertEqual(response.status_code, 200)
                self.client.logout()
        for role in READ_ONLY_ROLES:
            with self.subTest(role=role):
                self._login(role)
                response = self.client.get("/manutencao/manutencoes/abrir/")
                self.assertEqual(response.status_code, 403)
                self.client.logout()

    def test_open_maintenance_post_rejected_for_consulta(self):
        self._login(Role.CONSULTA)
        response = self.client.post(
            "/manutencao/manutencoes/abrir/",
            {
                "equipment": self.equipment.pk,
                "maintenance_type": "CORRETIVA",
                "responsible": self.admin.pk,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.equipment.maintenances.count(), 0)

    def test_close_maintenance_rejected_for_consulta(self):
        maintenance = open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type="CORRETIVA",
                responsible=self.admin,
                created_by=self.admin,
            )
        )
        self._login(Role.CONSULTA)
        response = self.client.get(f"/manutencao/manutencoes/{maintenance.pk}/concluir/")
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            f"/manutencao/manutencoes/{maintenance.pk}/concluir/", {"service_performed": "Tentativa indevida."}
        )
        self.assertEqual(response.status_code, 403)
        maintenance.refresh_from_db()
        self.assertEqual(maintenance.status, "ABERTA")

    def test_cancel_maintenance_rejected_for_consulta(self):
        maintenance = open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type="CORRETIVA",
                responsible=self.admin,
                created_by=self.admin,
            )
        )
        self._login(Role.CONSULTA)
        response = self.client.post(
            f"/manutencao/manutencoes/{maintenance.pk}/cancelar/", {"reason": "Tentativa indevida.", "confirm": "on"}
        )
        self.assertEqual(response.status_code, 403)
        maintenance.refresh_from_db()
        self.assertEqual(maintenance.status, "ABERTA")

    def test_create_cleaning_rejected_for_consulta(self):
        self._login(Role.CONSULTA)
        response = self.client.post(
            "/manutencao/higienizacoes/registrar/", {"equipment": self.equipment.pk, "responsible": self.admin.pk}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.equipment.cleanings.count(), 0)

    def test_cancel_cleaning_rejected_for_consulta(self):
        cleaning = create_cleaning(
            NewCleaningData(equipment_id=self.equipment.pk, responsible=self.admin, created_by=self.admin)
        )
        self._login(Role.CONSULTA)
        response = self.client.post(f"/manutencao/higienizacoes/{cleaning.pk}/cancelar/", {"confirm": "on"})
        self.assertEqual(response.status_code, 403)
        cleaning.refresh_from_db()
        self.assertTrue(cleaning.is_active)

    def test_write_roles_can_open_close_cancel(self):
        for role in WRITE_ROLES:
            with self.subTest(role=role):
                self._login(role)
                token = self.client.get("/manutencao/manutencoes/abrir/").context["submission_token"]
                response = self.client.post(
                    "/manutencao/manutencoes/abrir/",
                    {
                        "equipment": self.equipment.pk,
                        "maintenance_type": "CORRETIVA",
                        "responsible": self.admin.pk,
                        "submission_token": token,
                    },
                    follow=True,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.equipment.maintenances.filter(status="ABERTA", is_active=True).count(), 1)

                maintenance = self.equipment.maintenances.get(status="ABERTA", is_active=True)
                cancel_token = self.client.get(f"/manutencao/manutencoes/{maintenance.pk}/cancelar/").context[
                    "submission_token"
                ]
                response = self.client.post(
                    f"/manutencao/manutencoes/{maintenance.pk}/cancelar/",
                    {
                        "reason": "Aberta só para o teste de permissão.",
                        "confirm": "on",
                        "submission_token": cancel_token,
                    },
                    follow=True,
                )
                self.assertEqual(response.status_code, 200)
                maintenance.refresh_from_db()
                self.assertEqual(maintenance.status, "CANCELADA")
                self.client.logout()
