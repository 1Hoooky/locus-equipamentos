"""
Paginação de Unidades/Locais: bug pré-existente descoberto na auditoria
Fase 0 da rodada de UX/UI mobile-first (31/08/2026) — `LocationListView`
já paginava (`paginate_by=50`), mas `location_list.html` nunca renderizava
os controles de "Anterior/Próxima" (o bloco `{% if is_paginated %}`
simplesmente não existia no template, diferente de `client_list.html`,
que já tinha o mecanismo). Corrigido reaproveitando o MESMO mecanismo
genérico já usado em `client_list.html`/`equipment/list.html`
(`apps.core.templatetags.pagination_tags.url_replace`), sem tocar em
`LocationListView`/`LocationForm`/regra de negócio nenhuma — o bug era
só no template.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.operations.models import LocationType
from apps.operations.services import NewLocationData, create_location

User = get_user_model()


class LocationListPaginationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="loc_pag_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="loc_pag_admin", password="senha-forte-123")

        # paginate_by=50 em LocationListView — 55 unidades força uma 2ª página.
        for i in range(55):
            create_location(NewLocationData(name=f"Unidade Paginação {i:03d}", type=LocationType.ESTOQUE))

    def test_listagem_com_mais_de_50_unidades_fica_paginada(self):
        response = self.client.get("/operacao/unidades/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_paginated"])

    def test_controles_de_paginacao_aparecem_no_html(self):
        # Antes da correção: `is_paginated` já vinha True no contexto, mas
        # nenhum link "Próxima"/indicador de página aparecia na tela —
        # usuário não tinha como saber que havia mais unidades além das
        # primeiras 50.
        response = self.client.get("/operacao/unidades/")
        content = response.content.decode()
        self.assertIn("Próxima", content)
        self.assertIn("Página 1 de 2", content)

    def test_link_de_proxima_pagina_preserva_filtro_type(self):
        response = self.client.get("/operacao/unidades/?type=ESTOQUE")
        self.assertContains(response, "type=ESTOQUE")

        page2 = self.client.get("/operacao/unidades/?type=ESTOQUE&page=2")
        self.assertEqual(page2.status_code, 200)
        for location in page2.context["locations"]:
            self.assertEqual(location.type, LocationType.ESTOQUE)
