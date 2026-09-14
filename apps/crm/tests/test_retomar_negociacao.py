"""
RODADA 3 DE REFINAMENTOS DO HUB DA OPORTUNIDADE (14/09/2026) — seção 52-59:
"RETOMAR NEGOCIAÇÃO", nova ação visível SOMENTE em oportunidades já GANHAS,
que reabre a negociação sem apagar histórico algum.

Decisão de arquitetura (documentada nos comentários de
`OpportunityDetailView.get()`/`opportunity_detail.html`): NENHUM serviço
novo foi criado. A ação reusa 100% o MESMO endpoint/form/service já
existente (`crm:opportunity_change_stage` → `OpportunityStageChangeForm` →
`change_opportunity_stage()`), que já limpa `won_at`/`lost_at`/
`loss_reason`/`loss_notes`/`closed_value` ao mover para uma etapa
intermediária — o mesmo comportamento que qualquer correção manual de
etapa já tinha antes desta rodada. O que é genuinamente novo aqui é só a
UI (botão + modal condicionados a `can_show_retomar_negociacao`/
`open_stages`) e a garantia de que nada relacionado a Propostas/Contratos/
Anexos é apagado ou revertido no processo.

Convenções desta suíte (mesmas de `test_opportunity_detail_redesign.py`):
`_user_with_perms` para montar um usuário com um subconjunto exato de
Permission do app `crm`; a permissão que controla a visibilidade/POST é
`crm.change_opportunity_stage` (confirmado em
`OpportunityDetailView.get()`).
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client as DjangoTestClient
from django.test import TestCase
from django.utils import timezone

from apps.clients.models import Client
from apps.crm.models import (
    BusinessType,
    CommercialSource,
    Opportunity,
    OpportunityStage,
    ProposalVersionStatus,
)
from apps.crm.services import (
    NewOpportunityData,
    ProposalItemData,
    accept_proposal_version,
    add_proposal_item,
    create_opportunity,
    generate_documents,
    get_or_create_active_proposal,
)
from apps.catalog.models import Category, EquipmentModel

User = get_user_model()


def _user_with_perms(username, *codenames):
    user = User.objects.create_user(username=username, password="senha-forte-123")
    if codenames:
        perms = Permission.objects.filter(codename__in=codenames, content_type__app_label="crm")
        group, _ = Group.objects.get_or_create(name=f"perm-{username}")
        group.permissions.set(perms)
        user.groups.add(group)
    return user


class RetomarNegociacaoTestBase(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(company_name="Cliente Retomar Negociação")
        self.source = CommercialSource.objects.create(name="Indicação")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_qualificacao = OpportunityStage.objects.create(name="Qualificação", order=2)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho", order=3, is_won=True)
        self.stage_perdido = OpportunityStage.objects.create(name="Perdido", order=4, is_lost=True)

        self.creator = _user_with_perms("criador_retomar", "add_opportunities")
        self.opportunity = create_opportunity(
            NewOpportunityData(
                client=self.client_obj,
                title="Oportunidade a retomar",
                owner=self.creator,
                source=self.source,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.creator,
            )
        )
        self.detail_url = f"/crm/oportunidades/{self.opportunity.pk}/"
        self.stage_url = f"/crm/oportunidades/{self.opportunity.pk}/etapa/"

    def _viewer(self, username, *extra_codenames):
        return _user_with_perms(username, "view_opportunities", *extra_codenames)

    def _mark_won(self, closed_value=Decimal("1000.00")):
        self.opportunity.stage = self.stage_ganho
        self.opportunity.won_at = timezone.now()
        self.opportunity.closed_value = closed_value
        self.opportunity.save(update_fields=["stage", "won_at", "closed_value"])


# 1/2. Visibilidade do botão/modal --------------------------------------------


class ButtonVisibilityTest(RetomarNegociacaoTestBase):
    def test_button_hidden_when_opportunity_is_not_won(self):
        actor = self._viewer("nao_ganho_retomar", "change_opportunity_stage")
        self.client.force_login(actor)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"Retomar neg", resp.content)
        self.assertNotIn(b'id="opp-retomar-negociacao-modal"', resp.content)

    def test_button_hidden_without_change_stage_permission_even_if_won(self):
        actor = self._viewer("sem_permissao_retomar")  # só view_opportunities
        self._mark_won()
        self.client.force_login(actor)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"Retomar neg", resp.content)
        self.assertNotIn(b'id="opp-retomar-negociacao-modal"', resp.content)

    def test_button_and_modal_visible_when_won_and_permitted(self):
        actor = self._viewer("ganho_com_permissao", "change_opportunity_stage")
        self._mark_won()
        self.client.force_login(actor)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Retomar negociação".encode(), resp.content)
        self.assertIn(b'id="opp-retomar-negociacao-modal"', resp.content)

    def test_button_hidden_when_no_open_stage_exists(self):
        """
        Se TODAS as etapas ativas forem ganho/perda (nenhuma etapa
        "aberta" candidata), a ação não pode aparecer — não há para onde
        reabrir sem inventar uma etapa.
        """
        self.stage_novo.is_active = False
        self.stage_novo.save(update_fields=["is_active"])
        self.stage_qualificacao.is_active = False
        self.stage_qualificacao.save(update_fields=["is_active"])

        actor = self._viewer("sem_etapa_aberta", "change_opportunity_stage")
        self._mark_won()
        self.client.force_login(actor)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"Retomar neg", resp.content)
        self.assertNotIn(b'id="opp-retomar-negociacao-modal"', resp.content)


# 3. `open_stages` com uma única candidata -> campo oculto, sem <select> -----


class OpenStagesSingleCandidateTest(RetomarNegociacaoTestBase):
    def test_single_open_stage_renders_hidden_field_not_select(self):
        self.stage_qualificacao.is_active = False
        self.stage_qualificacao.save(update_fields=["is_active"])  # só "Novo" fica aberta

        actor = self._viewer("uma_etapa_aberta", "change_opportunity_stage")
        self._mark_won()
        self.client.force_login(actor)
        resp = self.client.get(self.detail_url)
        content = resp.content.decode()
        self.assertIn(f'name="stage" value="{self.stage_novo.pk}"', content)
        self.assertNotIn('id="opp-retomar-negociacao-modal-stage"', content)


class OpenStagesMultipleCandidatesTest(RetomarNegociacaoTestBase):
    def test_multiple_open_stages_render_select(self):
        actor = self._viewer("varias_etapas_abertas", "change_opportunity_stage")
        self._mark_won()
        self.client.force_login(actor)
        resp = self.client.get(self.detail_url)
        content = resp.content.decode()
        self.assertIn('id="opp-retomar-negociacao-modal-stage"', content)
        self.assertIn(f'value="{self.stage_novo.pk}"', content)
        self.assertIn(f'value="{self.stage_qualificacao.pk}"', content)


# 4/5. POST reabre e preserva histórico ----------------------------------------


class ReopenFlowTest(RetomarNegociacaoTestBase):
    def test_reopen_moves_to_open_stage_and_clears_won_fields(self):
        actor = self._viewer("reabrir_fluxo", "change_opportunity_stage")
        self._mark_won(closed_value=Decimal("2500.00"))
        self.client.force_login(actor)

        resp = self.client.post(
            self.stage_url,
            {"stage": self.stage_novo.pk, "reason": "Negociação retomada."},
        )
        self.assertEqual(resp.status_code, 302)

        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_novo)
        self.assertIsNone(self.opportunity.won_at)
        self.assertIsNone(self.opportunity.lost_at)
        self.assertIsNone(self.opportunity.loss_reason)
        self.assertEqual(self.opportunity.loss_notes, "")
        self.assertIsNone(self.opportunity.closed_value)

    def test_reopen_records_stage_change_history_with_reason(self):
        actor = self._viewer("reabrir_historico", "change_opportunity_stage")
        self._mark_won()
        self.client.force_login(actor)

        before_count = self.opportunity.stage_changes.count()
        self.client.post(
            self.stage_url,
            {"stage": self.stage_qualificacao.pk, "reason": "Negociação retomada."},
        )
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage_changes.count(), before_count + 1)

        change = self.opportunity.stage_changes.order_by("-changed_at").first()
        self.assertEqual(change.from_stage, self.stage_ganho)
        self.assertEqual(change.to_stage, self.stage_qualificacao)
        self.assertEqual(change.reason, "Negociação retomada.")

    def test_reopen_without_permission_is_blocked_and_nothing_changes(self):
        user = self._viewer("sem_permissao_post_retomar")  # só view_opportunities
        self._mark_won()
        self.client.force_login(user)
        resp = self.client.post(
            self.stage_url,
            {"stage": self.stage_novo.pk, "reason": "Negociação retomada."},
        )
        self.assertEqual(resp.status_code, 403)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_ganho)
        self.assertIsNotNone(self.opportunity.won_at)


# 6. GET nunca muta -------------------------------------------------------------


class GetNeverMutatesTest(RetomarNegociacaoTestBase):
    def test_get_detail_page_never_changes_stage(self):
        actor = self._viewer("get_nao_muta_retomar", "change_opportunity_stage")
        self._mark_won()
        self.client.force_login(actor)
        self.client.get(self.detail_url)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_ganho)
        self.assertIsNotNone(self.opportunity.won_at)


# 7. Nada relacionado a Propostas/Contratos é apagado ou revertido -------------


class ProposalAndDocumentsPreservedOnReopenTest(TestCase):
    """
    Reabrir uma negociação NUNCA apaga histórico: a versão de proposta que
    foi aceita (com seu `status=ACCEPTED`/`accepted_at`/`accepted_by`) e os
    Anexos/PDFs já gerados continuam intactos — só a Opportunity muda de
    etapa. Uma NOVA rodada de negociação exige uma NOVA `ProposalVersion`
    (nova emissão + novo aceite); a versão antiga nunca é "reaproveitada"
    como se fosse a aceita de novo.
    """

    def setUp(self):
        self.client_obj = Client.objects.create(company_name="Cliente Preservação")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho", order=2, is_won=True)
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(code="NI23TC", name="NI23 Big Tank", category=self.category)

        self.owner = _user_with_perms(
            "dono_preservacao",
            "add_opportunities",
            "view_opportunities",
            "change_opportunity_stage",
            "issue_proposal_documents",
        )
        self.opportunity = Opportunity.objects.create(
            client=self.client_obj, title="Oportunidade Preservação", owner=self.owner, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage_novo, created_by=self.owner,
        )
        self.proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("500.00")),
        )
        generate_documents(proposal_version=self.proposal.latest_version, document_type="PROPOSTA", actor=self.owner)
        self.proposal.latest_version.refresh_from_db()
        self.accepted_version = accept_proposal_version(
            proposal_version=self.proposal.latest_version, accepted_by=self.owner, won_stage=self.stage_ganho
        )

    def _login(self, user):
        client = DjangoTestClient()
        client.force_login(user)
        return client

    def test_accepted_version_untouched_by_reopen(self):
        client = self._login(self.owner)
        resp = client.post(
            f"/crm/oportunidades/{self.opportunity.pk}/etapa/",
            {"stage": self.stage_novo.pk, "reason": "Negociação retomada."},
        )
        self.assertEqual(resp.status_code, 302)

        self.accepted_version.refresh_from_db()
        self.assertEqual(self.accepted_version.status, ProposalVersionStatus.ACCEPTED)
        self.assertIsNotNone(self.accepted_version.accepted_at)
        self.assertEqual(self.accepted_version.accepted_by, self.owner)

    def test_attachments_untouched_by_reopen(self):
        from apps.attachments.services import attachments_for

        before = set(attachments_for(self.opportunity).values_list("pk", flat=True))
        self.assertTrue(before)  # o PDF do orçamento já foi gerado no setUp

        client = self._login(self.owner)
        client.post(
            f"/crm/oportunidades/{self.opportunity.pk}/etapa/",
            {"stage": self.stage_novo.pk, "reason": "Negociação retomada."},
        )
        after = set(attachments_for(self.opportunity).values_list("pk", flat=True))
        self.assertEqual(before, after)

    def test_no_new_proposal_version_created_merely_by_reopening(self):
        """
        Reabrir a negociação por si só NÃO cria uma nova `ProposalVersion`
        — uma nova rodada só existe quando o usuário explicitamente
        edita/gera uma nova versão depois (fluxo já coberto por outros
        testes de Produtos e Serviços).
        """
        before_count = self.proposal.versions.count()
        client = self._login(self.owner)
        client.post(
            f"/crm/oportunidades/{self.opportunity.pk}/etapa/",
            {"stage": self.stage_novo.pk, "reason": "Negociação retomada."},
        )
        after_count = self.proposal.versions.count()
        self.assertEqual(before_count, after_count)
