"""
Views de gestão de Cargos (`apps/accounts/views_roles.py`) — restritas a
SUPERUSUÁRIO (`SuperuserRequiredMixin`, Nível C de sensibilidade, ver
apps/accounts/permission_catalog.py), deliberadamente mais estrito que
Administrador (`Role.ADMIN`/CAN_*). O ponto central destes testes é
provar que um Administrador comum (sem `is_superuser=True`) NÃO acessa
estas telas — é exatamente o comportamento que distingue Nível B de
Nível C na classificação de sensibilidade da aprovação de 09/09/2026.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from django.test import TestCase

from apps.accounts.models import Role

User = get_user_model()

ROLE_LIST_URL = "/contas/cargos/"
ROLE_CREATE_URL = "/contas/cargos/novo/"


def _role_update_url(pk):
    return f"/contas/cargos/{pk}/editar/"


def _role_delete_url(pk):
    return f"/contas/cargos/{pk}/excluir/"


class RoleViewsAccessControlTest(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_user(
            username="role_super", password="senha-forte-123", role=Role.ADMIN, is_superuser=True, is_staff=True
        )
        self.plain_admin = User.objects.create_user(username="role_plain_admin", password="senha-forte-123", role=Role.ADMIN)
        self.consulta_user = User.objects.create_user(username="role_consulta", password="senha-forte-123", role=Role.CONSULTA)
        self.operacional_group = Group.objects.get(name="Operacional")

    def test_superuser_can_list_cargos(self):
        self.client.login(username="role_super", password="senha-forte-123")
        response = self.client.get(ROLE_LIST_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Administrador")

    def test_plain_admin_role_is_rejected_even_though_admin_manages_everything_else(self):
        """
        Diferença deliberada de `RoleRequiredMixin`: `Role.ADMIN` sozinho
        NÃO basta para a gestão de cargos — só `is_superuser`.
        """
        self.client.login(username="role_plain_admin", password="senha-forte-123")
        response = self.client.get(ROLE_LIST_URL)
        self.assertEqual(response.status_code, 403)

    def test_non_admin_role_is_rejected(self):
        self.client.login(username="role_consulta", password="senha-forte-123")
        response = self.client.get(ROLE_LIST_URL)
        self.assertEqual(response.status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(ROLE_LIST_URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/contas/login/", response.url)

    def test_create_update_delete_all_require_superuser(self):
        self.client.login(username="role_plain_admin", password="senha-forte-123")
        for response in (
            self.client.get(ROLE_CREATE_URL),
            self.client.get(_role_update_url(self.operacional_group.pk)),
            self.client.post(_role_delete_url(self.operacional_group.pk)),
        ):
            with self.subTest(status=response.status_code):
                self.assertEqual(response.status_code, 403)


class RoleCreateViewTest(TestCase):
    def setUp(self):
        User.objects.create_user(
            username="role_creator", password="senha-forte-123", role=Role.ADMIN, is_superuser=True, is_staff=True
        )
        self.client.login(username="role_creator", password="senha-forte-123")

    def test_creates_cargo_with_selected_permissions(self):
        from django.contrib.auth.models import Permission

        perm = Permission.objects.get(codename="view_clients", content_type__app_label="clients")
        response = self.client.post(
            ROLE_CREATE_URL,
            {"name": "Suporte N1", "description": "Atendimento", "permissions": [perm.pk]},
        )
        self.assertRedirects(response, ROLE_LIST_URL)
        cargo = Group.objects.get(name="Suporte N1")
        self.assertEqual(list(cargo.permissions.values_list("codename", flat=True)), ["view_clients"])

    def test_rejects_duplicate_name(self):
        response = self.client.post(ROLE_CREATE_URL, {"name": "Administrador", "description": "", "permissions": []})
        self.assertEqual(response.status_code, 200)  # re-renderiza com erro, não redireciona
        self.assertContains(response, "Já existe um cargo")


class RoleUpdateViewProtectionTest(TestCase):
    def setUp(self):
        User.objects.create_user(
            username="role_editor", password="senha-forte-123", role=Role.ADMIN, is_superuser=True, is_staff=True
        )
        self.client.login(username="role_editor", password="senha-forte-123")
        self.admin_group = Group.objects.get(name="Administrador")
        self.operacional_group = Group.objects.get(name="Operacional")

    def test_get_shows_protected_state_without_error(self):
        response = self.client.get(_role_update_url(self.admin_group.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Acesso total")

    def test_post_on_protected_cargo_is_rejected_and_makes_no_change(self):
        original_permission_count = self.admin_group.permissions.count()
        response = self.client.post(
            _role_update_url(self.admin_group.pk),
            {"name": "Administrador Hackeado", "description": "", "permissions": []},
        )
        self.assertRedirects(response, ROLE_LIST_URL)
        self.admin_group.refresh_from_db()
        self.assertEqual(self.admin_group.name, "Administrador")
        self.assertEqual(self.admin_group.permissions.count(), original_permission_count)

    def test_post_on_unprotected_cargo_updates_permissions(self):
        from django.contrib.auth.models import Permission

        perm = Permission.objects.get(codename="manage_locations", content_type__app_label="operations")
        response = self.client.post(
            _role_update_url(self.operacional_group.pk),
            {"name": "Operacional", "description": "Ajustado", "permissions": [perm.pk]},
        )
        self.assertRedirects(response, ROLE_LIST_URL)
        self.operacional_group.refresh_from_db()
        self.assertEqual(
            list(self.operacional_group.permissions.values_list("codename", flat=True)), ["manage_locations"]
        )


class RoleDeleteViewTest(TestCase):
    def setUp(self):
        User.objects.create_user(
            username="role_deleter", password="senha-forte-123", role=Role.ADMIN, is_superuser=True, is_staff=True
        )
        self.client.login(username="role_deleter", password="senha-forte-123")

    def test_cannot_delete_protected_cargo(self):
        admin_group = Group.objects.get(name="Administrador")
        response = self.client.post(_role_delete_url(admin_group.pk))
        self.assertRedirects(response, ROLE_LIST_URL)
        self.assertTrue(Group.objects.filter(pk=admin_group.pk).exists())

    def test_cannot_delete_cargo_with_users(self):
        operacional_group = Group.objects.get(name="Operacional")
        user = User.objects.create_user(username="role_delete_target", password="senha-forte-123")
        user.groups.set([operacional_group])
        response = self.client.post(_role_delete_url(operacional_group.pk))
        self.assertRedirects(response, ROLE_LIST_URL)
        self.assertTrue(Group.objects.filter(pk=operacional_group.pk).exists())

    def test_deletes_an_empty_unprotected_cargo(self):
        financeiro_group = Group.objects.get(name="Financeiro")
        response = self.client.post(_role_delete_url(financeiro_group.pk))
        self.assertRedirects(response, ROLE_LIST_URL)
        self.assertFalse(Group.objects.filter(pk=financeiro_group.pk).exists())
