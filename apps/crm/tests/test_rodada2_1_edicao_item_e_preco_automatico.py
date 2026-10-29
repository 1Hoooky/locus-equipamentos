"""
Testes de RODADA 2.1 — "Automatizar o preenchimento do preço da tabela" +
"Adicionar edição de produto/serviço já inserido na proposta" (14/10/2026).

Cobre:
  1. exposição na UI (template) do botão/modal "Editar item" — o backend
     (`update_proposal_item()`/`ProposalItemUpdateView`/`ensure_editable_item()`)
     já existia ANTES desta rodada (auditoria confirmou), mas sem nenhuma
     cobertura HTTP até agora — por isso a maior parte deste arquivo é
     cobertura NOVA de um caminho que já funcionava sem teste;
  2. o pré-preenchimento do form de edição com os valores ATUAIS do item
     (nunca recalculado da Tabela de Preços);
  3. o comportamento de auto-versionamento (`ensure_editable_item()`) ao
     editar um item de uma versão já emitida;
  4. segurança (IDOR/permissão/CSRF/GET sem efeito colateral) do endpoint
     de edição, no mesmo padrão já usado por `test_proposal_views.py`;
  5. o conteúdo do JS corrigido (preenchimento automático que ATUALIZA o
     `unit_price`, não só na primeira vez) — mesma técnica de leitura de
     arquivo rastreado já usada por `test_i18n_encoding_audit.py`, já que
     este projeto não executa JavaScript em teste nenhum;
  6. regressão: Venda/Serviço continuam no caminho flat, sem nenhuma
     relação com `PriceTableRate`/matriz;
  7. P0-04/UX-001 (29/10/2026) — correção da sobrescrita silenciosa de
     `unit_price` introduzida por esta própria RODADA 2.1: a classe
     `JsAutofillOverwriteLogicTest` abaixo foi atualizada (nunca mais
     fixa o comportamento antigo como correto) e ganhou os testes da
     nova semântica de três estados (vazio/último-automático/manual),
     da correção dos N+1 listeners de plano/data nos modais de edição,
     e da proteção contra resposta assíncrona obsoleta — mesma técnica
     de leitura estática do arquivo `.js` rastreado, sem nenhum runner
     de JavaScript novo.
"""

from decimal import Decimal
from pathlib import Path

from django.conf import settings
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
    PriceTableItem,
    ProposalItemType,
    ProposalVersionStatus,
    ServiceCatalogItem,
)
from apps.crm.services import (
    PriceTableItemData,
    PriceTableRateData,
    ProposalItemData,
    add_proposal_item,
    get_or_create_active_proposal,
    issue_proposal,
    set_price_table_item,
    set_price_table_rate,
)
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


class ProposalItemEditTestBase(TestCase):
    def setUp(self):
        self.user = _user_with_perms(
            "vendedor_r21", "view_opportunities", "add_opportunities", "change_opportunities"
        )
        self.client_obj = Client.objects.create(company_name="Cliente RODADA 2.1")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage = OpportunityStage.objects.create(name="Novo", order=1)
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(code="NI23BT", name="NI23 Big Tank", category=self.category)
        self.other_model = EquipmentModel.objects.create(code="AQCP1", name="Aquecedor Pirâmide", category=self.category)
        self.service = ServiceCatalogItem.objects.create(name="Diária de operador", unit_label="hora")

        self.opportunity = Opportunity.objects.create(
            client=self.client_obj, title="Oportunidade RODADA 2.1", owner=self.user, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage, created_by=self.user,
        )
        self.proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.user)
        self.item = add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=2, unit_price=Decimal("650.00"), notes="Observação original"),
        )

    def _login(self, user=None):
        client = DjangoTestClient()
        client.force_login(user or self.user)
        return client

    def _update_url(self, item=None):
        return reverse("crm:proposal_item_update", args=[self.opportunity.pk, (item or self.item).pk])

    def _detail_url(self):
        return reverse("crm:opportunity_detail", args=[self.opportunity.pk])


# ---------------------------------------------------------------------------
# UI — botão/modal "Editar item" (seção 6 da especificação).
# ---------------------------------------------------------------------------
class EditButtonVisibilityTest(ProposalItemEditTestBase):
    def test_edit_button_and_modal_appear_with_change_permission(self):
        client = self._login(self.user)
        resp = client.get(self._detail_url())
        body = resp.content.decode()
        self.assertIn("Editar item", body)
        self.assertIn(f'proposal-item-edit-modal-{self.item.pk}', body)
        self.assertIn(f'action="{self._update_url()}"', body)

    def test_edit_button_absent_without_change_permission(self):
        viewer = _user_with_perms("so_visualiza_r21", "view_opportunities")
        client = self._login(viewer)
        resp = client.get(self._detail_url())
        body = resp.content.decode()
        self.assertNotIn("Editar item", body)
        self.assertNotIn(f"proposal-item-edit-modal-{self.item.pk}", body)

    def test_remover_item_button_still_present_unchanged(self):
        # Regressão: "Editar item" foi ADICIONADO antes de "Remover item"
        # no mesmo menu — o botão/modal de remover continua existindo.
        client = self._login(self.user)
        resp = client.get(self._detail_url())
        body = resp.content.decode()
        self.assertIn("Remover item", body)
        self.assertIn(f"proposal-item-remove-modal-{self.item.pk}", body)

    def test_two_items_on_the_same_page_never_duplicate_html_ids(self):
        # `auto_id` próprio por item (nunca `prefix`) — cada modal de
        # edição precisa de um `id`/`for` ÚNICO na página (HTML
        # inválido/acessibilidade quebrada do contrário), mas o `name`
        # dos campos tem que continuar `quantity`/`unit_price`/etc. SEM
        # prefixo, porque é por aí que o JS encontra os campos dentro de
        # CADA `<form>` (seletores já existentes, nunca alterados).
        second_item = add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(equipment_model=self.other_model, quantity=1, unit_price=Decimal("10.00")),
        )
        client = self._login(self.user)
        body = client.get(self._detail_url()).content.decode()

        id_first = f'id="id_edit_item_{self.item.pk}_quantity"'
        id_second = f'id="id_edit_item_{second_item.pk}_quantity"'
        self.assertIn(id_first, body)
        self.assertIn(id_second, body)
        self.assertNotEqual(id_first, id_second)
        self.assertEqual(body.count('name="quantity"'), 3)  # add form + 2 modais de edição, todos sem prefixo


# ---------------------------------------------------------------------------
# Pré-preenchimento do form de edição (seções 7/8/11).
# ---------------------------------------------------------------------------
class EditFormPrefillTest(ProposalItemEditTestBase):
    def test_edit_form_shows_the_item_current_values(self):
        client = self._login(self.user)
        resp = client.get(self._detail_url())
        body = resp.content.decode()
        self.assertIn('value="650.00"', body)
        self.assertIn('value="2"', body)
        self.assertIn("Observação original", body)

    def test_opening_edit_does_not_create_any_record(self):
        # Seção 16: GET nunca cria ProposalVersion/ProposalItem/Movement.
        from apps.crm.models import ProposalItem, ProposalVersion

        version_count = ProposalVersion.objects.count()
        item_count = ProposalItem.objects.count()
        client = self._login(self.user)
        client.get(self._detail_url())
        self.assertEqual(ProposalVersion.objects.count(), version_count)
        self.assertEqual(ProposalItem.objects.count(), item_count)

    def test_editing_never_shows_a_recalculated_price_from_an_updated_price_table(self):
        # Seção 11, exemplo exato da especificação: item salvo a R$650,00,
        # tabela hoje em R$700,00 — o formulário de edição abre com
        # R$650,00, nunca R$700,00.
        plan = CommercialPlan.objects.create(name="Locação Comum RODADA21", business_type=BusinessType.LOCACAO)
        term = CommercialTerm.objects.create(commercial_plan=plan, duration_value=5, duration_unit=DurationUnit.DIAS)
        set_price_table_rate(
            data=PriceTableRateData(equipment_model=self.model, commercial_plan=plan, commercial_term=term, amount=Decimal("700.00")),
            user=self.user,
        )
        client = self._login(self.user)
        resp = client.get(self._detail_url())
        body = resp.content.decode()
        self.assertIn('value="650.00"', body)
        self.assertNotIn('value="700.00"', body)


# ---------------------------------------------------------------------------
# POST de edição — cada campo (seção 7/19).
# ---------------------------------------------------------------------------
class EditPostUpdatesFieldsTest(ProposalItemEditTestBase):
    def _post(self, **overrides):
        payload = {
            "item_type": ProposalItemType.EQUIPAMENTO,
            "equipment_model": self.model.pk,
            "quantity": "2",
            "unit_price": "650.00",
            "item_discount_amount": "0",
            "notes": "Observação original",
        }
        payload.update(overrides)
        client = self._login(self.user)
        return client.post(self._update_url(), payload)

    def test_edit_quantity(self):
        resp = self._post(quantity="5")
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 5)

    def test_edit_unit_price(self):
        self._post(unit_price="999.99")
        self.item.refresh_from_db()
        self.assertEqual(self.item.unit_price, Decimal("999.99"))

    def test_edit_equipment_model(self):
        self._post(equipment_model=self.other_model.pk)
        self.item.refresh_from_db()
        self.assertEqual(self.item.equipment_model_id, self.other_model.pk)
        self.assertIn(self.other_model.code, self.item.description_snapshot)

    def test_edit_switch_equipamento_to_servico(self):
        self._post(item_type=ProposalItemType.SERVICO, service=self.service.pk, equipment_model="")
        self.item.refresh_from_db()
        self.assertEqual(self.item.item_type, ProposalItemType.SERVICO)
        self.assertEqual(self.item.service_id, self.service.pk)
        self.assertIsNone(self.item.equipment_model_id)
        self.assertEqual(self.item.unit_label_snapshot, "hora")

    def test_edit_discount(self):
        self._post(item_discount_amount="100.00")
        self.item.refresh_from_db()
        self.assertEqual(self.item.item_discount_amount, Decimal("100.00"))

    def test_edit_notes(self):
        self._post(notes="Observação atualizada na edição")
        self.item.refresh_from_db()
        self.assertEqual(self.item.notes, "Observação atualizada na edição")

    def test_totals_recalculated_after_edit(self):
        # quantidade × valor unitário não é recriado aqui — só confirmamos
        # que `calculate_proposal_version()` (mecanismo já existente) foi
        # mesmo chamado pelo fluxo de edição.
        self._post(quantity="3", unit_price="100.00", item_discount_amount="0")
        self.item.refresh_from_db()
        version = self.item.proposal_version
        version.refresh_from_db()
        self.assertEqual(self.item.line_total, Decimal("300.00"))
        self.assertEqual(version.subtotal, Decimal("300.00"))
        self.assertEqual(version.total, Decimal("300.00"))

    def test_discount_greater_than_gross_is_rejected(self):
        resp = self._post(unit_price="100.00", quantity="1", item_discount_amount="500.00")
        self.assertEqual(resp.status_code, 302)  # redireciona com mensagem de erro, nada muda
        self.item.refresh_from_db()
        self.assertEqual(self.item.item_discount_amount, Decimal("0.00"))


# ---------------------------------------------------------------------------
# Segurança — IDOR / permissão / CSRF / método HTTP (seções 14/15/16).
# ---------------------------------------------------------------------------
class EditSecurityTest(ProposalItemEditTestBase):
    def test_get_is_not_allowed(self):
        client = self._login(self.user)
        resp = client.get(self._update_url())
        self.assertEqual(resp.status_code, 405)

    def test_no_permission_is_forbidden(self):
        user = _user_with_perms("sem_permissao_editar_r21")
        client = self._login(user)
        resp = client.post(self._update_url(), {})
        self.assertEqual(resp.status_code, 403)

    def test_view_only_cannot_edit(self):
        user = _user_with_perms("so_view_editar_r21", "view_opportunities")
        client = self._login(user)
        resp = client.post(self._update_url(), {})
        self.assertEqual(resp.status_code, 403)

    def test_csrf_required(self):
        strict_client = DjangoTestClient(enforce_csrf_checks=True)
        strict_client.force_login(self.user)
        resp = strict_client.post(
            self._update_url(),
            {"item_type": "EQUIPAMENTO", "equipment_model": self.model.pk, "quantity": "1", "unit_price": "10"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_item_from_another_opportunity_cannot_be_edited(self):
        other_opportunity = Opportunity.objects.create(
            client=self.client_obj, title="Outra Oportunidade", owner=self.user, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage, created_by=self.user,
        )
        client = self._login(self.user)
        url = reverse("crm:proposal_item_update", args=[other_opportunity.pk, self.item.pk])
        resp = client.post(
            url, {"item_type": "EQUIPAMENTO", "equipment_model": self.model.pk, "quantity": "9", "unit_price": "1.00"}
        )
        self.assertEqual(resp.status_code, 404)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 2)  # inalterado


# ---------------------------------------------------------------------------
# Auto-versionamento (seção 10) — já existia para Add/Remove; aqui a
# cobertura é especificamente da exposição via Update.
# ---------------------------------------------------------------------------
class EditAutoVersioningTest(ProposalItemEditTestBase):
    def test_editing_item_on_issued_version_clones_new_draft_and_leaves_old_untouched(self):
        add_full_installment(self.proposal.latest_version)
        issued_version = issue_proposal(proposal_version=self.proposal.latest_version, issued_by=self.user)
        self.assertEqual(issued_version.status, ProposalVersionStatus.ISSUED)
        old_item_pk = self.item.pk

        client = self._login(self.user)
        resp = client.post(
            self._update_url(),
            {"item_type": "EQUIPAMENTO", "equipment_model": self.model.pk, "quantity": "9", "unit_price": "650.00", "item_discount_amount": "0"},
        )
        self.assertEqual(resp.status_code, 302)

        issued_version.refresh_from_db()
        self.assertEqual(issued_version.status, ProposalVersionStatus.ISSUED)
        old_item = issued_version.items.get(pk=old_item_pk)
        self.assertEqual(old_item.quantity, 2, "a versão EMITIDA nunca é alterada diretamente")

        self.proposal.refresh_from_db()
        new_version = self.proposal.latest_version
        self.assertNotEqual(new_version.pk, issued_version.pk)
        self.assertEqual(new_version.status, ProposalVersionStatus.DRAFT)
        new_item = new_version.items.get()
        self.assertEqual(new_item.quantity, 9, "a mutação de verdade cai na nova versão DRAFT clonada")


# ---------------------------------------------------------------------------
# Preenchimento automático — contrato do endpoint que o JS consome
# (seção 18, itens 1-5; a execução do JS em si não é testável nesta
# suíte — ver `JsAutofillOverwriteLogicTest` abaixo).
# ---------------------------------------------------------------------------
class SuggestedPriceAcrossAllPackagesTest(ProposalItemEditTestBase):
    def test_all_four_day_packages_resolve_the_correct_amount(self):
        plan = CommercialPlan.objects.create(name="Locação Comum RODADA21 Grade", business_type=BusinessType.LOCACAO)
        term_1 = CommercialTerm.objects.create(commercial_plan=plan, duration_value=1, duration_unit=DurationUnit.DIAS)
        term_5 = CommercialTerm.objects.create(commercial_plan=plan, duration_value=5, duration_unit=DurationUnit.DIAS)
        term_15 = CommercialTerm.objects.create(commercial_plan=plan, duration_value=15, duration_unit=DurationUnit.DIAS)
        term_30 = CommercialTerm.objects.create(commercial_plan=plan, duration_value=30, duration_unit=DurationUnit.DIAS)
        for term, amount in ((term_1, "300.00"), (term_5, "700.00"), (term_15, "1300.00"), (term_30, "2200.00")):
            set_price_table_rate(
                data=PriceTableRateData(equipment_model=self.model, commercial_plan=plan, commercial_term=term, amount=Decimal(amount)),
                user=self.user,
            )

        client = self._login(self.user)
        url = reverse("crm:proposal_suggested_price", args=[self.opportunity.pk])
        cases = [
            ("2026-11-01", "2026-11-01", "300.00", "1 dia"),
            ("2026-11-01", "2026-11-05", "700.00", "5 dias"),
            ("2026-11-01", "2026-11-15", "1300.00", "15 dias"),
            ("2026-11-01", "2026-11-30", "2200.00", "30 dias"),
        ]
        for start, end, expected_amount, expected_term in cases:
            resp = client.get(url, {
                "equipment_model": self.model.pk, "commercial_plan": plan.pk,
                "contracted_start_date": start, "contracted_end_date": end,
            })
            data = resp.json()
            self.assertTrue(data["found"], data)
            self.assertEqual(data["unit_price"], expected_amount)
            self.assertEqual(data["commercial_term"], expected_term)

    def test_no_rate_configured_never_invents_a_price(self):
        plan = CommercialPlan.objects.create(name="Plano Sem Rate R21", business_type=BusinessType.LOCACAO)
        CommercialTerm.objects.create(commercial_plan=plan, duration_value=5, duration_unit=DurationUnit.DIAS)
        client = self._login(self.user)
        url = reverse("crm:proposal_suggested_price", args=[self.opportunity.pk])
        resp = client.get(url, {
            "equipment_model": self.model.pk, "commercial_plan": plan.pk,
            "contracted_start_date": "2026-11-01", "contracted_end_date": "2026-11-05",
        })
        data = resp.json()
        self.assertFalse(data["found"])
        self.assertIsNone(data["unit_price"])


# ---------------------------------------------------------------------------
# Regressão — Venda/Serviço continuam 100% no caminho flat (seção 13/20).
# ---------------------------------------------------------------------------
class VendaServicoEditRegressionTest(TestCase):
    def setUp(self):
        self.user = _user_with_perms("vendedor_venda_r21", "view_opportunities", "add_opportunities", "change_opportunities")
        self.client_obj = Client.objects.create(company_name="Cliente Venda RODADA21")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage = OpportunityStage.objects.create(name="Novo", order=1)
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(code="NI23BT", name="NI23 Big Tank", category=self.category)
        self.opportunity = Opportunity.objects.create(
            client=self.client_obj, title="Oportunidade Venda RODADA21", owner=self.user, source=self.source,
            business_type=BusinessType.VENDA, stage=self.stage, created_by=self.user,
        )
        set_price_table_item(
            data=PriceTableItemData(business_type=BusinessType.VENDA, equipment_model=self.model, unit_price=Decimal("25000.00")),
            user=self.user,
        )
        self.proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.user)
        self.item = add_proposal_item(
            proposal_version=self.proposal.latest_version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("25000.00")),
        )

    def _login(self):
        client = DjangoTestClient()
        client.force_login(self.user)
        return client

    def test_editing_a_venda_item_never_touches_the_rental_matrix(self):
        client = self._login()
        url = reverse("crm:proposal_item_update", args=[self.opportunity.pk, self.item.pk])
        resp = client.post(
            url,
            {"item_type": "EQUIPAMENTO", "equipment_model": self.model.pk, "quantity": "2", "unit_price": "24000.00", "item_discount_amount": "0"},
        )
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 2)
        self.assertEqual(self.item.unit_price, Decimal("24000.00"))
        # Garantia de que Venda nunca cria/usa a matriz de Locação — os 5
        # `CommercialPlan` seguem existindo (seed da migration 0012,
        # independente deste teste), mas nenhum `PriceTableRate` é criado.
        from apps.crm.models import PriceTableRate

        self.assertFalse(PriceTableRate.objects.filter(price_table_item__equipment_model=self.model).exists())


# ---------------------------------------------------------------------------
# Conteúdo do JS — este projeto não executa JavaScript em teste nenhum
# (confirmado na auditoria); mesma técnica de `test_i18n_encoding_audit.py`
# (ler o arquivo rastreado direto) para proteger a regra já corrigida de
# não regredir silenciosamente.
#
# P0-04/UX-001 (29/10/2026): esta classe ANTES fixava como "correto" o
# comportamento que causava a sobrescrita silenciosa (ver investigação —
# `test_unit_price_is_overwritten_whenever_not_user_edited` original
# proibia exatamente a condição que protegeria o usuário). Os testes
# abaixo substituem essa cobertura pela semântica corrigida: nunca mais
# um único `data-user-edited` decide se o campo pode ser sobrescrito.
# ---------------------------------------------------------------------------
class JsAutofillOverwriteLogicTest(TestCase):
    def setUp(self):
        path = Path(settings.BASE_DIR) / "static" / "crm" / "proposal_composition.js"
        self.source = path.read_text(encoding="utf-8")

    def test_old_unconditional_overwrite_no_longer_exists(self):
        # A condição ANTIGA da RODADA 2.1 (só `data-user-edited` decide, e
        # sobrescreve direto com o valor cru da resposta) não pode mais
        # existir — nem a condição ORIGINAL ainda mais antiga ("só se
        # vazio"), que já tinha sido removida antes do P0-04.
        self.assertNotIn('if (!unitPriceField.getAttribute("data-user-edited")) {\n            unitPriceField.value = data.unit_price;', self.source)
        self.assertNotIn('if (!unitPriceField.value && !unitPriceField.getAttribute("data-user-edited")) {', self.source)
        self.assertNotIn("unitPriceField.value = data.unit_price;", self.source)

    def test_initialization_wires_every_item_form_not_only_the_add_form(self):
        self.assertIn("data-proposal-item-add-form", self.source)
        self.assertIn("data-proposal-item-edit-form", self.source)

    def test_empty_field_or_value_still_equal_to_last_automatic_updates_directly(self):
        # Estados 1 e 2 da semântica corrigida: campo vazio, OU valor
        # atual ainda igual ao último valor que o PRÓPRIO script aplicou
        # (`data-auto-price`) — os dois casos em que não há nada manual a
        # proteger, então pode atualizar sem pedir confirmação.
        self.assertIn(
            'if (currentValue === "" || (lastAuto !== null && moneyEquals(currentValue, lastAuto))) {\n'
            "            applyAutomatically(amountStr, baseMessage);\n"
            "            return;\n"
            "          }",
            self.source,
        )

    def test_manual_or_unknown_server_initial_value_is_never_silently_overwritten(self):
        # Estado 4 da semântica corrigida: qualquer outro valor (manual,
        # ou valor inicial do servidor diferente da sugestão) cai no
        # `offerSuggestedPrice` — nunca em uma atribuição direta a
        # `unitPriceField.value` fora de uma ação explícita do usuário.
        self.assertIn('offerSuggestedPrice(amountStr, "Novo preço sugerido disponível — " + baseMessage);', self.source)

    def test_server_initial_value_without_auto_price_marker_is_treated_as_protected(self):
        # Estado 3 (coincidência): valor atual igual à sugestão de agora,
        # mas SEM `data-auto-price` — não precisa confirmar, mas também
        # não "assume" o campo (não seta `data-auto-price`), então uma
        # sugestão FUTURA diferente ainda é protegida.
        self.assertIn(
            "if (lastAuto === null && moneyEquals(currentValue, amountStr)) {\n"
            "            clearPendingSuggestion();\n"
            "            hintEl.hidden = false;\n"
            "            hintEl.textContent = baseMessage;\n"
            "            return;\n"
            "          }",
            self.source,
        )
        # Não pode setar `data-auto-price` nesse ramo específico de
        # coincidência — só os dois outros ramos (`applyAutomatically` e
        # o clique em "Aplicar preço sugerido") fazem isso.
        self.assertEqual(self.source.count('setAttribute("data-auto-price"'), 2)

    def test_data_user_edited_is_no_longer_the_overwrite_authority(self):
        # Continua existindo por compatibilidade (setado no `input`), mas
        # a decisão de sobrescrever passou a usar `data-auto-price` +
        # comparação monetária — nunca mais um `if` baseado só nele.
        self.assertIn('unitPriceField.setAttribute("data-user-edited", "1");', self.source)
        self.assertNotIn("getAttribute(\"data-user-edited\"))", self.source)

    def test_applying_suggestion_sets_the_new_value_and_marks_it_automatic(self):
        # Botão "Aplicar preço sugerido" dentro do próprio
        # `data-suggested-price-hint" — nenhum modal novo.
        self.assertIn('button.textContent = "Aplicar preço sugerido";', self.source)
        self.assertIn(
            "unitPriceField.value = amountStr;\n"
            '        unitPriceField.setAttribute("data-auto-price", amountStr);\n'
            '        unitPriceField.removeAttribute("data-user-edited");',
            self.source,
        )

    def test_only_one_pending_suggestion_exists_per_form(self):
        # Qualquer nova oferta, qualquer digitação manual e qualquer
        # resultado "não encontrado"/erro limpam a oferta pendente antes
        # de decidir o que fazer — nunca duas ofertas acumuladas no mesmo
        # `hintEl`.
        self.assertGreaterEqual(self.source.count("clearPendingSuggestion();"), 5)

    def test_edit_modal_forms_no_longer_register_a_global_plan_or_date_listener(self):
        # P0-04/UX-001 — causa raiz dos N+1 listeners: só o form de
        # adicionar (identificado por NÃO estar dentro de um
        # `.kanban-modal-backdrop`) registra o listener global de
        # plano/data; só deve existir UMA chamada a esse `.forEach` no
        # arquivo inteiro.
        self.assertEqual(
            self.source.count("[commercialPlanField, startDateField, endDateField].forEach"), 1
        )
        self.assertIn(
            "if (!modalBackdrop) {",
            self.source,
        )

    def test_edit_modal_reconsults_price_only_when_opened_via_the_existing_trigger(self):
        # Reaproveita o próprio `[data-open-modal]` que já abre o modal
        # (`opportunity_detail.js`) — nenhum sistema de modal paralelo.
        self.assertIn(
            "var trigger = document.querySelector('[data-open-modal=\"' + modalBackdrop.id + '\"]');",
            self.source,
        )
        self.assertIn('trigger.addEventListener("click", check);', self.source)

    def test_own_item_fields_keep_triggering_recheck_regardless_of_form_kind(self):
        # equipment_model/service/tipo continuam disparando `check()` em
        # QUALQUER form (adicionar ou edição) — isso nunca fez parte do
        # bug e não pode regredir.
        own_field_listeners_index = self.source.index('modelField.addEventListener("change", check);')
        branch_index = self.source.index("if (!modalBackdrop) {")
        self.assertLess(own_field_listeners_index, branch_index)
        self.assertIn('serviceField.addEventListener("change", check);', self.source)
        self.assertIn('typeSelect.addEventListener("change", check);', self.source)

    def test_stale_async_response_never_wins_over_a_newer_one(self):
        # P0-04/UX-001 — concorrência assíncrona do frontend: um contador
        # de requisição por form garante que uma resposta antiga (ex.:
        # modelo A, já substituído por B e depois C) nunca mais seja
        # exibida/aplicada depois de uma resposta mais nova.
        self.assertIn("var thisRequestId = ++requestSeq;", self.source)
        self.assertIn("if (thisRequestId !== requestSeq) {\n            return;\n          }", self.source)

    def test_money_comparison_never_does_naive_string_equality(self):
        # "100" / "100.00" / "100,00" têm que comparar iguais — sem
        # introduzir nenhum cálculo de pricing em JS (só normalização de
        # separador decimal + arredondamento em centavos, nunca uma
        # regra de negócio nova).
        self.assertIn("function parseMoneyToCents(value) {", self.source)
        self.assertIn('text.replace(",", ".")', self.source)
        self.assertIn("Math.round(asNumber * 100)", self.source)
        self.assertIn("function moneyEquals(a, b) {", self.source)
        # Nenhuma comparação direta `===`/`==` entre o valor cru do campo
        # e o valor cru da resposta — sempre via `moneyEquals(...)`.
        self.assertNotIn("unitPriceField.value === data.unit_price", self.source)
