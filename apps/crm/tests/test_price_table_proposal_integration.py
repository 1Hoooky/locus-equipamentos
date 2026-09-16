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
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client as DjangoTestClient
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.crm.models import BusinessType, CommercialSource, Opportunity, OpportunityStage, ServiceCatalogItem
from apps.crm.services import (
    PriceTableItemData,
    ProposalItemData,
    add_proposal_item,
    get_or_create_active_proposal,
    set_price_table_item,
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
        # 1/2 — selecionar EquipmentModel com preço → unit_price sugerido.
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
        self.assertTrue(data["found"])
        self.assertEqual(data["unit_price"], "900.00")
        self.assertEqual(data["business_type_display"], "Locação")

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
        # 6/7/8 — mudar a tabela depois: proposta antiga intacta, nova consulta usa o novo valor.
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.user)
        old_item = add_proposal_item(
            proposal_version=proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("900.00")),
        )

        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("950.00")
            ),
            user=self.user,
        )

        old_item.refresh_from_db()
        self.assertEqual(old_item.unit_price, Decimal("900.00"))

        client = self._login()
        resp = client.get(self._suggested_price_url(), {"equipment_model": self.model.pk})
        self.assertEqual(resp.json()["unit_price"], "950.00")
