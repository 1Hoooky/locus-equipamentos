"""
Drawer do menu mobile interno (`templates/base.html`) — cobre a estrutura/
acessibilidade básica e a matriz de permissões, reaproveitando as MESMAS
condições já usadas na sidebar desktop (e nas próprias views) — nenhuma
regra nova foi inventada para o drawer.

Atualizado na rodada de REFINAMENTO DA SIDEBAR / REORGANIZAÇÃO DA
ARQUITETURA DE NAVEGAÇÃO (11/09/2026): a taxonomia do drawer foi
realinhada para os MESMOS 4 grupos da sidebar desktop, na mesma ordem —
CRM (quando aplicável) / Operação / Cadastros / Configurações do sistema
(era "Administração" — ver test_desktop_sidebar.py). "Usuários" virou
"Colaboradores" (mesma URL/permissão, só o rótulo visual) e migrou para
dentro de Cadastros; os 4 grupos agora são um acordeão de verdade
(`.mobile-menu-group-toggle`/`.mobile-menu-group-body`, `aria-expanded`)
em vez de um título estático (`.mobile-menu-group-title`).
"""

import re

from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()


def _group_title_present(html, title):
    """Texto do título do grupo, tolerante a espaço/quebra de linha entre `>`/`<` e o texto (o botão de acordeão não coloca o texto colado ao `>` como o antigo `<p>` fazia)."""
    return re.search(r">\s*" + re.escape(title) + r"\s*<", html) is not None


class MobileMenuDrawerAccessibilityTest(TestCase):
    def setUp(self):
        # Superusuário: bypassa `ModelBackend.has_perm()` automaticamente,
        # então também vê o grupo CRM sem precisar atribuir Group/
        # Permission — estes testes cobrem estrutura/taxonomia comum a
        # TODOS os grupos, não a matriz de permissão (coberta à parte em
        # `MobileMenuDrawerPermissionMatrixTest`).
        User.objects.create_user(username="drawer_admin", password="senha-forte-123", role="ADMIN", is_superuser=True)
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

    def test_drawer_has_the_four_shared_groups_in_order(self):
        content = self.client.get("/equipamentos/").content.decode()
        drawer = content.split('id="mobile-menu-drawer"', 1)[1].split("</nav>", 1)[0]
        for group_title in ("CRM", "Operação", "Cadastros", "Configurações do sistema"):
            self.assertTrue(_group_title_present(drawer, group_title), f"Título de grupo '{group_title}' ausente no drawer")
        crm_pos = drawer.index("CRM")
        operacao_pos = drawer.index("Operação")
        cadastros_pos = drawer.index("Cadastros")
        config_pos = drawer.index("Configurações do sistema")
        self.assertTrue(crm_pos < operacao_pos < cadastros_pos < config_pos)

    def test_no_leftover_flat_group_title_markup(self):
        content = self.client.get("/equipamentos/").content.decode()
        self.assertNotIn('class="mobile-menu-group-title"', content)

    def test_create_shortcuts_are_not_duplicated_in_drawer(self):
        """
        Os atalhos de criação não pertencem a nenhum dos grupos do menu —
        permanecem só na tela de listagem de Equipamentos.
        """
        content = self.client.get("/equipamentos/").content.decode()
        drawer = content.split('id="mobile-menu-drawer"', 1)[1].split("</nav>", 1)[0]
        self.assertNotIn('href="/equipamentos/novo/"', drawer)
        self.assertNotIn('href="/equipamentos/lote/novo/"', drawer)
        # ...mas o botão de criar continua existindo na própria tela.
        self.assertIn('href="/equipamentos/novo/"', content)


class MobileMenuDrawerAccordionTest(TestCase):
    """Mesmo comportamento de abertura automática por grupo já coberto na sidebar desktop — aqui, no drawer."""

    def setUp(self):
        User.objects.create_user(username="drawer_accordion_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="drawer_accordion_admin", password="senha-forte-123")

    def test_cadastros_group_auto_opens_on_clients_list(self):
        content = self.client.get("/clientes/").content.decode()
        drawer = content.split('id="mobile-menu-drawer"', 1)[1].split("</nav>", 1)[0]
        cadastros_toggle = drawer.split('data-group-key="cadastros"', 1)[1].split(">", 1)[0]
        self.assertIn('aria-expanded="true"', cadastros_toggle)
        operacao_toggle = drawer.split('data-group-key="operacao"', 1)[1].split(">", 1)[0]
        self.assertIn('aria-expanded="false"', operacao_toggle)


class MobileMenuDrawerPermissionMatrixTest(TestCase):
    """
    As mesmas condições `is_administrativo_ou_superior`/`is_admin` (ou
    `is_superuser`) já usadas na sidebar desktop e nas views
    (RoleRequiredMixin/allowed_roles) — nada reescrito "de cabeça" para o
    drawer.
    """

    def _get_equipment_list_as(self, role, is_superuser=False):
        username = f"drawer_{role.lower()}_{'super' if is_superuser else 'plain'}"
        User.objects.create_user(username=username, password="senha-forte-123", role=role, is_superuser=is_superuser)
        self.client.login(username=username, password="senha-forte-123")
        content = self.client.get("/equipamentos/").content.decode()
        return content.split('id="mobile-menu-drawer"', 1)[1].split("</nav>", 1)[0]

    def test_consulta_does_not_see_administrativo_or_admin_only_links(self):
        drawer = self._get_equipment_list_as("CONSULTA")
        for hidden_url in (
            "/equipamentos/importar/",
            "/catalogo/categorias/",
            "/catalogo/modelos/",
            "/contas/usuarios/",
            "/contas/cargos/",
            "/operacao/diagnostico/locations-duplicadas/",
        ):
            self.assertNotIn(f'href="{hidden_url}"', drawer)
        self.assertFalse(_group_title_present(drawer, "Configurações do sistema"))

    def test_operacional_does_not_see_administrativo_or_admin_only_links(self):
        drawer = self._get_equipment_list_as("OPERACIONAL")
        for hidden_url in (
            "/catalogo/categorias/",
            "/contas/usuarios/",
            "/operacao/diagnostico/locations-duplicadas/",
        ):
            self.assertNotIn(f'href="{hidden_url}"', drawer)

    def test_administrativo_sees_catalog_links_but_not_admin_only(self):
        drawer = self._get_equipment_list_as("ADMINISTRATIVO")
        for visible_url in ("/catalogo/categorias/", "/catalogo/modelos/"):
            self.assertIn(f'href="{visible_url}"', drawer)
        for hidden_url in ("/contas/usuarios/", "/contas/cargos/", "/equipamentos/importar/", "/operacao/diagnostico/locations-duplicadas/"):
            self.assertNotIn(f'href="{hidden_url}"', drawer)
        self.assertFalse(_group_title_present(drawer, "Configurações do sistema"))

    def test_admin_sees_every_group_including_diagnostics_but_not_cargos(self):
        drawer = self._get_equipment_list_as("ADMIN")
        for visible_url in (
            "/equipamentos/importar/",
            "/catalogo/categorias/",
            "/catalogo/modelos/",
            "/contas/usuarios/",
            "/operacao/diagnostico/locations-duplicadas/",
        ):
            self.assertIn(f'href="{visible_url}"', drawer)
        self.assertNotIn('href="/contas/cargos/"', drawer)
        self.assertTrue(_group_title_present(drawer, "Configurações do sistema"))
        self.assertTrue(_group_title_present(drawer, "Colaboradores") or "Colaboradores" in drawer)

    def test_superuser_with_consulta_role_still_sees_admin_only_links(self):
        """Válvula de segurança padrão do Django (`is_superuser`) — mesmo raciocínio de RoleRequiredMixin."""
        drawer = self._get_equipment_list_as("CONSULTA", is_superuser=True)
        self.assertIn('href="/contas/usuarios/"', drawer)
        self.assertIn('href="/contas/cargos/"', drawer)
        self.assertIn('href="/operacao/diagnostico/locations-duplicadas/"', drawer)

    def test_movimentacoes_is_not_a_standalone_menu_item(self):
        """Não existe listagem geral de Movement hoje — não inventar tela/link só para o menu."""
        drawer = self._get_equipment_list_as("ADMIN")
        self.assertNotIn(">Movimentações<", drawer)
