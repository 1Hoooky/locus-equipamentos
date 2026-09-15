"""
Testes da RODADA 4 DE REFINAMENTOS — "Refinamento da composição comercial"
(15/09/2026) — cobre especificamente o que MUDOU nesta rodada em relação à
entrega anterior (a funcional já testada em test_proposal_services.py/
test_proposal_views.py/test_proposal_composition_refinamento.py continua
íntegra e não é duplicada aqui):

  35. Ausência de UI: bloco "Aceite" removido, "Criar nova versão"
      removido, texto explicativo do "Gerar orçamento" removido, sem
      lacuna vazia deixada para trás; prefixo duplicado "PROPOSTA
      PROPOSTA-..." corrigido; Resumo financeiro centralizado.
  36. Auto-versionamento preguiçoso: GET nunca cria versão nova; a
      PRIMEIRA alteração após emissão clona; a segunda alteração
      reaproveita o MESMO rascunho (nunca uma 3ª versão); a versão
      emitida/aceita original nunca é tocada.
  37. Remoção de item: rascunho remove direto; versão emitida
      auto-versiona e remove só na nova versão; modal de confirmação
      (não `confirm()` nativo) com o texto do mockup.
  38. Item de Serviço: suporte a `ServiceCatalogItem`, validação
      cruzada equipamento/serviço, snapshot congelado, participação no
      cálculo financeiro, cartão visual com badge "Serviço".
  39. Regressão de item de Equipamento: nada quebrou no caminho já
      testado (campo obrigatório, cartão "unidades", mesmo form).

Backend real de aceite (`accept_proposal_version()`), emissão
(`issue_proposal()`) e cálculo (`calculate_proposal_version()`) NUNCA são
reimplementados aqui — só exercitados através da nova camada de
auto-versionamento/itens de serviço.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.crm.forms import ServiceCatalogItemForm
from apps.crm.models import (
    BusinessType,
    CommercialSource,
    Opportunity,
    OpportunityStage,
    ProposalItem,
    ProposalItemType,
    ProposalVersionStatus,
    ServiceCatalogItem,
)
from apps.crm.services import (
    ProposalConditionsData,
    ProposalItemData,
    accept_proposal_version,
    add_proposal_item,
    ensure_editable_item,
    ensure_editable_version,
    get_or_create_active_proposal,
    issue_proposal,
    remove_proposal_item,
    update_draft_conditions,
    update_proposal_item,
)
from apps.crm.tests.test_proposal_views import ProposalViewsTestBase, _user_with_perms

User = get_user_model()


# ---------------------------------------------------------------------------
# 35a — Bloco "Aceite" removido inteiramente da tela.
# ---------------------------------------------------------------------------


class AceiteBlockRemovedTest(ProposalViewsTestBase):
    def setUp(self):
        super().setUp()
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        add_proposal_item(
            proposal_version=proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100")),
        )
        issue_proposal(proposal_version=proposal.latest_version, issued_by=self.owner)
        self.proposal = proposal

    def _get_body(self):
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_aceite_heading_and_button_absent(self):
        body = self._get_body()
        self.assertNotIn("ACEITE DE VERSÃO", body)
        self.assertNotIn("Aceitar versão", body)

    def test_accept_form_context_keys_absent(self):
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        self.assertNotIn("candidate_versions", resp.context)
        self.assertNotIn("accept_form", resp.context)

    def test_no_empty_gap_left_after_documento_block(self):
        """O bloco Documento continua sendo o ÚLTIMO — nada (nenhum bloco
        vazio remanescente do antigo Aceite) aparece depois dele. Precisa
        de um usuário com `issue_proposal_documents`/`generate_contract`
        para o bloco "Documento" (`document_form`) sequer ser exibido —
        `self.owner` (só `view`/`change`) não o vê, então este teste usa
        um usuário próprio com a permissão certa."""
        user = _user_with_perms("doc_block_r4", "view_opportunities", "change_opportunities", "issue_proposal_documents")
        client = self._login(user)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        body = resp.content.decode()
        documento_idx = body.index(" Documento</h3>")
        # A partir daí, só o form/script do próprio bloco Documento e o
        # fechamento da página — nenhum outro `.proposal-block` novo.
        remainder = body[documento_idx:]
        self.assertLessEqual(remainder.count('class="proposal-block"'), 1)

    def test_accept_backend_endpoint_still_exists_and_works(self):
        """Seção 2: o mecanismo real de aceite NÃO foi removido — só a UI
        dentro desta aba. O endpoint POST continua funcionando de ponta a
        ponta (é o mesmo botão "Orçamento aceito" do topo que o aciona)."""
        user = _user_with_perms("accepter_r4", "view_opportunities", "change_opportunity_stage")
        client = self._login(user)
        resp = client.post(
            reverse("crm:proposal_accept_version", args=[self.opportunity.pk]),
            {"proposal_version": self.proposal.latest_version.pk, "stage": self.stage_ganho.pk},
        )
        self.assertEqual(resp.status_code, 302)
        self.proposal.latest_version.refresh_from_db()
        self.assertEqual(self.proposal.latest_version.status, ProposalVersionStatus.ACCEPTED)


# ---------------------------------------------------------------------------
# 35b — "Criar nova versão" removido da UI (backend preservado).
# ---------------------------------------------------------------------------


class CriarNovaVersaoRemovedTest(ProposalViewsTestBase):
    def setUp(self):
        super().setUp()
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        add_proposal_item(
            proposal_version=proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100")),
        )
        issue_proposal(proposal_version=proposal.latest_version, issued_by=self.owner)
        self.proposal = proposal

    def test_button_text_absent(self):
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        self.assertNotContains(resp, "Criar nova versão")

    def test_url_no_longer_registered(self):
        with self.assertRaises(NoReverseMatch):
            reverse("crm:proposal_new_version", args=[self.opportunity.pk])

    def test_explanatory_text_removed(self):
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        self.assertNotContains(resp, "NÃO significa negócio ganho")


# ---------------------------------------------------------------------------
# 35c — Bug do prefixo duplicado "PROPOSTA PROPOSTA-..." + badge de status.
# ---------------------------------------------------------------------------


class DisplayLabelAndStatusBadgeTest(ProposalViewsTestBase):
    def setUp(self):
        super().setUp()
        self.proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100")),
        )

    def _get_body(self):
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        return resp.content.decode()

    def test_no_duplicated_prefix_for_draft(self):
        """Bug original (seção 33): o rótulo da composição comercial
        aparecia como "PROPOSTA PROPOSTA-000002" (prefixo repetido dentro
        do MESMO span). Não confundir com o texto legítimo "Proposta
        PROPOSTA-000001 criada." da aba Histórico (frase normal, palavra
        + número, não o bug) — por isso o teste procura a marca exata do
        span do cabeçalho da composição comercial."""
        body = self._get_body()
        label = self.proposal.latest_version.display_label
        self.assertIn(f'<span class="text-sm font-medium">{label}</span>', body)
        self.assertNotIn(f"PROPOSTA {label}", body)
        self.assertNotIn(f"{label} {label}", body)

    def test_draft_shows_rascunho_badge(self):
        body = self._get_body()
        self.assertIn("Rascunho", body)

    def test_issued_shows_emitida_badge(self):
        issue_proposal(proposal_version=self.proposal.latest_version, issued_by=self.owner)
        body = self._get_body()
        self.assertIn("Emitida", body)

    def test_accepted_shows_aceita_badge(self):
        issue_proposal(proposal_version=self.proposal.latest_version, issued_by=self.owner)
        accept_proposal_version(
            proposal_version=self.proposal.latest_version, accepted_by=self.owner, won_stage=self.stage_ganho
        )
        body = self._get_body()
        self.assertIn("Aceita", body)

    def test_badge_reverts_to_rascunho_only_after_real_alteration_not_on_reload(self):
        """Seção 32-33: o usuário NUNCA aciona manualmente — o badge só
        volta a "Rascunho" depois de uma alteração de verdade (aqui,
        adicionar um item), nunca só por reabrir a página."""
        issue_proposal(proposal_version=self.proposal.latest_version, issued_by=self.owner)
        body_before = self._get_body()
        self.assertIn("Emitida", body_before)
        self.assertNotIn(">Rascunho<", body_before)

        client = self._login(self.owner)
        client.post(
            reverse("crm:proposal_item_add", args=[self.opportunity.pk]),
            {"item_type": "EQUIPAMENTO", "equipment_model": self.model.pk, "quantity": "1", "unit_price": "10", "item_discount_amount": "0"},
        )
        body_after = self._get_body()
        self.assertIn(">Rascunho<", body_after)


# ---------------------------------------------------------------------------
# 35d — Resumo financeiro centralizado.
# ---------------------------------------------------------------------------


class ResumoFinanceiroCenteredTest(ProposalViewsTestBase):
    def setUp(self):
        super().setUp()
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        add_proposal_item(
            proposal_version=proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100")),
        )

    def test_summary_wrap_and_table_classes_present(self):
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        body = resp.content.decode()
        self.assertIn('class="proposal-summary-wrap"', body)
        self.assertIn("proposal-summary-table", body)

    def test_total_row_still_most_prominent(self):
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        body = resp.content.decode()
        self.assertIn(">TOTAL<", body)
        self.assertIn("font-bold", body)


# ---------------------------------------------------------------------------
# 36 — Auto-versionamento preguiçoso.
# ---------------------------------------------------------------------------


class ProposalR4ServiceTestBase(TestCase):
    """Mesma base de `ProposalServiceTestBase` (test_proposal_services.py),
    reproduzida aqui para não criar dependência cruzada com um arquivo
    que pode mudar por outro motivo."""

    def setUp(self):
        self.user = User.objects.create_user(username="vendedor_r4", password="x")
        self.client_obj = Client.objects.create(company_name="Cliente R4 LTDA")
        self.source = CommercialSource.objects.create(name="Indicação")
        self.stage_novo = OpportunityStage.objects.create(name="Novo R4", order=1)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho R4", order=2, is_won=True)
        self.opportunity = Opportunity.objects.create(
            client=self.client_obj, title="Evento R4", owner=self.user, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage_novo, created_by=self.user,
        )
        self.category = Category.objects.create(name="Climatizador R4")
        self.model = EquipmentModel.objects.create(code="NI23R4", name="NI23 Big Tank", category=self.category)
        self.service = ServiceCatalogItem.objects.create(name="Hora técnica teste", order=0, unit_label="hora")

    def _proposal_and_version(self):
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.user)
        return proposal, proposal.latest_version

    def _issued_version_with_item(self):
        proposal, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100")))
        issue_proposal(proposal_version=version, issued_by=self.user)
        version.refresh_from_db()
        return proposal, version


class LazyAutoVersioningServiceTest(ProposalR4ServiceTestBase):
    def test_ensure_editable_version_returns_same_draft_unchanged(self):
        proposal, version = self._proposal_and_version()
        returned = ensure_editable_version(proposal=proposal, created_by=self.user)
        self.assertEqual(returned.pk, version.pk)
        self.assertEqual(proposal.versions.count(), 1)

    def test_ensure_editable_version_clones_when_issued(self):
        proposal, v1 = self._issued_version_with_item()
        v2 = ensure_editable_version(proposal=proposal, created_by=self.user)
        self.assertNotEqual(v2.pk, v1.pk)
        self.assertEqual(v2.status, ProposalVersionStatus.DRAFT)
        self.assertEqual(v2.version_number, v1.version_number + 1)
        self.assertEqual(proposal.versions.count(), 2)

    def test_ensure_editable_version_clones_when_accepted(self):
        proposal, v1 = self._issued_version_with_item()
        accept_proposal_version(proposal_version=v1, accepted_by=self.user, won_stage=self.stage_ganho)
        v2 = ensure_editable_version(proposal=proposal, created_by=self.user)
        self.assertEqual(v2.status, ProposalVersionStatus.DRAFT)
        self.assertEqual(proposal.versions.count(), 2)

    def test_second_call_reuses_same_draft_no_third_version(self):
        """Seção 12: nunca criar versões vazias/redundantes a cada
        chamada — duas alterações seguidas reaproveitam o MESMO rascunho."""
        proposal, v1 = self._issued_version_with_item()
        v2_first_call = ensure_editable_version(proposal=proposal, created_by=self.user)
        v2_second_call = ensure_editable_version(proposal=proposal, created_by=self.user)
        self.assertEqual(v2_first_call.pk, v2_second_call.pk)
        self.assertEqual(proposal.versions.count(), 2)

    def test_original_issued_version_never_touched(self):
        proposal, v1 = self._issued_version_with_item()
        v1_total_before = v1.total
        v1_status_before = v1.status
        v2 = ensure_editable_version(proposal=proposal, created_by=self.user)
        add_proposal_item(proposal_version=v2, data=ProposalItemData(equipment_model=self.model, quantity=5, unit_price=Decimal("999")))
        v1.refresh_from_db()
        self.assertEqual(v1.total, v1_total_before)
        self.assertEqual(v1.status, v1_status_before)
        self.assertEqual(v1.items.count(), 1)

    def test_ensure_editable_item_returns_same_item_when_draft(self):
        _, version = self._proposal_and_version()
        item = add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("10")))
        returned = ensure_editable_item(item=item, created_by=self.user)
        self.assertEqual(returned.pk, item.pk)

    def test_ensure_editable_item_clones_and_matches_by_order(self):
        proposal, v1 = self._issued_version_with_item()
        old_item = v1.items.get()
        new_item = ensure_editable_item(item=old_item, created_by=self.user)
        self.assertNotEqual(new_item.pk, old_item.pk)
        self.assertEqual(new_item.order, old_item.order)
        self.assertEqual(new_item.proposal_version.status, ProposalVersionStatus.DRAFT)
        self.assertEqual(new_item.description_snapshot, old_item.description_snapshot)

    def test_ensure_editable_item_second_call_reuses_same_new_version(self):
        proposal, v1 = self._issued_version_with_item()
        old_item = v1.items.get()
        first = ensure_editable_item(item=old_item, created_by=self.user)
        second = ensure_editable_item(item=old_item, created_by=self.user)
        self.assertEqual(first.proposal_version_id, second.proposal_version_id)
        self.assertEqual(proposal.versions.count(), 2)


class LazyAutoVersioningHttpTest(ProposalViewsTestBase):
    def setUp(self):
        super().setUp()
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        add_proposal_item(
            proposal_version=proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100")),
        )
        issue_proposal(proposal_version=proposal.latest_version, issued_by=self.owner)
        self.proposal = proposal

    def test_get_reload_never_creates_new_version(self):
        client = self._login(self.owner)
        client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        self.assertEqual(self.proposal.versions.count(), 1)

    def test_first_item_add_after_issue_creates_new_draft_version(self):
        client = self._login(self.owner)
        resp = client.post(
            reverse("crm:proposal_item_add", args=[self.opportunity.pk]),
            {"item_type": "EQUIPAMENTO", "equipment_model": self.model.pk, "quantity": "1", "unit_price": "10", "item_discount_amount": "0"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.proposal.versions.count(), 2)
        latest = self.proposal.latest_version
        self.assertEqual(latest.status, ProposalVersionStatus.DRAFT)
        self.assertEqual(latest.items.count(), 2)  # item original clonado + item novo

    def test_second_item_add_after_issue_reuses_same_draft(self):
        client = self._login(self.owner)
        client.post(
            reverse("crm:proposal_item_add", args=[self.opportunity.pk]),
            {"item_type": "EQUIPAMENTO", "equipment_model": self.model.pk, "quantity": "1", "unit_price": "10", "item_discount_amount": "0"},
        )
        client.post(
            reverse("crm:proposal_item_add", args=[self.opportunity.pk]),
            {"item_type": "EQUIPAMENTO", "equipment_model": self.model.pk, "quantity": "2", "unit_price": "20", "item_discount_amount": "0"},
        )
        self.assertEqual(self.proposal.versions.count(), 2)  # nunca uma 3ª versão

    def test_condition_save_after_issue_creates_new_draft_version(self):
        client = self._login(self.owner)
        resp = client.post(
            reverse("crm:proposal_conditions_save", args=[self.opportunity.pk]),
            {"payment_method": "", "general_notes": "alterado depois da emissão"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.proposal.versions.count(), 2)
        latest = self.proposal.latest_version
        self.assertEqual(latest.general_notes, "alterado depois da emissão")

    def test_old_issued_version_items_and_pdf_attachment_untouched_after_autoversion(self):
        from apps.attachments.services import attachments_for

        attachments_before = list(attachments_for(self.opportunity))
        v1 = self.proposal.versions.get(version_number=1)
        v1_items_before = v1.items.count()

        client = self._login(self.owner)
        client.post(
            reverse("crm:proposal_item_add", args=[self.opportunity.pk]),
            {"item_type": "EQUIPAMENTO", "equipment_model": self.model.pk, "quantity": "1", "unit_price": "10", "item_discount_amount": "0"},
        )

        v1.refresh_from_db()
        self.assertEqual(v1.items.count(), v1_items_before)
        self.assertEqual(v1.status, ProposalVersionStatus.ISSUED)
        attachments_after = list(attachments_for(self.opportunity))
        self.assertEqual(len(attachments_before), len(attachments_after))


# ---------------------------------------------------------------------------
# 37 — Remoção de item.
# ---------------------------------------------------------------------------


class ItemRemovalDraftTest(ProposalViewsTestBase):
    def setUp(self):
        super().setUp()
        self.proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        self.item = add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100")),
        )

    def test_remove_from_draft_does_not_create_new_version(self):
        client = self._login(self.owner)
        resp = client.post(reverse("crm:proposal_item_remove", args=[self.opportunity.pk, self.item.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.proposal.versions.count(), 1)
        self.assertEqual(self.proposal.latest_version.items.count(), 0)

    def test_remove_requires_change_permission(self):
        user = _user_with_perms("view_only_remove", "view_opportunities")
        client = self._login(user)
        resp = client.post(reverse("crm:proposal_item_remove", args=[self.opportunity.pk, self.item.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_remove_modal_confirmation_text_rendered(self):
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        body = resp.content.decode()
        self.assertIn("Remover item", body)
        self.assertIn(f"Remover \"{self.item.description_snapshot}\" desta composição comercial?", body)
        self.assertIn("Isso não altera orçamentos já emitidos.", body)
        self.assertIn(f'data-open-modal="proposal-item-remove-modal-{self.item.pk}"', body)

    def test_can_add_multiple_different_equipment_models(self):
        model2 = EquipmentModel.objects.create(code="6PROR4", name="6 PRO", category=self.category)
        client = self._login(self.owner)
        client.post(
            reverse("crm:proposal_item_add", args=[self.opportunity.pk]),
            {"item_type": "EQUIPAMENTO", "equipment_model": model2.pk, "quantity": "3", "unit_price": "50", "item_discount_amount": "0"},
        )
        self.proposal.latest_version.refresh_from_db()
        self.assertEqual(self.proposal.latest_version.items.count(), 2)
        models_used = {item.equipment_model_id for item in self.proposal.latest_version.items.all()}
        self.assertEqual(models_used, {self.model.pk, model2.pk})


class ItemRemovalIssuedVersionTest(ProposalViewsTestBase):
    def setUp(self):
        super().setUp()
        self.proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        self.model2 = EquipmentModel.objects.create(code="6PROR4B", name="6 PRO", category=self.category)
        self.item1 = add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100")),
        )
        self.item2 = add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model2, quantity=2, unit_price=Decimal("50")),
        )
        issue_proposal(proposal_version=self.proposal.latest_version, issued_by=self.owner)

    def test_remove_from_issued_version_autoversions(self):
        client = self._login(self.owner)
        resp = client.post(reverse("crm:proposal_item_remove", args=[self.opportunity.pk, self.item1.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.proposal.versions.count(), 2)
        latest = self.proposal.latest_version
        self.assertEqual(latest.status, ProposalVersionStatus.DRAFT)
        self.assertEqual(latest.items.count(), 1)
        self.assertEqual(latest.items.first().description_snapshot, self.item2.description_snapshot)

    def test_old_emitted_version_and_pdf_never_touched(self):
        v1 = self.proposal.versions.get(version_number=1)
        v1_pdf_before = v1.issued_at

        client = self._login(self.owner)
        client.post(reverse("crm:proposal_item_remove", args=[self.opportunity.pk, self.item1.pk]))

        v1.refresh_from_db()
        self.assertEqual(v1.items.count(), 2)  # a versão antiga NUNCA perde o item
        self.assertEqual(v1.issued_at, v1_pdf_before)
        self.assertEqual(v1.status, ProposalVersionStatus.ISSUED)

    def test_removing_second_item_after_first_reuses_same_new_draft(self):
        client = self._login(self.owner)
        client.post(reverse("crm:proposal_item_remove", args=[self.opportunity.pk, self.item1.pk]))
        latest_after_first_removal = self.proposal.latest_version
        item2_in_new_version = latest_after_first_removal.items.get(order=self.item2.order)

        client.post(reverse("crm:proposal_item_remove", args=[self.opportunity.pk, item2_in_new_version.pk]))
        self.assertEqual(self.proposal.versions.count(), 2)  # ainda só uma versão nova
        self.assertEqual(self.proposal.latest_version.items.count(), 0)


# ---------------------------------------------------------------------------
# 38 — Item de Serviço.
# ---------------------------------------------------------------------------


class ServiceItemServiceLayerTest(ProposalR4ServiceTestBase):
    def test_add_service_item_success(self):
        _, version = self._proposal_and_version()
        item = add_proposal_item(
            proposal_version=version,
            data=ProposalItemData(item_type=ProposalItemType.SERVICO, service=self.service, quantity=3, unit_price=Decimal("150.00")),
        )
        self.assertEqual(item.item_type, ProposalItemType.SERVICO)
        self.assertEqual(item.description_snapshot, self.service.name)
        self.assertEqual(item.unit_label_snapshot, "hora")
        # `line_total` só é gravado por `calculate_proposal_version()`,
        # que atualiza a linha no banco via uma query separada — o objeto
        # `item` devolvido por `add_proposal_item()` precisa recarregar
        # (mesmo comportamento de `test_line_total_is_decimal` em
        # test_proposal_services.py, que por isso só checa o TIPO, nunca
        # o valor, sem recarregar antes).
        item.refresh_from_db()
        self.assertEqual(item.line_total, Decimal("450.00"))

    def test_service_item_with_equipment_model_also_set_is_rejected(self):
        _, version = self._proposal_and_version()
        with self.assertRaises(ValueError):
            add_proposal_item(
                proposal_version=version,
                data=ProposalItemData(
                    item_type=ProposalItemType.SERVICO, service=self.service, equipment_model=self.model, quantity=1, unit_price=Decimal("10")
                ),
            )

    def test_equipamento_item_without_model_is_rejected(self):
        _, version = self._proposal_and_version()
        with self.assertRaises(ValueError):
            add_proposal_item(
                proposal_version=version,
                data=ProposalItemData(item_type=ProposalItemType.EQUIPAMENTO, equipment_model=None, quantity=1, unit_price=Decimal("10")),
            )

    def test_servico_item_without_service_is_rejected(self):
        _, version = self._proposal_and_version()
        with self.assertRaises(ValueError):
            add_proposal_item(
                proposal_version=version,
                data=ProposalItemData(item_type=ProposalItemType.SERVICO, service=None, quantity=1, unit_price=Decimal("10")),
            )

    def test_invalid_item_type_rejected(self):
        _, version = self._proposal_and_version()
        with self.assertRaises(ValueError):
            add_proposal_item(
                proposal_version=version,
                data=ProposalItemData(item_type="OUTRO", equipment_model=self.model, quantity=1, unit_price=Decimal("10")),
            )

    def test_service_snapshot_survives_catalog_rename_and_unit_change(self):
        _, version = self._proposal_and_version()
        item = add_proposal_item(
            proposal_version=version,
            data=ProposalItemData(item_type=ProposalItemType.SERVICO, service=self.service, quantity=1, unit_price=Decimal("150")),
        )
        original_description = item.description_snapshot
        original_unit = item.unit_label_snapshot
        self.service.name = "Hora técnica renomeada"
        self.service.unit_label = "diária"
        self.service.save()
        item.refresh_from_db()
        self.assertEqual(item.description_snapshot, original_description)
        self.assertEqual(item.unit_label_snapshot, original_unit)

    def test_equipment_and_service_items_share_same_financial_calculation(self):
        _, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=2, unit_price=Decimal("100.00")))
        add_proposal_item(
            proposal_version=version,
            data=ProposalItemData(item_type=ProposalItemType.SERVICO, service=self.service, quantity=3, unit_price=Decimal("150.00")),
        )
        version.refresh_from_db()
        self.assertEqual(version.subtotal, Decimal("650.00"))
        self.assertEqual(version.items.count(), 2)

    def test_update_item_can_change_type_from_equipamento_to_servico(self):
        _, version = self._proposal_and_version()
        item = add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("100")))
        update_proposal_item(
            item=item,
            data=ProposalItemData(item_type=ProposalItemType.SERVICO, service=self.service, quantity=2, unit_price=Decimal("150.00")),
        )
        item.refresh_from_db()
        self.assertEqual(item.item_type, ProposalItemType.SERVICO)
        self.assertIsNone(item.equipment_model_id)
        self.assertEqual(item.service_id, self.service.pk)

    def test_service_item_survives_new_version_clone(self):
        proposal, version = self._proposal_and_version()
        add_proposal_item(
            proposal_version=version,
            data=ProposalItemData(item_type=ProposalItemType.SERVICO, service=self.service, quantity=2, unit_price=Decimal("150.00")),
        )
        issue_proposal(proposal_version=version, issued_by=self.user)
        v2 = ensure_editable_version(proposal=proposal, created_by=self.user)
        cloned_item = v2.items.get()
        self.assertEqual(cloned_item.item_type, ProposalItemType.SERVICO)
        self.assertEqual(cloned_item.service_id, self.service.pk)
        self.assertEqual(cloned_item.unit_label_snapshot, "hora")

    def test_database_check_constraint_blocks_mismatched_service_reference(self):
        from django.db import IntegrityError, transaction

        _, version = self._proposal_and_version()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProposalItem.objects.create(
                    proposal_version=version,
                    item_type=ProposalItemType.SERVICO,
                    service=self.service,
                    equipment_model=self.model,  # os dois preenchidos — deve ser bloqueado
                    quantity=1,
                    unit_price=Decimal("10.00"),
                )

    def test_database_check_constraint_blocks_equipamento_type_with_service_reference(self):
        from django.db import IntegrityError, transaction

        _, version = self._proposal_and_version()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProposalItem.objects.create(
                    proposal_version=version,
                    item_type=ProposalItemType.EQUIPAMENTO,
                    service=self.service,
                    equipment_model=None,
                    quantity=1,
                    unit_price=Decimal("10.00"),
                )

    def test_no_patrimonio_or_equipment_instance_field_on_service_item(self):
        self.assertNotIn("equipment", [f.name for f in ProposalItem._meta.get_fields()])


class ServiceItemHttpTest(ProposalViewsTestBase):
    def setUp(self):
        super().setUp()
        self.service = ServiceCatalogItem.objects.create(name="Hora técnica HTTP", order=0, unit_label="hora")
        self.proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)

    def test_add_service_item_via_view(self):
        client = self._login(self.owner)
        resp = client.post(
            reverse("crm:proposal_item_add", args=[self.opportunity.pk]),
            {"item_type": "SERVICO", "service": self.service.pk, "quantity": "3", "unit_price": "150.00", "item_discount_amount": "0"},
        )
        self.assertEqual(resp.status_code, 302)
        self.proposal.latest_version.refresh_from_db()
        item = self.proposal.latest_version.items.get()
        self.assertEqual(item.item_type, ProposalItemType.SERVICO)
        self.assertEqual(item.line_total, Decimal("450.00"))

    def test_add_service_item_missing_service_shows_friendly_error_not_500(self):
        client = self._login(self.owner)
        resp = client.post(
            reverse("crm:proposal_item_add", args=[self.opportunity.pk]),
            {"item_type": "SERVICO", "quantity": "1", "unit_price": "10", "item_discount_amount": "0"},
        )
        self.assertEqual(resp.status_code, 302)
        self.proposal.latest_version.refresh_from_db()
        self.assertEqual(self.proposal.latest_version.items.count(), 0)

    def test_service_item_card_renders_with_badge_and_unit_label(self):
        add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(item_type=ProposalItemType.SERVICO, service=self.service, quantity=3, unit_price=Decimal("150.00")),
        )
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        body = resp.content.decode()
        self.assertIn(">Serviço<", body)
        self.assertIn(self.service.name, body)
        self.assertIn("3 horas", body)
        self.assertIn("R$ 150,00/hora", body)

    def test_item_add_form_offers_both_equipment_model_and_service_fields(self):
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        body = resp.content.decode()
        self.assertIn('data-item-type-group="EQUIPAMENTO"', body)
        self.assertIn('data-item-type-group="SERVICO"', body)
        self.assertIn('data-item-type-select', body)


# ---------------------------------------------------------------------------
# 39 — Regressão de item de Equipamento.
# ---------------------------------------------------------------------------


class EquipmentItemRegressionTest(ProposalViewsTestBase):
    def setUp(self):
        super().setUp()
        self.proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)

    def test_equipment_item_still_requires_model_field(self):
        client = self._login(self.owner)
        resp = client.post(
            reverse("crm:proposal_item_add", args=[self.opportunity.pk]),
            {"item_type": "EQUIPAMENTO", "quantity": "1", "unit_price": "10", "item_discount_amount": "0"},
        )
        self.assertEqual(resp.status_code, 302)
        self.proposal.latest_version.refresh_from_db()
        self.assertEqual(self.proposal.latest_version.items.count(), 0)

    def test_equipment_item_card_still_shows_unidades_wording_unchanged(self):
        add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=2, unit_price=Decimal("100")),
        )
        client = self._login(self.owner)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        body = resp.content.decode()
        self.assertIn("2 unidades", body)
        # Não confundir com a opção "Serviço" do próprio <select> Tipo
        # (sempre presente no form de adicionar item, seção 25) — o que
        # NÃO deve aparecer é o badge do CARTÃO de item de serviço.
        self.assertNotIn('class="badge-neutral text-xs uppercase tracking-wide align-middle mr-1">Serviço<', body)

    def test_default_item_type_is_equipamento(self):
        from apps.crm.forms import ProposalItemForm

        form = ProposalItemForm()
        self.assertEqual(form.fields["item_type"].initial, ProposalItemType.EQUIPAMENTO)


# ---------------------------------------------------------------------------
# Catálogo de serviços comerciais — tela de configuração.
# ---------------------------------------------------------------------------


class ServiceCatalogItemFormTest(TestCase):
    def test_valid_form_creates_item(self):
        form = ServiceCatalogItemForm(data={"name": "Instalação técnica", "order": "1", "unit_label": "un", "is_active": "on"})
        self.assertTrue(form.is_valid(), form.errors)
        item = form.save()
        self.assertEqual(item.unit_label, "un")

    def test_duplicate_name_rejected(self):
        ServiceCatalogItem.objects.create(name="Hora técnica dup", order=0, unit_label="hora")
        form = ServiceCatalogItemForm(data={"name": "Hora técnica dup", "order": "1", "unit_label": "hora"})
        self.assertFalse(form.is_valid())


class ServiceCatalogItemViewsTest(ProposalViewsTestBase):
    def test_list_requires_manage_commercial_settings_permission(self):
        client = self._login(self.owner)  # owner não tem manage_commercial_settings
        resp = client.get(reverse("crm:service_catalog_item_list"))
        self.assertEqual(resp.status_code, 403)

    def test_list_shows_seeded_hora_tecnica(self):
        user = _user_with_perms("catalog_admin_r4", "manage_commercial_settings")
        client = self._login(user)
        resp = client.get(reverse("crm:service_catalog_item_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Hora técnica")

    def test_only_hora_tecnica_seeded_no_other_example_services(self):
        seeded_names = set(ServiceCatalogItem.objects.values_list("name", flat=True))
        self.assertEqual(seeded_names, {"Hora técnica"})

    def test_create_new_service_catalog_item(self):
        user = _user_with_perms("catalog_creator_r4", "manage_commercial_settings")
        client = self._login(user)
        resp = client.post(
            reverse("crm:service_catalog_item_create"), {"name": "Montagem", "order": "5", "unit_label": "un", "is_active": "on"}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ServiceCatalogItem.objects.filter(name="Montagem").exists())

    def test_update_existing_service_catalog_item(self):
        item = ServiceCatalogItem.objects.create(name="Serviço R4 editar", order=9, unit_label="un")
        user = _user_with_perms("catalog_editor_r4", "manage_commercial_settings")
        client = self._login(user)
        resp = client.post(
            reverse("crm:service_catalog_item_update", args=[item.pk]),
            {"name": "Serviço R4 editado", "order": "9", "unit_label": "hora", "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.name, "Serviço R4 editado")
        self.assertEqual(item.unit_label, "hora")

    def test_sidebar_link_visible_only_with_permission(self):
        user_with_perm = _user_with_perms("sidebar_with_perm_r4", "manage_commercial_settings", "view_opportunities")
        client = self._login(user_with_perm)
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        self.assertContains(resp, "Serviços comerciais")

        user_without_perm = _user_with_perms("sidebar_without_perm_r4", "view_opportunities")
        client2 = self._login(user_without_perm)
        resp2 = client2.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        self.assertNotContains(resp2, "Serviços comerciais")

    def test_no_physical_delete_action_in_list_template(self):
        user = _user_with_perms("catalog_no_delete_r4", "manage_commercial_settings")
        client = self._login(user)
        resp = client.get(reverse("crm:service_catalog_item_list"))
        body = resp.content.decode()
        self.assertNotIn("Excluir", body)


# ---------------------------------------------------------------------------
# PDF — auditoria confirmou que nenhuma mudança de código é necessária
# (tabela já genérica, lê `description_snapshot` para qualquer tipo de
# item) — testes aqui confirmam isso comportamentalmente.
# ---------------------------------------------------------------------------


class PdfMixedItemsTest(ProposalR4ServiceTestBase):
    def test_pdf_renders_with_equipment_and_service_items(self):
        from apps.crm.pdf import render_proposal_pdf

        _, version = self._proposal_and_version()
        add_proposal_item(proposal_version=version, data=ProposalItemData(equipment_model=self.model, quantity=2, unit_price=Decimal("100.00")))
        add_proposal_item(
            proposal_version=version,
            data=ProposalItemData(item_type=ProposalItemType.SERVICO, service=self.service, quantity=3, unit_price=Decimal("150.00")),
        )
        issue_proposal(proposal_version=version, issued_by=self.user)
        version.refresh_from_db()
        pdf_bytes = render_proposal_pdf(version)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_service_item_snapshot_preserved_even_after_pdf_already_issued(self):
        _, version = self._proposal_and_version()
        add_proposal_item(
            proposal_version=version,
            data=ProposalItemData(item_type=ProposalItemType.SERVICO, service=self.service, quantity=1, unit_price=Decimal("150.00")),
        )
        issue_proposal(proposal_version=version, issued_by=self.user)
        snapshot_before = version.items.get().description_snapshot
        self.service.name = "Nome mudou depois de emitir"
        self.service.save()
        self.assertEqual(version.items.get().description_snapshot, snapshot_before)


# ---------------------------------------------------------------------------
# 40 — Regressão pontual (o essencial já é coberto em
# test_proposal_services.py/test_proposal_views.py/
# test_proposal_composition_refinamento.py — aqui só as interações NOVAS
# introduzidas por esta rodada).
# ---------------------------------------------------------------------------


class RegressionChecklistR4Test(ProposalViewsTestBase):
    def setUp(self):
        super().setUp()
        self.proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.owner)
        add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("500")),
        )

    def test_gerar_orcamento_still_never_wins_opportunity(self):
        user = _user_with_perms("issuer_r4", "view_opportunities", "issue_proposal_documents")
        client = self._login(user)
        resp = client.post(
            reverse("crm:proposal_generate_document", args=[self.opportunity.pk]), {"document_type": "PROPOSTA"}
        )
        self.assertEqual(resp.status_code, 302)
        self.opportunity.refresh_from_db()
        self.assertFalse(self.opportunity.stage.is_won)

    def test_top_orcamento_aceito_remains_only_acceptance_trigger_after_autoversion(self):
        """Depois de emitir, alterar (auto-versão), e emitir de novo — o
        único CTA de aceite visível continua sendo o do topo, mesmo com
        o histórico de auto-versionamento no meio do caminho."""
        user_issuer = _user_with_perms("issuer_r4b", "view_opportunities", "issue_proposal_documents", "change_opportunities")
        client = self._login(user_issuer)
        client.post(reverse("crm:proposal_generate_document", args=[self.opportunity.pk]), {"document_type": "PROPOSTA"})
        client.post(
            reverse("crm:proposal_item_add", args=[self.opportunity.pk]),
            {"item_type": "EQUIPAMENTO", "equipment_model": self.model.pk, "quantity": "1", "unit_price": "10", "item_discount_amount": "0"},
        )
        resp = client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        body = resp.content.decode()
        self.assertNotIn("Aceitar versão", body)

    def test_mixed_equipment_and_service_composition_can_still_be_accepted_via_top_flow(self):
        service = ServiceCatalogItem.objects.create(name="Hora técnica regressão", order=0, unit_label="hora")
        add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(item_type=ProposalItemType.SERVICO, service=service, quantity=2, unit_price=Decimal("150.00")),
        )
        issue_proposal(proposal_version=self.proposal.latest_version, issued_by=self.owner)
        self.proposal.latest_version.refresh_from_db()

        user = _user_with_perms("accepter_mixed_r4", "view_opportunities", "change_opportunity_stage")
        client = self._login(user)
        resp = client.post(
            reverse("crm:proposal_accept_version", args=[self.opportunity.pk]),
            {"proposal_version": self.proposal.latest_version.pk, "stage": self.stage_ganho.pk},
        )
        self.assertEqual(resp.status_code, 302)
        self.opportunity.refresh_from_db()
        self.assertTrue(self.opportunity.stage.is_won)
        self.assertEqual(self.opportunity.closed_value, self.proposal.latest_version.total)
