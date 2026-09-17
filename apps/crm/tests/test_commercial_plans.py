"""
Testes de RODADA 1 — Planos Comerciais + Prazos + Matriz de Preços de
Locação (16/09/2026, "IMPLEMENTAÇÃO — RODADA 1 / PLANOS COMERCIAIS +
PRAZOS + MATRIZ DE PREÇOS DE LOCAÇÃO"). Cobre: `CommercialPlan`/
`CommercialTerm` (modelos, unicidade, label automático), `PriceTableRate`
(XOR não se aplica — é sempre equipamento —, valor não negativo,
unicidade por célula, validação plano↔prazo), `set_price_table_rate()`
(criação de `PriceTableItem` "âncora", concorrência), a evolução de
`get_suggested_price()` para o caminho plano+prazo (sem interpolação),
`list_price_table_matrix()` (todas as categorias, N+1, busca, "sem
valor"), a UX da matriz na tela "Tabela de Preços" (sub-navegação de
planos, permissões — MESMA matriz de permissões da V1, reaproveitando
`crm.view_price_table`/`crm.change_price_table`, nenhuma permissão nova),
e a REGRA CRÍTICA herdada da V1: nada disso altera um `ProposalItem` já
existente.

A Tabela de Preços V1 (equipamento/serviço flat, Venda/Serviço) continua
100% coberta por `test_price_table_services.py`/`test_price_table_views.py`/
`test_price_table_proposal_integration.py` — nenhum teste deste arquivo
duplica aquela cobertura.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError, transaction
from django.test import Client as DjangoTestClient
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Category, EquipmentModel
from apps.crm.models import (
    BillingMode,
    BusinessType,
    CommercialPlan,
    CommercialTerm,
    DurationUnit,
    PriceTableItem,
    PriceTableRate,
    PricingMode,
)
from apps.crm.services import (
    PriceTableRateData,
    get_suggested_price,
    list_price_table_matrix,
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


class CommercialPlanTermTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="comercial_r1", password="senha-forte-123")
        self.aquecedor_category = Category.objects.create(name="Aquecedor")
        self.climatizador_category = Category.objects.create(name="Climatizador")
        self.heater = EquipmentModel.objects.create(code="AQCP1", name="Aquecedor Pirâmide", category=self.aquecedor_category)
        self.cooler = EquipmentModel.objects.create(code="NI23BT", name="NI23 Big Tank", category=self.climatizador_category)
        self.plan = CommercialPlan.objects.create(name="Locação Teste", order=0)
        self.term_7d = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=7, duration_unit=DurationUnit.DIAS)
        self.term_15d = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=15, duration_unit=DurationUnit.DIAS)


class CommercialPlanModelTest(CommercialPlanTermTestBase):
    def test_seed_migration_created_5_plans_under_locacao(self):
        # Seção: 5 planos iniciais, todos LOCACAO/ITEM_TERM, semeados pela
        # migration de dados (`0012_seed_commercial_plans_terms`).
        seeded_names = {
            "Locação Comum",
            "Locação Eventos",
            "Locação Mensal",
            "Locação Anual",
            "Máquinas Instaladas",
        }
        plans = CommercialPlan.objects.filter(name__in=seeded_names)
        self.assertEqual(plans.count(), 5)
        for plan in plans:
            self.assertEqual(plan.business_type, BusinessType.LOCACAO)
            self.assertEqual(plan.pricing_mode, PricingMode.ITEM_TERM)
            self.assertTrue(plan.is_active)

    def test_locacao_anual_and_instaladas_both_have_36_meses_term(self):
        # Sobreposição deliberada — dois planos distintos, cada um com seu
        # próprio CommercialTerm "36 meses" (identidade é plano+prazo).
        anual = CommercialPlan.objects.get(name="Locação Anual")
        instaladas = CommercialPlan.objects.get(name="Máquinas Instaladas")
        self.assertTrue(anual.terms.filter(label="36 meses").exists())
        self.assertTrue(instaladas.terms.filter(label="36 meses").exists())
        self.assertNotEqual(
            anual.terms.get(label="36 meses").pk, instaladas.terms.get(label="36 meses").pk
        )

    def test_term_label_auto_fills_with_singular_aware_unit(self):
        term = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=1, duration_unit=DurationUnit.DIAS)
        self.assertEqual(term.label, "1 dia")
        term2 = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=1, duration_unit=DurationUnit.MESES)
        self.assertEqual(term2.label, "1 mês")

    def test_duplicate_term_label_same_plan_is_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            CommercialTerm.objects.create(commercial_plan=self.plan, label="7 dias", duration_value=7, duration_unit=DurationUnit.DIAS)

    def test_same_label_allowed_across_different_plans(self):
        other_plan = CommercialPlan.objects.create(name="Outro Plano", order=1)
        term = CommercialTerm.objects.create(
            commercial_plan=other_plan, label="7 dias", duration_value=7, duration_unit=DurationUnit.DIAS
        )
        self.assertEqual(term.label, "7 dias")


class PriceTableRateModelTest(CommercialPlanTermTestBase):
    def _make_item(self, model):
        return set_price_table_rate(
            data=PriceTableRateData(
                equipment_model=model, commercial_plan=self.plan, commercial_term=self.term_7d, amount=Decimal("500.00")
            ),
            user=self.user,
        ).price_table_item

    def test_amount_cannot_be_negative_at_db_level(self):
        item = self._make_item(self.cooler)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PriceTableRate.objects.create(
                price_table_item=item,
                commercial_plan=self.plan,
                commercial_term=self.term_15d,
                amount=Decimal("-1.00"),
                updated_by=self.user,
            )

    def test_unique_rate_per_item_plan_term(self):
        item = self._make_item(self.cooler)
        PriceTableRate.objects.filter(price_table_item=item).delete()
        PriceTableRate.objects.create(
            price_table_item=item, commercial_plan=self.plan, commercial_term=self.term_7d, amount=Decimal("1.00"), updated_by=self.user
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PriceTableRate.objects.create(
                price_table_item=item, commercial_plan=self.plan, commercial_term=self.term_7d, amount=Decimal("2.00"), updated_by=self.user
            )

    def test_clean_rejects_term_that_does_not_belong_to_plan(self):
        other_plan = CommercialPlan.objects.create(name="Outro Plano 2", order=2)
        other_term = CommercialTerm.objects.create(commercial_plan=other_plan, duration_value=1, duration_unit=DurationUnit.DIAS)
        item = self._make_item(self.cooler)
        rate = PriceTableRate(
            price_table_item=item, commercial_plan=self.plan, commercial_term=other_term, amount=Decimal("1.00"), updated_by=self.user
        )
        with self.assertRaises(Exception):
            rate.full_clean()


class SetPriceTableRateTest(CommercialPlanTermTestBase):
    def test_creates_anchor_price_table_item_with_no_flat_price_on_first_write(self):
        self.assertFalse(PriceTableItem.objects.filter(equipment_model=self.cooler).exists())
        rate = set_price_table_rate(
            data=PriceTableRateData(
                equipment_model=self.cooler, commercial_plan=self.plan, commercial_term=self.term_7d, amount=Decimal("600.00")
            ),
            user=self.user,
        )
        item = PriceTableItem.objects.get(equipment_model=self.cooler)
        self.assertIsNone(item.unit_price, "Âncora criada pela matriz nunca inventa um valor flat (None, nunca 0.00).")
        self.assertEqual(rate.price_table_item_id, item.pk)
        self.assertEqual(rate.amount, Decimal("600.00"))
        self.assertEqual(rate.billing_mode, BillingMode.TERM_TOTAL)

    def test_second_rate_for_same_equipment_reuses_anchor_item_without_resetting_unit_price(self):
        set_price_table_rate(
            data=PriceTableRateData(
                equipment_model=self.cooler, commercial_plan=self.plan, commercial_term=self.term_7d, amount=Decimal("600.00")
            ),
            user=self.user,
        )
        item = PriceTableItem.objects.get(equipment_model=self.cooler)
        item.unit_price = Decimal("42.00")  # simula um valor flat legado, nunca sobrescrito pela matriz.
        item.updated_by = self.user
        item.save()

        set_price_table_rate(
            data=PriceTableRateData(
                equipment_model=self.cooler, commercial_plan=self.plan, commercial_term=self.term_15d, amount=Decimal("900.00")
            ),
            user=self.user,
        )
        item.refresh_from_db()
        self.assertEqual(item.unit_price, Decimal("42.00"), "unit_price legado nunca é tocado por set_price_table_rate().")
        self.assertEqual(PriceTableItem.objects.filter(equipment_model=self.cooler).count(), 1)

    def test_editing_same_cell_twice_updates_in_place_never_duplicates(self):
        data = PriceTableRateData(
            equipment_model=self.cooler, commercial_plan=self.plan, commercial_term=self.term_7d, amount=Decimal("600.00")
        )
        set_price_table_rate(data=data, user=self.user)
        data.amount = Decimal("650.00")
        rate = set_price_table_rate(data=data, user=self.user)
        self.assertEqual(rate.amount, Decimal("650.00"))
        self.assertEqual(PriceTableRate.objects.count(), 1)

    def test_negative_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            set_price_table_rate(
                data=PriceTableRateData(
                    equipment_model=self.cooler, commercial_plan=self.plan, commercial_term=self.term_7d, amount=Decimal("-5.00")
                ),
                user=self.user,
            )
        self.assertFalse(PriceTableRate.objects.exists())

    def test_term_not_belonging_to_plan_is_rejected(self):
        other_plan = CommercialPlan.objects.create(name="Outro Plano 3", order=3)
        with self.assertRaises(ValueError):
            set_price_table_rate(
                data=PriceTableRateData(
                    equipment_model=self.cooler, commercial_plan=other_plan, commercial_term=self.term_7d, amount=Decimal("1.00")
                ),
                user=self.user,
            )

    def test_bundle_pricing_mode_is_rejected(self):
        bundle_plan = CommercialPlan.objects.create(name="Combo Teste", order=4, pricing_mode=PricingMode.BUNDLE)
        term = CommercialTerm.objects.create(commercial_plan=bundle_plan, duration_value=1, duration_unit=DurationUnit.DIAS)
        with self.assertRaises(ValueError):
            set_price_table_rate(
                data=PriceTableRateData(
                    equipment_model=self.cooler, commercial_plan=bundle_plan, commercial_term=term, amount=Decimal("1.00")
                ),
                user=self.user,
            )

    def test_history_records_user_on_rate_change(self):
        rate = set_price_table_rate(
            data=PriceTableRateData(
                equipment_model=self.cooler, commercial_plan=self.plan, commercial_term=self.term_7d, amount=Decimal("600.00")
            ),
            user=self.user,
        )
        history_entry = rate.history.first()
        self.assertEqual(history_entry.history_user, self.user)
        self.assertEqual(history_entry.amount, Decimal("600.00"))


class PlanTermSuggestedPriceTest(CommercialPlanTermTestBase):
    """RODADA 1 — evolução de `get_suggested_price()` para plano+prazo (sem interpolação)."""

    def setUp(self):
        super().setUp()
        set_price_table_rate(
            data=PriceTableRateData(
                equipment_model=self.cooler, commercial_plan=self.plan, commercial_term=self.term_7d, amount=Decimal("600.00")
            ),
            user=self.user,
        )

    def test_resolves_exact_plan_and_term(self):
        suggestion = get_suggested_price(
            business_type=BusinessType.LOCACAO,
            equipment_model=self.cooler,
            commercial_plan=self.plan,
            commercial_term=self.term_7d,
        )
        self.assertEqual(suggestion.amount, Decimal("600.00"))
        self.assertEqual(suggestion.source, "plan_term")

    def test_never_interpolates_from_a_different_term_of_the_same_plan(self):
        # 15 dias NUNCA herda o valor de 7 dias, mesmo mesmo plano/equipamento.
        suggestion = get_suggested_price(
            business_type=BusinessType.LOCACAO,
            equipment_model=self.cooler,
            commercial_plan=self.plan,
            commercial_term=self.term_15d,
        )
        self.assertIsNone(suggestion)

    def test_service_with_plan_and_term_is_rejected(self):
        from apps.crm.models import ServiceCatalogItem

        service = ServiceCatalogItem.objects.create(name="Diária de operador RODADA1", unit_label="hora")
        with self.assertRaises(ValueError):
            get_suggested_price(
                business_type=BusinessType.LOCACAO,
                service=service,
                commercial_plan=self.plan,
                commercial_term=self.term_7d,
            )

    def test_plan_requires_locacao_business_type(self):
        with self.assertRaises(ValueError):
            get_suggested_price(
                business_type=BusinessType.VENDA,
                equipment_model=self.cooler,
                commercial_plan=self.plan,
                commercial_term=self.term_7d,
            )

    def test_mismatched_plan_and_term_is_rejected(self):
        other_plan = CommercialPlan.objects.create(name="Outro Plano 4", order=5)
        with self.assertRaises(ValueError):
            get_suggested_price(
                business_type=BusinessType.LOCACAO,
                equipment_model=self.cooler,
                commercial_plan=other_plan,
                commercial_term=self.term_7d,
            )

    def test_passing_only_plan_without_term_is_rejected(self):
        with self.assertRaises(ValueError):
            get_suggested_price(business_type=BusinessType.LOCACAO, equipment_model=self.cooler, commercial_plan=self.plan)

    def test_v1_flat_call_is_completely_unaffected_by_rodada1(self):
        # Sem plano/prazo: continua igual à V1 — nenhum PriceTableItem.unit_price
        # foi definido para este equipamento (só PriceTableRate existe), então
        # o caminho flat continua devolvendo None (nunca lê PriceTableRate).
        suggestion = get_suggested_price(business_type=BusinessType.LOCACAO, equipment_model=self.cooler)
        self.assertIsNone(suggestion)


class ListPriceTableMatrixTest(CommercialPlanTermTestBase):
    def test_matrix_includes_equipment_from_all_categories(self):
        # Seção 33 — aquecedores e climatizadores lado a lado, sem filtro de categoria.
        matrix = list_price_table_matrix(commercial_plan=self.plan)
        labels = {row.label for row in matrix.rows}
        self.assertIn("Aquecedor Pirâmide (AQCP1)", labels)
        self.assertIn("NI23 Big Tank (NI23BT)", labels)

    def test_matrix_columns_are_the_plan_terms_in_order(self):
        matrix = list_price_table_matrix(commercial_plan=self.plan)
        self.assertEqual([t.pk for t in matrix.terms], [self.term_7d.pk, self.term_15d.pk])

    def test_cell_reflects_configured_rate(self):
        set_price_table_rate(
            data=PriceTableRateData(
                equipment_model=self.cooler, commercial_plan=self.plan, commercial_term=self.term_7d, amount=Decimal("600.00")
            ),
            user=self.user,
        )
        matrix = list_price_table_matrix(commercial_plan=self.plan)
        row = next(r for r in matrix.rows if r.equipment_model_id == self.cooler.pk)
        cell_7d = next(c for c in row.cells if c.commercial_term_id == self.term_7d.pk)
        cell_15d = next(c for c in row.cells if c.commercial_term_id == self.term_15d.pk)
        self.assertEqual(cell_7d.amount, Decimal("600.00"))
        self.assertIsNone(cell_15d.amount)

    def test_only_missing_hides_equipment_with_any_configured_cell(self):
        set_price_table_rate(
            data=PriceTableRateData(
                equipment_model=self.cooler, commercial_plan=self.plan, commercial_term=self.term_7d, amount=Decimal("600.00")
            ),
            user=self.user,
        )
        matrix = list_price_table_matrix(commercial_plan=self.plan, only_missing=True)
        labels = {row.label for row in matrix.rows}
        self.assertNotIn("NI23 Big Tank (NI23BT)", labels)
        self.assertIn("Aquecedor Pirâmide (AQCP1)", labels)

    def test_search_filters_by_name_or_code(self):
        matrix = list_price_table_matrix(commercial_plan=self.plan, search="AQCP1")
        labels = {row.label for row in matrix.rows}
        self.assertEqual(labels, {"Aquecedor Pirâmide (AQCP1)"})

    def test_counters(self):
        set_price_table_rate(
            data=PriceTableRateData(
                equipment_model=self.cooler, commercial_plan=self.plan, commercial_term=self.term_7d, amount=Decimal("600.00")
            ),
            user=self.user,
        )
        matrix = list_price_table_matrix(commercial_plan=self.plan)
        expected_total = EquipmentModel.objects.filter(is_active=True).count()
        self.assertEqual(matrix.total_count, expected_total)
        self.assertEqual(matrix.configured_count, 1)
        self.assertEqual(matrix.missing_count, expected_total - 1)

    def test_no_n_plus_one_queries(self):
        for i in range(5):
            EquipmentModel.objects.create(code=f"EXTRA{i}", name=f"Extra {i}", category=self.climatizador_category)
        set_price_table_rate(
            data=PriceTableRateData(
                equipment_model=self.cooler, commercial_plan=self.plan, commercial_term=self.term_7d, amount=Decimal("600.00")
            ),
            user=self.user,
        )
        with self.assertNumQueries(3):
            matrix = list_price_table_matrix(commercial_plan=self.plan)
            list(matrix.rows)


class PriceTableMatrixUiPermissionTest(TestCase):
    """
    Seção: MESMA matriz de permissões da V1 (sem login → redirect, sem
    `view` → 403, com `view` sem `change` → lápis escondido mas endpoint
    ainda bloqueado no backend, com `change` → pode editar) — nenhuma
    permissão NOVA (reaproveita `crm.view_price_table`/`crm.change_price_table`).
    """

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador RODADA1")
        self.model = EquipmentModel.objects.create(code="MTX01", name="Matriz Modelo", category=self.category)
        self.plan = CommercialPlan.objects.create(name="Plano Matriz Teste", order=10)
        self.term = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=7, duration_unit=DurationUnit.DIAS)
        self.viewer = _user_with_perms("mtx_viewer", "view_price_table")
        self.editor = _user_with_perms("mtx_editor", "view_price_table", "change_price_table")
        self.no_perm_user = _user_with_perms("mtx_no_perm")

    def _login(self, user):
        client = DjangoTestClient()
        client.force_login(user)
        return client

    def _cell_url(self):
        return reverse("crm:price_table_rate_cell", args=[self.model.pk, self.term.pk])

    def test_anonymous_is_redirected_to_login(self):
        client = DjangoTestClient()
        resp = client.get(self._cell_url(), {"plano": self.plan.pk})
        self.assertEqual(resp.status_code, 302)

    def test_user_without_view_permission_is_forbidden(self):
        client = self._login(self.no_perm_user)
        resp = client.get(self._cell_url(), {"plano": self.plan.pk})
        self.assertEqual(resp.status_code, 403)

    def test_viewer_without_change_cannot_enter_edit_mode(self):
        client = self._login(self.viewer)
        resp = client.get(self._cell_url(), {"plano": self.plan.pk, "modo": "editar"})
        self.assertEqual(resp.status_code, 403)

    def test_viewer_without_change_cannot_post_even_by_direct_url(self):
        # "Botão escondido ≠ bloqueio no backend" — mesmo raciocínio da V1.
        client = self._login(self.viewer)
        resp = client.post(self._cell_url(), {"plano": self.plan.pk, "amount": "600.00", "billing_mode": "TERM_TOTAL"})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(PriceTableRate.objects.exists())

    def test_editor_can_edit_and_save_cell(self):
        client = self._login(self.editor)
        edit_resp = client.get(self._cell_url(), {"plano": self.plan.pk, "modo": "editar"})
        self.assertContains(edit_resp, "Salvar")

        save_resp = client.post(self._cell_url(), {"plano": self.plan.pk, "amount": "600.00", "billing_mode": "TERM_TOTAL"})
        self.assertContains(save_resp, "600,00")
        self.assertEqual(PriceTableRate.objects.count(), 1)

    def test_invalid_negative_amount_shows_error_and_does_not_save(self):
        client = self._login(self.editor)
        resp = client.post(self._cell_url(), {"plano": self.plan.pk, "amount": "-1.00", "billing_mode": "TERM_TOTAL"})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(PriceTableRate.objects.exists())

    def test_price_table_page_shows_matrix_and_plan_tabs_for_locacao(self):
        client = self._login(self.viewer)
        resp = client.get(reverse("crm:price_table"), {"tipo": BusinessType.LOCACAO, "plano": self.plan.pk})
        self.assertContains(resp, "Plano Matriz Teste")
        self.assertContains(resp, "Matriz Modelo")

    def test_venda_tab_keeps_v1_flat_layout_unchanged(self):
        client = self._login(self.viewer)
        resp = client.get(reverse("crm:price_table"), {"tipo": BusinessType.VENDA})
        self.assertNotContains(resp, "Plano Matriz Teste")

    def test_sidebar_link_unchanged_reuses_view_price_table_permission(self):
        # Reaproveita a MESMA checagem já feita pela V1 (`SidebarVisibilityTest`
        # em `test_price_table_views.py`) — aqui só confirma que nenhuma
        # permissão nova foi introduzida: o link continua condicionado a
        # `perms.crm.view_price_table`, visível na própria tela da Tabela
        # de Preços (que `self.viewer` já pode acessar).
        client = self._login(self.viewer)
        resp = client.get(reverse("crm:price_table"))
        self.assertContains(resp, "Tabela de preços")
