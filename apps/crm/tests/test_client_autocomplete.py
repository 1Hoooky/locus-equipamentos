"""
Autocomplete pesquisável do campo "Cliente" (LOCUSHUB — CRM: CORRIGIR
DEFINITIVAMENTE O CAMPO CLIENTE / AUTOCOMPLETE PESQUISÁVEL A PARTIR DE 3
CARACTERES, 12/09/2026).

Cobre o endpoint `OpportunityClientAutocompleteView`
(`/crm/oportunidades/clientes/buscar/`) e o contrato de validação do
campo `client` em `OpportunityCreateForm` que o widget depende dele para
nunca aceitar um cliente que não veio de uma seleção real no dropdown.

Cenários mínimos pedidos explicitamente: consulta com menos de 3
caracteres; consulta com exatamente 3; busca sem diferenciar
maiúsculas/minúsculas; prioridade de ordenação (prefixo > contém >
similaridade); limite de resultados; usuário sem permissão; ID inválido;
seleção válida; texto alterado invalida a seleção; criação final usa o
Client correto.

A invalidação da seleção ao editar o texto (`clearSelection()` em
`static/crm/client_autocomplete.js`) é comportamento de front-end puro —
não há nenhum evento DOM a disparar num `TestCase` do Django. O que ESTE
arquivo verifica é a garantia de backend da qual aquele comportamento
depende, e que é a que realmente protege contra "criar oportunidade para
o cliente errado": o servidor NUNCA aceita um nome digitado como se
fosse um cliente válido — só um PK real de `Client` ativo (exatamente o
que `ModelChoiceField.clean()` já fazia com o `<select>` nativo, nunca
alterado por este widget). Ver `test_typed_text_alone_never_creates_
opportunity` abaixo.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from apps.clients.models import Client
from apps.crm.models import BusinessType, CommercialSource, Opportunity, OpportunityStage

User = get_user_model()

SEARCH_URL = "/crm/oportunidades/clientes/buscar/"


def _user_with_perms(username, *codenames):
    user = User.objects.create_user(username=username, password="senha-forte-123")
    if codenames:
        perms = Permission.objects.filter(codename__in=codenames, content_type__app_label="crm")
        group, _ = Group.objects.get_or_create(name=f"perm-{username}")
        group.permissions.set(perms)
        user.groups.add(group)
    return user


class ClientAutocompleteTestBase(TestCase):
    def setUp(self):
        self.source = CommercialSource.objects.create(name="Site", order=1)
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)

        self.authorized = _user_with_perms("autocomplete_ok", "add_opportunities", "view_opportunities")
        self.unauthorized = _user_with_perms("autocomplete_sem_perm", "view_opportunities")

        # Exemplo da própria especificação: "KAU" deve achar, em ordem,
        # prefixo exato (Kaumeat/Kauane/Kauê), depois "contém", depois
        # similaridade aproximada real (Komodoro Ind/Kurizaki — que NÃO
        # contêm "kau" como substring).
        self.kaumeat = Client.objects.create(trade_name="Kaumeat", document="")
        self.kauane = Client.objects.create(trade_name="Kauane Ltda", document="")
        self.kaue = Client.objects.create(trade_name="Kaue Equipamentos", document="")
        self.mercado_kau = Client.objects.create(trade_name="Mercado Kau Distribuidora", document="")
        self.komodoro = Client.objects.create(trade_name="Komodoro Ind", document="")
        self.kurizaki = Client.objects.create(trade_name="Kurizaki", document="")
        self.unrelated = Client.objects.create(trade_name="Construtora ABC Ltda", document="")
        self.inactive_kau = Client.objects.create(trade_name="Kauzinho Inativo", document="", is_active=False)

    def _search(self, q, user=None):
        self.client.force_login(user or self.authorized)
        return self.client.get(SEARCH_URL, {"q": q})

    def _result_names(self, response):
        return [item["name"] for item in response.json()["results"]]


# ---------------------------------------------------------------------------
# Regra dos 3 caracteres.
# ---------------------------------------------------------------------------


class MinimumQueryLengthTest(ClientAutocompleteTestBase):
    def test_query_with_zero_characters_returns_empty_without_querying(self):
        response = self._search("")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"results": []})

    def test_query_with_one_character_returns_empty(self):
        response = self._search("K")
        self.assertEqual(response.json(), {"results": []})

    def test_query_with_two_characters_returns_empty(self):
        response = self._search("KA")
        self.assertEqual(response.json(), {"results": []})

    def test_query_with_exactly_three_characters_searches(self):
        response = self._search("KAU")
        names = self._result_names(response)
        self.assertIn("Kaumeat", names)
        self.assertIn("Kauane Ltda", names)

    def test_query_padded_with_whitespace_is_trimmed_before_the_length_check(self):
        """`"  KA  ".strip()` tem 2 caracteres — continua abaixo do
        mínimo, não pode ser burlado só adicionando espaços."""
        response = self._search("  KA  ")
        self.assertEqual(response.json(), {"results": []})


# ---------------------------------------------------------------------------
# Case-insensitive.
# ---------------------------------------------------------------------------


class CaseInsensitiveSearchTest(ClientAutocompleteTestBase):
    def test_lowercase_query_matches_mixed_case_names(self):
        response = self._search("kau")
        names = self._result_names(response)
        self.assertIn("Kaumeat", names)
        self.assertIn("Kauane Ltda", names)

    def test_uppercase_query_matches_the_same_results_as_lowercase(self):
        lower_names = self._result_names(self._search("kau"))
        upper_names = self._result_names(self._search("KAU"))
        self.assertEqual(set(lower_names), set(upper_names))


# ---------------------------------------------------------------------------
# Prioridade de ordenação: prefixo > contém > similaridade aproximada.
# ---------------------------------------------------------------------------


class OrderingPriorityTest(ClientAutocompleteTestBase):
    def test_prefix_matches_come_before_contains_matches(self):
        names = self._result_names(self._search("KAU"))
        # "Mercado Kau Distribuidora" contém "kau" mas não COMEÇA com
        # "kau" — deve vir depois dos três nomes que começam com "Kau".
        prefix_names = {"Kaumeat", "Kauane Ltda", "Kaue Equipamentos"}
        self.assertTrue(prefix_names.issubset(set(names)))
        contains_index = names.index("Mercado Kau Distribuidora")
        for prefix_name in prefix_names:
            self.assertLess(names.index(prefix_name), contains_index)

    def test_contains_matches_come_before_similarity_only_matches(self):
        """"Komodoro Ind"/"Kurizaki" não contêm "kau" — só aparecem pela
        similaridade aproximada (`pg_trgm`), e devem vir DEPOIS de quem
        contém o texto digitado."""
        names = self._result_names(self._search("KAU"))
        self.assertIn("Komodoro Ind", names)
        self.assertIn("Kurizaki", names)
        contains_index = names.index("Mercado Kau Distribuidora")
        self.assertGreater(names.index("Komodoro Ind"), contains_index)
        self.assertGreater(names.index("Kurizaki"), contains_index)

    def test_unrelated_client_never_appears(self):
        names = self._result_names(self._search("KAU"))
        self.assertNotIn("Construtora ABC Ltda", names)

    def test_inactive_client_never_appears_even_with_exact_prefix(self):
        names = self._result_names(self._search("KAU"))
        self.assertNotIn("Kauzinho Inativo", names)

    def test_no_results_found_returns_empty_list(self):
        # Query sem NENHUMA relação com qualquer nome cadastrado —
        # diferente de "XYZABC" (que ainda compartilha o trigrama "ABC"
        # com "Construtora ABC Ltda" e legitimamente pontua na
        # similaridade aproximada; ver `OrderingPriorityTest` acima:
        # isso é o comportamento CORRETO de fuzzy match, não um bug).
        response = self._search("QWERTYUIOP")
        self.assertEqual(response.json(), {"results": []})


# ---------------------------------------------------------------------------
# Limite de resultados.
# ---------------------------------------------------------------------------


class ResultLimitTest(ClientAutocompleteTestBase):
    def test_results_are_capped_at_result_limit(self):
        from apps.crm.views import OpportunityClientAutocompleteView

        limit = OpportunityClientAutocompleteView.RESULT_LIMIT
        for i in range(limit + 10):
            Client.objects.create(trade_name=f"Zebra Cliente {i:03d}", document="")

        response = self._search("Zebra")
        results = response.json()["results"]
        self.assertEqual(len(results), limit)


# ---------------------------------------------------------------------------
# Permissão.
# ---------------------------------------------------------------------------


class AutocompletePermissionTest(ClientAutocompleteTestBase):
    def test_user_without_add_opportunities_permission_is_blocked(self):
        response = self._search("KAU", user=self.unauthorized)
        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(SEARCH_URL, {"q": "KAU"})
        self.assertEqual(response.status_code, 302)

    def test_authorized_user_gets_results(self):
        response = self._search("KAU")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(response.json()["results"]) > 0)


# ---------------------------------------------------------------------------
# Resposta mínima — nunca dado fiscal completo.
# ---------------------------------------------------------------------------


class AutocompleteResponseShapeTest(ClientAutocompleteTestBase):
    def test_response_only_contains_id_and_name(self):
        response = self._search("KAU")
        for item in response.json()["results"]:
            self.assertEqual(set(item.keys()), {"id", "name"})

    def test_response_never_leaks_document_phone_or_email(self):
        client_with_data = Client.objects.create(
            trade_name="Kaubras Distribuidora",
            document="12345678000199",
            phone="11999998888",
            email="contato@kaubras.example.com",
        )
        response = self._search("KAU")
        content = response.content.decode()
        self.assertNotIn(client_with_data.document, content)
        self.assertNotIn(client_with_data.phone, content)
        self.assertNotIn(client_with_data.email, content)


# ---------------------------------------------------------------------------
# Contrato de criação: só um PK real de `Client` (vindo de uma seleção de
# verdade) é aceito — nunca texto digitado à mão.
# ---------------------------------------------------------------------------


class OpportunityCreationUsesRealClientTest(ClientAutocompleteTestBase):
    def _valid_payload(self, **overrides):
        payload = {
            "client": self.kaumeat.pk,
            "title": "Oportunidade autocomplete",
            "owner": self.authorized.pk,
            "source": self.source.pk,
            "business_type": BusinessType.LOCACAO,
            "stage": self.stage_novo.pk,
            "notes": "",
        }
        payload.update(overrides)
        return payload

    def test_valid_selection_creates_opportunity_with_the_correct_client(self):
        """Simula o fluxo real: usuário digitou "KAU", clicou em
        "Kaumeat" no dropdown (`static/crm/client_autocomplete.js`
        preenche o campo oculto com `self.kaumeat.pk`) e o form foi
        enviado — a oportunidade criada deve apontar exatamente para
        esse cliente, nunca outro."""
        self.client.force_login(self.authorized)
        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload())
        opportunity = Opportunity.objects.get(title="Oportunidade autocomplete")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(opportunity.client_id, self.kaumeat.pk)

    def test_invalid_client_id_is_rejected(self):
        """PK que não existe — nunca fruto de uma seleção real do
        dropdown (que só oferece clientes de verdade)."""
        self.client.force_login(self.authorized)
        before = Opportunity.objects.count()
        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload(client=999999))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"field-error", response.content)
        self.assertEqual(Opportunity.objects.count(), before)

    def test_inactive_client_id_is_rejected(self):
        """Cliente existe mas está inativo — o dropdown nunca o
        ofereceria (`is_active=True` no filtro do endpoint de busca), e
        o backend também não aceita o PK diretamente."""
        self.client.force_login(self.authorized)
        before = Opportunity.objects.count()
        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload(client=self.inactive_kau.pk))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"field-error", response.content)
        self.assertEqual(Opportunity.objects.count(), before)

    def test_typed_text_alone_never_creates_opportunity(self):
        """Garantia de backend por trás de "ALTEROU O TEXTO = INVALIDA A
        SELEÇÃO": mesmo que o front-end falhasse em limpar o campo
        oculto, mandar o NOME do cliente (texto livre) em vez do PK
        nunca é aceito — `ModelChoiceField` só entende PK numérico de um
        `Client` real."""
        self.client.force_login(self.authorized)
        before = Opportunity.objects.count()
        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload(client="Kaumeat"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"field-error", response.content)
        self.assertEqual(Opportunity.objects.count(), before)

    def test_missing_client_is_rejected(self):
        """Campo oculto vazio (nenhuma seleção válida feita ainda, ou
        invalidada por uma edição de texto) — `required=True` continua
        bloqueando no backend, nunca só no HTML (ver docstring de
        `ClientAutocompleteWidget`, que deliberadamente nunca emite
        `required` no `<input type="hidden">`)."""
        self.client.force_login(self.authorized)
        before = Opportunity.objects.count()
        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload(client=""))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"field-error", response.content)
        self.assertEqual(Opportunity.objects.count(), before)
