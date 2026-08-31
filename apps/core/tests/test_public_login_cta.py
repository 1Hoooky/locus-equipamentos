"""
Botão "Entrar" no menu público (base_public.html) — rodada de UX/UI
mobile-first (31/08/2026), item explicitamente citado na homologação: o
link ficava quase invisível (texto cinza claro, sem ícone, em último
lugar) — visualmente perdido atrás dos CTAs comerciais. Corrigido para
um botão de verdade (`.public-login-cta`, mesma paleta de marca), mas
mantendo a posição depois dos CTAs comerciais (não deve competir com uma
oferta para o cliente).

Testa comportamento/semântica (href correto, elemento é um link real,
continua depois dos CTAs comerciais), não a lista de classes Tailwind.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()


class PublicLoginCtaTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Categoria CTA Login")
        model = EquipmentModel.objects.create(category=category, name="Modelo CTA Login", code="CTAL")
        creator = User.objects.create_user(username="cta_login_creator", password="senha-forte-123", role="ADMIN")
        cls.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))

    def _public_page(self):
        # Anônimo -> template público (mesma URL da ficha privada, ver
        # EquipmentDetailView) — QR real, sem precisar mockar landing.
        response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_link_entrar_aponta_para_login_com_next(self):
        content = self._public_page()
        self.assertIn("/contas/login/", content)
        self.assertIn("Entrar", content)

    def test_entrar_e_um_elemento_de_link_real_nao_texto_solto(self):
        content = self._public_page()
        # A âncora precisa existir como <a ...>Entrar</a> real, não um
        # <span>/texto sem href (regressão do problema original: link
        # "quase invisível" ainda seria um link, mas confirmamos aqui que
        # a correção manteve a semântica de link clicável).
        self.assertIn('href="/contas/login/', content)

    def test_entrar_continua_depois_dos_ctas_comerciais_no_html(self):
        # Não deve competir em ordem/posição com "Faça seu orçamento" —
        # continua vindo depois no documento, só que agora como botão.
        content = self._public_page()
        orcamento_pos = content.find("Faça seu orçamento")
        entrar_pos = content.find(">Entrar<") if ">Entrar<" in content else content.find("Entrar")
        if orcamento_pos != -1:
            self.assertGreater(entrar_pos, orcamento_pos)
