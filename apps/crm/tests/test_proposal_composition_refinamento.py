"""
Testes do REFINAMENTO VISUAL E FUNCIONAL da aba "Produtos e Serviços"
(14/09/2026) — cobre especificamente o que MUDOU nesta rodada em relação
à entrega anterior (a funcional já testada em test_proposal_services.py/
test_proposal_views.py continua íntegra, ver também os testes de
regressão ao final deste arquivo):

1. "Tabela de preço" não aparece mais na tela.
2. "Condição" não aparece mais na tela.
3. "Outra forma (especifique)" não aparece mais na tela.
4. "Forma de pagamento" continua funcionando.
5. "Informações de valor e pagamento" continua funcionando.
6. Criação/edição de proposta continua funcionando.
7. Emissão continua funcionando.
8. Cálculo financeiro permanece idêntico (nenhuma regressão).
9. Nenhuma regressão de PDF (view de geração continua respondendo OK).
10. Layout sem lacunas quebradas (nenhum campo removido deixa
    `<label>`/`<input>` órfão no HTML).

Mais os testes da regra "Local de entrega/operação" — CORRIGIDA em
15/09/2026 (ver docs/apps/crm.md, seção "RODADA 4"): o select mostra
EXCLUSIVAMENTE as `Location`s do CLIENTE da PRÓPRIA Opportunity — nunca
uma busca/autocomplete global entre clientes. A especificação original
desta seção pedia qualificar cada opção com o nome do cliente
("Cliente — Unidade", reaproveitando `location_display_label`); a
correção substitui isso porque, com o select já escopado a um único
cliente, repetir o nome do cliente em toda linha é ruído — mostra só o
nome da unidade (`_client_location_display_label`, `apps/crm/forms.py`).
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from apps.clients.models import Client
from apps.crm.forms import ProposalConditionsForm
from apps.crm.models import BusinessType, Opportunity, PaymentMethod, ProposalVersionStatus
from apps.crm.services import ProposalItemData, add_proposal_item, get_or_create_active_proposal, issue_proposal
from apps.crm.tests._payment_test_helpers import add_full_installment
from apps.crm.tests.test_proposal_views import ProposalViewsTestBase, _user_with_perms
from apps.operations.models import Location, LocationType


class RemovedFieldsNotInFormTest(TestCase):
    """1/2/3 — os três campos não têm mais representação no form em si
    (não só escondidos por CSS/template — o form nem os declara)."""

    def test_price_table_label_not_a_form_field(self):
        self.assertNotIn("price_table_label", ProposalConditionsForm().fields)

    def test_payment_condition_not_a_form_field(self):
        self.assertNotIn("payment_condition", ProposalConditionsForm().fields)

    def test_payment_method_other_not_a_form_field(self):
        self.assertNotIn("payment_method_other", ProposalConditionsForm().fields)

    def test_payment_method_still_a_form_field(self):
        self.assertIn("payment_method", ProposalConditionsForm().fields)

    def test_payment_info_notes_still_a_form_field(self):
        self.assertIn("payment_info_notes", ProposalConditionsForm().fields)

    def test_payment_method_choices_exclude_outro(self):
        choices_values = [value for value, _ in ProposalConditionsForm().fields["payment_method"].choices]
        self.assertNotIn(PaymentMethod.OUTRO, choices_values)
        # As opções reais continuam oferecidas (auditoria confirmou que
        # são as únicas configuradas no sistema — seção "Forma de
        # pagamento" da correção).
        self.assertIn(PaymentMethod.PIX, choices_values)
        self.assertIn(PaymentMethod.BOLETO, choices_values)
        self.assertIn(PaymentMethod.CARTAO, choices_values)

    def test_form_has_no_conditional_outro_validation(self):
        """A correção pede para NÃO implementar nenhuma lógica
        condicional de "Outra forma" — confirmamos que enviar
        payment_method=OUTRO é simplesmente rejeitado como opção
        inválida (não existe mais nos choices), e não pela antiga
        validação de "especifique"."""
        form = ProposalConditionsForm(data={"payment_method": PaymentMethod.OUTRO})
        self.assertFalse(form.is_valid())
        self.assertIn("payment_method", form.errors)
        self.assertNotIn("payment_method_other", form.errors)


class RemovedFieldsNotRenderedTest(ProposalViewsTestBase):
    """1/2/3/10 — confirma na tela renderizada de verdade (view completa,
    não só o form isolado), e que nada fica "órfão" no HTML."""

    def setUp(self):
        super().setUp()
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        add_proposal_item(
            proposal_version=proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=2, unit_price=Decimal("150.00")),
        )
        self.proposal = proposal

    def _get_body(self):
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_tabela_de_preco_label_absent(self):
        body = self._get_body()
        self.assertNotIn(">Tabela de preço<", body)
        self.assertNotIn('id="id_price_table_label"', body)

    def test_condicao_label_absent(self):
        body = self._get_body()
        self.assertNotIn(">Condição<", body)
        self.assertNotIn('id="id_payment_condition"', body)
        # A seção continua existindo com outro nome (não é o mesmo texto)
        self.assertIn("Condições comerciais", body)

    def test_outra_forma_label_absent(self):
        body = self._get_body()
        self.assertNotIn("Outra forma (especifique)", body)
        self.assertNotIn('id="id_payment_method_other"', body)

    def test_forma_de_pagamento_still_rendered(self):
        body = self._get_body()
        self.assertIn(">Forma de pagamento<", body)
        self.assertIn('id="id_payment_method"', body)

    def test_informacoes_de_valor_e_pagamento_still_rendered(self):
        body = self._get_body()
        self.assertIn(">Informações de valor e pagamento<", body)
        self.assertIn('id="id_payment_info_notes"', body)

    def test_new_periodo_logistica_labels_exact(self):
        body = self._get_body()
        for label in (
            "Início do contrato",
            "Fim do contrato",
            "Entrega prevista",
            "Horário de entrega",
            "Retirada prevista",
            "Horário de retirada",
        ):
            self.assertIn(f">{label}<", body, f"Rótulo esperado ausente: {label!r}")
        # Rótulos antigos, mais técnicos, não devem mais aparecer.
        self.assertNotIn(">Início contratado<", body)
        self.assertNotIn(">Final contratado<", body)
        self.assertNotIn("Entrega prevista (data)", body)

    def test_item_card_shows_product_and_total(self):
        body = self._get_body()
        self.assertIn("proposal-item-card", body)
        self.assertIn("2 unidades", body)


class PaymentMethodAndNotesStillWorkTest(ProposalViewsTestBase):
    """4/5/6 — salvar rascunho com Forma de pagamento + Informações de
    valor e pagamento continua funcionando de ponta a ponta (view real,
    não só o service)."""

    def setUp(self):
        super().setUp()
        self.proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100.00")),
        )

    def test_saving_conditions_persists_payment_method_and_notes(self):
        client = self._login(self.owner)
        resp = client.post(
            reverse("crm:proposal_conditions_save", args=[self.opportunity.pk]),
            {
                "payment_method": PaymentMethod.PIX,
                "payment_info_notes": "50% de entrada via PIX e 50% em boleto para 28 dias.",
                "contracted_start_date": "2026-09-20",
                "contracted_end_date": "2026-10-20",
            },
        )
        self.assertEqual(resp.status_code, 302)
        version = self.proposal.latest_version
        version.refresh_from_db()
        self.assertEqual(version.payment_method, PaymentMethod.PIX)
        self.assertEqual(version.payment_info_notes, "50% de entrada via PIX e 50% em boleto para 28 dias.")

    def test_saving_conditions_does_not_wipe_preexisting_price_table_label(self):
        """IMPORTANTE (correção da especificação): não apagar dado já
        persistido só porque o campo saiu da UI. Simula um valor
        legado gravado antes desta mudança (ex.: via admin) e confirma
        que "Salvar rascunho" pela tela nova não o zera."""
        version = self.proposal.latest_version
        version.price_table_label = "Tabela legada X"
        version.payment_condition = "Condição legada Y"
        version.save()

        client = self._login(self.owner)
        resp = client.post(
            reverse("crm:proposal_conditions_save", args=[self.opportunity.pk]),
            {"payment_method": PaymentMethod.BOLETO},
        )
        self.assertEqual(resp.status_code, 302)
        version.refresh_from_db()
        self.assertEqual(version.price_table_label, "Tabela legada X")
        self.assertEqual(version.payment_condition, "Condição legada Y")

    def test_dates_and_times_still_persist(self):
        client = self._login(self.owner)
        resp = client.post(
            reverse("crm:proposal_conditions_save", args=[self.opportunity.pk]),
            {
                "payment_method": "",
                "contracted_start_date": "2026-10-01",
                "contracted_end_date": "2026-10-15",
                "expected_delivery_date": "2026-10-02",
                "expected_delivery_time": "09:30",
                "expected_pickup_date": "2026-10-15",
                "expected_pickup_time": "17:00",
            },
        )
        self.assertEqual(resp.status_code, 302)
        version = self.proposal.latest_version
        version.refresh_from_db()
        self.assertEqual(str(version.contracted_start_date), "2026-10-01")
        self.assertEqual(str(version.contracted_end_date), "2026-10-15")
        self.assertEqual(str(version.expected_delivery_date), "2026-10-02")
        self.assertEqual(str(version.expected_delivery_time), "09:30:00")
        self.assertEqual(str(version.expected_pickup_date), "2026-10-15")
        self.assertEqual(str(version.expected_pickup_time), "17:00:00")


class IssuanceAndCalculationRegressionTest(ProposalViewsTestBase):
    """7/8/9 — emissão, cálculo financeiro e geração de documento (PDF)
    continuam funcionando exatamente como antes desta rodada visual."""

    def setUp(self):
        super().setUp()
        self.proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=2, unit_price=Decimal("100.00"), item_discount_amount=Decimal("20.00")),
        )

    def test_calculation_matches_expected_order(self):
        # RODADA 3 (14/09/2026): desconto do item agora é R$ (era %) —
        # 2 x R$100 = 200; desconto de item R$20 => subtotal 180.
        # + desconto geral 50, + frete 20, sem juros => total 150.
        client = self._login(self.owner)
        resp = client.post(
            reverse("crm:proposal_conditions_save", args=[self.opportunity.pk]),
            {"payment_method": "", "general_discount": "50.00", "freight_amount": "20.00"},
        )
        self.assertEqual(resp.status_code, 302)
        version = self.proposal.latest_version
        version.refresh_from_db()
        self.assertEqual(version.subtotal, Decimal("180.00"))
        self.assertEqual(version.total, Decimal("150.00"))

    def test_issuing_document_still_works(self):
        add_full_installment(self.proposal.latest_version)
        user = _user_with_perms("issuer_refin", "view_opportunities", "issue_proposal_documents")
        client = self._login(user)
        resp = client.post(
            reverse("crm:proposal_generate_document", args=[self.opportunity.pk]), {"document_type": "PROPOSTA"}
        )
        self.assertEqual(resp.status_code, 302)
        version = self.proposal.latest_version
        version.refresh_from_db()
        self.assertEqual(version.status, ProposalVersionStatus.ISSUED)
        self.assertFalse("Server Error" in client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk])).content.decode())


class DeliveryLocationScopedToOpportunityClientTest(ProposalViewsTestBase):
    """
    CORREÇÃO (15/09/2026) — "Local de entrega/operação" mostra
    EXCLUSIVAMENTE as `Location`s do cliente da PRÓPRIA `Opportunity`
    (`self.opportunity.client`, "Cliente Views" em `ProposalViewsTestBase`)
    — nunca Locations de outro cliente, mesmo que existam no banco.
    Substitui a antiga `MatrizUnidadeDisplayTest`, que (por engano,
    seguindo a especificação original já corrigida) testava Locations de
    clientes SEM NENHUMA relação com a Opportunity aparecendo no select.
    """

    def setUp(self):
        super().setUp()
        from apps.clients.models import Client as ClientModel

        # Locations do cliente DA PRÓPRIA Opportunity — devem aparecer.
        self.loc_norte = Location.objects.create(
            name="Unidade Norte", type=LocationType.CLIENTE, client=self.client_obj, is_active=True
        )
        self.loc_sul = Location.objects.create(
            name="Unidade Sul", type=LocationType.CLIENTE, client=self.client_obj, is_active=True
        )
        # Cliente DIFERENTE, sem nenhuma relação com esta Opportunity —
        # a Location dele nunca pode aparecer nem ser aceita no POST.
        self.other_client = ClientModel.objects.create(company_name="Gerdau Aços Especiais LTDA", trade_name="Gerdau")
        self.loc_outro_cliente = Location.objects.create(
            name="Unidade Maringá", type=LocationType.CLIENTE, client=self.other_client, is_active=True
        )

        self.proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100.00")),
        )

    def test_select_shows_only_locations_of_opportunity_client(self):
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        body = resp.content.decode()
        self.assertIn(">Unidade Norte<", body)
        self.assertIn(">Unidade Sul<", body)

    def test_other_client_locations_never_appear_in_select(self):
        """Item 2 da correção: outros clientes NUNCA aparecem, mesmo que
        existam no banco."""
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        body = resp.content.decode()
        self.assertNotIn("Unidade Maringá", body)
        self.assertNotIn("Gerdau", body)

    def test_label_shows_only_unit_name_never_repeats_client(self):
        """Item 5 da correção: como todas as opções já pertencem ao
        mesmo cliente, o rótulo mostra só o nome da unidade — nunca
        "Cliente — Unidade" (isso seria ruído aqui, ao contrário do
        select de destino de `MovementForm`, que mistura clientes)."""
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        body = resp.content.decode()
        self.assertIn(">Unidade Norte<", body)
        self.assertNotIn("Cliente Views — Unidade Norte", body)

    def test_saving_delivery_location_persists_and_does_not_alter_client_or_location(self):
        client = self._login(self.owner)
        resp = client.post(
            reverse("crm:proposal_conditions_save", args=[self.opportunity.pk]),
            {"payment_method": "", "delivery_location": self.loc_norte.pk},
        )
        self.assertEqual(resp.status_code, 302)
        version = self.proposal.latest_version
        version.refresh_from_db()
        self.assertEqual(version.delivery_location_id, self.loc_norte.pk)

        self.loc_norte.refresh_from_db()
        self.client_obj.refresh_from_db()
        self.assertEqual(self.loc_norte.client_id, self.client_obj.pk)
        self.assertEqual(self.loc_norte.name, "Unidade Norte")

    def test_posting_location_of_another_client_is_rejected(self):
        """Item 4 da correção — SEGURANÇA BACKEND: mesmo manipulando o
        POST manualmente com o PK de uma Location de OUTRO cliente, o
        form rejeita (queryset escopada por `opportunity.client` já
        recusa o valor — `ModelChoiceField` nunca aceita um PK fora da
        queryset) e nada é persistido."""
        client = self._login(self.owner)
        client.post(
            reverse("crm:proposal_conditions_save", args=[self.opportunity.pk]),
            {"payment_method": "", "delivery_location": self.loc_outro_cliente.pk},
        )
        version = self.proposal.latest_version
        version.refresh_from_db()
        self.assertNotEqual(version.delivery_location_id, self.loc_outro_cliente.pk)
        self.assertIsNone(version.delivery_location_id)

    def test_client_with_no_locations_shows_empty_state(self):
        """Item 8 da correção — cliente sem nenhuma unidade cadastrada
        mostra um estado vazio em vez de um select sem opções (e nunca
        cai para Locations de outro cliente como fallback)."""
        empty_client_opportunity = Opportunity.objects.create(
            client=Client.objects.create(company_name="Cliente Sem Unidade LTDA"),
            title="Oportunidade sem unidade", owner=self.owner, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage_novo, created_by=self.owner,
        )
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[empty_client_opportunity.pk]))
        body = resp.content.decode()
        self.assertIn("Nenhuma unidade cadastrada para este cliente.", body)

    def test_single_location_client_is_preselected_but_still_shown(self):
        """Item 6 da correção — cliente com uma única unidade ativa vem
        pré-selecionada no `initial`, mas o campo continua sendo um
        `<select>` normal mostrando claramente qual local será usado
        (nunca escondido)."""
        single_client = Client.objects.create(company_name="Cliente Uma Unidade LTDA")
        Location.objects.create(name="Unidade principal", type=LocationType.CLIENTE, client=single_client, is_active=True)
        single_opportunity = Opportunity.objects.create(
            client=single_client, title="Oportunidade unidade única", owner=self.owner, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage_novo, created_by=self.owner,
        )
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[single_opportunity.pk]))
        body = resp.content.decode()
        self.assertIn(">Unidade principal<", body)
        # A OPÇÃO em si vem marcada como selecionada — não só presente
        # no select (o campo continua mostrando claramente qual local
        # será usado, nunca escondido).
        self.assertIn("selected>Unidade principal</option>", body)

    def test_inactive_location_never_appears(self):
        """Item 3 da correção — respeita ativo/inativo."""
        inactive = Location.objects.create(
            name="Unidade Desativada", type=LocationType.CLIENTE, client=self.client_obj, is_active=False
        )
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        body = resp.content.decode()
        self.assertNotIn("Unidade Desativada", body)

    def test_editing_loads_the_previously_saved_location_selected(self):
        """Item 9 do checklist de testes obrigatórios — reabrir a tela
        depois de salvar mostra a MESMA Location marcada como
        selecionada no select (nunca perdida/trocada por outra)."""
        client = self._login(self.owner)
        client.post(
            reverse("crm:proposal_conditions_save", args=[self.opportunity.pk]),
            {"payment_method": "", "delivery_location": self.loc_sul.pk},
        )
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        body = resp.content.decode()
        self.assertIn("selected>Unidade Sul</option>", body)

    def test_no_global_location_autocomplete_endpoint_exists(self):
        """Item 10 do checklist — nenhum endpoint de busca global de
        Location foi criado (ao contrário da especificação original,
        já corrigida)."""
        for name in ("crm:location_autocomplete", "crm:location_search", "crm:delivery_location_search"):
            with self.assertRaises(NoReverseMatch):
                reverse(name)

    def test_issuing_proposal_preserves_the_saved_delivery_location(self):
        """Item 12 do checklist — a emissão continua usando a Location
        correta (nenhuma regressão introduzida pela correção)."""
        client = self._login(self.owner)
        client.post(
            reverse("crm:proposal_conditions_save", args=[self.opportunity.pk]),
            {"payment_method": "", "delivery_location": self.loc_norte.pk},
        )
        version = self.proposal.latest_version
        version.refresh_from_db()
        add_full_installment(version)
        issue_proposal(proposal_version=version, issued_by=self.owner)
        version.refresh_from_db()
        self.assertEqual(version.delivery_location_id, self.loc_norte.pk)
