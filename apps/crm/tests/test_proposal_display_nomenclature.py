"""
RODADA 3 DE REFINAMENTOS DO HUB DA OPORTUNIDADE (14/09/2026) — seção
11-15: nomenclatura de EXIBIÇÃO da Proposta muda de "PROP-000002 v1" para
"PROPOSTA-000001" (e "PROPOSTA-000001 — Versão 2" quando já existe mais
de uma versão) — SEM alterar o `Proposal.number`/`ProposalVersion.
version_number` armazenados (identidade interna intocada, só a
apresentação muda: `Proposal.display_number`/`ProposalVersion.
display_label`).

Cobre: transformação pura do prefixo "PROP-" → "PROPOSTA-"; rótulo sem
sufixo de versão quando é a única (nunca "— Versão 1"); rótulo com
sufixo a partir da 2ª versão; nome de arquivo do PDF gerado
("PROPOSTA-000001.pdf"/"PROPOSTA-000001-V2.pdf"); descrição do Anexo;
descrição do Contrato; motivo registrado no histórico de etapa ao
aceitar; nunca perde/renomeia o PDF já emitido de uma versão anterior.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.attachments.services import attachments_for
from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.core.models import Address
from apps.crm.models import BusinessType, CommercialSource, Opportunity, OpportunityStage
from apps.crm.services import (
    ProposalItemData,
    accept_proposal_version,
    acceptable_proposal_versions,
    add_proposal_item,
    create_new_version,
    generate_contract,
    get_or_create_active_proposal,
    issue_proposal,
)

User = get_user_model()


class ProposalDisplayNomenclatureTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="vendedor_nomenclatura", password="x")
        self.address = Address.objects.create(logradouro="Rua A", numero="10", bairro="Centro", cidade="SP", uf="SP", cep="01000-000")
        self.client_obj = Client.objects.create(
            company_name="Cliente Nomenclatura LTDA", document="12345678000199", fiscal_address=self.address, contact_name="Fulano"
        )
        self.source = CommercialSource.objects.create(name="Site")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho", order=2, is_won=True)
        self.opportunity = Opportunity.objects.create(
            client=self.client_obj,
            title="Evento Nomenclatura",
            owner=self.user,
            source=self.source,
            business_type=BusinessType.LOCACAO,
            stage=self.stage_novo,
            created_by=self.user,
        )
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(code="NI23TC", name="NI23 Big Tank", category=self.category)

    def _proposal_and_version(self):
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.user)
        return proposal, proposal.latest_version

    def _issue_v1(self):
        proposal, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("500")))
        issue_proposal(proposal_version=version, issued_by=self.user)
        version.refresh_from_db()
        return proposal, version


class DisplayNumberTransformTest(ProposalDisplayNomenclatureTestBase):
    def test_display_number_replaces_prop_prefix_with_proposta(self):
        proposal, _ = self._proposal_and_version()
        self.assertTrue(proposal.number.startswith("PROP-"))
        expected_suffix = proposal.number[len("PROP-"):]
        self.assertEqual(proposal.display_number, f"PROPOSTA-{expected_suffix}")

    def test_stored_number_is_never_touched(self):
        """A identidade interna (`Proposal.number`, com prefixo "PROP-") nunca muda — só a apresentação."""
        proposal, _ = self._proposal_and_version()
        original_number = proposal.number
        _ = proposal.display_number
        proposal.refresh_from_db()
        self.assertEqual(proposal.number, original_number)
        self.assertTrue(proposal.number.startswith("PROP-"))

    def test_str_uses_display_number(self):
        proposal, _ = self._proposal_and_version()
        self.assertEqual(str(proposal), proposal.display_number)
        self.assertNotIn("PROP-", str(proposal))


class DisplayLabelVersionSuffixTest(ProposalDisplayNomenclatureTestBase):
    def test_single_version_has_no_version_suffix(self):
        proposal, version = self._issue_v1()
        self.assertEqual(version.display_label, proposal.display_number)
        self.assertNotIn("Versão", version.display_label)

    def test_second_version_shows_version_suffix(self):
        proposal, version = self._issue_v1()
        v2 = create_new_version(proposal=proposal, created_by=self.user)
        self.assertEqual(v2.display_label, f"{proposal.display_number} — Versão 2")

    def test_first_version_label_unaffected_by_a_later_second_version_existing(self):
        proposal, version = self._issue_v1()
        create_new_version(proposal=proposal, created_by=self.user)
        version.refresh_from_db()
        # v1 continua sem sufixo — só a versão 2+ ganha "— Versão N".
        self.assertEqual(version.display_label, proposal.display_number)

    def test_version_str_uses_display_label(self):
        proposal, version = self._issue_v1()
        self.assertEqual(str(version), version.display_label)


class GeneratedPdfFilenameTest(ProposalDisplayNomenclatureTestBase):
    def test_first_version_pdf_filename_has_no_version_suffix(self):
        proposal, version = self._issue_v1()
        attachments = list(attachments_for(self.opportunity))
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].original_filename, f"{proposal.display_number}.pdf")
        self.assertIn(proposal.display_number, attachments[0].description)
        self.assertNotIn("PROP-", attachments[0].original_filename)

    def test_second_version_pdf_filename_has_version_suffix_and_first_pdf_is_kept(self):
        proposal, version = self._issue_v1()
        v2 = create_new_version(proposal=proposal, created_by=self.user)
        add_proposal_item(proposal_version=v2, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("500")))
        issue_proposal(proposal_version=v2, issued_by=self.user)

        attachments = sorted(attachments_for(self.opportunity), key=lambda a: a.created_at)
        self.assertEqual(len(attachments), 2)  # o PDF da v1 nunca é apagado/substituído
        self.assertEqual(attachments[0].original_filename, f"{proposal.display_number}.pdf")
        self.assertEqual(attachments[1].original_filename, f"{proposal.display_number}-V2.pdf")


class ContractDescriptionTest(ProposalDisplayNomenclatureTestBase):
    def test_contract_description_uses_display_label_not_prop_prefix(self):
        proposal, version = self._issue_v1()
        contract = generate_contract(proposal_version=version, created_by=self.user)
        attachments = [a for a in attachments_for(self.opportunity) if a.category == "CONTRATO"]
        self.assertEqual(len(attachments), 1)
        self.assertIn(proposal.display_number, attachments[0].description)
        self.assertNotIn("PROP-", attachments[0].description)
        self.assertTrue(contract.number.startswith("CONTR-"))  # Contract.number continua fora de escopo desta rodada


class AcceptReasonTest(ProposalDisplayNomenclatureTestBase):
    def test_stage_change_reason_on_accept_uses_display_number(self):
        proposal, version = self._issue_v1()
        candidate = acceptable_proposal_versions(self.opportunity).first()
        accept_proposal_version(proposal_version=candidate, accepted_by=self.user, won_stage=self.stage_ganho)

        self.opportunity.refresh_from_db()
        last_change = self.opportunity.stage_changes.order_by("-changed_at").first()
        self.assertIn(proposal.display_number, last_change.reason)
        self.assertNotIn("PROP-", last_change.reason)
