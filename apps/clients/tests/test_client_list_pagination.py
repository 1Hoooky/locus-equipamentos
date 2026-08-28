"""
Paginação de Clientes: correção aprovada na padronização visual (28/08/2026)
— `client_list.html` construía o link de página manualmente
(`?page=N&q=...`), conhecendo só o parâmetro `q`. Qualquer filtro futuro
além de `q` seria perdido ao trocar de página. Trocado pelo mesmo
mecanismo genérico já usado em `equipment/list.html`
(`apps.core.templatetags.pagination_tags.url_replace`), que preserva toda
a querystring atual sem precisar conhecer nomes de parâmetro específicos.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.clients.models import Client

User = get_user_model()


class ClientListPaginationPreservesQueryParamsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pag_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="pag_admin", password="senha-forte-123")

        # paginate_by=50 em ClientListView — 55 clientes força uma 2ª página.
        for i in range(55):
            Client.objects.create(company_name=f"Cliente Alfa {i:03d} LTDA")
        # Um cliente fora do filtro de busca usado abaixo, para confirmar
        # que o filtro realmente restringe o queryset nas duas páginas.
        Client.objects.create(company_name="Zeta Serviços LTDA")

    def test_link_de_proxima_pagina_preserva_filtro_q(self):
        response = self.client.get("/clientes/?q=Alfa")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_paginated"])

        # O link "Próxima" (montado via url_replace, mesmo mecanismo de
        # equipment/list.html) precisa preservar o filtro na querystring.
        self.assertContains(response, "q=Alfa")

        page2 = self.client.get("/clientes/?q=Alfa&page=2")
        self.assertEqual(page2.status_code, 200)
        self.assertEqual(page2.context["q"], "Alfa")
        for client in page2.context["clients"]:
            self.assertIn("Alfa", client.company_name)

    def test_url_replace_nao_descarta_outros_parametros_get(self):
        # url_replace preserva QUALQUER parâmetro presente na querystring —
        # não só `q` — diferente da montagem manual anterior, que só
        # conhecia `q` e descartaria silenciosamente qualquer outro filtro.
        response = self.client.get("/clientes/?q=Alfa&ordenar=nome")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "q=Alfa")
        self.assertContains(response, "ordenar=nome")
