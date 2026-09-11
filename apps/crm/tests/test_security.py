"""
Testes de segurança obrigatórios do CRM (LocusHub, Etapa 1): IDOR, GET
nunca muda estado, CSRF ativo, integridade de transição ganho/perda,
histórico correto, nenhuma alteração acidental de `Client`, proteção
contra cascata destrutiva, e não vazamento de dado por listagem/detalhe/
atividade para quem não tem permissão.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError, transaction
from django.test import Client as DjangoTestClient
from django.test import TestCase

from apps.clients.models import Client
from apps.crm.models import BusinessType, CommercialSource, LossReason, Opportunity, OpportunityStage, OpportunityStageChange
from apps.crm.services import NewOpportunityData, create_opportunity

User = get_user_model()


def _user_with_perms(username, *codenames):
    user = User.objects.create_user(username=username, password="senha-forte-123")
    if codenames:
        perms = Permission.objects.filter(codename__in=codenames, content_type__app_label="crm")
        group, _ = Group.objects.get_or_create(name=f"perm-{username}")
        group.permissions.set(perms)
        user.groups.add(group)
    return user


class CrmSecurityTestBase(TestCase):
    def setUp(self):
        self.client_a = Client.objects.create(company_name="Cliente A")
        self.client_b = Client.objects.create(company_name="Cliente B")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_outra = OpportunityStage.objects.create(name="Qualificação", order=2)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho", order=3, is_won=True)
        self.stage_perdido = OpportunityStage.objects.create(name="Perdido", order=4, is_lost=True)
        self.loss_reason = LossReason.objects.create(name="Preço")

        self.creator = _user_with_perms("criador_sec", "add_opportunities")
        self.opp_10 = create_opportunity(
            NewOpportunityData(
                client=self.client_a,
                title="Oportunidade dez — dados sensíveis A",
                owner=self.creator,
                source=self.source,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.creator,
                estimated_value=Decimal("12345.67"),
                notes="observação confidencial da oportunidade 10",
            )
        )
        self.opp_11 = create_opportunity(
            NewOpportunityData(
                client=self.client_b,
                title="Oportunidade onze — dados sensíveis B",
                owner=self.creator,
                source=self.source,
                business_type=BusinessType.VENDA,
                stage=self.stage_novo,
                created_by=self.creator,
                estimated_value=Decimal("99999.99"),
            )
        )


class IDORTest(CrmSecurityTestBase):
    """PK-tamper: /oportunidades/10/ -> /oportunidades/11/ e variações (edição, etapa)."""

    def test_unauthorized_user_cannot_reach_any_pk(self):
        stranger = _user_with_perms("estranho_idor")  # nenhuma permissão
        self.client.force_login(stranger)
        for opp in (self.opp_10, self.opp_11):
            with self.subTest(pk=opp.pk):
                resp = self.client.get(f"/crm/oportunidades/{opp.pk}/")
                self.assertEqual(resp.status_code, 403)

    def test_authorized_viewer_can_reach_any_pk_that_exists_by_permission_not_ownership(self):
        """
        A fronteira é a PERMISSÃO, não "ser o dono" — um usuário com
        `view_opportunities` pode ver QUALQUER oportunidade, mesmo sem
        ser o `owner`/`created_by` (não há conceito de "minhas
        oportunidades" restritivo nesta etapa). Isto é o comportamento
        ESPERADO, documentado aqui para não ser confundido com uma
        falha de IDOR: nenhum dado vaza para quem não tem a permissão
        (ver `test_unauthorized_user_cannot_reach_any_pk` acima) — quem
        TEM a permissão está autorizado a ver qualquer oportunidade,
        por design.
        """
        viewer = _user_with_perms("visualizador_idor", "view_opportunities")
        self.client.force_login(viewer)
        resp10 = self.client.get(f"/crm/oportunidades/{self.opp_10.pk}/")
        resp11 = self.client.get(f"/crm/oportunidades/{self.opp_11.pk}/")
        self.assertEqual(resp10.status_code, 200)
        self.assertEqual(resp11.status_code, 200)
        self.assertIn(b"Cliente A", resp10.content)
        self.assertIn(b"Cliente B", resp11.content)

    def test_edit_by_tampered_pk_is_blocked_without_permission(self):
        stranger = _user_with_perms("estranho_edit")
        self.client.force_login(stranger)
        resp = self.client.post(
            f"/crm/oportunidades/{self.opp_11.pk}/editar/",
            {"title": "Hackeado", "owner": self.creator.pk, "source": self.source.pk, "business_type": BusinessType.LOCACAO},
        )
        self.assertEqual(resp.status_code, 403)
        self.opp_11.refresh_from_db()
        self.assertNotEqual(self.opp_11.title, "Hackeado")

    def test_stage_change_by_tampered_pk_is_blocked_without_permission(self):
        stranger = _user_with_perms("estranho_stage")
        self.client.force_login(stranger)
        resp = self.client.post(f"/crm/oportunidades/{self.opp_11.pk}/etapa/", {"stage": self.stage_ganho.pk})
        self.assertEqual(resp.status_code, 403)
        self.opp_11.refresh_from_db()
        self.assertEqual(self.opp_11.stage, self.stage_novo)

    def test_activity_registration_by_tampered_pk_is_blocked_without_permission(self):
        stranger = _user_with_perms("estranho_activity")
        self.client.force_login(stranger)
        resp = self.client.post(
            f"/crm/oportunidades/{self.opp_11.pk}/atividades/nova/", {"activity_type": "LIGACAO", "description": "x"}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.opp_11.activities.count(), 0)

    def test_nonexistent_pk_returns_404_not_500(self):
        viewer = _user_with_perms("visualizador_404", "view_opportunities")
        self.client.force_login(viewer)
        resp = self.client.get("/crm/oportunidades/999999/")
        self.assertEqual(resp.status_code, 404)


class GetNeverMutatesTest(CrmSecurityTestBase):
    def test_get_on_stage_change_url_is_not_allowed(self):
        viewer = _user_with_perms("get_stage", "view_opportunities", "change_opportunity_stage")
        self.client.force_login(viewer)
        resp = self.client.get(f"/crm/oportunidades/{self.opp_10.pk}/etapa/")
        self.assertEqual(resp.status_code, 405)
        self.opp_10.refresh_from_db()
        self.assertEqual(self.opp_10.stage, self.stage_novo)

    def test_get_on_activity_create_url_is_not_allowed(self):
        viewer = _user_with_perms("get_activity", "view_opportunities", "add_commercial_activities")
        self.client.force_login(viewer)
        resp = self.client.get(f"/crm/oportunidades/{self.opp_10.pk}/atividades/nova/")
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(self.opp_10.activities.count(), 0)

    def test_get_on_detail_never_creates_activity_or_history_row(self):
        viewer = _user_with_perms("get_detail", "view_opportunities")
        history_before = OpportunityStageChange.objects.filter(opportunity=self.opp_10).count()
        self.client.force_login(viewer)
        self.client.get(f"/crm/oportunidades/{self.opp_10.pk}/")
        self.assertEqual(
            OpportunityStageChange.objects.filter(opportunity=self.opp_10).count(), history_before
        )


class CsrfTest(CrmSecurityTestBase):
    def test_stage_change_post_without_csrf_token_is_rejected(self):
        strict_client = DjangoTestClient(enforce_csrf_checks=True)
        user = _user_with_perms("csrf_user", "view_opportunities", "change_opportunity_stage")
        strict_client.force_login(user)
        resp = strict_client.post(f"/crm/oportunidades/{self.opp_10.pk}/etapa/", {"stage": self.stage_outra.pk})
        self.assertEqual(resp.status_code, 403)
        self.opp_10.refresh_from_db()
        self.assertEqual(self.opp_10.stage, self.stage_novo)


class WinLossIntegrityTest(CrmSecurityTestBase):
    def test_database_rejects_won_and_lost_at_the_same_time_at_the_model_layer(self):
        from django.utils import timezone

        self.opp_10.won_at = timezone.now()
        self.opp_10.lost_at = timezone.now()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.opp_10.save()

    def test_database_rejects_a_stage_that_is_both_won_and_lost(self):
        stage = OpportunityStage(name="Impossível", is_won=True, is_lost=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            stage.save()


class HistoryCorrectnessTest(CrmSecurityTestBase):
    def test_history_records_correct_user_and_stages(self):
        from apps.crm.services import change_opportunity_stage

        actor = _user_with_perms("historiador", "view_opportunities", "change_opportunity_stage")
        change_opportunity_stage(opportunity_id=self.opp_10.pk, new_stage=self.stage_outra, changed_by=actor, reason="motivo x")
        change = OpportunityStageChange.objects.filter(opportunity=self.opp_10).latest("changed_at")
        self.assertEqual(change.changed_by, actor)
        self.assertEqual(change.from_stage, self.stage_novo)
        self.assertEqual(change.to_stage, self.stage_outra)
        self.assertEqual(change.reason, "motivo x")

    def test_simple_history_snapshot_is_recorded_on_opportunity_field_change(self):
        from apps.crm.services import OpportunityUpdateData, update_opportunity

        update_opportunity(
            opportunity=self.opp_10,
            changed_by=self.creator,
            data=OpportunityUpdateData(
                title="Título alterado", owner=self.creator, source=self.source, business_type=BusinessType.SERVICO
            ),
        )
        self.assertTrue(self.opp_10.history.count() >= 2)  # criação + edição


class ClientNeverMutatedTest(CrmSecurityTestBase):
    def test_no_crm_write_action_ever_changes_client_fields(self):
        from apps.crm.services import OpportunityUpdateData, change_opportunity_stage, update_opportunity

        original = {
            "company_name": self.client_a.company_name,
            "document": self.client_a.document,
            "trade_name": self.client_a.trade_name,
        }
        update_opportunity(
            opportunity=self.opp_10,
            changed_by=self.creator,
            data=OpportunityUpdateData(
                title="X", owner=self.creator, source=self.source, business_type=BusinessType.SERVICO
            ),
        )
        change_opportunity_stage(opportunity_id=self.opp_10.pk, new_stage=self.stage_ganho, changed_by=self.creator)

        self.client_a.refresh_from_db()
        self.assertEqual(self.client_a.company_name, original["company_name"])
        self.assertEqual(self.client_a.document, original["document"])
        self.assertEqual(self.client_a.trade_name, original["trade_name"])


class DeactivationPreservesHistoryTest(CrmSecurityTestBase):
    def test_deactivating_a_used_stage_does_not_delete_history_or_opportunities(self):
        self.stage_novo.is_active = False
        self.stage_novo.save()
        self.opp_10.refresh_from_db()
        self.assertEqual(self.opp_10.stage, self.stage_novo)
        self.assertTrue(OpportunityStageChange.objects.filter(opportunity=self.opp_10).exists())

    def test_deactivating_a_used_source_does_not_delete_opportunities(self):
        self.source.is_active = False
        self.source.save()
        self.opp_10.refresh_from_db()
        self.assertEqual(self.opp_10.source, self.source)


class NoAccidentalCascadeTest(CrmSecurityTestBase):
    def test_stage_in_use_cannot_be_hard_deleted(self):
        with self.assertRaises(Exception):
            with transaction.atomic():
                self.stage_novo.delete()
        self.opp_10.refresh_from_db()
        self.assertIsNotNone(self.opp_10.pk)

    def test_client_in_use_by_an_opportunity_cannot_be_hard_deleted(self):
        with self.assertRaises(Exception):
            with transaction.atomic():
                self.client_a.delete()
        self.opp_10.refresh_from_db()
        self.assertIsNotNone(self.opp_10.pk)


class NoLeakViaListingOrSearchTest(CrmSecurityTestBase):
    def test_user_without_permission_gets_nothing_from_list_or_search(self):
        stranger = _user_with_perms("estranho_busca")
        self.client.force_login(stranger)
        resp = self.client.get("/crm/oportunidades/?q=sensíveis")
        self.assertEqual(resp.status_code, 403)

    def test_search_only_returns_matches_not_the_whole_table(self):
        viewer = _user_with_perms("buscador", "view_opportunities")
        self.client.force_login(viewer)
        resp = self.client.get("/crm/oportunidades/?q=dez")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Oportunidade dez", resp.content)
        self.assertNotIn(b"Oportunidade onze", resp.content)
