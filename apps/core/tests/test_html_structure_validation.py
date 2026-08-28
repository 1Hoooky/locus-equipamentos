"""
Validação estrutural de HTML — rodada CORRETIVA de UX/UI (homologação no
Render, item [1] do briefing de correção: "valide a estrutura HTML dos
templates alterados... `<div>` aberta sem fechamento; fechamento em ordem
incorreta; tags aninhadas incorretamente; blocos Django mal fechados;
elementos escapando do container esperado").

Usa `find_html_structure_issues` (ver html_validation.py, pilha simples
via `html.parser.HTMLParser` da biblioteca padrão — deliberadamente NÃO
usa BeautifulSoup/lxml/html5lib, que reparariam o HTML quebrado em vez de
denunciar o problema). Cobre as bases (`base.html`/`base_public.html`,
agora com a sidebar/drawer realinhados) e os templates explicitamente
citados no briefing: `equipment/detail_public.html`, `dashboard/home.html`.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.core.tests.html_validation import find_html_structure_issues
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()


class InternalPagesHtmlStructureTest(TestCase):
    """base.html (sidebar desktop + drawer mobile + header) por perfil."""

    def setUp(self):
        category = Category.objects.create(name="Climatizador")
        model = EquipmentModel.objects.create(category=category, name="Climatizador 9PRO", code="9PRO")
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            User.objects.create_user(username=f"html_check_{role.lower()}", password="senha-forte-123", role=role)
        User.objects.create_user(
            username="html_check_super", password="senha-forte-123", role="CONSULTA", is_superuser=True
        )
        creator = User.objects.get(username="html_check_admin")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))

    def _assert_well_formed(self, url, username):
        self.client.login(username=username, password="senha-forte-123")
        content = self.client.get(url).content.decode()
        issues = find_html_structure_issues(content)
        self.assertEqual(issues, [], f"{url} (usuário {username}) tem HTML malformado:\n" + "\n".join(issues))
        self.client.logout()

    def test_equipment_list_is_well_formed_for_every_role(self):
        for role in ("admin", "administrativo", "operacional", "consulta"):
            self._assert_well_formed("/equipamentos/", f"html_check_{role}")

    def test_equipment_list_is_well_formed_for_superuser(self):
        self._assert_well_formed("/equipamentos/", "html_check_super")

    def test_dashboard_home_is_well_formed(self):
        self._assert_well_formed("/", "html_check_admin")

    def test_equipment_private_detail_is_well_formed(self):
        self._assert_well_formed(f"/equipamentos/{self.equipment.patrimonio}/", "html_check_admin")

    def test_login_page_is_well_formed(self):
        content = self.client.get("/contas/login/").content.decode()
        issues = find_html_structure_issues(content)
        self.assertEqual(issues, [], "\n".join(issues))

    def test_sidebar_collapsed_and_expanded_markup_both_present_and_well_formed(self):
        """
        O estado colapsado/expandido é só CSS+JS no cliente (mesmo HTML
        server-side nos dois casos) — o que garante aqui é que os dois
        elementos de ícone do toggle (expandido/recolhido) e os dois
        elementos de marca (completa/compacta) existem exatamente uma vez
        cada no HTML enviado, para o JS poder alternar entre eles sem
        duplicar nem faltar elemento.
        """
        self.client.login(username="html_check_admin", password="senha-forte-123")
        content = self.client.get("/equipamentos/").content.decode()
        for expected_id in (
            'id="app-sidebar"',
            'id="app-sidebar-toggle"',
            'id="app-sidebar-toggle-icon-expanded"',
            'id="app-sidebar-toggle-icon-collapsed"',
            'id="app-sidebar-brand-full"',
            'id="app-sidebar-brand-compact"',
        ):
            self.assertEqual(content.count(expected_id), 1, f"{expected_id} deveria aparecer exatamente uma vez")


class PublicLandingHtmlStructureTest(TestCase):
    """base_public.html + equipment/detail_public.html — com e sem imagem real."""

    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        self.model = EquipmentModel.objects.create(category=category, name="Aquecedor Torre", code="AQTR")
        creator = User.objects.create_user(username="html_check_public_creator", password="senha-forte-123")
        self.equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=creator))

    def test_public_landing_is_well_formed_with_placeholder_image(self):
        """Sem imagem comercial real cadastrada — cai no fallback (`_placeholder.webp`)."""
        content = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/").content.decode()
        issues = find_html_structure_issues(content)
        self.assertEqual(issues, [], "\n".join(issues))
        self.assertIn("_placeholder.webp", content)

    def test_public_landing_is_well_formed_with_no_commercial_links_configured(self):
        """Nenhuma LOCUS_*_URL configurada neste ambiente — nenhum CTA aparece, mas o HTML continua íntegro."""
        content = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/").content.decode()
        issues = find_html_structure_issues(content)
        self.assertEqual(issues, [])
