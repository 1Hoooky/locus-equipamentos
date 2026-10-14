"""
Testes de RODADA 2 — Integração da Matriz de Preços com a Proposta
(13/10/2026). Cobre `get_suggested_rental_price()`/`_contracted_rental_days()`/
`_calendar_month_limit()` (`apps/crm/services.py`), a extensão de
`SuggestedPriceView` para Locação com plano+datas, e a migration de dados
`0016_rodada2_grade_dias_locacao_comum_eventos` (grade 1/5/15/30,
inativação de 3/7 dias, idempotência).

A Tabela de Preços V1 (flat) e a RODADA 1 (matriz, resolução exata
plano+prazo) continuam cobertas por `test_price_table_services.py`/
`test_price_table_proposal_integration.py`/`test_commercial_plans.py` —
nenhum teste aqui duplica aquela cobertura; os testes de regressão de
Venda/Serviço deste arquivo só confirmam que o caminho novo não os afeta.
"""

import importlib
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client as DjangoTestClient
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.crm.models import (
    BillingMode,
    BusinessType,
    CommercialPlan,
    CommercialSource,
    CommercialTerm,
    DurationUnit,
    Opportunity,
    OpportunityStage,
    PriceTableItem,
    PricingMode,
)
from apps.crm.services import (
    PriceTableRateData,
    RentalPriceSuggestion,
    _calendar_month_limit,
    _contracted_rental_days,
    get_suggested_rental_price,
    set_price_table_rate,
)

User = get_user_model()

_migration = importlib.import_module("apps.crm.migrations.0016_rodada2_grade_dias_locacao_comum_eventos")


class _FakeAppsRegistry:
    """Mímica mínima do `apps` de migration — mesma técnica de `test_backfill_principal_locations.py`."""

    def get_model(self, app_label, model_name):
        from django.apps import apps as real_apps

        return real_apps.get_model(app_label, model_name)


def _run_migration_forward():
    _migration.migrate_grade_forward(apps=_FakeAppsRegistry(), schema_editor=None)


def _run_migration_backward():
    _migration.migrate_grade_backward(apps=_FakeAppsRegistry(), schema_editor=None)


def _user_with_perms(username, *codenames):
    user = User.objects.create_user(username=username, password="senha-forte-123")
    if codenames:
        perms = Permission.objects.filter(codename__in=codenames, content_type__app_label="crm")
        group, _ = Group.objects.get_or_create(name=f"perm-{username}")
        group.permissions.set(perms)
        user.groups.add(group)
    return user


# ---------------------------------------------------------------------------
# _contracted_rental_days() — semântica comercial de dias (seção 1 da
# revisão: "+1", mesma data = 1 dia). Nunca a mesma função de
# `apps.crm.pdf._period_label()` (exibição, sem "+1") — testado aqui para
# deixar a diferença explícita e travada.
# ---------------------------------------------------------------------------
class ContractedRentalDaysTest(TestCase):
    """
    Regra comercial DEFINITIVA de dias (corrigida em 14/10/2026 a partir
    de bug reportado em teste manual): `max(1, (end-start).days)` — NUNCA
    `(end-start).days + 1`. Dia de início == dia de fim é 1 dia; 1 dia de
    calendário de diferença também é 1 dia (não 2); só a partir de 2 dias
    de calendário de diferença a duração comercial passa a ser 2, e assim
    por diante — sem piso artificial além do mínimo de 1.
    """

    def test_same_date_is_one_day(self):
        self.assertEqual(_contracted_rental_days(date(2026, 10, 14), date(2026, 10, 14)), 1)

    def test_next_day_is_still_one_day(self):
        # Bug reportado: dia 14 → dia 15 estava virando 2 dias (e puxando
        # o prazo de 5 dias). O correto é 1 dia.
        self.assertEqual(_contracted_rental_days(date(2026, 10, 14), date(2026, 10, 15)), 1)

    def test_six_calendar_days_apart_is_six_rental_days(self):
        self.assertEqual(_contracted_rental_days(date(2026, 9, 24), date(2026, 9, 30)), 6)

    def test_display_period_label_is_unaffected(self):
        # `_period_label()` (pdf.py) continua "(end-start).days", sem
        # piso de 1 — quando início==fim ele mostra "—" (0 dias não é
        # exibido), enquanto a duração COMERCIAL (`_contracted_rental_days`)
        # tem piso de 1. Esse é o ponto exato onde as duas semânticas
        # divergem, provando que continuam desacopladas mesmo após a
        # correção da regra de dias.
        from apps.crm.pdf import _period_label

        class _FakeVersion:
            contracted_start_date = date(2026, 10, 14)
            contracted_end_date = date(2026, 10, 14)

        self.assertEqual(_period_label(_FakeVersion(), is_venda=False), "—")
        self.assertEqual(_contracted_rental_days(date(2026, 10, 14), date(2026, 10, 14)), 1)


# ---------------------------------------------------------------------------
# _calendar_month_limit() — mês-calendário real, nunca 30 dias/mês nem
# 365/12 (seção 4/5 da revisão).
# ---------------------------------------------------------------------------
class CalendarMonthLimitTest(TestCase):
    def test_plain_month_add(self):
        self.assertEqual(_calendar_month_limit(date(2026, 1, 15), 1), date(2026, 2, 15))

    def test_day_31_clamps_to_last_day_of_shorter_month(self):
        self.assertEqual(_calendar_month_limit(date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_day_30_clamps_in_february(self):
        self.assertEqual(_calendar_month_limit(date(2026, 1, 30), 1), date(2026, 2, 28))

    def test_day_29_clamps_in_non_leap_february(self):
        self.assertEqual(_calendar_month_limit(date(2026, 1, 29), 1), date(2026, 2, 28))

    def test_day_29_kept_in_leap_year_february(self):
        # 2028 é bissexto.
        self.assertEqual(_calendar_month_limit(date(2027, 1, 29), 13), date(2028, 2, 29))

    def test_leap_year_day_29_rolled_forward_twelve_months_to_non_leap_year(self):
        self.assertEqual(_calendar_month_limit(date(2028, 2, 29), 12), date(2029, 2, 28))

    def test_twelve_months_same_day_next_year(self):
        self.assertEqual(_calendar_month_limit(date(2026, 10, 13), 12), date(2027, 10, 13))

    def test_crosses_year_boundary(self):
        self.assertEqual(_calendar_month_limit(date(2026, 11, 20), 3), date(2027, 2, 20))


class RentalPriceServiceTestBase(TestCase):
    def setUp(self):
        self.user = _user_with_perms("comercial_r2", "view_opportunities", "change_opportunities", "add_opportunities")
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(code="NI23BT", name="NI23 Big Tank", category=self.category)
        self.plan = CommercialPlan.objects.create(name="Plano Dias Teste", business_type=BusinessType.LOCACAO, order=0)
        self.term_1 = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=1, duration_unit=DurationUnit.DIAS)
        self.term_5 = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=5, duration_unit=DurationUnit.DIAS)
        self.term_15 = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=15, duration_unit=DurationUnit.DIAS)
        self.term_30 = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=30, duration_unit=DurationUnit.DIAS)

    def _set_rate(self, term, amount, billing_mode=BillingMode.TERM_TOTAL):
        return set_price_table_rate(
            data=PriceTableRateData(
                equipment_model=self.model, commercial_plan=self.plan, commercial_term=term, amount=Decimal(amount), billing_mode=billing_mode
            ),
            user=self.user,
        )

    def _suggest(self, start, end, plan=None):
        return get_suggested_rental_price(
            equipment_model=self.model,
            commercial_plan=plan or self.plan,
            contracted_start_date=start,
            contracted_end_date=end,
        )


class DayGridSelectionTest(RentalPriceServiceTestBase):
    """
    Grade 1/5/15/30 — exemplos obrigatórios da regra comercial DEFINITIVA
    de dias (corrigida em 14/10/2026): `max(1, (end-start).days)`. Início
    fixo no dia 14 — os mesmos números do bug report original:

    14→14 = 1 dia  → termo 1
    14→15 = 1 dia  → termo 1
    14→16 = 2 dias → termo 5
    14→19 = 5 dias → termo 5
    14→20 = 6 dias → termo 15
    14→29 = 15 dias → termo 15
    14→30 = 16 dias → termo 30
    acima de 30 → found=False
    """

    START = date(2026, 10, 14)

    def setUp(self):
        super().setUp()
        self._set_rate(self.term_1, "300.00")
        self._set_rate(self.term_5, "700.00")
        self._set_rate(self.term_15, "1300.00")
        self._set_rate(self.term_30, "2200.00")

    def _end(self, calendar_days_apart):
        return self.START + timedelta(days=calendar_days_apart)

    def test_same_date_is_one_day_picks_term_1(self):
        result = self._suggest(self.START, self._end(0))
        self.assertTrue(result.found)
        self.assertEqual(result.commercial_term, self.term_1)
        self.assertEqual(result.amount, Decimal("300.00"))

    def test_14_to_15_is_one_day_picks_term_1(self):
        # Exemplo exato do bug report: isto NUNCA pode virar 2 dias.
        result = self._suggest(self.START, self._end(1))
        self.assertEqual(_contracted_rental_days(self.START, self._end(1)), 1)
        self.assertTrue(result.found)
        self.assertEqual(result.commercial_term, self.term_1)

    def test_14_to_16_is_two_days_picks_term_5(self):
        result = self._suggest(self.START, self._end(2))
        self.assertEqual(_contracted_rental_days(self.START, self._end(2)), 2)
        self.assertEqual(result.commercial_term, self.term_5)

    def test_exactly_5_days_picks_term_5(self):
        result = self._suggest(self.START, self._end(5))
        self.assertEqual(result.commercial_term, self.term_5)

    def test_6_days_picks_term_15(self):
        result = self._suggest(self.START, self._end(6))
        self.assertEqual(result.commercial_term, self.term_15)

    def test_10_days_picks_term_15(self):
        result = self._suggest(self.START, self._end(10))
        self.assertEqual(result.commercial_term, self.term_15)

    def test_exactly_15_days_picks_term_15(self):
        result = self._suggest(self.START, self._end(15))
        self.assertEqual(result.commercial_term, self.term_15)

    def test_16_days_picks_term_30(self):
        result = self._suggest(self.START, self._end(16))
        self.assertEqual(_contracted_rental_days(self.START, self._end(16)), 16)
        self.assertEqual(result.commercial_term, self.term_30)

    def test_25_days_picks_term_30(self):
        result = self._suggest(self.START, self._end(25))
        self.assertEqual(result.commercial_term, self.term_30)

    def test_exactly_30_days_picks_term_30(self):
        result = self._suggest(self.START, self._end(30))
        self.assertEqual(result.commercial_term, self.term_30)

    def test_above_30_without_bigger_term_returns_not_found(self):
        result = self._suggest(self.START, self._end(31))
        self.assertFalse(result.found)
        self.assertIn("maior prazo disponível", result.reason)

    def test_never_picks_lower_term(self):
        result = self._suggest(self.START, self._end(6))
        self.assertNotEqual(result.commercial_term, self.term_5)
        self.assertNotEqual(result.commercial_term, self.term_1)


class TermWithoutRateTest(RentalPriceServiceTestBase):
    def test_correct_term_without_rate_never_jumps_to_next_configured_term(self):
        # Só 15 dias tem preço — um contrato de 4 dias (→ termo correto:
        # 5 dias) NUNCA deve "aproveitar" o preço de 15 dias.
        self._set_rate(self.term_15, "1300.00")
        result = self._suggest(date(2026, 10, 1), date(2026, 10, 4))
        self.assertFalse(result.found)
        self.assertEqual(result.commercial_term, self.term_5)
        self.assertIn("5 dias", result.reason)


class NoTermsOrMissingDataTest(RentalPriceServiceTestBase):
    def test_plan_without_terms_returns_not_found(self):
        empty_plan = CommercialPlan.objects.create(name="Plano Vazio", business_type=BusinessType.LOCACAO, order=1)
        result = self._suggest(date(2026, 10, 1), date(2026, 10, 2), plan=empty_plan)
        self.assertFalse(result.found)

    def test_missing_start_date_returns_not_found_never_crashes(self):
        result = get_suggested_rental_price(
            equipment_model=self.model, commercial_plan=self.plan, contracted_start_date=None, contracted_end_date=date(2026, 10, 2)
        )
        self.assertFalse(result.found)
        self.assertIn("data", result.reason.lower())

    def test_missing_end_date_returns_not_found_never_crashes(self):
        result = get_suggested_rental_price(
            equipment_model=self.model, commercial_plan=self.plan, contracted_start_date=date(2026, 10, 1), contracted_end_date=None
        )
        self.assertFalse(result.found)

    def test_end_before_start_returns_not_found_never_crashes(self):
        result = self._suggest(date(2026, 10, 10), date(2026, 10, 1))
        self.assertFalse(result.found)

    def test_equipment_without_any_rate_returns_not_found(self):
        result = self._suggest(date(2026, 10, 1), date(2026, 10, 1))
        self.assertFalse(result.found)


class PlanIsolationTest(RentalPriceServiceTestBase):
    def test_plan_a_never_uses_rate_configured_for_plan_b(self):
        other_plan = CommercialPlan.objects.create(name="Outro Plano", business_type=BusinessType.LOCACAO, order=1)
        other_term = CommercialTerm.objects.create(commercial_plan=other_plan, duration_value=1, duration_unit=DurationUnit.DIAS)
        set_price_table_rate(
            data=PriceTableRateData(equipment_model=self.model, commercial_plan=other_plan, commercial_term=other_term, amount=Decimal("999.00")),
            user=self.user,
        )
        result = self._suggest(date(2026, 10, 1), date(2026, 10, 1))
        self.assertFalse(result.found)


class MixedDurationUnitPlanTest(RentalPriceServiceTestBase):
    def test_active_terms_mixing_dias_and_meses_never_pick_an_algorithm_arbitrarily(self):
        mixed_plan = CommercialPlan.objects.create(name="Plano Misto", business_type=BusinessType.LOCACAO, order=2)
        CommercialTerm.objects.create(commercial_plan=mixed_plan, duration_value=5, duration_unit=DurationUnit.DIAS)
        CommercialTerm.objects.create(commercial_plan=mixed_plan, duration_value=12, duration_unit=DurationUnit.MESES)
        result = self._suggest(date(2026, 10, 1), date(2026, 10, 5), plan=mixed_plan)
        self.assertFalse(result.found)
        self.assertIn("mistura", result.reason.lower())

    def test_inactive_term_of_a_different_unit_does_not_count_as_mixed(self):
        # Só termos ATIVOS contam para a checagem de unidade mista.
        plan = CommercialPlan.objects.create(name="Plano Quase Misto", business_type=BusinessType.LOCACAO, order=3)
        active_term = CommercialTerm.objects.create(commercial_plan=plan, duration_value=5, duration_unit=DurationUnit.DIAS)
        CommercialTerm.objects.create(commercial_plan=plan, duration_value=12, duration_unit=DurationUnit.MESES, is_active=False)
        set_price_table_rate(
            data=PriceTableRateData(equipment_model=self.model, commercial_plan=plan, commercial_term=active_term, amount=Decimal("500.00")),
            user=self.user,
        )
        result = self._suggest(date(2026, 10, 1), date(2026, 10, 5), plan=plan)
        self.assertTrue(result.found)
        self.assertEqual(result.commercial_term, active_term)


class InactiveTermIsNeverSelectedTest(RentalPriceServiceTestBase):
    def test_inactive_term_is_skipped_even_with_a_rate_configured(self):
        self._set_rate(self.term_5, "700.00")
        self.term_5.is_active = False
        self.term_5.save(update_fields=["is_active"])
        result = self._suggest(date(2026, 10, 1), date(2026, 10, 4))
        # "5 dias" está inativo, mesmo tendo preço — pula direto para o
        # próximo termo ATIVO (15 dias), que não tem preço cadastrado,
        # por isso `found=False`. Nunca usa o inferior (1 dia), nunca
        # "aproveita" o preço do inativo.
        self.assertEqual(result.commercial_term, self.term_15)
        self.assertFalse(result.found)


class MonthlyPlanCalendarTest(RentalPriceServiceTestBase):
    def setUp(self):
        self.user = _user_with_perms("comercial_r2_meses", "view_opportunities")
        self.category = Category.objects.create(name="Climatizador Industrial")
        self.model = EquipmentModel.objects.create(code="CLI60", name="Climatizador 60mil BTUs", category=self.category)
        self.plan = CommercialPlan.objects.create(name="Locação Anual Teste", business_type=BusinessType.LOCACAO, order=0)
        self.term_12m = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=12, duration_unit=DurationUnit.MESES)
        self.term_24m = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=24, duration_unit=DurationUnit.MESES)
        self.term_36m = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=36, duration_unit=DurationUnit.MESES)
        self._set_rate(self.term_12m, "12000.00", billing_mode=BillingMode.MONTHLY)
        self._set_rate(self.term_24m, "20000.00", billing_mode=BillingMode.MONTHLY)
        self._set_rate(self.term_36m, "27000.00", billing_mode=BillingMode.MONTHLY)

    def test_exactly_twelve_months_picks_12_month_term(self):
        result = self._suggest(date(2026, 10, 13), date(2027, 10, 13))
        self.assertTrue(result.found)
        self.assertEqual(result.commercial_term, self.term_12m)

    def test_slightly_less_than_twelve_months_still_picks_12_month_term(self):
        result = self._suggest(date(2026, 10, 13), date(2027, 10, 10))
        self.assertEqual(result.commercial_term, self.term_12m)

    def test_slightly_more_than_twelve_months_picks_next_term(self):
        result = self._suggest(date(2026, 10, 13), date(2027, 10, 20))
        self.assertEqual(result.commercial_term, self.term_24m)

    def test_start_on_day_31_clamped_correctly(self):
        result = self._suggest(date(2026, 1, 31), date(2027, 1, 28))
        self.assertEqual(result.commercial_term, self.term_12m)

    def test_leap_year_february_29_start(self):
        result = self._suggest(date(2028, 2, 29), date(2029, 2, 28))
        self.assertEqual(result.commercial_term, self.term_12m)

    def test_monthly_billing_mode_never_multiplies_amount(self):
        result = self._suggest(date(2026, 10, 13), date(2027, 10, 13))
        self.assertEqual(result.amount, Decimal("12000.00"))
        self.assertEqual(result.billing_mode, BillingMode.MONTHLY)

    def test_beyond_largest_term_returns_not_found(self):
        result = self._suggest(date(2026, 10, 13), date(2030, 10, 13))
        self.assertFalse(result.found)


class MaquinasInstaladasCalendarTest(RentalPriceServiceTestBase):
    """Mesma grade real (36/48/60 meses) — confirma que nenhum plano de meses fica fora da RODADA 2."""

    def setUp(self):
        self.user = _user_with_perms("comercial_r2_maquinas", "view_opportunities")
        category = Category.objects.create(name="Máquina Instalada")
        self.model = EquipmentModel.objects.create(code="MQ01", name="Máquina Instalada 01", category=category)
        self.plan = CommercialPlan.objects.create(name="Máquinas Instaladas Teste", business_type=BusinessType.LOCACAO, order=0)
        self.term_36 = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=36, duration_unit=DurationUnit.MESES)
        self.term_48 = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=48, duration_unit=DurationUnit.MESES)
        self.term_60 = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=60, duration_unit=DurationUnit.MESES)
        self._set_rate(self.term_36, "50000.00")
        self._set_rate(self.term_48, "65000.00")
        self._set_rate(self.term_60, "80000.00")

    def test_36_48_60_grid_resolves(self):
        result = self._suggest(date(2026, 1, 1), date(2029, 1, 1))
        self.assertEqual(result.commercial_term, self.term_36)


# ---------------------------------------------------------------------------
# Endpoint `SuggestedPriceView` — RODADA 2.
# ---------------------------------------------------------------------------
class SuggestedPriceEndpointRentalTest(TestCase):
    def setUp(self):
        self.user = _user_with_perms("vendedor_r2", "view_opportunities", "change_opportunities", "add_opportunities")
        self.django_client = DjangoTestClient()
        self.django_client.login(username="vendedor_r2", password="senha-forte-123")

        self.client_obj = Client.objects.create(company_name="Cliente Rodada 2")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage = OpportunityStage.objects.create(name="Novo", order=1)
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(code="NI23BT", name="NI23 Big Tank", category=self.category)

        self.opportunity = Opportunity.objects.create(
            client=self.client_obj, title="Oportunidade Rodada 2", source=self.source, stage=self.stage,
            owner=self.user, created_by=self.user, business_type=BusinessType.LOCACAO,
        )
        self.plan = CommercialPlan.objects.create(name="Plano Endpoint Teste", business_type=BusinessType.LOCACAO, order=0)
        self.term_5 = CommercialTerm.objects.create(commercial_plan=self.plan, duration_value=5, duration_unit=DurationUnit.DIAS)
        set_price_table_rate(
            data=PriceTableRateData(equipment_model=self.model, commercial_plan=self.plan, commercial_term=self.term_5, amount=Decimal("700.00")),
            user=self.user,
        )

        self.url = reverse("crm:proposal_suggested_price", args=[self.opportunity.pk])

    def _get(self, **params):
        return self.django_client.get(self.url, params)

    def test_locacao_with_plan_and_dates_returns_matrix_price(self):
        response = self._get(equipment_model=self.model.pk, commercial_plan=self.plan.pk, contracted_start_date="2026-10-01", contracted_end_date="2026-10-04")
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["found"])
        self.assertEqual(data["unit_price"], "700.00")
        self.assertEqual(data["commercial_term"], "5 dias")
        self.assertIn("contracted_duration", data)

    def test_locacao_without_plan_returns_not_found_with_reason_never_falls_back_to_flat(self):
        response = self._get(equipment_model=self.model.pk)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["found"])
        self.assertIn("plano", data["reason"].lower())

    def test_locacao_without_dates_returns_not_found_with_reason(self):
        response = self._get(equipment_model=self.model.pk, commercial_plan=self.plan.pk)
        data = response.json()
        self.assertFalse(data["found"])
        self.assertIn("data", data["reason"].lower())

    def test_invalid_commercial_plan_id_returns_not_found_never_500(self):
        response = self._get(equipment_model=self.model.pk, commercial_plan=999999, contracted_start_date="2026-10-01", contracted_end_date="2026-10-04")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["found"])

    def test_commercial_plan_from_another_business_type_is_rejected(self):
        venda_plan = CommercialPlan.objects.create(name="Plano Venda Indevido", business_type=BusinessType.VENDA, order=1)
        response = self._get(equipment_model=self.model.pk, commercial_plan=venda_plan.pk, contracted_start_date="2026-10-01", contracted_end_date="2026-10-04")
        self.assertFalse(response.json()["found"])

    def test_get_never_creates_any_record(self):
        from apps.crm.models import PriceTableRate, Proposal, ProposalVersion

        proposal_count = Proposal.objects.count()
        version_count = ProposalVersion.objects.count()
        rate_count = PriceTableRate.objects.count()
        term_count = CommercialTerm.objects.count()

        self._get(equipment_model=self.model.pk, commercial_plan=self.plan.pk, contracted_start_date="2026-10-01", contracted_end_date="2026-10-04")

        self.assertEqual(Proposal.objects.count(), proposal_count)
        self.assertEqual(ProposalVersion.objects.count(), version_count)
        self.assertEqual(PriceTableRate.objects.count(), rate_count)
        self.assertEqual(CommercialTerm.objects.count(), term_count)

    def test_anonymous_is_redirected_to_login(self):
        anon_client = DjangoTestClient()
        response = anon_client.get(self.url, {"equipment_model": self.model.pk})
        self.assertEqual(response.status_code, 302)

    def test_user_without_view_opportunities_is_forbidden(self):
        no_perm_user = User.objects.create_user(username="sem_permissao_r2", password="senha-forte-123")
        other_client = DjangoTestClient()
        other_client.login(username="sem_permissao_r2", password="senha-forte-123")
        response = other_client.get(self.url, {"equipment_model": self.model.pk})
        self.assertEqual(response.status_code, 403)

    def test_any_user_with_view_opportunities_sees_any_opportunity_same_as_detail_view(self):
        # Documenta explicitamente a política real encontrada na
        # auditoria: `crm.view_opportunities` é visibilidade GLOBAL, sem
        # escopo por owner/equipe — `SuggestedPriceView` segue a MESMA
        # política de `OpportunityDetailView` (nenhuma política nova
        # criada nesta rodada).
        other_user = _user_with_perms("outro_vendedor_r2", "view_opportunities")
        other_client = DjangoTestClient()
        other_client.login(username="outro_vendedor_r2", password="senha-forte-123")
        detail_response = other_client.get(reverse("crm:opportunity_detail", args=[self.opportunity.pk]))
        suggested_price_response = other_client.get(self.url, {"equipment_model": self.model.pk})
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(suggested_price_response.status_code, 200)


class SuggestedPriceEndpointVendaServicoRegressionTest(TestCase):
    """Regressão: Venda/Serviço nunca passam pelo caminho novo da RODADA 2."""

    def setUp(self):
        self.user = _user_with_perms("vendedor_regressao_r2", "view_opportunities", "change_opportunities", "add_opportunities")
        self.django_client = DjangoTestClient()
        self.django_client.login(username="vendedor_regressao_r2", password="senha-forte-123")
        self.client_obj = Client.objects.create(company_name="Cliente Regressão R2")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage = OpportunityStage.objects.create(name="Novo", order=1)
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(code="NI23BT", name="NI23 Big Tank", category=self.category)

    def _opportunity(self, business_type):
        return Opportunity.objects.create(
            client=self.client_obj, title=f"Oportunidade {business_type}", source=self.source, stage=self.stage,
            owner=self.user, created_by=self.user, business_type=business_type,
        )

    def test_venda_ignores_commercial_plan_param_and_uses_flat_price_table(self):
        from apps.crm.services import PriceTableItemData, set_price_table_item

        opportunity = self._opportunity(BusinessType.VENDA)
        set_price_table_item(data=PriceTableItemData(business_type=BusinessType.VENDA, equipment_model=self.model, unit_price=Decimal("9999.00")), user=self.user)
        plan = CommercialPlan.objects.create(name="Plano Que Não Deveria Ser Usado", business_type=BusinessType.LOCACAO, order=0)

        url = reverse("crm:proposal_suggested_price", args=[opportunity.pk])
        response = self.django_client.get(url, {"equipment_model": self.model.pk, "commercial_plan": plan.pk})
        data = response.json()
        self.assertTrue(data["found"])
        self.assertEqual(data["unit_price"], "9999.00")
        self.assertNotIn("commercial_term", data)

    def test_locacao_service_item_keeps_using_flat_price_table(self):
        from apps.crm.models import ServiceCatalogItem
        from apps.crm.services import PriceTableItemData, set_price_table_item

        opportunity = self._opportunity(BusinessType.LOCACAO)
        service = ServiceCatalogItem.objects.create(name="Diária de operador", unit_label="hora")
        set_price_table_item(data=PriceTableItemData(business_type=BusinessType.LOCACAO, service=service, unit_price=Decimal("150.00")), user=self.user)

        url = reverse("crm:proposal_suggested_price", args=[opportunity.pk])
        response = self.django_client.get(url, {"service": service.pk})
        data = response.json()
        self.assertTrue(data["found"])
        self.assertEqual(data["unit_price"], "150.00")


# ---------------------------------------------------------------------------
# Migration 0016 — grade 1/5/15/30, idempotência.
# ---------------------------------------------------------------------------
class GradeMigrationTest(TestCase):
    def setUp(self):
        # Simula o estado pós-`0012_seed_commercial_plans_terms` sem
        # depender da migration de seed já ter corrido neste TestCase
        # (o banco de teste já aplica todas as migrations reais antes
        # da suíte rodar — isto só garante um estado conhecido/isolado
        # para o teste, igual ao padrão de `CommercialPlanTermTestBase`).
        self.comum = CommercialPlan.objects.get(name="Locação Comum")
        self.eventos = CommercialPlan.objects.get(name="Locação Eventos")
        self.mensal = CommercialPlan.objects.get(name="Locação Mensal")

    def test_3_and_7_days_are_deactivated_in_both_plans(self):
        _run_migration_forward()
        for plan in (self.comum, self.eventos):
            for value in (3, 7):
                term = CommercialTerm.objects.get(commercial_plan=plan, duration_value=value, duration_unit=DurationUnit.DIAS)
                self.assertFalse(term.is_active)

    def test_1_5_15_remain_active_and_untouched(self):
        before = {
            (t.commercial_plan_id, t.duration_value): t.pk
            for t in CommercialTerm.objects.filter(commercial_plan__in=[self.comum, self.eventos], duration_value__in=[1, 5, 15])
        }
        _run_migration_forward()
        for plan in (self.comum, self.eventos):
            for value in (1, 5, 15):
                term = CommercialTerm.objects.get(commercial_plan=plan, duration_value=value, duration_unit=DurationUnit.DIAS)
                self.assertTrue(term.is_active)
                self.assertEqual(term.pk, before[(plan.pk, value)])

    def test_30_days_is_created_active_for_both_plans(self):
        _run_migration_forward()
        for plan in (self.comum, self.eventos):
            term = CommercialTerm.objects.get(commercial_plan=plan, duration_value=30, duration_unit=DurationUnit.DIAS)
            self.assertTrue(term.is_active)

    def test_mensal_plan_is_never_touched(self):
        before = list(self.mensal.terms.values_list("pk", "duration_value", "is_active"))
        _run_migration_forward()
        after = list(self.mensal.terms.values_list("pk", "duration_value", "is_active"))
        self.assertEqual(before, after)

    def test_migration_is_idempotent(self):
        _run_migration_forward()
        _run_migration_forward()
        for plan in (self.comum, self.eventos):
            self.assertEqual(CommercialTerm.objects.filter(commercial_plan=plan, duration_value=30, duration_unit=DurationUnit.DIAS).count(), 1)
            term = CommercialTerm.objects.get(commercial_plan=plan, duration_value=30, duration_unit=DurationUnit.DIAS)
            self.assertTrue(term.is_active)

    def test_reactivates_30_days_if_it_already_exists_inactive(self):
        _run_migration_forward()
        thirty = CommercialTerm.objects.get(commercial_plan=self.comum, duration_value=30, duration_unit=DurationUnit.DIAS)
        thirty.is_active = False
        thirty.save(update_fields=["is_active"])

        _run_migration_forward()

        thirty.refresh_from_db()
        self.assertTrue(thirty.is_active)
        self.assertEqual(CommercialTerm.objects.filter(commercial_plan=self.comum, duration_value=30, duration_unit=DurationUnit.DIAS).count(), 1)

    def test_preserves_price_table_rate_already_linked_to_3_or_7_days(self):
        user = _user_with_perms("auditor_migracao_r2", "view_opportunities")
        category = Category.objects.create(name="Categoria Migração")
        model = EquipmentModel.objects.create(code="MIG01", name="Equipamento Migração", category=category)
        term_3d = CommercialTerm.objects.get(commercial_plan=self.comum, duration_value=3, duration_unit=DurationUnit.DIAS)
        rate = set_price_table_rate(
            data=PriceTableRateData(equipment_model=model, commercial_plan=self.comum, commercial_term=term_3d, amount=Decimal("450.00")),
            user=user,
        )

        _run_migration_forward()

        rate.refresh_from_db()
        self.assertEqual(rate.amount, Decimal("450.00"))
        term_3d.refresh_from_db()
        self.assertFalse(term_3d.is_active)

    def test_backward_reactivates_3_and_7_but_leaves_30_untouched(self):
        _run_migration_forward()
        _run_migration_backward()
        for plan in (self.comum, self.eventos):
            for value in (3, 7):
                term = CommercialTerm.objects.get(commercial_plan=plan, duration_value=value, duration_unit=DurationUnit.DIAS)
                self.assertTrue(term.is_active)
            thirty = CommercialTerm.objects.get(commercial_plan=plan, duration_value=30, duration_unit=DurationUnit.DIAS)
            self.assertTrue(thirty.is_active)
