"""
RODADA 3 DE REFINAMENTOS DO HUB DA OPORTUNIDADE (14/09/2026) — seção
30-51: botão final "GERAR ORÇAMENTO" (nunca "Gerar documento" genérico),
bloco "Documento" movido para o FIM da página (depois de condições,
período/logística, produtos, resumo financeiro, informações
complementares), download automático do PDF após gerar, e a regra crítica
repetida: gerar orçamento NUNCA marca a oportunidade como ganha — só o
botão "Orçamento aceito" no topo faz isso.

CORREÇÃO (15/09/2026): confirmado que o rótulo ESPECÍFICO por tipo de
documento ("Gerar orçamento"/"Gerar contrato"/"Gerar proposta +
contrato", nunca o genérico "Gerar documento") permanece exatamente como
na RODADA 3 — a relabelagem dinâmica via JS não foi tocada; esta rodada
só reordenou os blocos ao redor (ver `templates/crm/_proposal_composition.html`).
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client as DjangoTestClient
from django.test import TestCase
from django.urls import reverse

from apps.attachments.models import AttachmentCategory
from apps.attachments.services import attachments_for
from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.crm.models import BusinessType, CommercialSource, Opportunity, OpportunityStage
from apps.crm.services import ProposalItemData, add_proposal_item, generate_documents, get_or_create_active_proposal

User = get_user_model()


def _user_with_perms(username, *codenames):
    user = User.objects.create_user(username=username, password="senha-forte-123")
    if codenames:
        perms = Permission.objects.filter(codename__in=codenames, content_type__app_label="crm")
        group, _ = Group.objects.get_or_create(name=f"perm-{username}")
        group.permissions.set(perms)
        user.groups.add(group)
    return user


class GenerateOrcamentoFlowTestBase(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(company_name="Cliente Orçamento")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho", order=2, is_won=True)
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(code="NI23TC", name="NI23 Big Tank", category=self.category)

        self.owner = _user_with_perms(
            "owner_orcamento", "add_opportunities", "view_opportunities", "change_opportunities", "issue_proposal_documents"
        )
        self.opportunity = Opportunity.objects.create(
            client=self.client_obj, title="Oportunidade Orçamento", owner=self.owner, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage_novo, created_by=self.owner,
        )
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        add_proposal_item(
            proposal_version=proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("500.00")),
        )
        self.proposal = proposal

    def _login(self, user):
        client = DjangoTestClient()
        client.force_login(user)
        return client


class ButtonNamingAndPositionTest(GenerateOrcamentoFlowTestBase):
    def test_button_default_label_is_gerar_orcamento_not_generic(self):
        client = self._login(self.owner)
        resp = client.get(f"/crm/oportunidades/{self.opportunity.pk}/")
        self.assertContains(resp, "Gerar orçamento")
        self.assertNotContains(resp, "Gerar documento")

    def test_documento_block_appears_after_informacoes_complementares_and_produtos(self):
        client = self._login(self.owner)
        resp = client.get(f"/crm/oportunidades/{self.opportunity.pk}/")
        content = resp.content.decode()
        self.assertIn("id_document_type", content)
        # Busca pelos `<h3>` reais dos blocos (nunca por texto solto —
        # evitaria falsos positivos vindos de comentários CSS/JS
        # embutidos em `_design_tokens.html`, que também mencionam esses
        # nomes de bloco em prosa).
        pos_produtos = content.index('Produtos / Serviços</h3>')
        pos_info_complementares = content.index('Informações complementares</h3>')
        pos_documento = content.index("id_document_type")
        self.assertLess(pos_produtos, pos_info_complementares)
        self.assertLess(pos_info_complementares, pos_documento)

    def test_document_button_is_right_aligned(self):
        client = self._login(self.owner)
        resp = client.get(f"/crm/oportunidades/{self.opportunity.pk}/")
        self.assertContains(resp, 'data-document-generation-submit')
        self.assertContains(resp, "ml-auto")


class GenerateDoesNotWinOpportunityTest(GenerateOrcamentoFlowTestBase):
    def test_generating_proposta_never_marks_opportunity_as_won(self):
        client = self._login(self.owner)
        resp = client.post(
            reverse("crm:proposal_generate_document", args=[self.opportunity.pk]).split("?")[0],
            {"document_type": "PROPOSTA"},
        )
        self.assertEqual(resp.status_code, 302)
        self.opportunity.refresh_from_db()
        self.assertIsNone(self.opportunity.won_at)
        self.assertEqual(self.opportunity.stage, self.stage_novo)

    def test_generating_does_not_create_stage_change_history(self):
        before_count = self.opportunity.stage_changes.count()
        client = self._login(self.owner)
        client.post(reverse("crm:proposal_generate_document", args=[self.opportunity.pk]), {"document_type": "PROPOSTA"})
        self.assertEqual(self.opportunity.stage_changes.count(), before_count)


class AutoDownloadTest(GenerateOrcamentoFlowTestBase):
    def test_generating_redirects_with_download_query_param(self):
        client = self._login(self.owner)
        resp = client.post(
            reverse("crm:proposal_generate_document", args=[self.opportunity.pk]), {"document_type": "PROPOSTA"}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("baixar_pdf=", resp.url)

    def test_redirect_target_triggers_auto_download_link_in_page(self):
        client = self._login(self.owner)
        post_resp = client.post(
            reverse("crm:proposal_generate_document", args=[self.opportunity.pk]), {"document_type": "PROPOSTA"}
        )
        detail_resp = client.get(post_resp.url)
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, 'id="opp-auto-download-link"')
        attachment = attachments_for(self.opportunity).filter(category=AttachmentCategory.ORCAMENTO_PROPOSTA).first()
        expected_url = reverse("crm:attachment_download", args=[self.opportunity.pk, attachment.pk])
        self.assertContains(detail_resp, expected_url)

    def test_arbitrary_attachment_id_from_another_opportunity_is_ignored(self):
        """IDOR: um `baixar_pdf` forjado apontando para Anexo de OUTRA Opportunity nunca vira link de download."""
        other_owner = _user_with_perms("outro_dono", "add_opportunities", "view_opportunities", "change_opportunities", "issue_proposal_documents")
        other_opportunity = Opportunity.objects.create(
            client=self.client_obj, title="Outra Oportunidade", owner=other_owner, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage_novo, created_by=other_owner,
        )
        other_proposal = get_or_create_active_proposal(opportunity=other_opportunity, created_by=other_owner)
        add_proposal_item(
            proposal_version=other_proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("10.00")),
        )
        generate_documents(proposal_version=other_proposal.latest_version, document_type="PROPOSTA", actor=other_owner)
        other_attachment = attachments_for(other_opportunity).filter(category=AttachmentCategory.ORCAMENTO_PROPOSTA).first()

        client = self._login(self.owner)
        resp = client.get(f"/crm/oportunidades/{self.opportunity.pk}/?baixar_pdf={other_attachment.pk}")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'id="opp-auto-download-link"')


class NoDuplicatePdfGenerationTest(GenerateOrcamentoFlowTestBase):
    def test_generating_twice_on_already_issued_version_does_not_duplicate_pdf(self):
        version = self.proposal.latest_version
        generate_documents(proposal_version=version, document_type="PROPOSTA", actor=self.owner)
        first_count = attachments_for(self.opportunity).filter(category=AttachmentCategory.ORCAMENTO_PROPOSTA).count()
        self.assertEqual(first_count, 1)

        version.refresh_from_db()
        result = generate_documents(proposal_version=version, document_type="PROPOSTA", actor=self.owner)
        second_count = attachments_for(self.opportunity).filter(category=AttachmentCategory.ORCAMENTO_PROPOSTA).count()
        self.assertEqual(second_count, 1)  # nenhum PDF duplicado — reaproveita o já existente
        self.assertIsNotNone(result["download_attachment"])
