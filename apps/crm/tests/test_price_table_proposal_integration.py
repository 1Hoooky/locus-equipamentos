"""
Testes de integração Tabela de Preços V1 ↔ Proposta (16/09/2026, seção
23-25/34). `SuggestedPriceView` é o endpoint AJAX consultado pelo form de
"Adicionar produto/serviço" (`static/crm/proposal_composition.js`) — só
LEITURA, nunca preenche/bloqueia o campo no backend (quem decide usar a
sugestão ou digitar outro valor é sempre o navegador/usuário). O POST real
de `ProposalItemAddView` continua exatamente como antes (`unit_price`
sempre vem explícito no corpo do POST) — por isso os testes de "preço
sugerido" batem no endpoint AJAX, e os testes de "snapshot"/"tabela muda
depois" batem em `add_proposal_item()` diretamente (já teria cobertura
equivalente em `test_price_table_services.py`; aqui o foco é a
composição PriceTable → endpoint AJAX → formulário de item).

RODADA 2 (13/10/2026, "INTEGRAÇÃO DA MATRIZ DE PREÇOS COM A PROPOSTA"):
decisão de produto explícita e aprovada removeu, para Opportunity de
LOCACAO + item de EQUIPAMENTO, o fallback para o `PriceTableItem`
"chapado" da V1 — a matriz (`PriceTableRate`, via
`get_suggested_rental_price()`) passou a ser a ÚNICA fonte, mesmo que um
valor "chapado" continue configurado (nunca mais usado nesse caso) e
mesmo sem `commercial_plan`/datas informados (nesse caso, `found=False`
com motivo, nunca um fallback silencioso). Os testes abaixo que dependiam
do comportamento antigo foram atualizados para documentar/provar a nova
regra em vez da antiga — a cobertura completa do caminho novo (matriz +
plano + datas, todas as combinações de unidade/calendário) está em
`test_rodada2_rental_price_integration.py`.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client as DjangoTestClient
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.crm.models import (
    BusinessType,
    CommercialPlan,
    CommercialSource,
    CommercialTerm,
    DurationUnit,
    Opportunity,
    OpportunityStage,
    ServiceCatalogItem,
)
from apps.crm.services import (
    PriceTableItemData,
    PriceTableRateData,
    ProposalItemData,
    add_proposal_item,
    get_or_create_active_proposal,
    set_price_table_item,
    set_price_table_rate,
)

User = get_user_model()


def _user_with_perms(username, *codenames):
    user = User.objects.create_user(username=username, password="senha-forte-123")
    if codenames:
        perms = Permission.objects.filter(codename__in=codenames, content_type__app_label="crm")
        group, _ = Group.objects.get_or_create(name=f"perm-{username}")
        group.permissions.set(perms)
        user.groups.add(group)
    return user


class SuggestedPriceIntegrationTestBase(TestCase):
    def setUp(self):
        self.user = _user_with_perms(
            "vendedor_preco", "view_opportunities", "add_opportunities", "change_opportunities"
        )
        self.client_obj = Client.objects.create(company_name="Cliente Preço Sugerido")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage = OpportunityStage.objects.create(name="Novo", order=1)
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(code="NI23BT", name="NI23 Big Tank", category=self.category)
        self.service = ServiceCatalogItem.objects.create(name="Diária de operador", unit_label="hora")
        self.opportunity = Opportunity.objects.create(
            client=self.client_obj,
            title="Oportunidade Preço Sugerido",
            owner=self.user,
            source=self.source,
            business_type=BusinessType.LOCACAO,
            stage=self.stage,
            created_by=self.user,
        )

    def _login(self):
        client = DjangoTestClient()
        client.force_login(self.user)
        return client

    def _suggested_price_url(self, **params):
        return reverse("crm:proposal_suggested_price", args=[self.opportunity.pk])


class SuggestedPriceViewTest(SuggestedPriceIntegrationTestBase):
    def test_equipment_model_with_configured_price_is_suggested(self):
        # RODADA 2 (13/10/2026): este teste cobria o fallback V1
        # (`PriceTableItem` "chapado") para LOCACAO+equipamento — removido
        # por decisão de produto explícita ("a matriz é a ÚNICA fonte para
        # Locação; nunca fallback silencioso para o item chapado").
        # Mantido como teste de REGRESSÃO da nova regra: mesmo havendo um
        # `PriceTableItem` configurado, uma Opportunity de Locação SEM
        # `commercial_plan` informado nunca usa esse valor.
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        client = self._login()
        resp = client.get(self._suggested_price_url(), {"equipment_model": self.model.pk})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertFalse(
            data["found"], "Locação+equipamento nunca usa o PriceTableItem chapado, mesmo com preço configurado"
        )
        self.assertIsNone(data["unit_price"])
        self.assertEqual(data["reason"], "Selecione um plano comercial.")
        self.assertEqual(data["business_type_display"], "Locação")

    def test_equipment_model_with_plan_and_dates_uses_the_rate_matrix(self):
        # RODADA 2: caminho novo e positivo — com `commercial_plan` +
        # datas, a sugestão vem da matriz (`PriceTableRate`), nunca do
        # `PriceTableItem` chapado (que fica deliberadamente sem preço
        # aqui, para provar que não é essa a fonte usada).
        plan = CommercialPlan.objects.create(name="Locação Teste RODADA2", business_type=BusinessType.LOCACAO)
        term = CommercialTerm.objects.create(commercial_plan=plan, duration_value=15, duration_unit=DurationUnit.DIAS)
        set_price_table_rate(
            data=PriceTableRateData(
                equipment_model=self.model, commercial_plan=plan, commercial_term=term, amount=Decimal("900.00")
            ),
            user=self.user,
        )
        client = self._login()
        resp = client.get(
            self._suggested_price_url(),
            {
                "equipment_model": self.model.pk,
                "commercial_plan": plan.pk,
                "contracted_start_date": "2026-10-01",
                "contracted_end_date": "2026-10-10",
            },
        )
        data = resp.json()
        self.assertTrue(data["found"])
        self.assertEqual(data["unit_price"], "900.00")
        self.assertEqual(data["commercial_term"], term.label)

    def test_service_with_configured_price_is_suggested(self):
        # 9 — ServiceCatalogItem segue a mesma lógica.
        set_price_table_item(
            data=PriceTableItemData(business_type=BusinessType.LOCACAO, service=self.service, unit_price=Decimal("150.00")),
            user=self.user,
        )
        client = self._login()
        resp = client.get(self._suggested_price_url(), {"service": self.service.pk})
        data = resp.json()
        self.assertTrue(data["found"])
        self.assertEqual(data["unit_price"], "150.00")

    def test_no_configured_price_returns_not_found_never_zero(self):
        # 10 — ausência de preço permite entrada manual (nunca inventa 0).
        client = self._login()
        resp = client.get(self._suggested_price_url(), {"equipment_model": self.model.pk})
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["found"])
        self.assertIsNone(data["unit_price"])

    def test_uses_opportunity_business_type_not_a_client_supplied_one(self):
        # A Opportunity é LOCACAO — mesmo que exista um preço de VENDA
        # configurado para o mesmo modelo, a sugestão respeita o
        # business_type da PRÓPRIA Opportunity (nunca aceita um
        # `business_type` vindo da querystring).
        set_price_table_item(
            data=PriceTableItemData(business_type=BusinessType.VENDA, equipment_model=self.model, unit_price=Decimal("25000.00")),
            user=self.user,
        )
        client = self._login()
        resp = client.get(self._suggested_price_url() + "?business_type=VENDA", {"equipment_model": self.model.pk})
        data = resp.json()
        self.assertFalse(data["found"])

    def test_requires_login(self):
        client = DjangoTestClient()
        resp = client.get(self._suggested_price_url(), {"equipment_model": self.model.pk})
        self.assertEqual(resp.status_code, 302)

    def test_requires_view_opportunities_permission(self):
        other_user = _user_with_perms("sem_permissao_preco")
        client = DjangoTestClient()
        client.force_login(other_user)
        resp = client.get(self._suggested_price_url(), {"equipment_model": self.model.pk})
        self.assertEqual(resp.status_code, 403)

    def test_without_selection_returns_error(self):
        client = self._login()
        resp = client.get(self._suggested_price_url())
        self.assertEqual(resp.status_code, 400)


class ProposalItemManualOverrideAndSnapshotTest(SuggestedPriceIntegrationTestBase):
    def test_proposal_item_can_be_saved_with_manually_overridden_price(self):
        # 3/4 — salvar ProposalItem com preço alterado manualmente (o
        # POST real de `ProposalItemAddView` sempre recebe `unit_price`
        # explícito — a sugestão só preenche o campo no navegador).
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        client = self._login()
        resp = client.post(
            reverse("crm:proposal_item_add", args=[self.opportunity.pk]),
            {"equipment_model": self.model.pk, "quantity": "1", "unit_price": "850.00", "item_discount_amount": "0"},
        )
        self.assertEqual(resp.status_code, 302)
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.user)
        item = proposal.latest_version.items.get()
        self.assertEqual(item.unit_price, Decimal("850.00"), "usuário pode negociar valor diferente do sugerido")

    def test_price_table_change_after_save_does_not_affect_old_proposal_new_one_gets_new_price(self):
        # 6/7/8 — mudar a tabela depois: proposta antiga intacta, nova
        # consulta usa o novo valor.
        #
        # RODADA 2 (13/10/2026): adaptado para a matriz (`PriceTableRate`)
        # — LOCACAO+equipamento não usa mais o `PriceTableItem` chapado
        # (ver comentário no topo do arquivo). `ProposalItem` continua
        # sendo um snapshot congelado de qualquer forma: este `add_proposal_item()`
        # recebe `unit_price` explícito, sem FK viva para a tabela/matriz,
        # então o ponto central do teste (editar a célula depois não afeta
        # o item já salvo) permanece válido e coberto aqui.
        plan = CommercialPlan.objects.create(name="Locação Teste RODADA2 Snapshot", business_type=BusinessType.LOCACAO)
        term = CommercialTerm.objects.create(commercial_plan=plan, duration_value=15, duration_unit=DurationUnit.DIAS)
        set_price_table_rate(
            data=PriceTableRateData(
                equipment_model=self.model, commercial_plan=plan, commercial_term=term, amount=Decimal("900.00")
            ),
            user=self.user,
        )
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.user)
        old_item = add_proposal_item(
            proposal_version=proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("900.00")),
        )

        # "Tabela muda depois": mesma célula (modelo + plano + prazo),
        # novo valor — `set_price_table_rate()` atualiza a linha existente
        # da matriz, nunca cria uma segunda.
        set_price_table_rate(
            data=PriceTableRateData(
                equipment_model=self.model, commercial_plan=plan, commercial_term=term, amount=Decimal("950.00")
            ),
            user=self.user,
        )

        old_item.refresh_from_db()
        self.assertEqual(old_item.unit_price, Decimal("900.00"), "item já salvo nunca é afetado retroativamente")

        client = self._login()
        resp = client.get(
            self._suggested_price_url(),
            {
                "equipment_model": self.model.pk,
                "commercial_plan": plan.pk,
                "contracted_start_date": "2026-10-01",
                "contracted_end_date": "2026-10-10",
            },
        )
        data = resp.json()
        self.assertTrue(data["found"])
        self.assertEqual(data["unit_price"], "950.00", "nova consulta reflete o valor atualizado da matriz")
