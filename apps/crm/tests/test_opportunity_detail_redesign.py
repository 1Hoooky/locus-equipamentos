"""
REDESIGN COMPLETO DA TELA INTERNA DA OPORTUNIDADE (12/09/2026) — testes da
nova apresentação (`templates/crm/opportunity_detail.html`) e das duas
ações novas na UI ("Registrar perda"/"Orçamento aceito"), que continuam
sendo o MESMO endpoint/form/service já cobertos por
`test_permission_matrix.py`/`test_security.py`.

Convenções desta suíte (mesmas dos dois arquivos acima): `_user_with_perms`
para montar um usuário com um subconjunto exato de Permission do app
`crm`, matriz de 4 perfis (A=nenhuma permissão, B=só `view_opportunities`,
C=permissão exata, D=superusuário), `DjangoTestClient(enforce_csrf_checks=True)`
para o teste de CSRF.

Estes testes focam no que é GENUINAMENTE novo nesta rodada: visibilidade
condicional dos botões "Registrar perda"/"Orçamento aceito" na
renderização (permissão + estado já alcançado), o fluxo dos dois modais
(que postam para o MESMO `crm:opportunity_change_stage` de sempre), e a
garantia de que nenhuma arquitetura paralela (model/campo booleano novo)
foi criada. Cobertura de IDOR/GET-nunca-muta/histórico-correto/etc já
genérica em `test_security.py` não é duplicada aqui.
"""


from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client as DjangoTestClient
from django.test import TestCase

from apps.clients.models import Client
from apps.crm.models import (
    BusinessType,
    CommercialSource,
    LossReason,
    Opportunity,
    OpportunityStage,
    OpportunityStageChange,
)
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


class OpportunityDetailRedesignTestBase(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(company_name="Cliente Redesign")
        self.source = CommercialSource.objects.create(name="Indicação")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_qualificacao = OpportunityStage.objects.create(name="Qualificação", order=2)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho", order=3, is_won=True)
        self.stage_perdido = OpportunityStage.objects.create(name="Perdido", order=4, is_lost=True)
        self.loss_reason = LossReason.objects.create(name="Preço")

        self.creator = _user_with_perms("criador_redesign", "add_opportunities")
        self.opportunity = create_opportunity(
            NewOpportunityData(
                client=self.client_obj,
                title="Oportunidade do redesign",
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


# 1/2/3. Visibilidade condicionada por permissão -----------------------------


class ButtonVisibilityByPermissionTest(OpportunityDetailRedesignTestBase):
    """
    Um usuário que só pode VER a oportunidade (sem `change_opportunity_stage`)
    enxerga a etapa atual, mas NUNCA um seletor editável nem os botões
    "Registrar perda"/"Orçamento aceito" — nem no HTML (não é só CSS
    escondendo, o backend nunca envia o formulário/modal no contexto).
    """

    def test_view_only_user_sees_stage_but_no_stage_change_controls(self):
        viewer = self._viewer("view_only_redesign")
        self.client.force_login(viewer)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Novo", resp.content)  # etapa atual, mostrada como badge
        self.assertNotIn(b'id="opp-quick-stage-form"', resp.content)
        self.assertNotIn(b"Registrar perda", resp.content)
        self.assertNotIn("Orçamento aceito".encode(), resp.content)

    def test_user_with_change_stage_permission_sees_all_controls(self):
        actor = self._viewer("can_change_stage_redesign", "change_opportunity_stage")
        self.client.force_login(actor)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'id="opp-quick-stage-form"', resp.content)
        self.assertIn(b"Registrar perda", resp.content)
        self.assertIn("Orçamento aceito".encode(), resp.content)
        self.assertIn(b'id="opp-loss-modal"', resp.content)
        self.assertIn(b'id="opp-accept-modal"', resp.content)

    def test_editar_oportunidade_is_a_secondary_action_inside_options_menu(self):
        actor = self._viewer("can_edit_redesign", "change_opportunities")
        self.client.force_login(actor)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Editar oportunidade", resp.content)
        self.assertIn(b"data-action-menu-panel", resp.content)


# 4. Manual POST sem permissão continua bloqueado (defesa também no backend) -


class ManualPostWithoutPermissionBlockedTest(OpportunityDetailRedesignTestBase):
    def test_post_loss_fields_without_permission_is_blocked_and_nothing_changes(self):
        user = self._viewer("no_stage_perm_loss")  # só view_opportunities
        self.client.force_login(user)
        resp = self.client.post(
            self.stage_url,
            {"stage": self.stage_perdido.pk, "loss_reason": self.loss_reason.pk, "loss_notes": "tentativa indevida"},
        )
        self.assertEqual(resp.status_code, 403)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_novo)
        self.assertIsNone(self.opportunity.lost_at)

    def test_post_won_fields_without_permission_is_blocked_and_nothing_changes(self):
        user = self._viewer("no_stage_perm_won")
        self.client.force_login(user)
        resp = self.client.post(self.stage_url, {"stage": self.stage_ganho.pk})
        self.assertEqual(resp.status_code, 403)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_novo)
        self.assertIsNone(self.opportunity.won_at)


# 5/6/7. Fluxo "Registrar perda" (exatamente os campos que o novo modal envia)


class RegistrarPerdaFlowTest(OpportunityDetailRedesignTestBase):
    def test_registrar_perda_moves_to_lost_stage_and_records_history(self):
        actor = self._viewer("perda_flow", "change_opportunity_stage")
        self.client.force_login(actor)

        resp = self.client.post(
            self.stage_url,
            {
                "stage": self.stage_perdido.pk,
                "loss_reason": self.loss_reason.pk,
                "loss_notes": "Cliente escolheu concorrente.",
            },
        )
        self.assertEqual(resp.status_code, 302)

        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_perdido)
        self.assertIsNotNone(self.opportunity.lost_at)
        self.assertEqual(self.opportunity.loss_reason, self.loss_reason)
        self.assertEqual(self.opportunity.loss_notes, "Cliente escolheu concorrente.")

        change = self.opportunity.stage_changes.order_by("-changed_at").first()
        self.assertIsNotNone(change)
        self.assertEqual(change.to_stage, self.stage_perdido)
        self.assertEqual(change.from_stage, self.stage_novo)

    def test_registrar_perda_without_loss_reason_is_rejected_by_backend(self):
        """
        A validação de motivo obrigatório continua 100% no backend
        (`OpportunityStageChangeForm.clean()`) — o modal novo não introduz
        nenhum caminho que contorne essa exigência.
        """
        actor = self._viewer("perda_sem_motivo", "change_opportunity_stage")
        self.client.force_login(actor)
        resp = self.client.post(self.stage_url, {"stage": self.stage_perdido.pk})
        self.assertEqual(resp.status_code, 302)  # redireciona de volta com mensagem de erro
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_novo)  # nada mudou


# 8. Fluxo "Orçamento aceito" -------------------------------------------------


class OrcamentoAceitoFlowTest(OpportunityDetailRedesignTestBase):
    def test_orcamento_aceito_moves_to_won_stage_and_records_history(self):
        actor = self._viewer("aceite_flow", "change_opportunity_stage")
        self.client.force_login(actor)

        resp = self.client.post(self.stage_url, {"stage": self.stage_ganho.pk})
        self.assertEqual(resp.status_code, 302)

        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_ganho)
        self.assertIsNotNone(self.opportunity.won_at)

        change = self.opportunity.stage_changes.order_by("-changed_at").first()
        self.assertIsNotNone(change)
        self.assertEqual(change.to_stage, self.stage_ganho)


# 9. Nenhuma arquitetura paralela criada --------------------------------------


class NoParallelArchitectureTest(TestCase):
    """
    "Orçamento aceito" é sempre uma mudança de ETAPA (`change_opportunity_
    stage()` para uma etapa `is_won`) — nunca um booleano/model novo. Estes
    testes protegem a decisão explícita contra reintrodução futura
    acidental de `orcamento_aceito`/`accepted_budget`/`Proposal`.
    """

    def test_opportunity_model_has_no_accepted_budget_style_field(self):
        field_names = {f.name for f in Opportunity._meta.get_fields()}
        forbidden = {"orcamento_aceito", "accepted_budget", "budget_accepted", "is_accepted"}
        self.assertFalse(field_names & forbidden, f"campo booleano paralelo encontrado: {field_names & forbidden}")

    def test_no_proposal_model_exists_in_crm_app(self):
        import apps.crm.models as crm_models

        self.assertFalse(hasattr(crm_models, "Proposal"))
        self.assertFalse(hasattr(crm_models, "ProposalItem"))


# 10. GET nunca muda estado (endpoint único, já sem `get()`) ------------------


class GetNeverMutatesForNewActionsTest(OpportunityDetailRedesignTestBase):
    def test_get_with_lost_stage_payload_is_not_allowed(self):
        actor = self._viewer("get_loss_redesign", "change_opportunity_stage")
        self.client.force_login(actor)
        resp = self.client.get(self.stage_url, {"stage": self.stage_perdido.pk, "loss_reason": self.loss_reason.pk})
        self.assertEqual(resp.status_code, 405)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_novo)

    def test_get_with_won_stage_payload_is_not_allowed(self):
        actor = self._viewer("get_won_redesign", "change_opportunity_stage")
        self.client.force_login(actor)
        resp = self.client.get(self.stage_url, {"stage": self.stage_ganho.pk})
        self.assertEqual(resp.status_code, 405)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_novo)


# 11. CSRF continua obrigatório -------------------------------------------------


class CsrfStillMandatoryForNewActionsTest(OpportunityDetailRedesignTestBase):
    def test_orcamento_aceito_post_without_csrf_token_is_rejected(self):
        actor = self._viewer("csrf_won_redesign", "change_opportunity_stage")
        strict_client = DjangoTestClient(enforce_csrf_checks=True)
        strict_client.force_login(actor)
        resp = strict_client.post(self.stage_url, {"stage": self.stage_ganho.pk})
        self.assertEqual(resp.status_code, 403)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_novo)

    def test_registrar_perda_post_without_csrf_token_is_rejected(self):
        actor = self._viewer("csrf_lost_redesign", "change_opportunity_stage")
        strict_client = DjangoTestClient(enforce_csrf_checks=True)
        strict_client.force_login(actor)
        resp = strict_client.post(
            self.stage_url, {"stage": self.stage_perdido.pk, "loss_reason": self.loss_reason.pk}
        )
        self.assertEqual(resp.status_code, 403)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_novo)


# 12/13. Estado já alcançado nunca mostra a ação como se ainda estivesse aberta


class AlreadyWonOrLostHidesMatchingActionTest(OpportunityDetailRedesignTestBase):
    def test_already_won_hides_accept_action_but_keeps_loss_action(self):
        actor = self._viewer("already_won_redesign", "change_opportunity_stage")
        self.opportunity.stage = self.stage_ganho
        self.opportunity.save(update_fields=["stage"])

        self.client.force_login(actor)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b'id="opp-accept-modal"', resp.content)
        self.assertIn(b"Registrar perda", resp.content)  # ação oposta ainda disponível (corrigir por engano)
        self.assertIn("Orçamento aceito".encode(), resp.content)  # indicador de estado positivo, não o botão de ação

    def test_already_lost_hides_loss_action_but_keeps_accept_action(self):
        actor = self._viewer("already_lost_redesign", "change_opportunity_stage")
        self.opportunity.stage = self.stage_perdido
        self.opportunity.loss_reason = self.loss_reason
        self.opportunity.save(update_fields=["stage", "loss_reason"])

        self.client.force_login(actor)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b'id="opp-loss-modal"', resp.content)
        self.assertIn("Orçamento aceito".encode(), resp.content)  # ação oposta ainda disponível
        self.assertIn("Negociação perdida".encode(), resp.content)
        self.assertIn("Preço".encode(), resp.content)  # motivo da perda exibido


# 14. Mudança de etapa normal continua funcionando -----------------------------


class NormalStageChangeStillWorksTest(OpportunityDetailRedesignTestBase):
    def test_moving_to_an_intermediate_stage_still_works(self):
        actor = self._viewer("normal_stage_redesign", "change_opportunity_stage")
        self.client.force_login(actor)
        resp = self.client.post(self.stage_url, {"stage": self.stage_qualificacao.pk})
        self.assertEqual(resp.status_code, 302)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_qualificacao)


# 15/16. Atividades e Histórico continuam sendo exibidos na tela -------------


class ActivitiesAndHistoryStillDisplayTest(OpportunityDetailRedesignTestBase):
    def test_commercial_activity_still_displays_in_the_activities_tab(self):
        self.opportunity.activities.create(
            activity_type="LIGACAO", description="ligação de acompanhamento redesign", created_by=self.creator
        )
        actor = self._viewer("activities_display_redesign", "view_commercial_activities")
        self.client.force_login(actor)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"liga\xc3\xa7\xc3\xa3o de acompanhamento redesign", resp.content)
        self.assertIn(b'data-tab-panel="atividades"', resp.content)

    def test_stage_history_still_displays_in_the_historico_tab(self):
        actor = self._viewer("history_display_redesign", "change_opportunity_stage")
        self.client.force_login(actor)
        self.client.post(self.stage_url, {"stage": self.stage_qualificacao.pk})

        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'data-tab-panel="historico"', resp.content)
        self.assertIn(b"Qualifica\xc3\xa7\xc3\xa3o", resp.content)
        self.assertEqual(
            OpportunityStageChange.objects.filter(opportunity=self.opportunity).count(),
            2,  # criação + a mudança acima
        )


# 17. Edição continua funcionando (mesmo form/fluxo de sempre) ----------------


class EditingStillWorksTest(OpportunityDetailRedesignTestBase):
    def test_edit_flow_still_reachable_and_functional(self):
        actor = self._viewer("edit_still_works_redesign", "change_opportunities")
        self.client.force_login(actor)
        edit_url = f"/crm/oportunidades/{self.opportunity.pk}/editar/"
        resp = self.client.post(
            edit_url,
            {
                "title": "Título editado pelo redesign",
                "owner": self.creator.pk,
                "source": self.source.pk,
                "business_type": BusinessType.VENDA,
                "notes": "",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.title, "Título editado pelo redesign")


# 18. Cliente nunca é alterado pelos novos fluxos -----------------------------


class ClientNeverAlteredByNewActionsTest(OpportunityDetailRedesignTestBase):
    def test_client_untouched_after_registrar_perda_and_orcamento_aceito(self):
        original_name = self.client_obj.company_name
        actor = self._viewer("client_untouched_redesign", "change_opportunity_stage")
        self.client.force_login(actor)

        self.client.post(
            self.stage_url, {"stage": self.stage_perdido.pk, "loss_reason": self.loss_reason.pk}
        )
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.company_name, original_name)

        # reabre e aceita, em seguida.
        self.client.post(self.stage_url, {"stage": self.stage_novo.pk})
        self.client.post(self.stage_url, {"stage": self.stage_ganho.pk})
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.company_name, original_name)


# 19. Kanban permanece consistente após mudança de etapa pela tela de detalhe -


class KanbanConsistentAfterDetailStageChangeTest(OpportunityDetailRedesignTestBase):
    def test_kanban_reflects_stage_change_made_from_detail_page(self):
        actor = self._viewer("kanban_consistency_redesign", "change_opportunity_stage")
        self.client.force_login(actor)

        resp = self.client.post(self.stage_url, {"stage": self.stage_ganho.pk})
        self.assertEqual(resp.status_code, 302)

        kanban_resp = self.client.get("/crm/oportunidades/")
        self.assertEqual(kanban_resp.status_code, 200)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_ganho)
        self.assertIn(self.opportunity.title.encode(), kanban_resp.content)
