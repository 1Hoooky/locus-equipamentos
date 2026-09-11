"""
Sidebar administrativa DESKTOP (`templates/base.html`, >= 640px). Cobre a
mesma garantia de sempre (permissões 100% reaproveitadas, nenhuma regra
nova) e a taxonomia compartilhada com o drawer mobile: 4 grupos, nesta
ordem — CRM (quando aplicável) / Operação / Cadastros / Configurações do
sistema.

Atualizado na rodada de REFINAMENTO DA SIDEBAR / REORGANIZAÇÃO DA
ARQUITETURA DE NAVEGAÇÃO (11/09/2026): a marca virou "LL"/"Locus
Locações" (era "LH"/"LocusHub"); "Administração" virou "Configurações do
sistema" (Usuários saiu de lá e virou "Colaboradores" dentro de
Cadastros); os 4 grupos agora são um acordeão real
(`.sidebar-group-toggle`/`.sidebar-group-body`, `aria-expanded`) em vez
de um título estático (`.sidebar-group-title`); "Configurações
comerciais" (um único link agregador do CRM) virou 3 itens diretos
(Origens/Etapas/Motivos de perda). `DesktopSidebarHoverExpandTest` segue
cobrindo o mecanismo de expansão no hover/foco, sem alteração (não
mudou nesta rodada).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()


class DesktopSidebarAccessibilityTest(TestCase):
    def setUp(self):
        # Superusuário: bypassa `ModelBackend.has_perm()` automaticamente
        # (ver apps/crm/urls.py — PermissionRequiredMixin), então também
        # vê o grupo CRM sem precisar atribuir Group/Permission — útil
        # aqui porque estes testes cobrem estrutura/taxonomia comum a
        # TODOS os grupos, não a matriz de permissão em si (essa é
        # coberta à parte por `DesktopSidebarPermissionMatrixTest` e
        # `CrmSidebarGroupTest`).
        User.objects.create_user(username="sidebar_admin", password="senha-forte-123", role="ADMIN", is_superuser=True)
        self.client.login(username="sidebar_admin", password="senha-forte-123")

    def test_sidebar_markup_has_required_accessibility_attributes(self):
        content = self.client.get("/equipamentos/").content.decode()
        self.assertIn('id="app-sidebar"', content)
        self.assertIn('aria-label="Navegação principal"', content)
        self.assertIn('id="app-sidebar-brand"', content)
        self.assertIn('aria-label="Locus Locações — ir para o Início"', content)

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

    def test_sidebar_and_drawer_share_the_same_group_taxonomy_and_order(self):
        """
        Requisito explícito da rodada: desktop (sidebar) e mobile (drawer)
        usam a MESMA taxonomia/ordem de grupos — CRM / Operação /
        Cadastros / Configurações do sistema (admin vê os 4; "Cargos"
        exige ainda superusuário dentro do último).
        """
        content = self.client.get("/equipamentos/").content.decode()
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        drawer = content.split('id="mobile-menu-drawer"', 1)[1].split("</nav>", 1)[0]
        for surface_name, surface_html in (("sidebar", sidebar), ("drawer", drawer)):
            for group_title in ("CRM", "Operação", "Cadastros", "Configurações do sistema"):
                self.assertIn(group_title, surface_html, f"Grupo '{group_title}' ausente no {surface_name}")
            # Ordem: CRM antes de Operação, Operação antes de Cadastros,
            # Cadastros antes de Configurações do sistema.
            crm_pos = surface_html.index("CRM")
            operacao_pos = surface_html.index("Operação")
            cadastros_pos = surface_html.index("Cadastros")
            config_pos = surface_html.index("Configurações do sistema")
            self.assertTrue(
                crm_pos < operacao_pos < cadastros_pos < config_pos,
                f"Ordem dos grupos incorreta no {surface_name}",
            )

    def test_no_leftover_flat_group_title_markup(self):
        """
        A marcação antiga de título de grupo estático (`.sidebar-group-title`/
        `.mobile-menu-group-title`, sem botão/aria-expanded) não deve mais
        existir — todo grupo agora é um botão de acordeão de verdade.
        """
        content = self.client.get("/equipamentos/").content.decode()
        self.assertNotIn('class="sidebar-group-title"', content)
        self.assertNotIn('class="mobile-menu-group-title"', content)


class DesktopSidebarHoverExpandTest(TestCase):
    """
    Mecanismo (inalterado nesta rodada): sem botão de colapso/JS — a
    sidebar nasce compacta e expande em CSS puro (:hover/:focus-within).
    Django não tem motor de CSS para verificar visualmente o hover (só um
    navegador real faz isso — coberto à parte por verificação manual/
    Playwright, reportada em separado); o que dá para garantir aqui,
    estruturalmente, é: (1) o botão de colapso antigo não existe mais;
    (2) a marca aparece uma única vez (não duplicada full/compact); (3) a
    regra de CSS que implementa a expansão continua presente na página
    (guarda de regressão, mesmo padrão já usado para o bug do modal de
    perda).
    """

    def setUp(self):
        User.objects.create_user(username="sidebar_hover_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="sidebar_hover_admin", password="senha-forte-123")

    def test_old_click_toggle_button_no_longer_exists(self):
        # Busca pela CLASSE/seletor funcional de verdade (não uma
        # substring solta) — comentários explicativos no CSS/JS mencionam
        # "is-collapsed" pelo nome histórico ao descrever o que foi
        # removido, o que faria uma busca ingênua por substring dar falso
        # positivo (mesma lição já registrada no bugfix do modal de
        # perda: comentário explicativo != uso funcional).
        content = self.client.get("/equipamentos/").content.decode()
        self.assertNotIn('id="app-sidebar-toggle"', content)
        self.assertNotIn('class="is-collapsed', content)
        self.assertNotIn("#app-sidebar.is-collapsed", content)
        self.assertNotIn('id="app-sidebar-brand-full"', content)
        self.assertNotIn('id="app-sidebar-brand-compact"', content)

    def test_brand_appears_exactly_once_in_the_sidebar(self):
        content = self.client.get("/equipamentos/").content.decode()
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        self.assertEqual(sidebar.count('id="app-sidebar-brand"'), 1)
        self.assertIn("Locus Locações", sidebar)
        self.assertIn(">LL<", sidebar)

    def test_hover_expand_css_rule_is_present(self):
        """
        Guarda de regressão: sem esta regra, a sidebar nunca expandiria no
        hover/foco — ficaria permanentemente compacta (ou permanentemente
        larga, dependendo de como a regra fosse removida).
        """
        content = self.client.get("/equipamentos/").content.decode()
        self.assertIn(".sidebar-shell:hover .sidebar-panel", content)
        self.assertIn(".sidebar-shell:focus-within .sidebar-panel", content)

    def test_every_sidebar_link_has_title_and_aria_label_for_compact_state(self):
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


class DesktopSidebarAccordionTest(TestCase):
    """
    Comportamento de acordeão dos grupos (REORGANIZAÇÃO DA ARQUITETURA DE
    NAVEGAÇÃO, 11/09/2026): grupo da página atual nasce aberto
    (`aria-expanded="true"`) sozinho, sem exigir nenhuma ação manual;
    demais grupos nascem fechados no HTML vindo do servidor (a
    reabertura de grupos que o usuário abriu manualmente antes é 100%
    client-side, via localStorage — não há como/por que testar isso
    aqui, sem navegador real).
    """

    def setUp(self):
        # Superusuário: "Cargos" (accounts:role_list) exige superusuário à
        # parte de is_admin (SuperuserRequiredMixin) — necessário para
        # este teste alcançar a rota e ver o grupo "Configurações do
        # sistema" abrir sozinho nela.
        User.objects.create_user(username="accordion_admin", password="senha-forte-123", role="ADMIN", is_superuser=True)
        self.client.login(username="accordion_admin", password="senha-forte-123")

    def test_operacao_group_auto_opens_on_equipment_list(self):
        content = self.client.get("/equipamentos/").content.decode()
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        operacao_toggle = sidebar.split('data-group-key="operacao"', 1)[1].split(">", 1)[0]
        self.assertIn('aria-expanded="true"', operacao_toggle)
        cadastros_toggle = sidebar.split('data-group-key="cadastros"', 1)[1].split(">", 1)[0]
        self.assertIn('aria-expanded="false"', cadastros_toggle)

    def test_cadastros_group_auto_opens_on_clients_list(self):
        content = self.client.get("/clientes/").content.decode()
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        cadastros_toggle = sidebar.split('data-group-key="cadastros"', 1)[1].split(">", 1)[0]
        self.assertIn('aria-expanded="true"', cadastros_toggle)

    def test_configuracoes_group_auto_opens_on_role_list(self):
        content = self.client.get("/contas/cargos/").content.decode()
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        config_toggle = sidebar.split('data-group-key="configuracoes"', 1)[1].split(">", 1)[0]
        self.assertIn('aria-expanded="true"', config_toggle)

    def test_active_item_is_highlighted_inside_its_auto_opened_group(self):
        content = self.client.get("/equipamentos/").content.decode()
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        body = sidebar.split('id="sidebar-group-body-operacao"', 1)[1].split("</div>", 1)[0]
        self.assertIn("sidebar-link-active", body)


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
            "/contas/cargos/",
            "/operacao/diagnostico/locations-duplicadas/",
        ):
            self.assertNotIn(f'href="{hidden_url}"', sidebar)
        self.assertNotIn("Configurações do sistema", sidebar)

    def test_administrativo_sees_cadastros_management_links_but_not_configuracoes_group(self):
        content = self._get_equipment_list_as("ADMINISTRATIVO")
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        for visible_url in ("/catalogo/categorias/", "/catalogo/modelos/"):
            self.assertIn(f'href="{visible_url}"', sidebar)
        for hidden_url in ("/equipamentos/importar/", "/contas/usuarios/", "/contas/cargos/", "/operacao/diagnostico/locations-duplicadas/"):
            self.assertNotIn(f'href="{hidden_url}"', sidebar)
        self.assertNotIn("Configurações do sistema", sidebar)

    def test_admin_sees_every_group_including_diagnostics_but_not_cargos(self):
        """Admin (não superusuário) vê Configurações do sistema, mas Cargos exige superusuário à parte."""
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
        self.assertNotIn('href="/contas/cargos/"', sidebar)
        self.assertIn("Configurações do sistema", sidebar)
        self.assertIn("Colaboradores", sidebar)
        self.assertNotIn(">Usuários<", sidebar)

    def test_superuser_with_consulta_role_still_sees_admin_only_links(self):
        content = self._get_equipment_list_as("CONSULTA", is_superuser=True)
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        self.assertIn('href="/contas/usuarios/"', sidebar)
        self.assertIn('href="/contas/cargos/"', sidebar)
        self.assertIn('href="/operacao/diagnostico/locations-duplicadas/"', sidebar)

    def test_movimentacoes_is_not_a_standalone_menu_item(self):
        content = self._get_equipment_list_as("ADMIN")
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        self.assertNotIn(">Movimentações<", sidebar)

    def test_colaboradores_uses_the_same_url_and_permission_as_before(self):
        """
        A troca de rótulo (Usuários -> Colaboradores) não pode mudar a URL
        nem a permissão: precisa continuar sendo exatamente
        `accounts:user_list` (`/contas/usuarios/`), gated por
        `user.is_admin or user.is_superuser` (igual antes).
        """
        content_admin = self._get_equipment_list_as("ADMIN")
        sidebar_admin = content_admin.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        self.assertIn('href="/contas/usuarios/"', sidebar_admin)

        content_administrativo = self._get_equipment_list_as("ADMINISTRATIVO")
        sidebar_administrativo = content_administrativo.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        self.assertNotIn('href="/contas/usuarios/"', sidebar_administrativo)


class CrmSidebarGroupTest(TestCase):
    """
    Grupo CRM: nunca vazio quando visível; "Origens"/"Etapas"/"Motivos de
    perda" são itens diretos (substituem o antigo link único "Config.
    comerciais"), cada um exigindo `perms.crm.manage_commercial_settings`
    — mesma permissão de antes, só reorganizada visualmente.
    """

    def setUp(self):
        User.objects.create_user(username="sidebar_no_crm_perm", password="senha-forte-123", role="CONSULTA")
        self.client.login(username="sidebar_no_crm_perm", password="senha-forte-123")

    def test_group_absent_without_any_crm_permission(self):
        content = self.client.get("/equipamentos/").content.decode()
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        self.assertNotIn("data-group-key=\"crm\"", sidebar)
        self.assertNotIn(">CRM<", sidebar)

    def test_admin_sees_crm_group_with_all_four_items(self):
        User.objects.create_user(username="sidebar_crm_admin", password="senha-forte-123", role="ADMIN", is_superuser=True)
        self.client.login(username="sidebar_crm_admin", password="senha-forte-123")
        content = self.client.get("/equipamentos/").content.decode()
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        self.assertIn('data-group-key="crm"', sidebar)
        body = sidebar.split('id="sidebar-group-body-crm"', 1)[1].split('data-group-key="operacao"', 1)[0]
        self.assertIn(">Funil<", body)
        self.assertIn(">Origens<", body)
        self.assertIn(">Etapas<", body)
        self.assertIn(">Motivos de perda<", body)
        self.assertNotIn("Config. comerciais", body)
