"""
Integração do campo "Cargo" nos formulários de gestão de usuários
(`UserCreateForm`/`UserUpdateForm`, adjustment #7 da aprovação de
09/09/2026) — e a prova de que o sistema legado (`Role`/CAN_*/
`RoleRequiredMixin`) continua sendo a autorização de fato, independente
de o usuário ter ou não um Cargo atribuído (os dois sistemas coexistem
nesta rodada, ver apps/accounts/models.py).
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from django.test import TestCase

from apps.accounts.models import Role

User = get_user_model()

USER_CREATE_URL = "/contas/usuarios/novo/"


def _user_update_url(pk):
    return f"/contas/usuarios/{pk}/editar/"


class UserCreateFormCargoTest(TestCase):
    def setUp(self):
        User.objects.create_user(username="uc_admin", password="senha-forte-123", role=Role.ADMIN)
        self.client.login(username="uc_admin", password="senha-forte-123")
        self.operacional_group = Group.objects.get(name="Operacional")

    def test_creating_a_user_with_a_cargo_assigns_it(self):
        response = self.client.post(
            USER_CREATE_URL,
            {
                "username": "novo_operacional",
                "first_name": "Novo",
                "last_name": "Operacional",
                "email": "novo@example.com",
                "role": Role.OPERACIONAL,
                "cargo": self.operacional_group.pk,
                "password1": "senha-forte-123",
                "password2": "senha-forte-123",
            },
        )
        self.assertRedirects(response, "/contas/usuarios/")
        user = User.objects.get(username="novo_operacional")
        self.assertEqual(user.cargo, self.operacional_group)

    def test_creating_a_user_without_a_cargo_leaves_it_unset(self):
        response = self.client.post(
            USER_CREATE_URL,
            {
                "username": "sem_cargo",
                "first_name": "Sem",
                "last_name": "Cargo",
                "email": "semcargo@example.com",
                "role": Role.CONSULTA,
                "cargo": "",
                "password1": "senha-forte-123",
                "password2": "senha-forte-123",
            },
        )
        self.assertRedirects(response, "/contas/usuarios/")
        user = User.objects.get(username="sem_cargo")
        self.assertIsNone(user.cargo)


class UserUpdateFormCargoTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="uu_admin", password="senha-forte-123", role=Role.ADMIN)
        self.client.login(username="uu_admin", password="senha-forte-123")
        self.target = User.objects.create_user(username="uu_target", password="senha-forte-123", role=Role.OPERACIONAL)
        self.operacional_group = Group.objects.get(name="Operacional")
        self.consulta_group = Group.objects.get(name="Consulta")

    def test_update_form_prefills_current_cargo(self):
        self.target.groups.set([self.operacional_group])
        response = self.client.get(_user_update_url(self.target.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].fields["cargo"].initial, self.operacional_group)

    def test_changing_cargo_replaces_the_previous_one(self):
        self.target.groups.set([self.operacional_group])
        response = self.client.post(
            _user_update_url(self.target.pk),
            {
                "first_name": self.target.first_name,
                "last_name": self.target.last_name,
                "email": self.target.email,
                "role": self.target.role,
                "is_active": "on",
                "cargo": self.consulta_group.pk,
            },
        )
        self.assertRedirects(response, "/contas/usuarios/")
        self.target.refresh_from_db()
        self.assertEqual(list(self.target.groups.all()), [self.consulta_group])


class LegacyAuthorizationIndependentOfCargoTest(TestCase):
    """
    Prova explícita de que, nesta rodada, o novo Cargo NÃO participa da
    autorização de nenhuma view existente — só `Role`/CAN_*/
    `RoleRequiredMixin` (adjustment #10/#11 da aprovação: não alterar o
    legado). Um usuário Role.ADMIN sem NENHUM cargo atribuído continua
    acessando telas administrativas normalmente; um usuário com o cargo
    "Administrador" mas Role.CONSULTA continua BLOQUEADO.
    """

    def test_admin_role_without_any_cargo_still_has_full_legacy_access(self):
        user = User.objects.create_user(username="legacy_admin_no_cargo", password="senha-forte-123", role=Role.ADMIN)
        self.assertIsNone(user.cargo)
        self.client.login(username="legacy_admin_no_cargo", password="senha-forte-123")
        response = self.client.get("/contas/usuarios/")
        self.assertEqual(response.status_code, 200)

    def test_consulta_role_with_administrador_cargo_is_still_blocked_by_legacy_views(self):
        user = User.objects.create_user(username="legacy_consulta_admin_cargo", password="senha-forte-123", role=Role.CONSULTA)
        admin_group = Group.objects.get(name="Administrador")
        user.groups.set([admin_group])
        self.client.login(username="legacy_consulta_admin_cargo", password="senha-forte-123")
        response = self.client.get("/contas/usuarios/")
        self.assertEqual(response.status_code, 403)
