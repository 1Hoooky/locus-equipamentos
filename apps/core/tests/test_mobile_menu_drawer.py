"""
Drawer do menu mobile interno (`templates/base.html`) — cobre a estrutura/
acessibilidade básica e a matriz de permissões, reaproveitando as MESMAS
condições já usadas na sidebar desktop (e nas próprias views) — nenhuma
regra nova foi inventada para o drawer.

Atualizado na rodada CORRETIVA de UX/UI (homologação no Render): a
taxonomia do drawer foi realinhada de 5 grupos (Operação/Equipamentos/
Manutenção/Cadastros/Administração) para os mesmos 3 grupos da sidebar
desktop (Operação/Cadastros/Administração — ver test_desktop_sidebar.py).
Como consequência direta, os atalhos de criação rápida "Novo equipamento"/
"Adicionar em lote" saíram da navegação de chrome (não pertenciam a
nenhum dos 3 grupos aprovados no briefing) — continuam alcançáveis pelo
botão dourado já existente na própria tela de listagem de Equipamentos
(item [6] do briefing: "não redesenhe essa tela"), então nenhuma
funcionalidade foi perdida, só a duplicação de entrada removida. "Importar
planilha" migrou do antigo grupo "Equipamentos" para "Administração",
mesma permissão de antes (`is_admin`/`is_superuser`).
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

    def test_drawer_has_exactly_the_three_shared_groups(self):
        content = self.client.get("/equipamentos/").content.decode()
        drawer = content.split('id="mobile-menu-drawer"', 1)[1].split("</nav>", 1)[0]
        for group_title in ("Operação", "Cadastros", "Administração"):
            self.assertIn(f">{group_title}<", drawer)
        self.assertEqual(drawer.count('class="mobile-menu-group-title"'), 3)

    def test_create_shortcuts_are_not_duplicated_in_drawer(self):
        """
        Decisão explícita da rodada corretiva (ver docstring do módulo):
        os atalhos de criação não pertencem a nenhum dos 3 grupos
        aprovados — permanecem só na tela de listagem de Equipamentos.
        """
        content = self.client.get("/equipamentos/").content.decode()
        drawer = content.split('id="mobile-menu-drawer"', 1)[1].split("</nav>", 1)[0]
        self.assertNotIn('href="/equipamentos/novo/"', drawer)
        self.assertNotIn('href="/equipamentos/lote/novo/"', drawer)
        # ...mas o botão de criar continua existindo na própria tela.
        self.assertIn('href="/equipamentos/novo/"', content)


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
            "/operacao/diagnostico/locations-duplicadas/",
        ):
            self.assertNotIn(f'href="{hidden_url}"', drawer)
        self.assertNotIn(">Administração<", drawer)

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
        for hidden_url in ("/contas/usuarios/", "/equipamentos/importar/", "/operacao/diagnostico/locations-duplicadas/"):
            self.assertNotIn(f'href="{hidden_url}"', drawer)
        self.assertNotIn(">Administração<", drawer)

    def test_admin_sees_every_group_including_diagnostics(self):
        drawer = self._get_equipment_list_as("ADMIN")
        for visible_url in (
            "/equipamentos/importar/",
            "/catalogo/categorias/",
            "/catalogo/modelos/",
            "/contas/usuarios/",
            "/operacao/diagnostico/locations-duplicadas/",
        ):
            self.assertIn(f'href="{visible_url}"', drawer)
        self.assertIn(">Administração<", drawer)

    def test_superuser_with_consulta_role_still_sees_admin_only_links(self):
        """Válvula de segurança padrão do Django (`is_superuser`) — mesmo raciocínio de RoleRequiredMixin."""
        drawer = self._get_equipment_list_as("CONSULTA", is_superuser=True)
        self.assertIn('href="/contas/usuarios/"', drawer)
        self.assertIn('href="/operacao/diagnostico/locations-duplicadas/"', drawer)

    def test_movimentacoes_is_not_a_standalone_menu_item(self):
        """Não existe listagem geral de Movement hoje — não inventar tela/link só para o menu."""
        drawer = self._get_equipment_list_as("ADMIN")
        self.assertNotIn(">Movimentações<", drawer)
