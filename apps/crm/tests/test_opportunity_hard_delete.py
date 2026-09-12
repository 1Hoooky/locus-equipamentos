"""
Exclusão definitiva (hard delete) de `Opportunity` — rodada "AMBIENTE EM
DESENVOLVIMENTO / HARD DELETE DURANTE DESENVOLVIMENTO / NÃO FAZER
CASCADE CEGO", 11/09/2026.

Este é exatamente o exemplo dado pelo próprio usuário no pedido:
`OpportunityStageChange`/`CommercialActivity` são dependentes exclusivos
(CASCADE já no schema) e podem ser removidos junto; o Cliente NUNCA pode
ser excluído por causa disto ("Excluir uma oportunidade NÃO deve excluir
o Cliente"). `Opportunity` nem é `SoftDeleteModel` — antes desta rodada
não havia NENHUM caminho de exclusão real.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from apps.clients.models import Client, ClientType
from apps.crm.models import (
    BusinessType,
    CommercialActivity,
    CommercialSource,
    LossReason,
    Opportunity,
    OpportunityStage,
    OpportunityStageChange,
)
from apps.crm.services import (
    HardDeleteAuthorizationError,
    HardDeleteBlocked,
    NewActivityData,
    NewOpportunityData,
    change_opportunity_stage,
    create_activity,
    create_opportunity,
    hard_delete_opportunity,
    preview_opportunity_hard_delete,
)

User = get_user_model()


def _grant(user, *codenames):
    perms = Permission.objects.filter(codename__in=codenames, content_type__app_label="crm")
    group, _ = Group.objects.get_or_create(name=f"teste-crm-hd-{user.pk}")
    group.permissions.set(perms)
    user.groups.add(group)
    return user


class OpportunityHardDeleteServiceTest(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_user(
            username="ophd_super", password="senha-forte-123", is_superuser=True
        )
        self.manager = _grant(
            User.objects.create_user(username="ophd_manager", password="senha-forte-123"),
            "add_opportunities",
            "change_opportunities",
            "view_opportunities",
        )
        self.client_obj = Client.objects.create(
            client_type=ClientType.PJ, company_name="Cliente Oportunidade HD LTDA", document="11.222.333/0001-81"
        )
        self.source = CommercialSource.objects.create(name="Origem HD")
        self.stage_novo = OpportunityStage.objects.create(name="Novo HD", order=1)
        self.stage_outra = OpportunityStage.objects.create(name="Qualificação HD", order=2)
        self.opportunity = create_opportunity(
            NewOpportunityData(
                client=self.client_obj,
                title="Oportunidade para excluir",
                owner=self.manager,
                source=self.source,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.manager,
                estimated_value=Decimal("1000.00"),
            )
        )

    def test_superuser_can_hard_delete_opportunity(self):
        opportunity_id = self.opportunity.pk
        result = hard_delete_opportunity(opportunity_id=opportunity_id, actor=self.superuser)
        self.assertFalse(Opportunity.objects.filter(pk=opportunity_id).exists())
        # Primeira transição de etapa (criação) já existe automaticamente.
        self.assertGreaterEqual(result.total_dependents, 1)

    def test_non_superuser_actor_is_rejected_even_with_change_opportunities_permission(self):
        """Defesa em profundidade: crm.change_opportunities NÃO é suficiente — só is_superuser."""
        with self.assertRaises(HardDeleteAuthorizationError):
            hard_delete_opportunity(opportunity_id=self.opportunity.pk, actor=self.manager)
        self.assertTrue(Opportunity.objects.filter(pk=self.opportunity.pk).exists())

    def test_stage_changes_and_activities_cascade_automatically_as_exclusive_dependents(self):
        change_opportunity_stage(
            opportunity_id=self.opportunity.pk, new_stage=self.stage_outra, changed_by=self.manager, reason="teste"
        )
        create_activity(
            NewActivityData(
                opportunity=self.opportunity, activity_type="LIGACAO", created_by=self.manager, description="Ligação teste"
            )
        )
        opportunity_id = self.opportunity.pk
        self.assertEqual(OpportunityStageChange.objects.filter(opportunity_id=opportunity_id).count(), 2)
        self.assertEqual(CommercialActivity.objects.filter(opportunity_id=opportunity_id).count(), 1)

        preview = preview_opportunity_hard_delete(self.opportunity)
        self.assertEqual(preview.dependents.get("histórico de etapas"), 2)
        self.assertEqual(preview.dependents.get("atividades comerciais"), 1)

        result = hard_delete_opportunity(opportunity_id=opportunity_id, actor=self.superuser)

        self.assertEqual(result.total_dependents, 3)
        self.assertFalse(OpportunityStageChange.objects.filter(opportunity_id=opportunity_id).exists())
        self.assertFalse(CommercialActivity.objects.filter(opportunity_id=opportunity_id).exists())

    def test_client_is_never_deleted_when_opportunity_is_hard_deleted(self):
        """Pedido explícito do usuário: 'Excluir uma oportunidade NÃO deve excluir o Cliente.'"""
        client_id = self.client_obj.pk
        hard_delete_opportunity(opportunity_id=self.opportunity.pk, actor=self.superuser)
        self.assertTrue(Client.objects.filter(pk=client_id).exists())

    def test_shared_configuration_is_never_touched(self):
        source_id = self.source.pk
        stage_id = self.stage_novo.pk
        hard_delete_opportunity(opportunity_id=self.opportunity.pk, actor=self.superuser)
        self.assertTrue(CommercialSource.objects.filter(pk=source_id).exists())
        self.assertTrue(OpportunityStage.objects.filter(pk=stage_id).exists())


class OpportunityHardDeleteViewTest(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_user(
            username="ophd_super_view", password="senha-forte-123", is_superuser=True
        )
        self.manager = _grant(
            User.objects.create_user(username="ophd_manager_view", password="senha-forte-123"),
            "add_opportunities",
            "change_opportunities",
            "view_opportunities",
        )
        client_obj = Client.objects.create(
            client_type=ClientType.PJ, company_name="Cliente View HD LTDA", document="11.444.777/0001-61"
        )
        source = CommercialSource.objects.create(name="Origem View HD")
        stage = OpportunityStage.objects.create(name="Novo View HD", order=1)
        self.opportunity = create_opportunity(
            NewOpportunityData(
                client=client_obj,
                title="Oportunidade da tela",
                owner=self.manager,
                source=source,
                business_type=BusinessType.LOCACAO,
                stage=stage,
                created_by=self.manager,
            )
        )
        self.url = f"/crm/oportunidades/{self.opportunity.pk}/excluir-definitivamente/"

    def test_get_requires_superuser_not_just_change_opportunities_permission(self):
        self.client.login(username="ophd_manager_view", password="senha-forte-123")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.client.login(username="ophd_super_view", password="senha-forte-123")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Excluir definitivamente")

    def test_post_with_confirmation_deletes_and_redirects_to_list(self):
        self.client.login(username="ophd_super_view", password="senha-forte-123")
        response = self.client.post(self.url, {"confirm": "on"})
        self.assertRedirects(response, "/crm/oportunidades/")
        self.assertFalse(Opportunity.objects.filter(pk=self.opportunity.pk).exists())

    def test_non_superuser_post_is_forbidden_and_opportunity_survives(self):
        self.client.login(username="ophd_manager_view", password="senha-forte-123")
        response = self.client.post(self.url, {"confirm": "on"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Opportunity.objects.filter(pk=self.opportunity.pk).exists())

    def test_hard_delete_button_only_visible_to_superuser_on_detail_page(self):
        detail_url = f"/crm/oportunidades/{self.opportunity.pk}/"
        self.client.login(username="ophd_manager_view", password="senha-forte-123")
        response = self.client.get(detail_url)
        self.assertNotContains(response, "excluir-definitivamente")

        self.client.login(username="ophd_super_view", password="senha-forte-123")
        response = self.client.get(detail_url)
        self.assertContains(response, "excluir-definitivamente")
