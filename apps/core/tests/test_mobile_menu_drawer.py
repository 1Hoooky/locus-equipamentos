"""
Drawer do menu mobile interno (`templates/base.html`) — etapa de UX/UI,
28/08/2026 (ver AUDITORIA_UX_HOME_NAVEGACAO_QR.md, item [24]). Cobre a
estrutura/acessibilidade básica e, principalmente, que as MESMAS
permissões já usadas na navegação desktop (e nas próprias views) foram
reaproveitadas — nenhuma regra nova foi inventada para o drawer.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()


class MobileMenuDrawerAccessibilityTest(TestCase):
    def setUp(self):
        User.objects.create_user(username="drawer_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="drawer_admin", password="senha-forte-123")

    def test_drawer_markup_has_required_accessibility_attributes(self):
        content = self.client.get("/equipamentos/").content.decode()

        self.assertIn('id="mobile-menu-drawer"', content)
        self.assertIn('id="mobile-menu-backdrop"', content)
        self.assertIn('aria-label="Menu principal"', content)
        self.assertIn('aria-controls="mobile-menu-drawer"', content)
        self.assertIn('aria-expanded="false"', content)
        self.assertIn('aria-label="Fechar menu"', content)

    def test_drawer_has_no_new_js_dependency(self):
        """Nenhuma lib nova (Alpine/React/etc.) foi adicionada — só vanilla JS inline, como todo o resto do projeto."""
        content = self.client.get("/equipamentos/").content.decode()
        for forbidden in ("alpinejs", "react", "vue.js", "jquery"):
            self.assertNotIn(forbidden, content.lower())

    def test_active_item_gets_aria_current(self):
        content = self.client.get("/equipamentos/").content.decode()
        # O link "Equipamentos" do drawer, na tela de listagem de
        # equipamentos, deve estar marcado como página atual.
        self.assertIn('aria-current="page"', content)


class MobileMenuDrawerPermissionMatrixTest(TestCase):
    """
    As mesmas condições `is_administrativo_ou_superior`/`is_admin` (ou
    `is_superuser`) já usadas na navegação desktop e nas views
    (RoleRequiredMixin/allowed_roles) — nada reescrito "de cabeça" para o
    drawer (auditoria, item [24]).
    """

    def _get_equipment_list_as(self, role, is_superuser=False):
        username = f"drawer_{role.lower()}_{'super' if is_superuser else 'plain'}"
        User.objects.create_user(username=username, password="senha-forte-123", role=role, is_superuser=is_superuser)
        self.client.login(username=username, password="senha-forte-123")
        return self.client.get("/equipamentos/").content.decode()

    def test_consulta_does_not_see_administrativo_or_admin_only_links(self):
        content = self._get_equipment_list_as("CONSULTA")
        for hidden_url in (
            "/equipamentos/novo/",
            "/equipamentos/lote/novo/",
            "/equipamentos/importar/",
            "/catalogo/categorias/",
            "/catalogo/modelos/",
            "/contas/usuarios/",
            "/operacao/diagnostico/locations-duplicadas/",
        ):
            self.assertNotIn(f'href="{hidden_url}"', content)

    def test_operacional_does_not_see_administrativo_or_admin_only_links(self):
        content = self._get_equipment_list_as("OPERACIONAL")
        for hidden_url in (
            "/equipamentos/novo/",
            "/catalogo/categorias/",
            "/contas/usuarios/",
            "/operacao/diagnostico/locations-duplicadas/",
        ):
            self.assertNotIn(f'href="{hidden_url}"', content)

    def test_administrativo_sees_catalog_and_equipment_management_links_but_not_admin_only(self):
        content = self._get_equipment_list_as("ADMINISTRATIVO")
        for visible_url in ("/equipamentos/novo/", "/equipamentos/lote/novo/", "/catalogo/categorias/", "/catalogo/modelos/"):
            self.assertIn(f'href="{visible_url}"', content)
        for hidden_url in ("/contas/usuarios/", "/equipamentos/importar/", "/operacao/diagnostico/locations-duplicadas/"):
            self.assertNotIn(f'href="{hidden_url}"', content)

    def test_admin_sees_every_group_including_diagnostics(self):
        content = self._get_equipment_list_as("ADMIN")
        for visible_url in (
            "/equipamentos/novo/",
            "/equipamentos/lote/novo/",
            "/equipamentos/importar/",
            "/catalogo/categorias/",
            "/catalogo/modelos/",
            "/contas/usuarios/",
            "/operacao/diagnostico/locations-duplicadas/",
        ):
            self.assertIn(f'href="{visible_url}"', content)

    def test_superuser_with_consulta_role_still_sees_admin_only_links(self):
        """Válvula de segurança padrão do Django (`is_superuser`) — mesmo raciocínio de RoleRequiredMixin."""
        content = self._get_equipment_list_as("CONSULTA", is_superuser=True)
        self.assertIn('href="/contas/usuarios/"', content)
        self.assertIn('href="/operacao/diagnostico/locations-duplicadas/"', content)

    def test_movimentacoes_is_not_a_standalone_menu_item(self):
        """Não existe listagem geral de Movement hoje (auditoria, item [23]) — não inventar tela/link só para o menu."""
        content = self._get_equipment_list_as("ADMIN")
        self.assertNotIn(">Movimentações<", content)
