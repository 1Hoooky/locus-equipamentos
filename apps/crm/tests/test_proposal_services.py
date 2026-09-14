"""
Testes de `apps.crm.services` — Produtos e Serviços/Proposta Comercial +
Contrato (14/09/2026). Cobre as regras críticas das seções 90-98 da
especificação: ordem de cálculo/Decimal/desconto/juros/frete/total
(seção 90), snapshots (seção 91), retirada operacional não altera preço
(seção 92 — cobertura conceitual: nada nesta implementação lê data de
retirada real para recalcular preço), emissão/imutabilidade (seção 93),
versionamento (seção 94), contrato (seção 95), aceite (seção 96) e
estoque somente-leitura (seção 97). A matriz de permissões HTTP fica em
`test_proposal_views.py`.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.attachments.models import AttachmentCategory
from apps.attachments.services import attachments_for
from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.core.models import Address
from apps.crm.models import (
    BusinessType,
    CommercialSource,
    Opportunity,
    OpportunityStage,
    ProposalVersionStatus,
)
from apps.crm.services import (
    DocumentType,
    ProposalConditionsData,
    ProposalItemData,
    accept_proposal_version,
    acceptable_proposal_versions,
    add_proposal_item,
    calculate_proposal_version,
    check_availability,
    create_new_version,
    generate_contract,
    generate_documents,
    get_or_create_active_proposal,
    issue_proposal,
    remove_proposal_item,
    update_draft_conditions,
    update_proposal_item,
)
from apps.equipment.models import Condition, Equipment, Status

User = get_user_model()


class ProposalServiceTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="vendedor", password="x")
        self.address = Address.objects.create(logradouro="Rua A", numero="10", bairro="Centro", cidade="SP", uf="SP", cep="01000-000")
        self.client_obj = Client.objects.create(
            company_name="Cliente LTDA", document="12345678000199", fiscal_address=self.address, contact_name="Fulano"
        )
        self.source = CommercialSource.objects.create(name="Site")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho", order=2, is_won=True)
        self.opportunity = Opportunity.objects.create(
            client=self.client_obj,
            title="Evento Teste",
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


class CreateProposalTest(ProposalServiceTestBase):
    def test_get_or_create_active_proposal_creates_first_draft_version(self):
        proposal, version = self._proposal_and_version()
        self.assertTrue(proposal.number.startswith("PROP-"))
        self.assertEqual(version.version_number, 1)
        self.assertEqual(version.status, ProposalVersionStatus.DRAFT)

    def test_get_or_create_active_proposal_is_idempotent(self):
        proposal1, _ = self._proposal_and_version()
        proposal2, _ = self._proposal_and_version()
        self.assertEqual(proposal1.pk, proposal2.pk)

    def test_numbering_is_sequential_and_unique(self):
        proposal1, _ = self._proposal_and_version()
        opportunity2 = Opportunity.objects.create(
            client=self.client_obj, title="Outra", owner=self.user, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage_novo, created_by=self.user,
        )
        proposal2 = get_or_create_active_proposal(opportunity=opportunity2, created_by=self.user)
        self.assertNotEqual(proposal1.number, proposal2.number)


class ProposalItemCompositionTest(ProposalServiceTestBase):
    def test_add_item_calculates_line_total_and_subtotal(self):
        _, version = self._proposal_and_version()
        add_proposal_item(
            proposal_version=version,
            data=ProposalItemData(equipment_model=self.model, quantity=9, unit_price=Decimal("2600.00")),
        )
        version.refresh_from_db()
        self.assertEqual(version.subtotal, Decimal("23400.00"))
        self.assertEqual(version.total, Decimal("23400.00"))

    def test_item_discount_percent_applied_before_subtotal(self):
        _, version = self._proposal_and_version()
        add_proposal_item(
            proposal_version=version,
            data=ProposalItemData(equipment_model=self.model, quantity=4, unit_price=Decimal("1000.00"), item_discount_percent=Decimal("10")),
        )
        version.refresh_from_db()
        # 4 * 1000 = 4000 bruto; 10% desconto = 3600 líquido (seção 22).
        self.assertEqual(version.subtotal, Decimal("3600.00"))

    def test_multiple_items_sum_into_subtotal(self):
        _, version = self._proposal_and_version()
        model2 = EquipmentModel.objects.create(code="6PRO", name="6 PRO", category=self.category)
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=2, unit_price=Decimal("100.00")))
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=model2, quantity=3, unit_price=Decimal("50.00")))
        version.refresh_from_db()
        self.assertEqual(version.subtotal, Decimal("350.00"))
        self.assertEqual(version.items.count(), 2)

    def test_remove_item_recalculates_subtotal(self):
        _, version = self._proposal_and_version()
        item = add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100.00")))
        remove_proposal_item(item=item)
        version.refresh_from_db()
        self.assertEqual(version.items.count(), 0)
        self.assertEqual(version.subtotal, Decimal("0.00"))

    def test_update_item_recalculates(self):
        _, version = self._proposal_and_version()
        item = add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100.00")))
        update_proposal_item(item=item, data=ProposalItemData(equipment_model=self.model, quantity=3, unit_price=Decimal("100.00")))
        version.refresh_from_db()
        self.assertEqual(version.subtotal, Decimal("300.00"))

    def test_quantity_zero_rejected(self):
        _, version = self._proposal_and_version()
        with self.assertRaises(ValueError):
            add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=0, unit_price=Decimal("100.00")))

    def test_negative_unit_price_rejected(self):
        _, version = self._proposal_and_version()
        with self.assertRaises(ValueError):
            add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("-1")))

    def test_discount_out_of_range_rejected(self):
        _, version = self._proposal_and_version()
        with self.assertRaises(ValueError):
            add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("10"), item_discount_percent=Decimal("101")))

    def test_line_total_is_decimal(self):
        _, version = self._proposal_and_version()
        item = add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("10.10")))
        self.assertIsInstance(item.line_total, Decimal)

    def test_item_description_snapshot_survives_catalog_rename(self):
        _, version = self._proposal_and_version()
        item = add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("10")))
        original_description = item.description_snapshot
        self.model.name = "Nome Renomeado"
        self.model.save()
        item.refresh_from_db()
        self.assertEqual(item.description_snapshot, original_description)
        self.assertNotIn("Renomeado", item.description_snapshot)


class ProposalCalculationOrderTest(ProposalServiceTestBase):
    def test_general_discount_interest_freight_order(self):
        _, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("1000.00")))
        update_draft_conditions(
            proposal_version=version,
            data=ProposalConditionsData(general_discount=Decimal("100.00"), interest_amount=Decimal("50.00"), freight_amount=Decimal("30.00")),
        )
        version.refresh_from_db()
        # subtotal 1000 - desconto 100 + juros 50 + frete 30 = 980 (seção 24).
        self.assertEqual(version.subtotal, Decimal("1000.00"))
        self.assertEqual(version.total, Decimal("980.00"))

    def test_total_never_negative_raises(self):
        _, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100.00")))
        with self.assertRaises(ValueError):
            update_draft_conditions(proposal_version=version, data=ProposalConditionsData(general_discount=Decimal("500.00")))

    def test_negative_general_discount_rejected(self):
        _, version = self._proposal_and_version()
        with self.assertRaises(ValueError):
            update_draft_conditions(proposal_version=version, data=ProposalConditionsData(general_discount=Decimal("-1")))


class DraftEditabilityTest(ProposalServiceTestBase):
    def test_saving_draft_does_not_issue(self):
        _, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("10")))
        update_draft_conditions(proposal_version=version, data=ProposalConditionsData(general_notes="rascunho"))
        version.refresh_from_db()
        self.assertEqual(version.status, ProposalVersionStatus.DRAFT)
        self.assertIsNone(version.issued_at)

    def test_client_and_location_fields_persisted(self):
        _, version = self._proposal_and_version()
        from apps.operations.models import Location, LocationType

        location = Location.objects.create(name="Depósito", type=LocationType.ESTOQUE)
        update_draft_conditions(
            proposal_version=version,
            data=ProposalConditionsData(payment_condition="28 dias", delivery_location=location, general_notes="obs"),
        )
        version.refresh_from_db()
        self.assertEqual(version.payment_condition, "28 dias")
        self.assertEqual(version.delivery_location_id, location.pk)


class IssueProposalTest(ProposalServiceTestBase):
    def _issue_with_one_item(self):
        _, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("500")))
        issue_proposal(proposal_version=version, issued_by=self.user)
        version.refresh_from_db()
        return version

    def test_cannot_issue_without_items(self):
        _, version = self._proposal_and_version()
        with self.assertRaises(ValueError):
            issue_proposal(proposal_version=version, issued_by=self.user)

    def test_issue_freezes_version_and_sets_metadata(self):
        version = self._issue_with_one_item()
        self.assertEqual(version.status, ProposalVersionStatus.ISSUED)
        self.assertIsNotNone(version.issued_at)
        self.assertEqual(version.issued_by, self.user)

    def test_issue_snapshots_client_and_company(self):
        version = self._issue_with_one_item()
        self.assertEqual(version.client_name_snapshot, self.client_obj.display_name())
        self.assertEqual(version.client_document_snapshot, self.client_obj.document)
        self.assertEqual(version.seller_snapshot, str(self.opportunity.owner))

    def test_issue_creates_attachment(self):
        version = self._issue_with_one_item()
        attachments = list(attachments_for(self.opportunity))
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].category, AttachmentCategory.ORCAMENTO_PROPOSTA)

    def test_issued_version_is_immutable_to_item_changes(self):
        version = self._issue_with_one_item()
        with self.assertRaises(ValueError):
            add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("1")))

    def test_issued_version_is_immutable_to_condition_changes(self):
        version = self._issue_with_one_item()
        with self.assertRaises(ValueError):
            update_draft_conditions(proposal_version=version, data=ProposalConditionsData(general_notes="tentativa de editar"))

    def test_catalog_rename_after_issue_does_not_change_snapshot(self):
        version = self._issue_with_one_item()
        company_snapshot_before = version.company_name_snapshot
        from apps.core.services import CompanyProfileData, update_company_profile

        update_company_profile(CompanyProfileData(company_name="Nome Novo da Empresa"))
        version.refresh_from_db()
        self.assertEqual(version.company_name_snapshot, company_snapshot_before)


class VersioningTest(ProposalServiceTestBase):
    def test_cannot_create_new_version_while_draft_exists(self):
        proposal, version = self._proposal_and_version()
        with self.assertRaises(ValueError):
            create_new_version(proposal=proposal, created_by=self.user)

    def test_new_version_clones_items_and_conditions(self):
        proposal, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=2, unit_price=Decimal("100")))
        update_draft_conditions(proposal_version=version, data=ProposalConditionsData(payment_condition="À vista"))
        issue_proposal(proposal_version=version, issued_by=self.user)

        v2 = create_new_version(proposal=proposal, created_by=self.user)
        self.assertEqual(v2.version_number, 2)
        self.assertEqual(v2.status, ProposalVersionStatus.DRAFT)
        self.assertEqual(v2.items.count(), 1)
        self.assertEqual(v2.payment_condition, "À vista")

    def test_previous_version_preserved_after_new_version(self):
        proposal, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100")))
        issue_proposal(proposal_version=version, issued_by=self.user)
        v1_total = version.total

        create_new_version(proposal=proposal, created_by=self.user)
        version.refresh_from_db()
        self.assertEqual(version.status, ProposalVersionStatus.ISSUED)
        self.assertEqual(version.total, v1_total)

    def test_editing_v2_never_touches_v1_snapshot(self):
        proposal, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100")))
        issue_proposal(proposal_version=version, issued_by=self.user)
        v1_client_snapshot = version.client_name_snapshot

        v2 = create_new_version(proposal=proposal, created_by=self.user)
        update_draft_conditions(proposal_version=v2, data=ProposalConditionsData(general_notes="v2 only"))
        version.refresh_from_db()
        self.assertEqual(version.client_name_snapshot, v1_client_snapshot)
        self.assertEqual(version.general_notes, "")


class ContractTest(ProposalServiceTestBase):
    def _draft_with_item(self):
        _, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100")))
        return version

    def test_cannot_generate_contract_from_draft(self):
        version = self._draft_with_item()
        with self.assertRaises(ValueError):
            generate_contract(proposal_version=version, created_by=self.user)

    def test_generate_contract_from_issued_version(self):
        version = self._draft_with_item()
        issue_proposal(proposal_version=version, issued_by=self.user)
        contract = generate_contract(proposal_version=version, created_by=self.user)
        self.assertTrue(contract.number.startswith("CONTR-"))
        self.assertTrue(contract.legal_text_is_placeholder)

    def test_proposta_e_contrato_creates_two_distinct_documents(self):
        version = self._draft_with_item()
        result = generate_documents(proposal_version=version, document_type=DocumentType.PROPOSTA_E_CONTRATO, actor=self.user)
        version.refresh_from_db()
        self.assertEqual(version.status, ProposalVersionStatus.ISSUED)
        self.assertIn("contract", result)
        attachments = {a.category for a in attachments_for(self.opportunity)}
        self.assertEqual(attachments, {AttachmentCategory.ORCAMENTO_PROPOSTA, AttachmentCategory.CONTRATO})

    def test_generate_contract_does_not_accept_proposal(self):
        version = self._draft_with_item()
        issue_proposal(proposal_version=version, issued_by=self.user)
        generate_contract(proposal_version=version, created_by=self.user)
        version.refresh_from_db()
        self.opportunity.refresh_from_db()
        self.assertEqual(version.status, ProposalVersionStatus.ISSUED)
        self.assertFalse(self.opportunity.stage.is_won)

    def test_contract_snapshot_matches_version(self):
        version = self._draft_with_item()
        issue_proposal(proposal_version=version, issued_by=self.user)
        contract = generate_contract(proposal_version=version, created_by=self.user)
        self.assertEqual(contract.proposal_version_id, version.pk)


class AcceptTest(ProposalServiceTestBase):
    def _issued_version(self):
        _, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=2, unit_price=Decimal("500")))
        issue_proposal(proposal_version=version, issued_by=self.user)
        version.refresh_from_db()
        return version

    def test_only_issued_version_acceptable(self):
        _, draft_version = self._proposal_and_version()
        with self.assertRaises(ValueError):
            accept_proposal_version(proposal_version=draft_version, accepted_by=self.user, won_stage=self.stage_ganho)

    def test_accept_sets_accepted_fields(self):
        version = self._issued_version()
        accept_proposal_version(proposal_version=version, accepted_by=self.user, won_stage=self.stage_ganho)
        version.refresh_from_db()
        self.assertEqual(version.status, ProposalVersionStatus.ACCEPTED)
        self.assertIsNotNone(version.accepted_at)
        self.assertEqual(version.accepted_by, self.user)

    def test_accept_marks_opportunity_won_via_change_stage(self):
        version = self._issued_version()
        accept_proposal_version(proposal_version=version, accepted_by=self.user, won_stage=self.stage_ganho)
        self.opportunity.refresh_from_db()
        self.assertTrue(self.opportunity.stage.is_won)
        self.assertIsNotNone(self.opportunity.won_at)

    def test_accept_sets_closed_value_from_version_total(self):
        version = self._issued_version()
        accept_proposal_version(proposal_version=version, accepted_by=self.user, won_stage=self.stage_ganho)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.closed_value, version.total)

    def test_creates_opportunity_stage_change_entry(self):
        from apps.crm.models import OpportunityStageChange

        version = self._issued_version()
        before = OpportunityStageChange.objects.filter(opportunity=self.opportunity).count()
        accept_proposal_version(proposal_version=version, accepted_by=self.user, won_stage=self.stage_ganho)
        after = OpportunityStageChange.objects.filter(opportunity=self.opportunity).count()
        self.assertEqual(after, before + 1)

    def test_double_accept_rejected(self):
        version = self._issued_version()
        accept_proposal_version(proposal_version=version, accepted_by=self.user, won_stage=self.stage_ganho)
        with self.assertRaises(ValueError):
            accept_proposal_version(proposal_version=version, accepted_by=self.user, won_stage=self.stage_ganho)

    def test_acceptable_versions_excludes_draft_and_already_accepted(self):
        version = self._issued_version()
        self.assertIn(version, list(acceptable_proposal_versions(self.opportunity)))
        accept_proposal_version(proposal_version=version, accepted_by=self.user, won_stage=self.stage_ganho)
        self.assertNotIn(version, list(acceptable_proposal_versions(self.opportunity)))


class AvailabilityTest(ProposalServiceTestBase):
    def test_availability_counts_only_active_available_equipment(self):
        Equipment.objects.create(
            patrimonio="LOC-NI23TC-0001", model=self.model, model_sequence=1, category=self.category,
            status=Status.DISPONIVEL, condition=Condition.BOM, created_by=self.user,
        )
        Equipment.objects.create(
            patrimonio="LOC-NI23TC-0002", model=self.model, model_sequence=2, category=self.category,
            status=Status.EM_OPERACAO, condition=Condition.BOM, created_by=self.user,
        )
        Equipment.objects.create(
            patrimonio="LOC-NI23TC-0003", model=self.model, model_sequence=3, category=self.category,
            status=Status.DISPONIVEL, condition=Condition.BOM, created_by=self.user, is_active=False,
        )
        result = check_availability(equipment_model=self.model, requested_quantity=5)
        self.assertEqual(result.available, 1)
        self.assertEqual(result.missing, 4)

    def test_availability_check_creates_no_movement_or_reservation(self):
        from apps.operations.models import Movement

        check_availability(equipment_model=self.model, requested_quantity=1)
        self.assertEqual(Movement.objects.count(), 0)

    def test_availability_does_not_touch_proposal_item(self):
        # Consultar disponibilidade nunca seleciona patrimônio na proposta
        # (seção 10/12, REGRA CRÍTICA) — não existe nenhum campo de
        # patrimônio em ProposalItem para começo de conversa; este teste
        # documenta a garantia estrutural.
        from apps.crm.models import ProposalItem

        self.assertNotIn("equipment", [f.name for f in ProposalItem._meta.get_fields()])
        self.assertNotIn("patrimonio", [f.name for f in ProposalItem._meta.get_fields()])
