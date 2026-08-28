"""
Bug relatado pelo usuário: os links "Anterior"/"Próxima" da listagem de
equipamentos eram montados como `?page=N` puro, descartando qualquer
filtro (`?model=`, `?status=`, `?q=`...) já aplicado — ao trocar de
página, o resultado passava a mostrar TODOS os equipamentos, não só os
filtrados.

Correção: `apps.core.templatetags.pagination_tags.url_replace` monta o
link de paginação a partir da querystring atual (`request.GET`),
sobrescrevendo só `page` — nunca hardcoded para um filtro específico.

Estes testes verificam o HTML renderizado (os `href` dos links de
paginação), não só a queryset — o bug relatado é especificamente sobre o
link ficar errado na tela, então a prova tem que olhar a página.
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
    """
    Acha o `href` da âncora cujo texto visível é `link_text` (ex.:
    'Próxima', 'Anterior') e devolve o valor já com entidades HTML
    decodificadas (o template, corretamente, renderiza `&` como `&amp;`
    dentro do atributo — um navegador real decodifica isso ao navegar).

    Percorre cada `<a ...>...</a>` isoladamente (não cruza de uma âncora
    pra outra) e compara o TEXTO VISÍVEL (tags internas removidas, espaços
    colapsados) com `link_text`. Isso tolera o ícone SVG que a auditoria
    de iconografia (28/08/2026) passou a renderizar junto do texto
    ("Anterior" ganhou um ícone ANTES do texto, "Próxima" ganhou um ícone
    DEPOIS) sem arriscar "vazar" de uma âncora pra outra em busca do
    texto — o que uma versão ingênua com `.*?` solto faria.
    """
    for match in re.finditer(r'<a href="([^"]*)"[^>]*>(.*?)</a>', content, re.DOTALL):
        href, inner = match.group(1), match.group(2)
        visible_text = re.sub(r"<[^>]+>", "", inner)
        visible_text = re.sub(r"\s+", " ", visible_text).strip()
        if visible_text == link_text:
            return html.unescape(href)
    return None


def _query_params(href: str) -> dict:
    return parse_qs(urlparse(href).query)


class EquipmentListPaginationPreservesFiltersTest(TestCase):
    """
    Validação obrigatória do bug: filtro por modelo com mais de 50
    resultados, navegação para a página 2 e volta para a página 1,
    combinação de filtros, busca textual + filtro, e ausência de
    duplicação do parâmetro `page` — tudo preservando os demais
    parâmetros GET.
    """

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Aquecedor")
        cls.model_a = EquipmentModel.objects.create(category=category, name="Modelo A", code="MDLA")
        cls.model_b = EquipmentModel.objects.create(category=category, name="Modelo B", code="MDLB")
        cls.user = User.objects.create_user(username="listador_paginacao", password="senha-forte-123")

        # 52 equipamentos do Modelo A, todos DISPONIVEL — mais de 50 (o
        # limite de paginação, paginate_by=50), para forçar 2 páginas
        # quando o filtro por modelo/status é aplicado.
        for _ in range(52):
            create_equipment(
                NewEquipmentData(model_id=cls.model_a.pk, created_by=cls.user, status=Status.DISPONIVEL)
            )
        # 3 equipamentos de OUTRO modelo/status — provam que o filtro (e a
        # paginação sobre ele) realmente exclui o que não deveria aparecer.
        for _ in range(3):
            create_equipment(
                NewEquipmentData(model_id=cls.model_b.pk, created_by=cls.user, status=Status.MANUTENCAO)
            )

    def setUp(self):
        self.client.login(username="listador_paginacao", password="senha-forte-123")

    # -- filtro por modelo com mais de 50 resultados -----------------------

    def test_model_filter_with_more_than_50_results_paginates_over_filtered_set(self):
        response = self.client.get("/equipamentos/", {"model": self.model_a.pk})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_paginated"])

        # A contagem/paginação tem que vir da queryset FILTRADA (52), não
        # de todos os equipamentos (55).
        self.assertEqual(response.context["paginator"].count, 52)
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
        self.assertEqual(len(response.context["equipment_list"]), 50)
        for equipment in response.context["equipment_list"]:
            self.assertEqual(equipment.model_id, self.model_a.pk)

    # -- navegação para página 2 preservando o filtro ------------------------

    def test_next_link_on_page_1_preserves_model_filter(self):
        response = self.client.get("/equipamentos/", {"model": self.model_a.pk})
        content = response.content.decode()

        href = _extract_href(content, "Próxima")
        self.assertIsNotNone(href, "Link 'Próxima' não encontrado na página 1.")

        params = _query_params(href)
        self.assertEqual(params.get("page"), ["2"])
        self.assertEqual(params.get("model"), [str(self.model_a.pk)])

    def test_following_next_link_shows_only_filtered_model_on_page_2(self):
        response = self.client.get("/equipamentos/", {"model": self.model_a.pk, "page": "2"})
        self.assertEqual(response.status_code, 200)

        equipment_list = response.context["equipment_list"]
        self.assertEqual(len(equipment_list), 2)  # 52 - 50 = 2 restantes
        for equipment in equipment_list:
            self.assertEqual(equipment.model_id, self.model_a.pk)

    # -- voltar para página anterior preservando o filtro --------------------

    def test_previous_link_on_page_2_preserves_model_filter(self):
        response = self.client.get("/equipamentos/", {"model": self.model_a.pk, "page": "2"})
        content = response.content.decode()

        href = _extract_href(content, "Anterior")
        self.assertIsNotNone(href, "Link 'Anterior' não encontrado na página 2.")

        params = _query_params(href)
        self.assertEqual(params.get("page"), ["1"])
        self.assertEqual(params.get("model"), [str(self.model_a.pk)])

    # -- combinação de dois ou mais filtros -----------------------------------

    def test_pagination_links_preserve_combination_of_two_filters(self):
        response = self.client.get("/equipamentos/", {"model": self.model_a.pk, "status": Status.DISPONIVEL})
        self.assertTrue(response.context["is_paginated"])
        content = response.content.decode()

        href = _extract_href(content, "Próxima")
        params = _query_params(href)
        self.assertEqual(params.get("page"), ["2"])
        self.assertEqual(params.get("model"), [str(self.model_a.pk)])
        self.assertEqual(params.get("status"), [Status.DISPONIVEL])

    # -- busca textual + filtro + paginação -----------------------------------

    def test_pagination_links_preserve_text_search_plus_filter(self):
        # Todos os patrimônios do Modelo A contêm "MDLA" (LOC-MDLA-0001...).
        response = self.client.get("/equipamentos/", {"q": "MDLA", "status": Status.DISPONIVEL})
        self.assertTrue(response.context["is_paginated"])
        self.assertEqual(response.context["paginator"].count, 52)
        content = response.content.decode()

        href = _extract_href(content, "Próxima")
        params = _query_params(href)
        self.assertEqual(params.get("page"), ["2"])
        self.assertEqual(params.get("q"), ["MDLA"])
        self.assertEqual(params.get("status"), [Status.DISPONIVEL])

    # -- ausência de duplicação do parâmetro page -----------------------------

    def test_page_param_is_not_duplicated_when_already_present_in_url(self):
        # Já chega numa página com `page` na querystring — o link para a
        # próxima página tem que SUBSTITUIR o valor, não acrescentar outro.
        response = self.client.get("/equipamentos/", {"model": self.model_a.pk, "page": "1"})
        content = response.content.decode()

        href = _extract_href(content, "Próxima")
        self.assertEqual(href.count("page="), 1, f"Parâmetro 'page' duplicado no link: {href}")

        params = _query_params(href)
        self.assertEqual(params.get("page"), ["2"])
        self.assertEqual(params.get("model"), [str(self.model_a.pk)])

    def test_no_stray_params_and_filters_untouched_by_pagination_fix(self):
        """A correção não pode ter alterado a lógica do filtro em si, só o link."""
        response = self.client.get("/equipamentos/", {"model": self.model_b.pk})
        self.assertFalse(response.context["is_paginated"])  # só 3 itens, sem paginação
        self.assertEqual(response.context["paginator"].count, 3)
        for equipment in response.context["equipment_list"]:
            self.assertEqual(equipment.model_id, self.model_b.pk)
