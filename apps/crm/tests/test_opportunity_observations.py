"""
RODADA 3 DE REFINAMENTOS DO HUB DA OPORTUNIDADE (14/09/2026) — itens 1-8
da especificação: botão "+" de Observações na Visão Geral.

REAPROVEITA 100% a infraestrutura de Atividades já existente — nenhum
model novo, nenhuma permissão nova, nenhum endpoint novo: o modal
"Adicionar observação" envia POST para a MESMA `crm:activity_create`
(`CommercialActivityForm` → `create_activity()`), só com o tipo
"Observação" (`ActivityType.code="OBSERVACAO"`) fixo num campo oculto —
ver `apps.crm.services.get_observation_activity_type()`.

Cobre: botão só aparece com `add_commercial_activities`; salvar cria uma
`CommercialActivity` do tipo Observação tied à Opportunity certa (texto,
usuário, data/hora); a lista de observações na Visão Geral respeita
`view_commercial_activities` (mesma checagem de segurança já testada
para a aba Atividades); `opportunity.notes` (o texto livre único já
existente) continua exibido sem nenhuma mudança de comportamento;
CSRF é exigido (POST simples de formulário, `Client.post` do Django já
inclui token — o teste de ausência de token cobre a proteção).
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, Client as DjangoTestClient

from apps.clients.models import Client
from apps.crm.models import ActivityType, BusinessType, CommercialActivity, CommercialSource, LossReason, OpportunityStage
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


class OpportunityObservationsTestBase(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(company_name="Cliente Observações")
        self.source = CommercialSource.objects.create(name="Indicação")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        LossReason.objects.create(name="Preço")

        self.creator = _user_with_perms("criador_obs", "add_opportunities")
        self.opportunity = create_opportunity(
            NewOpportunityData(
                client=self.client_obj,
                title="Oportunidade com observações",
                owner=self.creator,
                source=self.source,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.creator,
            )
        )
        self.detail_url = f"/crm/oportunidades/{self.opportunity.pk}/"
        self.activity_create_url = f"/crm/oportunidades/{self.opportunity.pk}/atividades/nova/"
        self.observation_type = ActivityType.objects.get(code="OBSERVACAO")

    def _viewer(self, username, *extra_codenames):
        return _user_with_perms(username, "view_opportunities", *extra_codenames)


class ObservationButtonVisibilityTest(OpportunityObservationsTestBase):
    def test_add_button_hidden_without_add_commercial_activities(self):
        viewer = self._viewer("obs_sem_permissao", "view_commercial_activities")
        self.client.force_login(viewer)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b'data-open-modal="opp-observation-modal"', resp.content)
        self.assertNotIn(b'id="opp-observation-modal"', resp.content)

    def test_add_button_visible_with_add_commercial_activities(self):
        actor = self._viewer("obs_com_permissao", "add_commercial_activities")
        self.client.force_login(actor)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'data-open-modal="opp-observation-modal"', resp.content)
        self.assertIn(b'id="opp-observation-modal"', resp.content)


class SaveObservationTest(OpportunityObservationsTestBase):
    def test_saving_creates_a_commercial_activity_of_type_observacao(self):
        actor = self._viewer("obs_salvar", "add_commercial_activities")
        self.client.force_login(actor)
        resp = self.client.post(
            self.activity_create_url,
            {"activity_type": self.observation_type.pk, "description": "Cliente solicitou retorno amanhã."},
        )
        self.assertEqual(resp.status_code, 302)
        obs = CommercialActivity.objects.get(opportunity=self.opportunity)
        self.assertEqual(obs.activity_type, self.observation_type)
        self.assertEqual(obs.description, "Cliente solicitou retorno amanhã.")
        self.assertEqual(obs.created_by, actor)
        self.assertIsNotNone(obs.created_at)

    def test_saved_observation_appears_in_visao_geral_list(self):
        actor = self._viewer("obs_lista", "add_commercial_activities", "view_commercial_activities")
        self.client.force_login(actor)
        self.client.post(
            self.activity_create_url,
            {"activity_type": self.observation_type.pk, "description": "Observação visível na lista."},
        )
        resp = self.client.get(self.detail_url)
        self.assertContains(resp, "Observação visível na lista.")

    def test_missing_activity_type_is_rejected(self):
        """
        `description` é opcional no form geral de Atividades (mesmo
        comportamento de sempre, não alterado por esta rodada — o
        `required` no `<textarea>` do modal é só client-side/UX). O que
        de fato invalida o POST é faltar o tipo (campo oculto adulterado/
        removido).
        """
        actor = self._viewer("obs_sem_tipo", "add_commercial_activities")
        self.client.force_login(actor)
        resp = self.client.post(self.activity_create_url, {"description": "sem tipo"})
        self.assertEqual(resp.status_code, 302)  # redireciona de volta com mensagem de erro
        self.assertFalse(CommercialActivity.objects.filter(opportunity=self.opportunity).exists())


class ObservationVisibilityRespectsViewPermissionTest(OpportunityObservationsTestBase):
    def test_observations_list_hidden_without_view_commercial_activities(self):
        self.opportunity.activities.create(
            activity_type=self.observation_type, description="conteudo-sensivel-observacao", created_by=self.creator
        )
        viewer = self._viewer("obs_sem_view")  # só view_opportunities
        self.client.force_login(viewer)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"conteudo-sensivel-observacao", resp.content)

    def test_observations_list_visible_with_view_commercial_activities(self):
        self.opportunity.activities.create(
            activity_type=self.observation_type, description="conteudo-visivel-observacao", created_by=self.creator
        )
        viewer = self._viewer("obs_com_view", "view_commercial_activities")
        self.client.force_login(viewer)
        resp = self.client.get(self.detail_url)
        self.assertContains(resp, "conteudo-visivel-observacao")


class LegacyNotesFieldStillWorksTest(OpportunityObservationsTestBase):
    """`opportunity.notes` (texto livre único já existente) não pode ser afetado por esta rodada."""

    def test_legacy_notes_field_still_displays_unchanged(self):
        self.opportunity.notes = "Nota antiga registrada na criação da oportunidade."
        self.opportunity.save(update_fields=["notes"])
        viewer = self._viewer("obs_notas_legado")
        self.client.force_login(viewer)
        resp = self.client.get(self.detail_url)
        self.assertContains(resp, "Nota antiga registrada na criação da oportunidade.")

    def test_empty_state_shown_when_no_notes_and_no_observations(self):
        viewer = self._viewer("obs_estado_vazio", "view_commercial_activities")
        self.client.force_login(viewer)
        resp = self.client.get(self.detail_url)
        self.assertContains(resp, "Nenhuma observação cadastrada.")


class ObservationCsrfProtectionTest(OpportunityObservationsTestBase):
    def test_post_without_csrf_token_is_rejected(self):
        actor = self._viewer("obs_csrf", "add_commercial_activities")
        enforced_client = DjangoTestClient(enforce_csrf_checks=True)
        enforced_client.force_login(actor)
        resp = enforced_client.post(
            self.activity_create_url,
            {"activity_type": self.observation_type.pk, "description": "sem csrf"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(CommercialActivity.objects.filter(opportunity=self.opportunity).exists())
