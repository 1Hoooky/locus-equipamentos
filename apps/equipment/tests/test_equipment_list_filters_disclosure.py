"""
Painel de filtros da listagem de Equipamentos — rodada de UX/UI
mobile-first (31/08/2026). Os 4 selects (status/condição/categoria/
modelo), que antes ficavam permanentemente abertos ocupando altura útil
no mobile, agora vivem dentro de um `<details>` nativo: fechado por
padrão, mas abre sozinho quando a página já carrega com algum filtro
aplicado (para nunca esconder um filtro ativo). A busca (`q`) continua
sempre visível, fora do `<details>`. Backend/querystring inalterados —
só testamos que os campos continuam presentes/funcionais.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.equipment.models import Status
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()


class EquipmentListFiltersDisclosureTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Categoria Filtros Disclosure")
        cls.model = EquipmentModel.objects.create(category=category, name="Modelo Filtros Disclosure", code="FLTD")
        cls.admin = User.objects.create_user(username="filtros_admin", password="senha-forte-123", role="ADMIN")
        cls.equipment = create_equipment(NewEquipmentData(model_id=cls.model.pk, created_by=cls.admin))

    def setUp(self):
        self.client.login(username="filtros_admin", password="senha-forte-123")

    def test_busca_continua_sempre_visivel_fora_do_details(self):
        response = self.client.get("/equipamentos/")
        content = response.content.decode()
        details_start = content.find("<details")
        search_input_pos = content.find('name="q"')
        self.assertNotEqual(search_input_pos, -1)
        self.assertLess(search_input_pos, details_start)

    def test_details_fechado_por_padrao_sem_filtro_ativo(self):
        response = self.client.get("/equipamentos/")
        content = response.content.decode()
        # Sem nenhum filtro selecionado, o <details> não deve carregar o
        # atributo `open`.
        details_tag = content[content.find("<details"):content.find(">", content.find("<details")) + 1]
        self.assertNotIn("open", details_tag)

    def test_details_abre_sozinho_quando_ha_filtro_ativo_na_url(self):
        response = self.client.get(f"/equipamentos/?status={Status.DISPONIVEL}")
        content = response.content.decode()
        details_tag = content[content.find("<details"):content.find(">", content.find("<details")) + 1]
        self.assertIn("open", details_tag)

    def test_campos_de_filtro_continuam_presentes_e_preservam_selecao(self):
        response = self.client.get(f"/equipamentos/?status={Status.DISPONIVEL}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_status"], Status.DISPONIVEL)
        content = response.content.decode()
        self.assertIn('name="status"', content)
        self.assertIn('name="condition"', content)
        self.assertIn('name="category"', content)
        self.assertIn('name="model"', content)

    def test_filtro_continua_restringindo_o_queryset(self):
        # Comportamento do backend não muda — só a apresentação do form.
        other_category = Category.objects.create(name="Outra Categoria Disclosure")
        other_model = EquipmentModel.objects.create(category=other_category, name="Outro Modelo Disclosure", code="OFLD")
        create_equipment(NewEquipmentData(model_id=other_model.pk, created_by=self.admin))

        response = self.client.get(f"/equipamentos/?category={other_category.pk}")
        model_ids = {g.model_id for g in response.context["model_groups"]}
        self.assertEqual(model_ids, {other_model.pk})
