"""
Sidebar administrativa DESKTOP (`templates/base.html`, >= 640px) — rodada
CORRETIVA de UX/UI (homologação no Render). Substitui
`test_desktop_nav_dropdowns.py` (a navegação por barra horizontal +
dropdowns "Cadastros"/"Administração" foi removida do template — nenhum
elemento `[data-dropdown]`/`#main-nav` é mais renderizado). Cobre a mesma
garantia de antes (permissões 100% reaproveitadas, nenhuma regra nova) e
acrescenta o comportamento novo: colapsar/expandir e a taxonomia
compartilhada com o drawer mobile (Operação/Cadastros/Administração).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()


class DesktopSidebarAccessibilityTest(TestCase):
    def setUp(self):
        User.objects.create_user(username="sidebar_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="sidebar_admin", password="senha-forte-123")

    def test_sidebar_markup_has_required_accessibility_attributes(self):
        content = self.client.get("/equipamentos/").content.decode()
        self.assertIn('id="app-sidebar"', content)
        self.assertIn('aria-label="Navegação principal"', content)
        self.assertIn('id="app-sidebar-toggle"', content)
        self.assertIn('aria-controls="app-sidebar"', content)
        self.assertIn('aria-expanded="true"', content)

    def test_sidebar_has_no_new_js_dependency(self):
        content = self.client.get("/equipamentos/").content.decode()
        for forbidden in ("alpinejs", "react", "vue.js", "jquery"):
            self.assertNotIn(forbidden, content.lower())

    def test_active_item_gets_aria_current_in_sidebar(self):
        content = self.client.get("/equipamentos/").content.decode()
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        self.assertIn('aria-current="page"', sidebar)

    def test_old_dropdown_navigation_is_gone(self):
        """A barra horizontal + dropdowns da etapa anterior não existem mais no template."""
        content = self.client.get("/equipamentos/").content.decode()
        body = content.split("<body", 1)[1]
        self.assertNotIn('id="main-nav"', body)
        self.assertNotIn("data-dropdown", body)
        self.assertNotIn('id="nav-dropdown-cadastros"', body)
        self.assertNotIn('id="nav-dropdown-administracao"', body)

    def test_sidebar_and_drawer_share_the_same_three_group_taxonomy(self):
        """
        Requisito explícito da rodada corretiva: desktop (sidebar) e mobile
        (drawer) usam a MESMA taxonomia de 3 grupos — Operação/Cadastros/
        Administração — nem mais nem menos grupos em nenhum dos dois.
        """
        content = self.client.get("/equipamentos/").content.decode()
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        drawer = content.split('id="mobile-menu-drawer"', 1)[1].split("</nav>", 1)[0]
        for surface_name, surface_html in (("sidebar", sidebar), ("drawer", drawer)):
            for group_title in ("Operação", "Cadastros", "Administração"):
                self.assertIn(group_title, surface_html, f"Grupo '{group_title}' ausente no {surface_name}")
            # Nenhum outro nome de grupo antigo sobrou (ex.: um grupo
            # "Equipamentos"/"Manutenção" separado, da estrutura anterior).
            self.assertEqual(
                surface_html.count('class="sidebar-group-title"') + surface_html.count('class="mobile-menu-group-title"'),
                3,
                f"{surface_name} deveria ter exatamente 3 títulos de grupo",
            )


class DesktopSidebarCollapseTest(TestCase):
    def setUp(self):
        User.objects.create_user(username="sidebar_collapse_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="sidebar_collapse_admin", password="senha-forte-123")

    def test_collapse_toggle_button_and_both_icon_states_are_rendered(self):
        content = self.client.get("/equipamentos/").content.decode()
        self.assertIn('id="app-sidebar-toggle-icon-expanded"', content)
        self.assertIn('id="app-sidebar-toggle-icon-collapsed"', content)
        # Recolhido/expandido é 100% client-side (JS alterna a classe
        # "is-collapsed" e o aria-expanded do botão) — o servidor sempre
        # manda os dois ícones e os dois textos de marca, um visível e
        # outro `hidden`, para o JS poder alternar sem re-renderizar.
        self.assertIn('id="app-sidebar-brand-full"', content)
        self.assertIn('id="app-sidebar-brand-compact"', content)

    def test_every_sidebar_link_has_title_and_aria_label_for_collapsed_state(self):
        """
        Requisito explícito: ícones isolados (sidebar recolhida) precisam
        de `aria-label`/`title` — como o recolhimento é só CSS/JS no
        cliente, isso significa que TODO link da sidebar já sai do
        servidor com os dois atributos, independente do estado inicial.
        """
        content = self.client.get("/equipamentos/").content.decode()
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        import re

        links = re.findall(r"<a\s[^>]*class=\"sidebar-link[^\"]*\"[^>]*>", sidebar)
        self.assertTrue(links, "Nenhum link de sidebar encontrado para verificar")
        for link_tag in links:
            self.assertIn("title=", link_tag)
            self.assertIn("aria-label=", link_tag)


class DesktopSidebarPermissionMatrixTest(TestCase):
    """Mesmas condições `is_administrativo_ou_superior`/`is_admin`/`is_superuser` já usadas antes — nada reescrito."""

    def _get_equipment_list_as(self, role, is_superuser=False):
        username = f"sidebar_{role.lower()}_{'super' if is_superuser else 'plain'}"
        User.objects.create_user(username=username, password="senha-forte-123", role=role, is_superuser=is_superuser)
        self.client.login(username=username, password="senha-forte-123")
        return self.client.get("/equipamentos/").content.decode()

    def test_consulta_sees_only_operacao_and_ungated_cadastros_items(self):
        content = self._get_equipment_list_as("CONSULTA")
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        for visible_url in ("/equipamentos/", "/manutencao/manutencoes/", "/clientes/", "/operacao/unidades/"):
            self.assertIn(f'href="{visible_url}"', sidebar)
        for hidden_url in (
            "/catalogo/categorias/",
            "/catalogo/modelos/",
            "/equipamentos/importar/",
            "/contas/usuarios/",
            "/operacao/diagnostico/locations-duplicadas/",
        ):
            self.assertNotIn(f'href="{hidden_url}"', sidebar)
        self.assertNotIn("Administração", sidebar)

    def test_administrativo_sees_cadastros_management_links_but_not_administracao_group(self):
        content = self._get_equipment_list_as("ADMINISTRATIVO")
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        for visible_url in ("/catalogo/categorias/", "/catalogo/modelos/"):
            self.assertIn(f'href="{visible_url}"', sidebar)
        for hidden_url in ("/equipamentos/importar/", "/contas/usuarios/", "/operacao/diagnostico/locations-duplicadas/"):
            self.assertNotIn(f'href="{hidden_url}"', sidebar)
        self.assertNotIn("Administração", sidebar)

    def test_admin_sees_every_group_including_diagnostics(self):
        content = self._get_equipment_list_as("ADMIN")
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        for visible_url in (
            "/catalogo/categorias/",
            "/catalogo/modelos/",
            "/equipamentos/importar/",
            "/contas/usuarios/",
            "/operacao/diagnostico/locations-duplicadas/",
        ):
            self.assertIn(f'href="{visible_url}"', sidebar)
        self.assertIn("Administração", sidebar)

    def test_superuser_with_consulta_role_still_sees_admin_only_links(self):
        content = self._get_equipment_list_as("CONSULTA", is_superuser=True)
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        self.assertIn('href="/contas/usuarios/"', sidebar)
        self.assertIn('href="/operacao/diagnostico/locations-duplicadas/"', sidebar)

    def test_movimentacoes_is_not_a_standalone_menu_item(self):
        content = self._get_equipment_list_as("ADMIN")
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        self.assertNotIn(">Movimentações<", sidebar)
