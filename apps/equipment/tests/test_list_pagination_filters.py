"""
Bug relatado pelo usuário (histórico): os links "Anterior"/"Próxima" da
listagem de equipamentos eram montados como `?page=N` puro, descartando
qualquer filtro (`?model=`, `?status=`, `?q=`...) já aplicado.

Correção original: `apps.core.templatetags.pagination_tags.url_replace`
monta o link de paginação a partir da querystring atual (`request.GET`),
sobrescrevendo só `page` — nunca hardcoded para um filtro específico.

ATUALIZADO na melhoria de UX/consulta da listagem (agrupamento por
modelo, rodada pós-homologação): `/equipamentos/` deixou de paginar uma
tabela plana de equipamentos — agora mostra grupos por `EquipmentModel`,
e os equipamentos individuais só existem dentro do fragmento HTMX de
`EquipmentModelItemsView` (`GET /equipamentos/modelo/<id>/itens/`), que
pagina internamente (20 por página). A garantia original (link de
paginação preserva os filtros ativos) continua existindo — só migrou
para esse endpoint, que reaproveita a MESMA tag `url_replace`. Este
arquivo testa essa garantia no lugar novo onde ela vive.
"""

import html
import re
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.equipment.models import Status
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()


def _extract_href(content: str, link_text: str) -> str | None:
    """Igual ao helper original: acha o href de uma âncora pelo texto visível."""
    for match in re.finditer(r'<a href="([^"]*)"[^>]*>(.*?)</a>', content, re.DOTALL):
        href, inner = match.group(1), match.group(2)
        visible_text = re.sub(r"<[^>]+>", "", inner)
        visible_text = re.sub(r"\s+", " ", visible_text).strip()
        if visible_text == link_text:
            return html.unescape(href)
    return None


def _extract_hx_get(content: str, link_text: str) -> str | None:
    """
    Os controles "Anterior"/"Próxima" do fragmento do grupo são `<button
    hx-get="...">`, não `<a href="...">` (a navegação é via HTMX, não um
    link de página inteira) — mesmo princípio do helper acima, adaptado
    para o atributo `hx-get`.
    """
    for match in re.finditer(r'<button[^>]*hx-get="([^"]*)"[^>]*>(.*?)</button>', content, re.DOTALL):
        href, inner = match.group(1), match.group(2)
        visible_text = re.sub(r"<[^>]+>", "", inner)
        visible_text = re.sub(r"\s+", " ", visible_text).strip()
        if visible_text == link_text:
            return html.unescape(href)
    return None


def _query_params(href: str) -> dict:
    return parse_qs(urlparse(href).query)


class ModelItemsPaginationPreservesFiltersTest(TestCase):
    """
    Mesma validação do bug original (modelo com mais de 20 resultados —
    limite de paginação do grupo —, navegação para a página 2 e volta,
    combinação de filtros, busca textual + filtro, ausência de
    duplicação de `page`), agora contra o fragmento HTMX do grupo.
    """

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Aquecedor")
        cls.model_a = EquipmentModel.objects.create(category=category, name="Modelo A", code="MDLA")
        cls.model_b = EquipmentModel.objects.create(category=category, name="Modelo B", code="MDLB")
        cls.user = User.objects.create_user(username="listador_paginacao", password="senha-forte-123")

        # 22 equipamentos do Modelo A, todos DISPONIVEL — mais que o
        # limite de paginação do grupo (GROUP_PAGE_SIZE=20).
        for _ in range(22):
            create_equipment(
                NewEquipmentData(model_id=cls.model_a.pk, created_by=cls.user, status=Status.DISPONIVEL)
            )
        # 3 equipamentos de OUTRO modelo/status — provam que o filtro
        # exclui o que não deveria aparecer.
        for _ in range(3):
            create_equipment(
                NewEquipmentData(model_id=cls.model_b.pk, created_by=cls.user, status=Status.MANUTENCAO)
            )

    def setUp(self):
        self.client.login(username="listador_paginacao", password="senha-forte-123")

    def _items_url(self, model):
        return f"/equipamentos/modelo/{model.pk}/itens/"

    # -- grupo com mais de 20 resultados ----------------------------------

    def test_model_group_with_more_than_20_results_paginates(self):
        response = self.client.get(self._items_url(self.model_a))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_paginated"])
        self.assertEqual(response.context["paginator"].count, 22)
        self.assertEqual(response.context["paginator"].num_pages, 2)
        self.assertEqual(len(response.context["page_obj"].object_list), 20)
        for equipment in response.context["page_obj"].object_list:
            self.assertEqual(equipment.model_id, self.model_a.pk)

    # -- navegação para página 2 preservando o filtro ---------------------

    def test_next_control_on_page_1_preserves_active_filter(self):
        response = self.client.get(self._items_url(self.model_a), {"status": Status.DISPONIVEL})
        content = response.content.decode()

        href = _extract_hx_get(content, "Próxima")
        self.assertIsNotNone(href, "Controle 'Próxima' não encontrado no fragmento.")

        params = _query_params(href)
        self.assertEqual(params.get("page"), ["2"])
        self.assertEqual(params.get("status"), [Status.DISPONIVEL])

    def test_following_next_control_shows_only_filtered_model_on_page_2(self):
        response = self.client.get(self._items_url(self.model_a), {"page": "2"})
        self.assertEqual(response.status_code, 200)

        items = response.context["page_obj"].object_list
        self.assertEqual(len(items), 2)  # 22 - 20 = 2 restantes
        for equipment in items:
            self.assertEqual(equipment.model_id, self.model_a.pk)

    # -- voltar para página anterior preservando o filtro ------------------

    def test_previous_control_on_page_2_preserves_active_filter(self):
        response = self.client.get(self._items_url(self.model_a), {"status": Status.DISPONIVEL, "page": "2"})
        content = response.content.decode()

        href = _extract_hx_get(content, "Anterior")
        self.assertIsNotNone(href, "Controle 'Anterior' não encontrado no fragmento.")

        params = _query_params(href)
        self.assertEqual(params.get("page"), ["1"])
        self.assertEqual(params.get("status"), [Status.DISPONIVEL])

    # -- combinação de filtros ---------------------------------------------

    def test_pagination_controls_preserve_combination_of_filters(self):
        response = self.client.get(
            self._items_url(self.model_a), {"status": Status.DISPONIVEL, "condition": "BOM"}
        )
        self.assertTrue(response.context["is_paginated"])
        content = response.content.decode()

        href = _extract_hx_get(content, "Próxima")
        params = _query_params(href)
        self.assertEqual(params.get("page"), ["2"])
        self.assertEqual(params.get("status"), [Status.DISPONIVEL])
        self.assertEqual(params.get("condition"), ["BOM"])

    # -- busca textual + filtro + paginação ---------------------------------

    def test_pagination_controls_preserve_text_search_plus_filter(self):
        # Todos os patrimônios do Modelo A contêm "MDLA" (LOC-MDLA-0001...).
        response = self.client.get(self._items_url(self.model_a), {"q": "MDLA", "status": Status.DISPONIVEL})
        self.assertTrue(response.context["is_paginated"])
        self.assertEqual(response.context["paginator"].count, 22)
        content = response.content.decode()

        href = _extract_hx_get(content, "Próxima")
        params = _query_params(href)
        self.assertEqual(params.get("page"), ["2"])
        self.assertEqual(params.get("q"), ["MDLA"])
        self.assertEqual(params.get("status"), [Status.DISPONIVEL])

    # -- ausência de duplicação do parâmetro page ----------------------------

    def test_page_param_is_not_duplicated_when_already_present_in_url(self):
        response = self.client.get(self._items_url(self.model_a), {"page": "1"})
        content = response.content.decode()

        href = _extract_hx_get(content, "Próxima")
        self.assertIsNotNone(href)
        self.assertEqual(href.count("page="), 1, f"Parâmetro 'page' duplicado no link: {href}")

        params = _query_params(href)
        self.assertEqual(params.get("page"), ["2"])

    def test_no_stray_params_and_filters_untouched_by_pagination(self):
        """A correção não altera a lógica do filtro em si, só o link."""
        response = self.client.get(self._items_url(self.model_b))
        self.assertFalse(response.context["is_paginated"])  # só 3 itens, sem paginação
        self.assertEqual(response.context["paginator"].count, 3)
        for equipment in response.context["page_obj"].object_list:
            self.assertEqual(equipment.model_id, self.model_b.pk)


class TopLevelListingLinksToGroupItemsEndpointTest(TestCase):
    """
    A página principal (`/equipamentos/`) não lista mais patrimônios
    diretamente — cada grupo tem um botão que aponta (via `hx-get`) para
    `EquipmentModelItemsView`, preservando os filtros ativos na querystring.
    """

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Climatizador")
        cls.model_a = EquipmentModel.objects.create(category=category, name="Modelo A", code="MDLC")
        cls.user = User.objects.create_user(username="listador_top", password="senha-forte-123")
        create_equipment(NewEquipmentData(model_id=cls.model_a.pk, created_by=cls.user, status=Status.DISPONIVEL))

    def setUp(self):
        self.client.login(username="listador_top", password="senha-forte-123")

    def test_group_toggle_hx_get_points_to_model_items_endpoint_with_filters(self):
        response = self.client.get("/equipamentos/", {"status": Status.DISPONIVEL})
        content = response.content.decode()

        match = re.search(r'hx-get="([^"]*)"[^>]*hx-target="#model-group-items-%d"' % self.model_a.pk, content)
        self.assertIsNotNone(match, "Botão do grupo não tem hx-get apontando para o próprio container de itens.")

        href = html.unescape(match.group(1))
        self.assertTrue(href.startswith(f"/equipamentos/modelo/{self.model_a.pk}/itens/"))
        params = _query_params(href)
        self.assertEqual(params.get("status"), [Status.DISPONIVEL])

    def test_flat_pagination_controls_no_longer_rendered_on_top_level_page(self):
        """A tabela única (com "Anterior"/"Próxima" por página inteira) foi substituída pelos grupos."""
        response = self.client.get("/equipamentos/")
        content = response.content.decode()
        self.assertNotIn('id="model-group-toggle"', content)  # não é um id fixo repetido
        self.assertNotIn("<table", content)  # a página principal não renderiza mais tabela nenhuma
