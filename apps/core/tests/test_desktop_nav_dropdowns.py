"""
Navegação desktop por dropdowns (`templates/base.html`, >= 640px) — etapa
de UX/UI, 28/08/2026 (ver AUDITORIA_UX_HOME_NAVEGACAO_QR.md, item [25],
Opção B aprovada). Ações de uso frequente continuam como link direto;
"Cadastros" e "Administração" viram dropdown, reaproveitando as MESMAS
permissões que já existiam antes.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()


class DesktopNavDropdownAccessibilityTest(TestCase):
    def setUp(self):
        User.objects.create_user(username="dropdown_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="dropdown_admin", password="senha-forte-123")

    def test_dropdown_toggles_have_required_aria_attributes(self):
        content = self.client.get("/equipamentos/").content.decode()
        self.assertIn('aria-haspopup="true"', content)
        self.assertIn('aria-controls="nav-dropdown-cadastros"', content)
        self.assertIn('aria-controls="nav-dropdown-administracao"', content)
        # Fechado por padrão ao carregar a página.
        self.assertIn('id="nav-dropdown-cadastros"', content)

    def test_frequent_actions_stay_as_direct_links_not_inside_a_dropdown(self):
        """Opção B: Equipamentos/Manutenções/Higienizações/Clientes/Unidades nunca ficam escondidos atrás de um dropdown."""
        content = self.client.get("/equipamentos/").content.decode()
        main_nav = content.split('id="main-nav"', 1)[1].split("</nav>", 1)[0]
        for direct_link_url in (
            "/equipamentos/",
            "/manutencao/manutencoes/",
            "/manutencao/higienizacoes/",
            "/clientes/",
            "/operacao/unidades/",
        ):
            self.assertIn(f'href="{direct_link_url}"', main_nav)


class DesktopNavDropdownPermissionMatrixTest(TestCase):
    def _get_equipment_list_as(self, role, is_superuser=False):
        username = f"nav_{role.lower()}_{'super' if is_superuser else 'plain'}"
        User.objects.create_user(username=username, password="senha-forte-123", role=role, is_superuser=is_superuser)
        self.client.login(username=username, password="senha-forte-123")
        return self.client.get("/equipamentos/").content.decode()

    def test_consulta_sees_no_dropdown_at_all(self):
        # Só o <body> importa: o <head> inclui o partial de tokens
        # compartilhado, cujo CSS tem comentários de código mencionando
        # "Cadastros"/"Administração" como documentação — não é conteúdo
        # visível (mesmo cuidado já tomado em test_public_landing.py).
        # O JS genérico do controlador de dropdown (que procura por
        # `[data-dropdown]`) continua no HTML para todo mundo — ele só
        # não encontra nada para agir quando não há dropdown renderizado
        # (`dropdowns.length` fica 0). O que importa aqui é que NENHUM
        # elemento de dropdown foi de fato renderizado no <body>.
        content = self._get_equipment_list_as("CONSULTA")
        body = content.split("<body", 1)[1].split("<script>", 1)[0]
        self.assertNotIn("data-dropdown", body)
        self.assertNotIn('aria-controls="nav-dropdown-cadastros"', body)
        self.assertNotIn('aria-controls="nav-dropdown-administracao"', body)

    def test_administrativo_sees_cadastros_dropdown_but_not_administracao(self):
        content = self._get_equipment_list_as("ADMINISTRATIVO")
        self.assertIn('aria-controls="nav-dropdown-cadastros"', content)
        self.assertNotIn('aria-controls="nav-dropdown-administracao"', content)
        self.assertIn('href="/catalogo/categorias/"', content)
        self.assertIn('href="/catalogo/modelos/"', content)

    def test_admin_sees_both_dropdowns_with_all_their_items(self):
        content = self._get_equipment_list_as("ADMIN")
        self.assertIn('aria-controls="nav-dropdown-cadastros"', content)
        self.assertIn('aria-controls="nav-dropdown-administracao"', content)
        for expected_url in (
            "/catalogo/categorias/",
            "/catalogo/modelos/",
            "/equipamentos/importar/",
            "/contas/usuarios/",
            "/operacao/diagnostico/locations-duplicadas/",
        ):
            self.assertIn(f'href="{expected_url}"', content)

    def test_superuser_with_consulta_role_still_sees_both_dropdowns(self):
        content = self._get_equipment_list_as("CONSULTA", is_superuser=True)
        self.assertIn('aria-controls="nav-dropdown-cadastros"', content)
        self.assertIn('aria-controls="nav-dropdown-administracao"', content)
