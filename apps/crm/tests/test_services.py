"""
Testes de `apps/crm/services.py` — regras de negócio do CRM (LocusHub,
Etapa 1): criação/edição de `Opportunity`, mudança de etapa (inclui
ganho/perda), elegibilidade de responsável comercial, registro de
atividade. Não cobre views/permissões/HTTP — ver `test_permission_matrix.py`
e `test_security.py`.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from apps.clients.models import Client
from apps.crm.models import (
    ActivityType,
    BusinessType,
    CommercialSource,
    LossReason,
    Opportunity,
    OpportunityStage,
    OpportunityStageChange,
)
from apps.crm.services import (
    NewActivityData,
    NewOpportunityData,
    OpportunityUpdateData,
    change_opportunity_stage,
    create_activity,
    create_opportunity,
    eligible_owner_queryset,
    update_opportunity,
)

User = get_user_model()


def _grant(user, *codenames):
    perms = Permission.objects.filter(codename__in=codenames, content_type__app_label="crm")
    group, _ = Group.objects.get_or_create(name=f"teste-crm-{user.pk}")
    group.permissions.set(perms)
    user.groups.add(group)
    return user


class OpportunityServiceTestBase(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(company_name="Cliente LTDA")
        self.owner = _grant(User.objects.create_user(username="vendedor", password="x"), "add_opportunities")
        self.creator = self.owner
        self.source = CommercialSource.objects.create(name="Indicação")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_outra = OpportunityStage.objects.create(name="Qualificação", order=2)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho", order=3, is_won=True)
        self.stage_perdido = OpportunityStage.objects.create(name="Perdido", order=4, is_lost=True)
        self.loss_reason = LossReason.objects.create(name="Preço")


class CreateOpportunityTest(OpportunityServiceTestBase):
    def test_creates_with_valid_data(self):
        opp = create_opportunity(
            NewOpportunityData(
                client=self.client_obj,
                title="Locação de gerador",
                owner=self.owner,
                source=self.source,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.creator,
                estimated_value=Decimal("5000.00"),
            )
        )
        self.assertEqual(opp.stage, self.stage_novo)
        self.assertIsNone(opp.won_at)
        self.assertIsNone(opp.lost_at)

    def test_first_stage_change_row_is_created_with_null_from_stage(self):
        opp = create_opportunity(
            NewOpportunityData(
                client=self.client_obj,
                title="Locação",
                owner=self.owner,
                source=self.source,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.creator,
            )
        )
        change = OpportunityStageChange.objects.get(opportunity=opp)
        self.assertIsNone(change.from_stage)
        self.assertEqual(change.to_stage, self.stage_novo)

    def test_blank_title_is_rejected(self):
        with self.assertRaises(ValueError):
            create_opportunity(
                NewOpportunityData(
                    client=self.client_obj,
                    title="   ",
                    owner=self.owner,
                    source=self.source,
                    business_type=BusinessType.LOCACAO,
                    stage=self.stage_novo,
                    created_by=self.creator,
                )
            )

    def test_negative_estimated_value_is_rejected(self):
        with self.assertRaises(ValueError):
            create_opportunity(
                NewOpportunityData(
                    client=self.client_obj,
                    title="Locação",
                    owner=self.owner,
                    source=self.source,
                    business_type=BusinessType.LOCACAO,
                    stage=self.stage_novo,
                    created_by=self.creator,
                    estimated_value=Decimal("-1.00"),
                )
            )

    def test_cannot_be_created_directly_in_a_won_stage(self):
        with self.assertRaises(ValueError):
            create_opportunity(
                NewOpportunityData(
                    client=self.client_obj,
                    title="Locação",
                    owner=self.owner,
                    source=self.source,
                    business_type=BusinessType.LOCACAO,
                    stage=self.stage_ganho,
                    created_by=self.creator,
                )
            )

    def test_cannot_be_created_directly_in_a_lost_stage(self):
        with self.assertRaises(ValueError):
            create_opportunity(
                NewOpportunityData(
                    client=self.client_obj,
                    title="Locação",
                    owner=self.owner,
                    source=self.source,
                    business_type=BusinessType.LOCACAO,
                    stage=self.stage_perdido,
                    created_by=self.creator,
                )
            )

    def test_cannot_be_created_in_a_deactivated_stage(self):
        self.stage_novo.is_active = False
        self.stage_novo.save()
        with self.assertRaises(ValueError):
            create_opportunity(
                NewOpportunityData(
                    client=self.client_obj,
                    title="Locação",
                    owner=self.owner,
                    source=self.source,
                    business_type=BusinessType.LOCACAO,
                    stage=self.stage_novo,
                    created_by=self.creator,
                )
            )

    def test_estimated_value_is_decimal_not_float(self):
        opp = create_opportunity(
            NewOpportunityData(
                client=self.client_obj,
                title="Locação",
                owner=self.owner,
                source=self.source,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.creator,
                estimated_value=Decimal("1234.56"),
            )
        )
        opp.refresh_from_db()
        self.assertIsInstance(opp.estimated_value, Decimal)


class UpdateOpportunityTest(OpportunityServiceTestBase):
    def setUp(self):
        super().setUp()
        self.opportunity = create_opportunity(
            NewOpportunityData(
                client=self.client_obj,
                title="Original",
                owner=self.owner,
                source=self.source,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.creator,
            )
        )

    def test_updates_editable_fields(self):
        update_opportunity(
            opportunity=self.opportunity,
            changed_by=self.owner,
            data=OpportunityUpdateData(
                title="Atualizado",
                owner=self.owner,
                source=self.source,
                business_type=BusinessType.VENDA,
                estimated_value=Decimal("100.00"),
                notes="nota",
            ),
        )
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.title, "Atualizado")
        self.assertEqual(self.opportunity.business_type, BusinessType.VENDA)

    def test_never_touches_client(self):
        original_client_id = self.opportunity.client_id
        update_opportunity(
            opportunity=self.opportunity,
            changed_by=self.owner,
            data=OpportunityUpdateData(
                title="Atualizado",
                owner=self.owner,
                source=self.source,
                business_type=BusinessType.VENDA,
            ),
        )
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.client_id, original_client_id)

    def test_never_touches_stage_or_win_loss_fields(self):
        update_opportunity(
            opportunity=self.opportunity,
            changed_by=self.owner,
            data=OpportunityUpdateData(
                title="Atualizado", owner=self.owner, source=self.source, business_type=BusinessType.VENDA
            ),
        )
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_novo)
        self.assertIsNone(self.opportunity.won_at)
        self.assertIsNone(self.opportunity.lost_at)

    def test_editing_opportunity_never_alters_linked_client_fields(self):
        original_name = self.client_obj.company_name
        update_opportunity(
            opportunity=self.opportunity,
            changed_by=self.owner,
            data=OpportunityUpdateData(
                title="Novo título", owner=self.owner, source=self.source, business_type=BusinessType.SERVICO
            ),
        )
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.company_name, original_name)


class ChangeOpportunityStageTest(OpportunityServiceTestBase):
    def setUp(self):
        super().setUp()
        self.opportunity = create_opportunity(
            NewOpportunityData(
                client=self.client_obj,
                title="Locação",
                owner=self.owner,
                source=self.source,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.creator,
            )
        )

    def test_moves_to_intermediate_stage(self):
        change_opportunity_stage(opportunity_id=self.opportunity.pk, new_stage=self.stage_outra, changed_by=self.owner)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_outra)

    def test_records_stage_change_history_row(self):
        change_opportunity_stage(
            opportunity_id=self.opportunity.pk, new_stage=self.stage_outra, changed_by=self.owner, reason="avançou"
        )
        change = OpportunityStageChange.objects.filter(opportunity=self.opportunity).latest("changed_at")
        self.assertEqual(change.from_stage, self.stage_novo)
        self.assertEqual(change.to_stage, self.stage_outra)
        self.assertEqual(change.changed_by, self.owner)
        self.assertEqual(change.reason, "avançou")

    def test_marking_won_sets_won_at_and_clears_loss_state(self):
        change_opportunity_stage(
            opportunity_id=self.opportunity.pk,
            new_stage=self.stage_ganho,
            changed_by=self.owner,
            closed_value=Decimal("4500.00"),
        )
        self.opportunity.refresh_from_db()
        self.assertIsNotNone(self.opportunity.won_at)
        self.assertIsNone(self.opportunity.lost_at)
        self.assertIsNone(self.opportunity.loss_reason)
        self.assertEqual(self.opportunity.closed_value, Decimal("4500.00"))

    def test_marking_lost_requires_loss_reason(self):
        with self.assertRaises(ValueError):
            change_opportunity_stage(opportunity_id=self.opportunity.pk, new_stage=self.stage_perdido, changed_by=self.owner)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_novo)  # nada mudou

    def test_marking_lost_with_reason_sets_lost_at_and_clears_win_state(self):
        change_opportunity_stage(
            opportunity_id=self.opportunity.pk,
            new_stage=self.stage_perdido,
            changed_by=self.owner,
            loss_reason=self.loss_reason,
            loss_notes="foi para o concorrente",
        )
        self.opportunity.refresh_from_db()
        self.assertIsNotNone(self.opportunity.lost_at)
        self.assertIsNone(self.opportunity.won_at)
        self.assertEqual(self.opportunity.loss_reason, self.loss_reason)
        self.assertIsNone(self.opportunity.closed_value)

    def test_reopening_from_won_clears_all_closing_state(self):
        change_opportunity_stage(
            opportunity_id=self.opportunity.pk, new_stage=self.stage_ganho, changed_by=self.owner, closed_value=Decimal("10.00")
        )
        change_opportunity_stage(opportunity_id=self.opportunity.pk, new_stage=self.stage_novo, changed_by=self.owner)
        self.opportunity.refresh_from_db()
        self.assertIsNone(self.opportunity.won_at)
        self.assertIsNone(self.opportunity.lost_at)
        self.assertIsNone(self.opportunity.closed_value)

    def test_reopening_from_lost_clears_all_closing_state(self):
        change_opportunity_stage(
            opportunity_id=self.opportunity.pk,
            new_stage=self.stage_perdido,
            changed_by=self.owner,
            loss_reason=self.loss_reason,
        )
        change_opportunity_stage(opportunity_id=self.opportunity.pk, new_stage=self.stage_outra, changed_by=self.owner)
        self.opportunity.refresh_from_db()
        self.assertIsNone(self.opportunity.won_at)
        self.assertIsNone(self.opportunity.lost_at)
        self.assertIsNone(self.opportunity.loss_reason)

    def test_cannot_move_to_the_same_stage(self):
        with self.assertRaises(ValueError):
            change_opportunity_stage(opportunity_id=self.opportunity.pk, new_stage=self.stage_novo, changed_by=self.owner)

    def test_cannot_move_to_a_deactivated_stage(self):
        self.stage_outra.is_active = False
        self.stage_outra.save()
        with self.assertRaises(ValueError):
            change_opportunity_stage(opportunity_id=self.opportunity.pk, new_stage=self.stage_outra, changed_by=self.owner)

    def test_negative_closed_value_is_rejected(self):
        with self.assertRaises(ValueError):
            change_opportunity_stage(
                opportunity_id=self.opportunity.pk,
                new_stage=self.stage_ganho,
                changed_by=self.owner,
                closed_value=Decimal("-1.00"),
            )

    def test_a_failed_transition_leaves_no_partial_state(self):
        """
        `change_opportunity_stage()` inteira é `@transaction.atomic` — se
        a validação de motivo de perda falha DEPOIS de já ter mudado
        `stage` em memória, nada disso pode ter sido persistido.
        """
        history_count_before = OpportunityStageChange.objects.filter(opportunity=self.opportunity).count()
        with self.assertRaises(ValueError):
            change_opportunity_stage(opportunity_id=self.opportunity.pk, new_stage=self.stage_perdido, changed_by=self.owner)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_novo)
        self.assertIsNone(self.opportunity.lost_at)
        self.assertEqual(
            OpportunityStageChange.objects.filter(opportunity=self.opportunity).count(), history_count_before
        )


class EligibleOwnerQuerysetTest(TestCase):
    def test_superuser_is_always_eligible(self):
        su = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
        self.assertIn(su, eligible_owner_queryset())

    def test_user_with_add_opportunities_permission_is_eligible(self):
        user = _grant(User.objects.create_user(username="vendedor2", password="x"), "add_opportunities")
        self.assertIn(user, eligible_owner_queryset())

    def test_user_without_permission_is_not_eligible(self):
        user = User.objects.create_user(username="ninguem", password="x")
        self.assertNotIn(user, eligible_owner_queryset())

    def test_inactive_user_is_not_eligible_even_with_permission(self):
        user = _grant(User.objects.create_user(username="desativado", password="x", is_active=False), "add_opportunities")
        self.assertNotIn(user, eligible_owner_queryset())


class CreateActivityTest(OpportunityServiceTestBase):
    def setUp(self):
        super().setUp()
        self.opportunity = create_opportunity(
            NewOpportunityData(
                client=self.client_obj,
                title="Locação",
                owner=self.owner,
                source=self.source,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.creator,
            )
        )

    def test_creates_activity(self):
        activity = create_activity(
            NewActivityData(
                opportunity=self.opportunity, activity_type=ActivityType.LIGACAO, created_by=self.owner, description="ligou"
            )
        )
        self.assertEqual(activity.opportunity, self.opportunity)

    def test_invalid_activity_type_is_rejected(self):
        with self.assertRaises(ValueError):
            create_activity(
                NewActivityData(opportunity=self.opportunity, activity_type="INVALIDO", created_by=self.owner)
            )
