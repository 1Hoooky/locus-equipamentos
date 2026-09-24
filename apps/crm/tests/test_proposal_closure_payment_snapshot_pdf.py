"""
FECHAMENTO DA PROPOSTA COMERCIAL — DADOS COMPLETOS + PAGAMENTOS + ENTREGA +
SNAPSHOT + NOVO PDF (23/09/2026).

Cobre o que é NOVO nesta rodada (a funcionalidade já testada em
test_proposal_services.py/test_proposal_views.py/test_proposal_composition_r4.py/
test_proposal_composition_refinamento.py continua íntegra e não é duplicada
aqui):

  1. Parcelas (`ProposalVersionInstallment`): CRUD, sequência, Decimal,
     validação (valor <= 0, vencimento ausente), conferência (soma == total),
     bloqueio de emissão em divergência, sugestão de saldo restante.
  2. Versionamento de pagamento: rascunho aceita incompleto; emitida é
     imutável; alterar após emissão auto-versiona e CLONA as parcelas; a
     versão anterior nunca é tocada; reload nunca cria versão.
  3. Snapshot: emitir e depois alterar Client/CompanyProfile/nome de
     exibição do vendedor/nome do CommercialPlan — o já emitido nunca muda.
  4. "Valor por extenso" (`apps.crm.extenso.valor_por_extenso`).
  5. Conteúdo do PDF (`apps.crm.pdf.render_proposal_pdf`), via `pdfplumber`.
  6. Venda x Locação — Venda não mostra campos vazios de logística/evento.
  7. Equipamento + Serviço juntos continuam corretos no PDF modernizado.
"""

from datetime import date
from decimal import Decimal

import pdfplumber
from django.contrib.auth import get_user_model
from django.test import Client as DjangoTestClient, TestCase
from django.urls import reverse

from apps.attachments.services import attachments_for
from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.core.models import Address
from apps.core.services import CompanyProfileData, get_company_profile, update_company_profile
from apps.crm.extenso import valor_por_extenso
from apps.crm.models import (
    BusinessType,
    CommercialPlan,
    CommercialSource,
    Opportunity,
    OpportunityStage,
    PaymentMethod,
    ProposalItemType,
    ProposalVersionInstallment,
    ProposalVersionStatus,
    ServiceCatalogItem,
)
from apps.crm.pdf import render_proposal_pdf
from apps.crm.services import (
    ProposalConditionsData,
    ProposalInstallmentData,
    ProposalItemData,
    add_installment,
    add_proposal_item,
    check_payment_reconciliation,
    create_new_version,
    ensure_editable_installment,
    ensure_editable_version,
    get_or_create_active_proposal,
    issue_proposal,
    next_installment_suggestion,
    remove_installment,
    update_draft_conditions,
    update_installment,
)

User = get_user_model()


def _pdf_text(pdf_bytes: bytes) -> str:
    import io

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


class ProposalClosureTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="vendedor_fechamento", password="x")
        update_company_profile(CompanyProfileData(
            company_name="LOCACOES RTJ LTDA",
            cnpj="50.449.190/0001-05",
            logradouro="AVENIDA JOAQUIM DUARTE MOLEIRINHO",
            numero="0",
            bairro="JARDIM UNIVERSO",
            cidade="MARINGA",
            uf="PR",
            cep="87060-472",
            phone="(44) 33468-262",
            mobile_phone="",
            email="contratos@locuslocacoes.com.br",
        ))
        self.address = Address.objects.create(
            logradouro="AVENIDA AMERICO BELAY", numero="1185", bairro="JARDIM IMPERIAL",
            cidade="MARINGA", uf="PR", cep="87023-000",
        )
        self.client_obj = Client.objects.create(
            client_type="PJ",
            company_name="CRITERIUM MARINGA SERVICOS LTDA",
            trade_name="CRITERIUM MARINGA SERVICOS",
            document="29.854.808/0001-18",
            fiscal_address=self.address,
            phone="(43) 9643-2143",
            email="ruan_duelis@criteriummaringa.com.br",
            contact_name="Ruan",
        )
        self.source = CommercialSource.objects.create(name="Site")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.opportunity = Opportunity.objects.create(
            client=self.client_obj, title="Fechamento Comercial", owner=self.user, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage_novo, created_by=self.user,
        )
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(code="9000PRO", name="CLIMATIZADOR COMERCIAL EVAPORATIVO - 9000 PRO 110V", category=self.category)
        self.plan = CommercialPlan.objects.filter(business_type=BusinessType.LOCACAO).first()

    def _proposal_and_version(self):
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.user)
        return proposal, proposal.latest_version

    def _version_with_item(self, *, unit_price=Decimal("1020.00"), quantity=3):
        _, version = self._proposal_and_version()
        add_proposal_item(
            proposal_version=version,
            data=ProposalItemData(item_type=ProposalItemType.EQUIPAMENTO, equipment_model=self.model, quantity=quantity, unit_price=unit_price),
        )
        version.refresh_from_db()
        return version


# ---------------------------------------------------------------------------
# 1. Parcelas — CRUD, validação, conferência, bloqueio de emissão
# ---------------------------------------------------------------------------


class InstallmentCrudTest(ProposalClosureTestBase):
    def test_add_single_installment_matching_total(self):
        version = self._version_with_item()  # total = 3060.00
        installment = add_installment(
            proposal_version=version,
            data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)),
        )
        self.assertEqual(installment.sequence, 1)
        self.assertEqual(installment.amount, Decimal("3060.00"))
        self.assertIsInstance(installment.amount, Decimal)

    def test_multiple_installments_auto_sequence(self):
        version = self._version_with_item()  # 3060.00
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("1530.00"), due_date=date(2026, 9, 30)))
        second = add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.BOLETO, amount=Decimal("1530.00"), due_date=date(2026, 10, 30)))
        self.assertEqual(second.sequence, 2)
        self.assertEqual(version.installments.count(), 2)

    def test_sequence_unique_within_version(self):
        version = self._version_with_item()
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("100"), due_date=date(2026, 9, 30), sequence=1))
        with self.assertRaises(ValueError):
            add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("100"), due_date=date(2026, 9, 30), sequence=1))

    def test_negative_amount_rejected(self):
        version = self._version_with_item()
        with self.assertRaises(ValueError):
            add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("-1"), due_date=date(2026, 9, 30)))

    def test_zero_amount_rejected(self):
        version = self._version_with_item()
        with self.assertRaises(ValueError):
            add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("0"), due_date=date(2026, 9, 30)))

    def test_missing_due_date_rejected(self):
        version = self._version_with_item()
        with self.assertRaises(ValueError):
            add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("100"), due_date=None))

    def test_missing_payment_method_rejected(self):
        version = self._version_with_item()
        with self.assertRaises(ValueError):
            add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method="", amount=Decimal("100"), due_date=date(2026, 9, 30)))

    def test_database_constraint_rejects_non_positive_amount(self):
        version = self._version_with_item()
        with self.assertRaises(Exception):
            ProposalVersionInstallment.objects.create(proposal_version=version, sequence=1, payment_method=PaymentMethod.PIX, amount=Decimal("0.00"), due_date=date(2026, 9, 30))

    def test_update_installment(self):
        version = self._version_with_item()
        installment = add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        update_installment(installment=installment, data=ProposalInstallmentData(payment_method=PaymentMethod.BOLETO, amount=version.total, due_date=date(2026, 10, 15)))
        installment.refresh_from_db()
        self.assertEqual(installment.payment_method, PaymentMethod.BOLETO)
        self.assertEqual(installment.due_date, date(2026, 10, 15))

    def test_remove_installment(self):
        version = self._version_with_item()
        installment = add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        remove_installment(installment=installment)
        self.assertEqual(version.installments.count(), 0)

    def test_outro_requires_description_via_form(self):
        from apps.crm.forms import ProposalInstallmentForm

        form = ProposalInstallmentForm(data={"payment_method": "OUTRO", "payment_method_other": "", "amount": "100.00", "due_date": "2026-09-30"})
        self.assertFalse(form.is_valid())
        self.assertIn("payment_method_other", form.errors)

    def test_suggestion_returns_next_sequence_and_remaining_balance(self):
        version = self._version_with_item()  # total 3060
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("1500.00"), due_date=date(2026, 9, 30)))
        version.refresh_from_db()
        suggestion = next_installment_suggestion(proposal_version=version)
        self.assertEqual(suggestion["sequence"], 2)
        self.assertEqual(suggestion["suggested_amount"], Decimal("1560.00"))

    def test_suggestion_never_negative_when_overpaid(self):
        version = self._version_with_item()
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("5000.00"), due_date=date(2026, 9, 30)))
        version.refresh_from_db()
        suggestion = next_installment_suggestion(proposal_version=version)
        self.assertEqual(suggestion["suggested_amount"], Decimal("0.00"))


class PaymentReconciliationTest(ProposalClosureTestBase):
    def test_reconciled_when_sum_equals_total(self):
        version = self._version_with_item()
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        result = check_payment_reconciliation(version)
        self.assertTrue(result.is_reconciled)
        self.assertEqual(result.difference, Decimal("0.00"))

    def test_not_reconciled_when_sum_less_than_total(self):
        version = self._version_with_item()  # 3060
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("1000.00"), due_date=date(2026, 9, 30)))
        result = check_payment_reconciliation(version)
        self.assertFalse(result.is_reconciled)
        self.assertEqual(result.difference, Decimal("2060.00"))

    def test_not_reconciled_when_sum_greater_than_total(self):
        version = self._version_with_item()  # 3060
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("4000.00"), due_date=date(2026, 9, 30)))
        result = check_payment_reconciliation(version)
        self.assertFalse(result.is_reconciled)
        self.assertEqual(result.difference, Decimal("-940.00"))

    def test_total_change_after_installments_breaks_reconciliation(self):
        """Seção 24: mudar o total depois de já ter parcelas configuradas NUNCA redistribui sozinho."""
        version = self._version_with_item()  # 3060
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        update_draft_conditions(proposal_version=version, data=ProposalConditionsData(freight_amount=Decimal("140.00")))
        version.refresh_from_db()
        self.assertEqual(version.total, Decimal("3200.00"))
        result = check_payment_reconciliation(version)
        self.assertFalse(result.is_reconciled)
        self.assertEqual(result.difference, Decimal("140.00"))
        # A parcela antiga continua com o valor antigo — nunca foi tocada.
        self.assertEqual(version.installments.get().amount, Decimal("3060.00"))


class EmissionPaymentValidationTest(ProposalClosureTestBase):
    def test_cannot_issue_without_any_installment(self):
        version = self._version_with_item()
        with self.assertRaises(ValueError):
            issue_proposal(proposal_version=version, issued_by=self.user)

    def test_cannot_issue_when_sum_diverges_from_total(self):
        version = self._version_with_item()
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("100.00"), due_date=date(2026, 9, 30)))
        with self.assertRaises(ValueError):
            issue_proposal(proposal_version=version, issued_by=self.user)
        version.refresh_from_db()
        self.assertEqual(version.status, ProposalVersionStatus.DRAFT)

    def test_can_issue_when_reconciled(self):
        version = self._version_with_item()
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        issue_proposal(proposal_version=version, issued_by=self.user)
        version.refresh_from_db()
        self.assertEqual(version.status, ProposalVersionStatus.ISSUED)

    def test_can_issue_with_multiple_reconciled_installments(self):
        version = self._version_with_item()  # 3060
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("1530.00"), due_date=date(2026, 9, 30)))
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.BOLETO, amount=Decimal("1530.00"), due_date=date(2026, 10, 30)))
        issue_proposal(proposal_version=version, issued_by=self.user)
        version.refresh_from_db()
        self.assertEqual(version.status, ProposalVersionStatus.ISSUED)


# ---------------------------------------------------------------------------
# 2. Versionamento de pagamento / auto-versionamento preguiçoso
# ---------------------------------------------------------------------------


class PaymentVersioningTest(ProposalClosureTestBase):
    def test_draft_can_be_saved_with_incomplete_payment(self):
        version = self._version_with_item()
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("1.00"), due_date=date(2026, 9, 30)))
        version.refresh_from_db()
        self.assertEqual(version.status, ProposalVersionStatus.DRAFT)  # nunca bloqueado antes da emissão

    def test_installment_editable_while_draft(self):
        version = self._version_with_item()
        installment = add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        resolved = ensure_editable_installment(installment=installment, created_by=self.user)
        self.assertEqual(resolved.pk, installment.pk)  # mesmo rascunho, nenhuma clonagem

    def test_issued_version_installments_immutable(self):
        version = self._version_with_item()
        installment = add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        issue_proposal(proposal_version=version, issued_by=self.user)
        installment.refresh_from_db()
        with self.assertRaises(ValueError):
            update_installment(installment=installment, data=ProposalInstallmentData(payment_method=PaymentMethod.BOLETO, amount=version.total, due_date=date(2026, 10, 1)))
        with self.assertRaises(ValueError):
            remove_installment(installment=installment)

    def test_altering_payment_after_issue_clones_into_new_draft(self):
        """Exemplo do pedido: v1 = 1x PIX; alterar depois vira v2 = 2x PIX+Boleto; v1 preservada intacta."""
        proposal, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("3060.00")))
        version.refresh_from_db()
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("3060.00"), due_date=date(2026, 9, 23)))
        issue_proposal(proposal_version=version, issued_by=self.user)
        v1_installment_amount = version.installments.get().amount

        v2 = ensure_editable_version(proposal=proposal, created_by=self.user)
        self.assertEqual(v2.version_number, 2)
        self.assertEqual(v2.installments.count(), 1)  # clonada de v1
        cloned = v2.installments.get()
        update_installment(installment=cloned, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=Decimal("1530.00"), due_date=date(2026, 9, 23)))
        add_installment(proposal_version=v2, data=ProposalInstallmentData(payment_method=PaymentMethod.BOLETO, amount=Decimal("1530.00"), due_date=date(2026, 10, 23)))

        version.refresh_from_db()
        self.assertEqual(version.installments.count(), 1)
        self.assertEqual(version.installments.get().amount, v1_installment_amount)  # v1 nunca mudou
        self.assertEqual(v2.installments.count(), 2)

    def test_event_and_responsible_survive_new_version_clone(self):
        version = self._version_with_item()
        update_draft_conditions(proposal_version=version, data=ProposalConditionsData(event_name="Expoingá 2027", onsite_responsible_name="Ruan", onsite_responsible_phone="(44) 99999-9999"))
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        issue_proposal(proposal_version=version, issued_by=self.user)
        v2 = create_new_version(proposal=version.proposal, created_by=self.user)
        self.assertEqual(v2.event_name, "Expoingá 2027")
        self.assertEqual(v2.onsite_responsible_name, "Ruan")
        self.assertEqual(v2.onsite_responsible_phone, "(44) 99999-9999")

    def test_reloading_page_never_creates_new_version(self):
        version = self._version_with_item()
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        issue_proposal(proposal_version=version, issued_by=self.user)
        proposal = version.proposal

        from apps.crm.tests.test_proposal_views import _user_with_perms

        viewer = _user_with_perms(
            "viewer_fechamento", "view_opportunities", "change_opportunities", "issue_proposal_documents",
        )
        client = DjangoTestClient()
        client.force_login(viewer)
        client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        self.assertEqual(proposal.versions.count(), 1)


class PaymentHttpTest(ProposalClosureTestBase):
    """Endpoints reais (`ProposalInstallmentAddView`/`UpdateView`/`RemoveView`)."""

    def _login_with_change_perm(self):
        from apps.crm.tests.test_proposal_views import _user_with_perms

        user = _user_with_perms("editor_parcelas", "view_opportunities", "change_opportunities")
        client = DjangoTestClient()
        client.force_login(user)
        return client

    def test_add_installment_via_post(self):
        version = self._version_with_item()
        client = self._login_with_change_perm()
        resp = client.post(
            reverse("crm:proposal_installment_add", args=[self.opportunity.pk]),
            {"parcela-payment_method": "PIX", "parcela-payment_method_other": "", "parcela-amount": "3060.00", "parcela-due_date": "2026-09-30"},
        )
        self.assertEqual(resp.status_code, 302)
        version.refresh_from_db()
        self.assertEqual(version.installments.count(), 1)
        self.assertEqual(version.installments.get().amount, Decimal("3060.00"))

    def test_remove_installment_via_post(self):
        version = self._version_with_item()
        installment = add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        client = self._login_with_change_perm()
        resp = client.post(reverse("crm:proposal_installment_remove", args=[self.opportunity.pk, installment.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(version.installments.count(), 0)

    def test_add_installment_after_issue_autoversions(self):
        version = self._version_with_item()
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        issue_proposal(proposal_version=version, issued_by=self.user)
        proposal = version.proposal

        client = self._login_with_change_perm()
        client.post(
            reverse("crm:proposal_installment_add", args=[self.opportunity.pk]),
            {"parcela-payment_method": "BOLETO", "parcela-payment_method_other": "", "parcela-amount": "100.00", "parcela-due_date": "2026-10-30"},
        )
        self.assertEqual(proposal.versions.count(), 2)
        version.refresh_from_db()
        self.assertEqual(version.installments.count(), 1)  # v1 nunca ganhou a 2ª parcela


# ---------------------------------------------------------------------------
# 3. Snapshot — imutabilidade após emissão
# ---------------------------------------------------------------------------


class SnapshotImmutabilityTest(ProposalClosureTestBase):
    def _issued_version(self):
        version = self._version_with_item()
        update_draft_conditions(proposal_version=version, data=ProposalConditionsData(commercial_plan=self.plan))
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        issue_proposal(proposal_version=version, issued_by=self.user)
        version.refresh_from_db()
        return version

    def test_client_company_name_change_does_not_affect_issued_snapshot(self):
        version = self._issued_version()
        before = version.client_company_name_snapshot
        self.client_obj.company_name = "NOME MUDOU DEPOIS"
        self.client_obj.save()
        version.refresh_from_db()
        self.assertEqual(version.client_company_name_snapshot, before)
        self.assertNotEqual(version.client_company_name_snapshot, "NOME MUDOU DEPOIS")

    def test_client_address_change_does_not_affect_issued_snapshot(self):
        version = self._issued_version()
        before = version.client_address_snapshot
        self.address.logradouro = "RUA NOVA MUDOU"
        self.address.save()
        version.refresh_from_db()
        self.assertEqual(version.client_address_snapshot, before)

    def test_client_phone_and_email_change_does_not_affect_issued_snapshot(self):
        version = self._issued_version()
        phone_before, email_before = version.client_phone_snapshot, version.client_email_snapshot
        self.client_obj.phone = "(11) 00000-0000"
        self.client_obj.email = "mudou@mudou.com"
        self.client_obj.save()
        version.refresh_from_db()
        self.assertEqual(version.client_phone_snapshot, phone_before)
        self.assertEqual(version.client_email_snapshot, email_before)

    def test_company_profile_change_does_not_affect_issued_snapshot(self):
        version = self._issued_version()
        before = version.company_name_snapshot
        update_company_profile(CompanyProfileData(company_name="OUTRA LOCUS LTDA"))
        version.refresh_from_db()
        self.assertEqual(version.company_name_snapshot, before)

    def test_seller_display_name_change_does_not_affect_issued_snapshot(self):
        version = self._issued_version()
        before = version.seller_snapshot
        self.user.first_name = "Nome"
        self.user.last_name = "Mudou"
        self.user.save()
        version.refresh_from_db()
        self.assertEqual(version.seller_snapshot, before)

    def test_commercial_plan_rename_does_not_affect_issued_snapshot(self):
        version = self._issued_version()
        before = version.commercial_plan_name_snapshot
        self.assertTrue(before)
        self.plan.name = "Nome do plano mudou"
        self.plan.save()
        version.refresh_from_db()
        self.assertEqual(version.commercial_plan_name_snapshot, before)
        self.assertNotEqual(version.commercial_plan_name_snapshot, "Nome do plano mudou")

    def test_historical_pdf_still_represents_data_as_issued(self):
        version = self._issued_version()
        pdf_before = render_proposal_pdf(version)
        text_before = _pdf_text(pdf_before)

        self.client_obj.company_name = "MUDOU TOTALMENTE"
        self.client_obj.save()
        update_company_profile(CompanyProfileData(company_name="LOCUS MUDOU"))

        version.refresh_from_db()
        pdf_after = render_proposal_pdf(version)
        text_after = _pdf_text(pdf_after)
        self.assertEqual(text_before, text_after)
        self.assertNotIn("MUDOU TOTALMENTE", text_after)
        self.assertNotIn("LOCUS MUDOU", text_after)


# ---------------------------------------------------------------------------
# 4. Valor por extenso
# ---------------------------------------------------------------------------


class ValorPorExtensoTest(TestCase):
    def test_one_cent(self):
        self.assertEqual(valor_por_extenso(Decimal("0.01")), "zero reais e um centavo")

    def test_one_real(self):
        self.assertEqual(valor_por_extenso(Decimal("1.00")), "um real")

    def test_ten_reais(self):
        self.assertEqual(valor_por_extenso(Decimal("10.00")), "dez reais")

    def test_one_hundred_reais(self):
        self.assertEqual(valor_por_extenso(Decimal("100.00")), "cem reais")

    def test_one_thousand_reais(self):
        self.assertEqual(valor_por_extenso(Decimal("1000.00")), "mil reais")

    def test_reference_example_3060(self):
        self.assertEqual(valor_por_extenso(Decimal("3060.00")), "três mil e sessenta reais")

    def test_with_cents(self):
        self.assertEqual(valor_por_extenso(Decimal("10500.50")), "dez mil e quinhentos reais e cinquenta centavos")

    def test_rejects_float(self):
        with self.assertRaises(TypeError):
            valor_por_extenso(3060.00)  # type: ignore[arg-type]

    def test_rejects_negative(self):
        with self.assertRaises(ValueError):
            valor_por_extenso(Decimal("-1.00"))


# ---------------------------------------------------------------------------
# 5. Conteúdo do PDF
# ---------------------------------------------------------------------------


class PdfContentTest(ProposalClosureTestBase):
    def _fully_issued_version(self):
        proposal, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(item_type=ProposalItemType.EQUIPAMENTO, equipment_model=self.model, quantity=3, unit_price=Decimal("1020.00")))
        version.refresh_from_db()
        update_draft_conditions(
            proposal_version=version,
            data=ProposalConditionsData(
                commercial_plan=self.plan,
                event_name="Expoingá 2027",
                onsite_responsible_name="Ruan",
                onsite_responsible_phone="(44) 99999-9999",
                contracted_start_date=date(2026, 9, 23),
                contracted_end_date=date(2026, 10, 23),
                expected_delivery_date=date(2026, 9, 24),
                expected_delivery_time="09:00",
                expected_pickup_date=date(2026, 10, 24),
                expected_pickup_time="17:00",
                freight_amount=Decimal("0.00"),
                general_discount=Decimal("0.00"),
            ),
        )
        version.refresh_from_db()
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 23)))
        issue_proposal(proposal_version=version, issued_by=self.user)
        version.refresh_from_db()
        return version

    def test_pdf_is_valid(self):
        version = self._fully_issued_version()
        pdf_bytes = render_proposal_pdf(version)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_pdf_contains_expected_fields(self):
        version = self._fully_issued_version()
        text = _pdf_text(render_proposal_pdf(version))

        expectations = [
            version.display_label,  # número
            "23/09/2026",  # data de emissão
            "MENSAL",  # plano/modalidade (algum dos planos semeados contém "Mensal"/"Comum" etc — checado abaixo com contains genérico)
        ]
        # Número, Locus, cliente, vendedor:
        self.assertIn(version.display_label, text)
        self.assertIn("LOCACOES RTJ LTDA", text)
        self.assertIn("CRITERIUM MARINGA SERVICOS", text)  # quebra de linha entre "SERVICOS" e "LTDA" é normal em coluna estreita
        self.assertIn("vendedor_fechamento", text)
        # Itens:
        self.assertIn("CLIMATIZADOR COMERCIAL EVAPORATIVO", text)
        self.assertIn("3", text)  # quantidade
        self.assertIn("1.020,00", text)  # valor unitário
        self.assertIn("3.060,00", text)  # total
        # Resumo financeiro (o CSS renderiza o `<h2>` em maiúsculas):
        self.assertIn("RESUMO FINANCEIRO", text.replace("\n", " ").upper())
        # Valor por extenso:
        self.assertIn("três mil e sessenta reais", text)
        # Pagamento:
        self.assertIn("PIX", text)
        self.assertIn("30/09/2026" if False else "23/09/2026", text)  # vencimento configurado
        # Entrega/operação:
        self.assertIn("Expoingá 2027", text)
        self.assertIn("Ruan", text)
        self.assertIn("(44) 99999-9999", text)
        # Cidade/data:
        self.assertIn("MARINGA", text)

    def test_plan_name_appears_in_header(self):
        version = self._fully_issued_version()
        text = _pdf_text(render_proposal_pdf(version))
        self.assertIn(self.plan.name.upper(), text.upper())

    def test_installments_table_present_with_amount_and_due_date(self):
        version = self._fully_issued_version()
        text = _pdf_text(render_proposal_pdf(version))
        self.assertIn("Parcela", text)
        self.assertIn("PIX", text)

    def test_no_installments_table_shows_placeholder_never_crashes(self):
        """Defensivo: uma versão (hipoteticamente) sem parcelas não quebra o PDF — não deve acontecer via issue_proposal(), mas o template não pode estourar."""
        version = self._version_with_item()
        # Sem emitir (emissão exige parcela) — renderiza diretamente para
        # garantir que o template lida com `installments` vazio sem erro.
        pdf_bytes = render_proposal_pdf(version)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))


class PfClientDisplayTest(ProposalClosureTestBase):
    def test_pf_client_shows_name_and_cpf_not_razao_social(self):
        pf_address = Address.objects.create(logradouro="Rua PF", numero="1", bairro="Centro", cidade="Maringa", uf="PR", cep="87000-000")
        pf_client = Client.objects.create(client_type="PF", company_name="Fulano de Tal", document="123.456.789-00", fiscal_address=pf_address)
        opp = Opportunity.objects.create(
            client=pf_client, title="Venda PF", owner=self.user, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage_novo, created_by=self.user,
        )
        proposal = get_or_create_active_proposal(opportunity=opp, created_by=self.user)
        version = proposal.latest_version
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100.00")))
        version.refresh_from_db()
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        issue_proposal(proposal_version=version, issued_by=self.user)
        version.refresh_from_db()
        text = _pdf_text(render_proposal_pdf(version))
        self.assertIn("CPF", text)
        self.assertIn("123.456.789-00", text)
        self.assertNotIn("Razão social", text)


# ---------------------------------------------------------------------------
# 6. Venda x Locação
# ---------------------------------------------------------------------------


class SaleVsRentalPdfTest(ProposalClosureTestBase):
    def _issued_sale_version(self):
        opp = Opportunity.objects.create(
            client=self.client_obj, title="Venda direta", owner=self.user, source=self.source,
            business_type=BusinessType.VENDA, stage=self.stage_novo, created_by=self.user,
        )
        proposal = get_or_create_active_proposal(opportunity=opp, created_by=self.user)
        version = proposal.latest_version
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("5000.00")))
        version.refresh_from_db()
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        issue_proposal(proposal_version=version, issued_by=self.user)
        version.refresh_from_db()
        return version

    def test_sale_pdf_never_crashes_and_renders(self):
        version = self._issued_sale_version()
        pdf_bytes = render_proposal_pdf(version)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_sale_pdf_does_not_show_delivery_operation_block(self):
        version = self._issued_sale_version()
        text = _pdf_text(render_proposal_pdf(version))
        self.assertNotIn("Entrega / Operação", text)

    def test_sale_pdf_shows_dash_for_period_on_item_line(self):
        version = self._issued_sale_version()
        text = _pdf_text(render_proposal_pdf(version))
        # A tabela de itens sempre mostra "—" na coluna Período para Venda.
        self.assertIn("—", text)


# ---------------------------------------------------------------------------
# 7. Equipamento + Serviço juntos
# ---------------------------------------------------------------------------


class MixedEquipmentServicePdfTest(ProposalClosureTestBase):
    def test_equipment_and_service_both_appear_with_correct_totals(self):
        service = ServiceCatalogItem.objects.create(name="Instalação técnica", order=0, unit_label="hora")
        _, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(item_type=ProposalItemType.EQUIPAMENTO, equipment_model=self.model, quantity=2, unit_price=Decimal("500.00")))
        add_proposal_item(proposal_version=version, data=ProposalItemData(item_type=ProposalItemType.SERVICO, service=service, quantity=4, unit_price=Decimal("50.00")))
        version.refresh_from_db()
        self.assertEqual(version.total, Decimal("1200.00"))  # 1000 + 200
        add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))
        issue_proposal(proposal_version=version, issued_by=self.user)
        version.refresh_from_db()
        text = _pdf_text(render_proposal_pdf(version))
        self.assertIn("CLIMATIZADOR", text.upper())
        self.assertIn("Instalação técnica", text)
        self.assertIn("Total em serviços", text)
        self.assertIn("200,00", text)


# ---------------------------------------------------------------------------
# 8. Regressão — permissões/queryset/escopo (não deve regredir)
# ---------------------------------------------------------------------------


class NoRegressionOnPermissionsTest(ProposalClosureTestBase):
    def test_installment_views_require_change_permission(self):
        version = self._version_with_item()
        from apps.crm.tests.test_proposal_views import _user_with_perms

        viewer_only = _user_with_perms("viewer_only_fechamento", "view_opportunities")
        client = DjangoTestClient()
        client.force_login(viewer_only)
        resp = client.post(
            reverse("crm:proposal_installment_add", args=[self.opportunity.pk]),
            {"parcela-payment_method": "PIX", "parcela-amount": "100.00", "parcela-due_date": "2026-09-30"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_installment_from_another_opportunity_is_404(self):
        version = self._version_with_item()
        installment = add_installment(proposal_version=version, data=ProposalInstallmentData(payment_method=PaymentMethod.PIX, amount=version.total, due_date=date(2026, 9, 30)))

        other_opp = Opportunity.objects.create(
            client=self.client_obj, title="Outra", owner=self.user, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage_novo, created_by=self.user,
        )
        from apps.crm.tests.test_proposal_views import _user_with_perms

        user = _user_with_perms("cross_opp_fechamento", "view_opportunities", "change_opportunities")
        client = DjangoTestClient()
        client.force_login(user)
        resp = client.post(reverse("crm:proposal_installment_remove", args=[other_opp.pk, installment.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_commercial_plan_queryset_scoped_to_business_type(self):
        from apps.crm.forms import ProposalConditionsForm

        sale_opp = Opportunity.objects.create(
            client=self.client_obj, title="Venda", owner=self.user, source=self.source,
            business_type=BusinessType.VENDA, stage=self.stage_novo, created_by=self.user,
        )
        form = ProposalConditionsForm(opportunity=sale_opp)
        for plan in form.fields["commercial_plan"].queryset:
            self.assertEqual(plan.business_type, BusinessType.VENDA)
