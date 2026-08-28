"""
Fluxo "QR -> landing pública -> menu -> Entrar -> login -> mesma ficha
privada do equipamento" (etapa de UX/UI, 28/08/2026 — ver
AUDITORIA_UX_HOME_NAVEGACAO_QR.md, itens [12]/[21]).

Este comportamento já funcionava ANTES de qualquer alteração de código
desta etapa (verificado empiricamente durante a auditoria: o form de login
não tem `action`, então o navegador reenvia o POST para a URL atual,
incluindo `?next=...`, e `django.contrib.auth.views.LoginView` já lê esse
parâmetro do POST/GET com a proteção contra open redirect embutida via
`django.utils.http.url_has_allowed_host_and_scheme`). Os testes abaixo
travam esse comportamento — tanto o caminho feliz quanto a proteção contra
open redirect — para que uma mudança futura no template/na view de login
não quebre isso silenciosamente.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()


class LoginNextRedirectTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Torre", code="AQNX")
        admin = User.objects.create_user(username="criador_next", password="senha-forte-123", role="ADMIN")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=admin))

        User.objects.create_user(username="tecnico_next", password="senha-forte-123", role="OPERACIONAL")

    def _equipment_path(self):
        return f"/equipamentos/{self.equipment.patrimonio}/"

    def test_login_page_renders_hidden_next_field_when_next_is_present(self):
        response = self.client.get(f"/contas/login/?next={self._equipment_path()}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'name="next" value="{self._equipment_path()}"')

    def test_login_page_has_no_hidden_next_field_without_querystring(self):
        response = self.client.get("/contas/login/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="next"')

    def test_post_login_with_next_redirects_to_the_same_equipment(self):
        """
        Caminho completo do QR: um funcionário (ainda não autenticado)
        escaneia o QR, cai na landing pública, clica em "Entrar" (que
        monta o link com `?next=<caminho do equipamento>`), preenche o
        login e deve voltar DIRETO para a ficha PRIVADA daquele mesmo
        equipamento — nunca para a Home nem para a listagem geral.
        """
        login_url = f"/contas/login/?next={self._equipment_path()}"

        response = self.client.post(
            login_url,
            {"username": "tecnico_next", "password": "senha-forte-123"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self._equipment_path())

        # E a página para onde foi redirecionado é de fato a ficha
        # PRIVADA (não a landing pública) — a sessão já está autenticada.
        follow_up = self.client.get(response["Location"])
        self.assertTemplateUsed(follow_up, "equipment/detail_private.html")

    def test_post_login_without_next_does_not_redirect_to_equipment(self):
        """Login normal (sem vir do QR) não deve ser afetado por este campo."""
        response = self.client.post(
            "/contas/login/",
            {"username": "tecnico_next", "password": "senha-forte-123"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response["Location"], self._equipment_path())

    def test_post_login_without_next_redirects_to_home(self):
        """
        Item [19] da auditoria: `LOGIN_REDIRECT_URL` agora aponta para a
        Home operacional (`apps.dashboard`) — login normal, sem `next`,
        cai nela. O caminho com `next` (teste acima) continua tendo
        prioridade: é o próprio `LoginView` do Django que garante isso,
        nenhuma lógica própria foi escrita para decidir entre os dois.
        """
        response = self.client.post(
            "/contas/login/",
            {"username": "tecnico_next", "password": "senha-forte-123"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")

    def test_post_login_with_external_next_is_rejected_as_open_redirect(self):
        """
        Proteção padrão do Django (`url_has_allowed_host_and_scheme`,
        usada internamente por `LoginView`/`RedirectURLMixin`) — um
        `next` apontando para um host externo NUNCA deve ser seguido.
        Nenhuma validação própria foi escrita para isto (decisão
        aprovada, item [12]): é inteiramente o mecanismo padrão do
        Django que garante este teste passar.
        """
        response = self.client.post(
            "/contas/login/?next=https://evil.example.com/phishing",
            {"username": "tecnico_next", "password": "senha-forte-123"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("evil.example.com", response["Location"])

    def test_post_login_with_protocol_relative_next_is_rejected_as_open_redirect(self):
        """Variante clássica de open redirect (`//host/...`, sem esquema explícito)."""
        response = self.client.post(
            "/contas/login/?next=//evil.example.com/phishing",
            {"username": "tecnico_next", "password": "senha-forte-123"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("evil.example.com", response["Location"])
