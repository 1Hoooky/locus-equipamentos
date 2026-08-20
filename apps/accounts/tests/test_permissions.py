"""
Testes da matriz de permissões — especificação, seção 11: "Essa matriz
deve virar testes automatizados, não apenas documentação."

O ponto central destes testes não é "o botão aparece na tela", e sim
"a rota recusa a ação mesmo chamada diretamente" — é isso que a
especificação pede explicitamente (seção 5: "Permissões são validadas no
backend/API em toda rota sensível, nunca apenas escondendo botões no
frontend").
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from apps.accounts.models import Role
from apps.accounts.permissions import CAN_MANAGE_USERS, roles_required

User = get_user_model()


@roles_required(*CAN_MANAGE_USERS)
def _fake_admin_only_view(request):
    return HttpResponse("ok")


class RolesRequiredDecoratorTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _user(self, role):
        return User.objects.create_user(username=f"user_{role.lower()}", password="senha-forte-123", role=role)

    def test_admin_can_access(self):
        request = self.factory.get("/fake/")
        request.user = self._user(Role.ADMIN)
        response = _fake_admin_only_view(request)
        self.assertEqual(response.status_code, 200)

    def test_non_admin_roles_are_rejected(self):
        for role in (Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA):
            with self.subTest(role=role):
                request = self.factory.get("/fake/")
                request.user = self._user(role)
                with self.assertRaises(PermissionDenied):
                    _fake_admin_only_view(request)

    def test_anonymous_is_rejected(self):
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get("/fake/")
        request.user = AnonymousUser()
        with self.assertRaises(PermissionDenied):
            _fake_admin_only_view(request)


class EquipmentListAccessTest(TestCase):
    """Todos os 4 perfis autenticados podem consultar (matriz, seção 11)."""

    def setUp(self):
        for role in (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA):
            User.objects.create_user(username=f"list_{role.lower()}", password="senha-forte-123", role=role)

    def test_all_roles_can_list_equipment(self):
        for role in (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA):
            with self.subTest(role=role):
                self.client.login(username=f"list_{role.lower()}", password="senha-forte-123")
                response = self.client.get("/equipamentos/")
                self.assertEqual(response.status_code, 200)
                self.client.logout()

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get("/equipamentos/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/contas/login/", response.url)
