"""
Camadas de ação da ficha do equipamento — rodada de UX/UI mobile-first
(31/08/2026). A antiga lista de links soltos de mesmo peso visual virou
3 camadas (primária/secundária/avançada); este arquivo cobre o que É
NOVO nessa reorganização — o painel de movimentação em si (cards,
permissões, hrefs) já é coberto por
`apps.equipment.tests.test_equipment_movement_panel`, não duplicado
aqui.

Cobre:
 - "Serviços" (Abrir manutenção / Registrar higienização) continuam
   visíveis para quem tem CAN_REGISTER_OPERATIONS.
 - "Ajustes" (Alterar status/condição) continuam presentes.
 - "Administração" vira um disclosure (aria-expanded/aria-controls),
   fechado por padrão, só aparece para quem tem alguma ação admin, e o
   conteúdo continua no HTML mesmo fechado (progressive enhancement —
   sem JS, o link ainda existe, só a exibição inicial que é CSS).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()


class FichaActionTiersTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Categoria Camadas Ficha")
        cls.model = EquipmentModel.objects.create(category=category, name="Modelo Camadas Ficha", code="CMFC")
        cls.admin = User.objects.create_user(username="camadas_admin", password="senha-forte-123", role=Role.ADMIN)
        cls.administrativo = User.objects.create_user(
            username="camadas_administrativo", password="senha-forte-123", role=Role.ADMINISTRATIVO
        )
        cls.operacional = User.objects.create_user(
            username="camadas_operacional", password="senha-forte-123", role=Role.OPERACIONAL
        )
        cls.consulta = User.objects.create_user(username="camadas_consulta", password="senha-forte-123", role=Role.CONSULTA)
        cls.equipment = create_equipment(NewEquipmentData(model_id=cls.model.pk, created_by=cls.admin))

    def _get(self, username):
        self.client.login(username=username, password="senha-forte-123")
        response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")
        self.client.logout()
        return response.content.decode()

    def test_servicos_e_ajustes_visiveis_para_operacional(self):
        content = self._get("camadas_operacional")
        self.assertIn("Serviços", content)
        self.assertIn("Registrar higienização", content)
        self.assertIn("Abrir manutenção", content)
        self.assertIn("Ajustes", content)
        self.assertIn("Alterar status", content)
        self.assertIn("Alterar condição", content)

    def test_operacional_nao_ve_bloco_administracao(self):
        # Operacional não tem nenhuma ação administrativa — o disclosure
        # inteiro não deve renderizar (nem fechado).
        content = self._get("camadas_operacional")
        self.assertNotIn("Administração", content)

    def test_consulta_nao_ve_nenhuma_camada_de_acao(self):
        content = self._get("camadas_consulta")
        self.assertNotIn("Serviços", content)
        self.assertNotIn("Ajustes", content)
        self.assertNotIn("Administração", content)

    def test_administrativo_ve_administracao_fechada_por_padrao_mas_com_conteudo_no_html(self):
        content = self._get("camadas_administrativo")
        self.assertIn(">Administração<", content)
        self.assertIn('aria-expanded="false"', content)
        self.assertIn("aria-controls=\"ficha-admin-body\"", content)
        # Mesmo fechado, o link "Editar dados" já está no HTML (disclosure
        # é só CSS lendo aria-expanded — nunca esconde via ausência real).
        self.assertIn("Editar dados", content)
        self.assertIn("Ver QR Code", content)

    def test_apenas_admin_ve_reclassificar_e_reemitir_dentro_da_administracao(self):
        administrativo_content = self._get("camadas_administrativo")
        self.assertNotIn("Reclassificar modelo", administrativo_content)
        self.assertNotIn("Reemitir patrimônio", administrativo_content)

        admin_content = self._get("camadas_admin")
        self.assertIn("Reclassificar modelo", admin_content)
        self.assertIn("Reemitir patrimônio", admin_content)
