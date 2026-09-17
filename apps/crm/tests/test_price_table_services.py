"""
Testes de `apps.crm.services` — Tabela de Preços V1 (16/09/2026, "TABELA
DE PREÇOS V1 / LOCUSHUB / CRM / PROPOSTAS"). Cobre a seção 32 da
especificação: `PriceTable` por `BusinessType`, `PriceTableItem` de
`EquipmentModel`/`ServiceCatalogItem`, XOR obrigatório, preço não
negativo, `get_suggested_price()`, item sem preço, alteração de preço,
usuário/data registrados, histórico preservado (simple-history), e a
REGRA CRÍTICA: alterar a Tabela de Preços nunca altera um `ProposalItem`
já existente (snapshot congelado).

A matriz de permissões HTTP fica em `test_price_table_views.py`; a
integração com o fluxo de Proposta (preço sugerido ao adicionar item)
fica em `test_price_table_proposal_integration.py`.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.crm.models import BusinessType, PriceTable, PriceTableItem, ServiceCatalogItem
from apps.crm.services import (
    PriceTableItemData,
    ProposalItemData,
    add_proposal_item,
    get_or_create_active_proposal,
    get_suggested_price,
    list_price_table_rows,
    set_price_table_item,
)

User = get_user_model()


class PriceTableServiceTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="comercial", password="senha-forte-123")
        self.other_user = User.objects.create_user(username="comercial2", password="senha-forte-123")
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(code="NI23BT", name="NI23 Big Tank", category=self.category)
        self.other_model = EquipmentModel.objects.create(code="NI23TC", name="NI23 Tank Chiller", category=self.category)
        self.service = ServiceCatalogItem.objects.create(name="Diária de operador", unit_label="hora")


class SetPriceTableItemTest(PriceTableServiceTestBase):
    """1/2/3/6 — cria `PriceTable` por `BusinessType` sob demanda, cria/edita `PriceTableItem` de equipamento OU serviço."""

    def test_creates_price_table_for_business_type_on_demand(self):
        self.assertEqual(PriceTable.objects.count(), 0)
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        self.assertEqual(PriceTable.objects.count(), 1)
        table = PriceTable.objects.get()
        self.assertEqual(table.business_type, BusinessType.LOCACAO)
        self.assertEqual(table.name, "Tabela de Locação")

    def test_creates_item_for_equipment_model(self):
        item = set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        self.assertEqual(item.equipment_model, self.model)
        self.assertIsNone(item.service)
        self.assertEqual(item.unit_price, Decimal("900.00"))

    def test_creates_item_for_service(self):
        item = set_price_table_item(
            data=PriceTableItemData(business_type=BusinessType.LOCACAO, service=self.service, unit_price=Decimal("150.00")),
            user=self.user,
        )
        self.assertIsNone(item.equipment_model)
        self.assertEqual(item.service, self.service)

    def test_second_call_updates_same_row_instead_of_duplicating(self):
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("950.00")
            ),
            user=self.other_user,
        )
        self.assertEqual(PriceTableItem.objects.count(), 1)
        item = PriceTableItem.objects.get()
        self.assertEqual(item.unit_price, Decimal("950.00"))
        self.assertEqual(item.updated_by, self.other_user)


class XorConstraintTest(PriceTableServiceTestBase):
    """4 — XOR obrigatório entre `equipment_model` e `service`."""

    def test_service_rejects_both_references(self):
        with self.assertRaises(ValueError):
            set_price_table_item(
                data=PriceTableItemData(
                    business_type=BusinessType.LOCACAO,
                    equipment_model=self.model,
                    service=self.service,
                    unit_price=Decimal("10.00"),
                ),
                user=self.user,
            )

    def test_service_rejects_neither_reference(self):
        with self.assertRaises(ValueError):
            set_price_table_item(
                data=PriceTableItemData(business_type=BusinessType.LOCACAO, unit_price=Decimal("10.00")), user=self.user
            )

    def test_database_constraint_rejects_both_references(self):
        table = PriceTable.objects.create(business_type=BusinessType.LOCACAO)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PriceTableItem.objects.create(
                price_table=table,
                equipment_model=self.model,
                service=self.service,
                unit_price=Decimal("10.00"),
                updated_by=self.user,
            )

    def test_database_constraint_rejects_neither_reference(self):
        table = PriceTable.objects.create(business_type=BusinessType.LOCACAO)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PriceTableItem.objects.create(price_table=table, unit_price=Decimal("10.00"), updated_by=self.user)

    def test_database_constraint_rejects_duplicate_row_for_same_equipment_model(self):
        table = PriceTable.objects.create(business_type=BusinessType.LOCACAO)
        PriceTableItem.objects.create(
            price_table=table, equipment_model=self.model, unit_price=Decimal("900.00"), updated_by=self.user
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PriceTableItem.objects.create(
                price_table=table, equipment_model=self.model, unit_price=Decimal("950.00"), updated_by=self.user
            )


class NegativePriceTest(PriceTableServiceTestBase):
    """5 — preço não negativo (service + `CheckConstraint`)."""

    def test_service_rejects_negative_price(self):
        with self.assertRaises(ValueError):
            set_price_table_item(
                data=PriceTableItemData(
                    business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("-1.00")
                ),
                user=self.user,
            )

    def test_service_accepts_zero_price(self):
        item = set_price_table_item(
            data=PriceTableItemData(business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("0.00")),
            user=self.user,
        )
        self.assertEqual(item.unit_price, Decimal("0.00"))

    def test_database_constraint_rejects_negative_price(self):
        table = PriceTable.objects.create(business_type=BusinessType.LOCACAO)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PriceTableItem.objects.create(
                price_table=table, equipment_model=self.model, unit_price=Decimal("-5.00"), updated_by=self.user
            )

    def test_invalid_business_type_is_rejected(self):
        with self.assertRaises(ValueError):
            set_price_table_item(
                data=PriceTableItemData(business_type="INEXISTENTE", equipment_model=self.model, unit_price=Decimal("1.00")),
                user=self.user,
            )


class GetSuggestedPriceTest(PriceTableServiceTestBase):
    """
    6/7/13/14 — `get_suggested_price()` é a autoridade única de leitura.

    RODADA 1 (16/09/2026): `get_suggested_price()` passou a devolver
    `SuggestedPrice` (dataclass: `amount`/`billing_mode`/`source`) em vez
    de um `Decimal` puro — evolução do CONTRATO da função para também
    suportar o caminho plano+prazo de Locação (ver
    `PlanTermSuggestedPriceTest` em `test_commercial_plans.py`). O
    comportamento em SI, chamando sem plano/prazo (V1), é 100%
    preservado — só o envelope do retorno mudou (`.amount` no lugar do
    valor cru).
    """

    def test_returns_none_when_no_price_table_item_configured(self):
        # 7: item sem preço nunca inventa R$ 0,00.
        self.assertIsNone(get_suggested_price(business_type=BusinessType.LOCACAO, equipment_model=self.model))

    def test_returns_configured_price_for_equipment_model(self):
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        suggestion = get_suggested_price(business_type=BusinessType.LOCACAO, equipment_model=self.model)
        self.assertEqual(suggestion.amount, Decimal("900.00"))
        self.assertEqual(suggestion.source, "item")
        self.assertIsNone(suggestion.billing_mode)

    def test_returns_configured_price_for_service(self):
        set_price_table_item(
            data=PriceTableItemData(business_type=BusinessType.LOCACAO, service=self.service, unit_price=Decimal("150.00")),
            user=self.user,
        )
        suggestion = get_suggested_price(business_type=BusinessType.LOCACAO, service=self.service)
        self.assertEqual(suggestion.amount, Decimal("150.00"))

    def test_business_type_correctly_selects_price_rental_vs_sale(self):
        # 13/14: preço de Venda não aparece em Locação e vice-versa.
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        set_price_table_item(
            data=PriceTableItemData(business_type=BusinessType.VENDA, equipment_model=self.model, unit_price=Decimal("25000.00")),
            user=self.user,
        )
        self.assertEqual(
            get_suggested_price(business_type=BusinessType.LOCACAO, equipment_model=self.model).amount, Decimal("900.00")
        )
        self.assertEqual(
            get_suggested_price(business_type=BusinessType.VENDA, equipment_model=self.model).amount, Decimal("25000.00")
        )
        # SERVICO nunca foi configurado — continua None, não confunde com nenhum outro tipo.
        self.assertIsNone(get_suggested_price(business_type=BusinessType.SERVICO, equipment_model=self.model))

    def test_requires_exactly_one_reference(self):
        with self.assertRaises(ValueError):
            get_suggested_price(business_type=BusinessType.LOCACAO)
        with self.assertRaises(ValueError):
            get_suggested_price(business_type=BusinessType.LOCACAO, equipment_model=self.model, service=self.service)


class UpdatedByAndHistoryTest(PriceTableServiceTestBase):
    """8/9/10 — alteração de preço, usuário/data registrados, histórico preservado (simple-history)."""

    def test_updated_by_is_recorded(self):
        item = set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        self.assertEqual(item.updated_by, self.user)

    def test_history_records_previous_and_new_value_with_user_and_timestamp(self):
        item = set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("950.00")
            ),
            user=self.other_user,
        )
        history_values = list(item.history.order_by("history_date").values_list("unit_price", "history_user__username"))
        self.assertEqual(history_values, [(Decimal("900.00"), "comercial"), (Decimal("950.00"), "comercial2")])
        for record in item.history.all():
            self.assertIsNotNone(record.history_date)

    def test_price_change_updates_item_in_place_price_history_preserved(self):
        item = set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        item_id = item.pk
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("950.00")
            ),
            user=self.user,
        )
        item.refresh_from_db()
        self.assertEqual(item.pk, item_id)
        self.assertEqual(item.unit_price, Decimal("950.00"))
        self.assertEqual(item.history.count(), 2)


class TableChangeDoesNotAffectExistingProposalItemTest(PriceTableServiceTestBase):
    """
    11/12 — REGRA CRÍTICA: alterar a Tabela de Preços NUNCA altera um
    `ProposalItem` já criado; `ProposalItem.unit_price` é sempre um
    snapshot congelado no momento da adição.
    """

    def setUp(self):
        super().setUp()
        from apps.clients.models import Client
        from apps.crm.models import CommercialSource, Opportunity, OpportunityStage

        self.client_obj = Client.objects.create(company_name="Cliente Preço")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage = OpportunityStage.objects.create(name="Novo", order=1)
        self.opportunity = Opportunity.objects.create(
            client=self.client_obj,
            title="Oportunidade Preço",
            owner=self.user,
            source=self.source,
            business_type=BusinessType.LOCACAO,
            stage=self.stage,
            created_by=self.user,
        )

    def test_changing_price_table_after_proposal_item_created_does_not_change_it(self):
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        proposal = get_or_create_active_proposal(opportunity=self.opportunity, created_by=self.user)
        version = proposal.latest_version
        item = add_proposal_item(
            proposal_version=version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("900.00")),
        )
        self.assertEqual(item.unit_price, Decimal("900.00"))

        # Tabela muda DEPOIS que o item já foi criado.
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("950.00")
            ),
            user=self.user,
        )

        item.refresh_from_db()
        self.assertEqual(item.unit_price, Decimal("900.00"), "ProposalItem já criado precisa continuar com o valor antigo.")
        self.assertEqual(
            get_suggested_price(business_type=BusinessType.LOCACAO, equipment_model=self.model).amount, Decimal("950.00")
        )


class ListPriceTableRowsTest(PriceTableServiceTestBase):
    """Suporte à tela: linhas de equipamento/serviço, com/sem valor, busca, contadores (seções 12/13/14/21/22/37)."""

    def test_active_equipment_model_and_service_appear_without_manual_row(self):
        rows = list_price_table_rows(business_type=BusinessType.LOCACAO)
        equipment_labels = {row.label for row in rows.equipment_rows}
        service_labels = {row.label for row in rows.service_rows}
        self.assertIn("NI23 Big Tank (NI23BT)", equipment_labels)
        self.assertIn("Diária de operador", service_labels)

    def test_unconfigured_item_shows_as_missing_price(self):
        rows = list_price_table_rows(business_type=BusinessType.LOCACAO)
        row = next(r for r in rows.equipment_rows if r.target_id == self.model.pk)
        self.assertIsNone(row.unit_price)
        self.assertFalse(row.has_price)

    def test_inactive_equipment_model_does_not_appear_but_price_table_item_is_preserved(self):
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        self.model.is_active = False
        self.model.save(update_fields=["is_active"])

        rows = list_price_table_rows(business_type=BusinessType.LOCACAO)
        self.assertNotIn(self.model.pk, [r.target_id for r in rows.equipment_rows])
        # Preservado no banco (seção 14).
        self.assertTrue(PriceTableItem.objects.filter(equipment_model=self.model).exists())

    def test_only_missing_filter(self):
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        rows = list_price_table_rows(business_type=BusinessType.LOCACAO, only_missing=True)
        target_ids = [r.target_id for r in rows.equipment_rows]
        self.assertNotIn(self.model.pk, target_ids)
        self.assertIn(self.other_model.pk, target_ids)

    def test_search_filters_by_name_or_code(self):
        rows = list_price_table_rows(business_type=BusinessType.LOCACAO, search="NI23BT")
        labels = {row.label for row in rows.equipment_rows}
        self.assertEqual(labels, {"NI23 Big Tank (NI23BT)"})

    def test_counters(self):
        # Conta dinamicamente em vez de fixar "3"/"2" — o app já semeia
        # "Hora técnica" (`apps/crm/migrations/0009_seed_hora_tecnica.py`)
        # além do `self.service` criado neste teste.
        expected_total = EquipmentModel.objects.filter(is_active=True).count() + ServiceCatalogItem.objects.filter(
            is_active=True
        ).count()
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.LOCACAO, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.user,
        )
        rows = list_price_table_rows(business_type=BusinessType.LOCACAO)
        self.assertEqual(rows.total_count, expected_total)
        self.assertEqual(rows.configured_count, 1)
        self.assertEqual(rows.missing_count, expected_total - 1)

    def test_no_n_plus_one_queries(self):
        for i in range(20):
            EquipmentModel.objects.create(code=f"EQ{i:03d}", name=f"Equipamento {i}", category=self.category)
        with self.assertNumQueries(3):
            rows = list_price_table_rows(business_type=BusinessType.LOCACAO)
            list(rows.equipment_rows)
            list(rows.service_rows)
