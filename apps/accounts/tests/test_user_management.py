"""
Testes da gestão de usuários pela interface web — especificação, seção 12
("Gestão de usuários", substituindo o admin/shell). Cobre criação, edição
de perfil/status e a trava de "não pode desativar a si mesmo", além da
matriz de permissões (seção 11: só Administrador acessa estas telas).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role

User = get_user_model()


class UserListAccessTest(TestCase):
    def setUp(self):
        User.objects.create_user(username="admin_ul", password="senha-forte-123", role=Role.ADMIN)
        for role in (Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA):
            User.objects.create_user(username=f"ul_{role.lower()}", password="senha-forte-123", role=role)

    def test_admin_can_list_users(self):
        self.client.login(username="admin_ul", password="senha-forte-123")
        response = self.client.get("/contas/usuarios/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin_ul")

    def test_non_admin_roles_are_rejected(self):
        for role in (Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA):
            with self.subTest(role=role):
                self.client.login(username=f"ul_{role.lower()}", password="senha-forte-123")
                response = self.client.get("/contas/usuarios/")
                self.assertEqual(response.status_code, 403)
                self.client.logout()

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get("/contas/usuarios/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/contas/login/", response.url)


class UserCreateViewTest(TestCase):
    def setUp(self):
        User.objects.create_user(username="admin_uc", password="senha-forte-123", role=Role.ADMIN)
        User.objects.create_user(username="consulta_uc", password="senha-forte-123", role=Role.CONSULTA)

    def test_get_renders_form(self):
        self.client.login(username="admin_uc", password="senha-forte-123")
        response = self.client.get("/contas/usuarios/novo/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Novo usuário")

    def test_admin_can_create_user_with_role(self):
        self.client.login(username="admin_uc", password="senha-forte-123")
        response = self.client.post(
            "/contas/usuarios/novo/",
            {
                "username": "novo_operacional",
                "first_name": "Novo",
                "last_name": "Operacional",
                "email": "novo@locuslocacoes.com.br",
                "role": Role.OPERACIONAL,
                "password1": "uma-senha-bem-forte-456",
                "password2": "uma-senha-bem-forte-456",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/contas/usuarios/")

        created = User.objects.get(username="novo_operacional")
        self.assertEqual(created.role, Role.OPERACIONAL)
        self.assertTrue(created.check_password("uma-senha-bem-forte-456"))

        # A senha definida na criação já funciona para login.
        self.client.logout()
        self.assertTrue(self.client.login(username="novo_operacional", password="uma-senha-bem-forte-456"))

    def test_invalid_submission_does_not_create_user(self):
        self.client.login(username="admin_uc", password="senha-forte-123")
        response = self.client.post(
            "/contas/usuarios/novo/",
            {
                "username": "quebrado",
                "role": Role.OPERACIONAL,
                "password1": "senha-a",
                "password2": "senha-b-diferente",
            },
        )
        self.assertEqual(response.status_code, 200)  # re-renderiza o formulário com erro
        self.assertFalse(User.objects.filter(username="quebrado").exists())

    def test_non_admin_cannot_create_user(self):
        self.client.login(username="consulta_uc", password="senha-forte-123")
        response = self.client.get("/contas/usuarios/novo/")
        self.assertEqual(response.status_code, 403)


class UserUpdateViewTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin_uu", password="senha-forte-123", role=Role.ADMIN)
        self.other_admin = User.objects.create_user(
            username="outro_admin_uu", password="senha-forte-123", role=Role.ADMIN
        )
        self.target = User.objects.create_user(
            username="alvo_uu", password="senha-forte-123", role=Role.OPERACIONAL
        )
        User.objects.create_user(username="consulta_uu", password="senha-forte-123", role=Role.CONSULTA)

    def test_get_renders_form_for_target_user(self):
        self.client.login(username="admin_uu", password="senha-forte-123")
        response = self.client.get(f"/contas/usuarios/{self.target.pk}/editar/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "alvo_uu")

    def test_admin_can_change_role_and_deactivate_another_user(self):
        self.client.login(username="admin_uu", password="senha-forte-123")
        response = self.client.post(
            f"/contas/usuarios/{self.target.pk}/editar/",
            {
                "first_name": self.target.first_name,
                "last_name": self.target.last_name,
                "email": self.target.email,
                "role": Role.ADMINISTRATIVO,
                # is_active ausente = desmarcado (checkbox HTML)
            },
        )
        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertEqual(self.target.role, Role.ADMINISTRATIVO)
        self.assertFalse(self.target.is_active)

    def test_admin_cannot_deactivate_self(self):
        self.client.login(username="admin_uu", password="senha-forte-123")
        response = self.client.post(
            f"/contas/usuarios/{self.admin.pk}/editar/",
            {
                "first_name": self.admin.first_name,
                "last_name": self.admin.last_name,
                "email": self.admin.email,
                "role": Role.ADMIN,
                # is_active ausente = tentativa de se autodesativar
            },
        )
        self.assertEqual(response.status_code, 200)  # re-renderiza com erro, não redireciona
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)  # continua ativo

    def test_admin_can_edit_self_without_touching_active_flag(self):
        self.client.login(username="admin_uu", password="senha-forte-123")
        response = self.client.post(
            f"/contas/usuarios/{self.admin.pk}/editar/",
            {
                "first_name": "Nome Atualizado",
                "last_name": self.admin.last_name,
                "email": self.admin.email,
                "role": Role.ADMIN,
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.first_name, "Nome Atualizado")
        self.assertTrue(self.admin.is_active)

    def test_non_admin_cannot_update_user(self):
        self.client.login(username="consulta_uu", password="senha-forte-123")
        response = self.client.get(f"/contas/usuarios/{self.target.pk}/editar/")
        self.assertEqual(response.status_code, 403)
