"""
Testes HTTP/permissões de Produtos e Serviços/Proposta Comercial +
Contrato (14/09/2026) — seção 85 (POST-only + CSRF), seção 98 (matriz de
permissões: sem `view` não vê, sem `change` não edita, sem `issue` não
emite, sem `accept` não aceita, sem `contract` não gera contrato,
endpoints protegidos).
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client as DjangoTestClient
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.crm.models import BusinessType, CommercialSource, Opportunity, OpportunityStage, ProposalVersionStatus
from apps.crm.services import ProposalItemData, add_proposal_item, get_or_create_active_proposal, issue_proposal
from apps.crm.tests._payment_test_helpers import add_full_installment

User = get_user_model()


def _user_with_perms(username, *codenames):
    user = User.objects.create_user(username=username, password="senha-forte-123")
    if codenames:
        perms = Permission.objects.filter(codename__in=codenames, content_type__app_label="crm")
        group, _ = Group.objects.get_or_create(name=f"perm-{username}")
        group.permissions.set(perms)
        user.groups.add(group)
    return user


class ProposalViewsTestBase(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(company_name="Cliente Views")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho", order=2, is_won=True)
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(code="NI23TC", name="NI23 Big Tank", category=self.category)

        self.owner = _user_with_perms("owner_views", "add_opportunities", "view_opportunities", "change_opportunities")
        self.opportunity = Opportunity.objects.create(
            client=self.client_obj, title="Oportunidade Views", owner=self.owner, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage_novo, created_by=self.owner,
        )

    def _login(self, user):
        client = DjangoTestClient()
        client.force_login(user)
        return client


class ItemAddViewPermissionTest(ProposalViewsTestBase):
    url_name = "crm:proposal_item_add"

    def test_get_not_allowed(self):
        client = self._login(self.owner)
        resp = client.get(reverse(self.url_name, args=[self.opportunity.pk]))
        self.assertEqual(resp.status_code, 405)

    def test_no_permission_forbidden(self):
        user = _user_with_perms("no_perm_add_item")
        client = self._login(user)
        resp = client.post(reverse(self.url_name, args=[self.opportunity.pk]), {})
        self.assertEqual(resp.status_code, 403)

    def test_view_only_cannot_add_item(self):
        user = _user_with_perms("view_only_add_item", "view_opportunities")
        client = self._login(user)
        resp = client.post(reverse(self.url_name, args=[self.opportunity.pk]), {})
        self.assertEqual(resp.status_code, 403)

    def test_change_permission_can_add_item(self):
        client = self._login(self.owner)
        resp = client.post(
            reverse(self.url_name, args=[self.opportunity.pk]),
            {"equipment_model": self.model.pk, "quantity": "2", "unit_price": "150.00", "item_discount_amount": "0"},
        )
        self.assertEqual(resp.status_code, 302)
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        self.assertEqual(proposal.latest_version.items.count(), 1)

    def test_csrf_required(self):
        strict_client = DjangoTestClient(enforce_csrf_checks=True)
        strict_client.force_login(self.owner)
        resp = strict_client.post(
            reverse(self.url_name, args=[self.opportunity.pk]),
            {"equipment_model": self.model.pk, "quantity": "1", "unit_price": "10"},
        )
        self.assertEqual(resp.status_code, 403)


class ItemDiscountAmountValidationTest(ProposalViewsTestBase):
    """
    RODADA 3 DE REFINAMENTOS (14/09/2026), seção 51-60: desconto do item
    é R$ — a validação (nunca negativo, nunca maior que o bruto) acontece
    tanto no form (erro amigável, sem round-trip até o banco) quanto no
    service (defesa em profundidade), nunca só num dos dois.
    """

    url_name = "crm:proposal_item_add"

    def test_discount_greater_than_gross_is_rejected_with_friendly_error(self):
        client = self._login(self.owner)
        resp = client.post(
            reverse(self.url_name, args=[self.opportunity.pk]),
            {"equipment_model": self.model.pk, "quantity": "1", "unit_price": "100.00", "item_discount_amount": "150.00"},
        )
        self.assertEqual(resp.status_code, 302)  # redireciona de volta com mensagem de erro, nada é criado
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        self.assertEqual(proposal.latest_version.items.count(), 0)

    def test_discount_equal_to_gross_is_allowed(self):
        """Item 100% "de graça" é um caso legítimo (desconto integral) — só MAIOR que o bruto é rejeitado."""
        client = self._login(self.owner)
        resp = client.post(
            reverse(self.url_name, args=[self.opportunity.pk]),
            {"equipment_model": self.model.pk, "quantity": "1", "unit_price": "100.00", "item_discount_amount": "100.00"},
        )
        self.assertEqual(resp.status_code, 302)
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        item = proposal.latest_version.items.get()
        self.assertEqual(item.item_discount_amount, Decimal("100.00"))
        self.assertEqual(item.line_total, Decimal("0.00"))

    def test_no_percent_symbol_anywhere_in_the_add_item_form(self):
        client = self._login(self.owner)
        resp = client.get(f"/crm/oportunidades/{self.opportunity.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Desconto do item (R$)")
        self.assertNotContains(resp, "Desconto do item (%)")


class GenerateDocumentViewPermissionTest(ProposalViewsTestBase):
    def setUp(self):
        super().setUp()
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        add_proposal_item(
            proposal_version=proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100")),
        )
        add_full_installment(proposal.latest_version)
        self.proposal = proposal

    def test_issuing_proposta_without_issue_permission_is_forbidden(self):
        client = self._login(self.owner)  # owner has view/change but not issue_proposal_documents
        resp = client.post(
            reverse("crm:proposal_generate_document", args=[self.opportunity.pk]), {"document_type": "PROPOSTA"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_issuing_proposta_with_permission_succeeds(self):
        user = _user_with_perms("issuer", "view_opportunities", "issue_proposal_documents")
        client = self._login(user)
        resp = client.post(
            reverse("crm:proposal_generate_document", args=[self.opportunity.pk]), {"document_type": "PROPOSTA"}
        )
        self.assertEqual(resp.status_code, 302)
        self.proposal.latest_version.refresh_from_db()
        self.assertEqual(self.proposal.latest_version.status, ProposalVersionStatus.ISSUED)

    def test_generating_contract_requires_contract_permission_not_just_issue(self):
        user = _user_with_perms("only_issue", "view_opportunities", "issue_proposal_documents")
        client = self._login(user)
        resp = client.post(
            reverse("crm:proposal_generate_document", args=[self.opportunity.pk]), {"document_type": "CONTRATO"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_generating_contract_with_permission_succeeds(self):
        user = _user_with_perms("contract_user", "view_opportunities", "generate_contract")
        client = self._login(user)
        resp = client.post(
            reverse("crm:proposal_generate_document", args=[self.opportunity.pk]), {"document_type": "CONTRATO"}
        )
        self.assertEqual(resp.status_code, 302)
        self.proposal.latest_version.refresh_from_db()
        self.assertEqual(self.proposal.latest_version.contracts.count(), 1)

    def test_get_not_allowed(self):
        client = self._login(self.owner)
        resp = client.get(reverse("crm:proposal_generate_document", args=[self.opportunity.pk]))
        self.assertEqual(resp.status_code, 405)


class AcceptViewPermissionTest(ProposalViewsTestBase):
    def setUp(self):
        super().setUp()
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        add_proposal_item(
            proposal_version=proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100")),
        )
        add_full_installment(proposal.latest_version)
        issue_proposal(proposal_version=proposal.latest_version, issued_by=self.owner)
        self.proposal = proposal

    def test_accept_without_change_stage_permission_forbidden(self):
        client = self._login(self.owner)  # no change_opportunity_stage
        resp = client.post(
            reverse("crm:proposal_accept_version", args=[self.opportunity.pk]),
            {"proposal_version": self.proposal.latest_version.pk, "stage": self.stage_ganho.pk},
        )
        self.assertEqual(resp.status_code, 403)

    def test_accept_with_permission_marks_opportunity_won(self):
        user = _user_with_perms("accepter", "view_opportunities", "change_opportunity_stage")
        client = self._login(user)
        resp = client.post(
            reverse("crm:proposal_accept_version", args=[self.opportunity.pk]),
            {"proposal_version": self.proposal.latest_version.pk, "stage": self.stage_ganho.pk},
        )
        self.assertEqual(resp.status_code, 302)
        self.opportunity.refresh_from_db()
        self.assertTrue(self.opportunity.stage.is_won)

    def test_get_not_allowed(self):
        user = _user_with_perms("accept_get_test", "view_opportunities", "change_opportunity_stage")
        client = self._login(user)
        resp = client.get(reverse("crm:proposal_accept_version", args=[self.opportunity.pk]))
        self.assertEqual(resp.status_code, 405)


class AvailabilityCheckViewTest(ProposalViewsTestBase):
    def test_requires_view_permission(self):
        user = _user_with_perms("no_view_avail")
        client = self._login(user)
        resp = client.get(
            reverse("crm:proposal_availability_check", args=[self.opportunity.pk]),
            {"equipment_model": self.model.pk, "quantity": "1"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_returns_json_and_creates_no_state(self):
        from apps.operations.models import Movement

        client = self._login(self.owner)
        resp = client.get(
            reverse("crm:proposal_availability_check", args=[self.opportunity.pk]),
            {"equipment_model": self.model.pk, "quantity": "3"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["requested"], 3)
        self.assertEqual(Movement.objects.count(), 0)


class OpportunityDetailTabRenderingTest(ProposalViewsTestBase):
    def test_hub_page_renders_produtos_e_servicos_tab(self):
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Produtos e Serviços", body)
        self.assertIn("Anexos", body)

    def test_view_only_user_sees_no_item_form(self):
        user = _user_with_perms("view_only_hub", "view_opportunities")
        client = self._login(user)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        self.assertEqual(resp.status_code, 200)
        # Sem `change_opportunities`, nenhuma proposta é criada
        # automaticamente (GET nunca cria por conta própria) e o form de
        # item não aparece.
        self.assertIsNone(resp.context["proposal"])
        self.assertIsNone(resp.context["item_form"])
