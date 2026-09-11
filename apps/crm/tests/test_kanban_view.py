"""
Funil Kanban de oportunidades (CRM) — testes da view de listagem
(`crm:opportunity_list`, agora Kanban) e do endpoint AJAX de mudança de
etapa (`crm:opportunity_change_stage`, branch JSON via
`X-Requested-With: XMLHttpRequest`), adicionados na rodada de 11/09/2026
que substituiu a listagem em tabela pelo Kanban (drag-and-drop real).

Cobre especificamente o que é NOVO nesta rodada — a matriz de permissão
genérica de cada ação já existe em `test_permission_matrix.py`, e a
integridade da própria transição de etapa (ganho/perda/reabertura) já é
coberta por `test_services.py`/`test_security.py`. Aqui: agrupamento por
etapa, totais consolidados, filtros sem "Etapa", e o comportamento da
resposta JSON (sucesso e erro) do endpoint AJAX — incluindo a garantia de
que o form-POST normal (não-AJAX) continua se comportando exatamente como
antes (redirect + framework de messages).
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from apps.clients.models import Client
from apps.crm.models import BusinessType, CommercialSource, LossReason, OpportunityStage
from apps.crm.services import NewOpportunityData, change_opportunity_stage, create_opportunity

User = get_user_model()


def _user_with_perms(username, *codenames):
    user = User.objects.create_user(username=username, password="senha-forte-123")
    if codenames:
        perms = Permission.objects.filter(codename__in=codenames, content_type__app_label="crm")
        group, _ = Group.objects.get_or_create(name=f"perm-{username}")
        group.permissions.set(perms)
        user.groups.add(group)
    return user


class KanbanViewTestBase(TestCase):
    def setUp(self):
        self.client_a = Client.objects.create(company_name="Cliente Kanban A")
        self.client_b = Client.objects.create(company_name="Cliente Kanban B")
        self.source_site = CommercialSource.objects.create(name="Site", order=1)
        self.source_indicacao = CommercialSource.objects.create(name="Indicação", order=2)
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_qualificacao = OpportunityStage.objects.create(name="Qualificação", order=2)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho", order=3, is_won=True)
        self.stage_perdido = OpportunityStage.objects.create(name="Perdido", order=4, is_lost=True)
        self.stage_inativa = OpportunityStage.objects.create(name="Descontinuada", order=5, is_active=False)
        self.loss_reason = LossReason.objects.create(name="Preço")

        self.viewer = _user_with_perms("kanban_viewer", "view_opportunities")
        self.mover = _user_with_perms("kanban_mover", "view_opportunities", "change_opportunity_stage")
        self.stranger = _user_with_perms("kanban_stranger")  # nenhuma permissão

        self.opp_1 = create_opportunity(
            NewOpportunityData(
                client=self.client_a,
                title="Oportunidade Locação A",
                owner=self.viewer,
                source=self.source_site,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.viewer,
                estimated_value=Decimal("1000.00"),
            )
        )
        self.opp_2 = create_opportunity(
            NewOpportunityData(
                client=self.client_b,
                title="Oportunidade Venda B",
                owner=self.viewer,
                source=self.source_indicacao,
                business_type=BusinessType.VENDA,
                stage=self.stage_novo,
                created_by=self.viewer,
                estimated_value=Decimal("2500.50"),
            )
        )
        self.opp_3 = create_opportunity(
            NewOpportunityData(
                client=self.client_a,
                title="Oportunidade Serviço A",
                owner=self.viewer,
                source=self.source_site,
                business_type=BusinessType.SERVICO,
                stage=self.stage_qualificacao,
                created_by=self.viewer,
                estimated_value=Decimal("500.00"),
            )
        )


class KanbanRenderingTest(KanbanViewTestBase):
    def test_kanban_groups_opportunities_by_active_stage_and_hides_inactive_stage(self):
        self.client.force_login(self.viewer)
        response = self.client.get("/crm/oportunidades/")
        self.assertEqual(response.status_code, 200)

        columns = {column["stage"].pk: column for column in response.context["columns"]}
        self.assertIn(self.stage_novo.pk, columns)
        self.assertIn(self.stage_qualificacao.pk, columns)
        self.assertIn(self.stage_ganho.pk, columns)
        self.assertIn(self.stage_perdido.pk, columns)
        # Etapa desativada nunca vira coluna — mesmo raciocínio de
        # qualquer outro seletor de etapa ativa no sistema.
        self.assertNotIn(self.stage_inativa.pk, columns)

        self.assertEqual(columns[self.stage_novo.pk]["count"], 2)
        self.assertEqual(columns[self.stage_qualificacao.pk]["count"], 1)
        self.assertEqual(columns[self.stage_ganho.pk]["count"], 0)

        # Total consolidado da coluna "Novo": 1000,00 + 2500,50 = 3500,50.
        self.assertEqual(columns[self.stage_novo.pk]["total_value_display"], "R$ 3.500,50")
        self.assertContains(response, "R$ 3.500,50")
        self.assertContains(response, "Oportunidade Locação A")
        self.assertContains(response, "Oportunidade Venda B")

    def test_no_stage_filter_in_querystring_anymore(self):
        """Regressão: o antigo filtro "Etapa" não existe mais nesta tela."""
        self.client.force_login(self.viewer)
        response = self.client.get("/crm/oportunidades/")
        self.assertNotContains(response, 'name="stage"')

    def test_q_and_source_and_business_type_filters_still_work(self):
        self.client.force_login(self.viewer)

        response = self.client.get("/crm/oportunidades/", {"q": "Venda B"})
        titles = [o.title for column in response.context["columns"] for o in column["opportunities"]]
        self.assertEqual(titles, ["Oportunidade Venda B"])

        response = self.client.get("/crm/oportunidades/", {"source": self.source_indicacao.pk})
        titles = [o.title for column in response.context["columns"] for o in column["opportunities"]]
        self.assertEqual(titles, ["Oportunidade Venda B"])

        response = self.client.get("/crm/oportunidades/", {"business_type": BusinessType.SERVICO})
        titles = [o.title for column in response.context["columns"] for o in column["opportunities"]]
        self.assertEqual(titles, ["Oportunidade Serviço A"])

    def test_display_value_uses_closed_value_when_won_else_estimated(self):
        # Sem valor nenhum informado -> soma zero, nunca erro/None na tela.
        # (uma oportunidade nunca "nasce" ganha — precisa ser criada numa
        # etapa intermediária e então movida, ver apps.crm.services.
        # create_opportunity.)
        no_value_opp = create_opportunity(
            NewOpportunityData(
                client=self.client_a,
                title="Oportunidade sem valor",
                owner=self.viewer,
                source=self.source_site,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.viewer,
            )
        )
        change_opportunity_stage(
            opportunity_id=no_value_opp.pk, new_stage=self.stage_ganho, changed_by=self.viewer, closed_value=None
        )
        self.client.force_login(self.viewer)
        response = self.client.get("/crm/oportunidades/")
        columns = {column["stage"].pk: column for column in response.context["columns"]}
        self.assertEqual(columns[self.stage_ganho.pk]["total_value_display"], "R$ 0,00")

    def test_cards_not_draggable_without_change_stage_permission(self):
        self.client.force_login(self.viewer)  # só view_opportunities
        response = self.client.get("/crm/oportunidades/")
        self.assertContains(response, 'draggable="false"')
        self.assertNotContains(response, 'draggable="true"')

    def test_cards_draggable_with_change_stage_permission(self):
        self.client.force_login(self.mover)
        response = self.client.get("/crm/oportunidades/")
        self.assertContains(response, 'draggable="true"')

    def test_anonymous_and_stranger_blocked(self):
        response = self.client.get("/crm/oportunidades/")
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.stranger)
        response = self.client.get("/crm/oportunidades/")
        self.assertIn(response.status_code, (302, 403))


class KanbanAjaxStageChangeTest(KanbanViewTestBase):
    def _ajax_post(self, url, data):
        return self.client.post(url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_ajax_success_returns_json_with_origin_and_destination_summaries(self):
        self.client.force_login(self.mover)
        url = f"/crm/oportunidades/{self.opp_1.pk}/etapa/"
        response = self._ajax_post(url, {"stage": self.stage_qualificacao.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["origin_stage"]["id"], self.stage_novo.pk)
        self.assertEqual(data["origin_stage"]["count"], 1)  # só a opp_2 sobrou em "Novo"
        self.assertEqual(data["destination_stage"]["id"], self.stage_qualificacao.pk)
        self.assertEqual(data["destination_stage"]["count"], 2)  # opp_3 + opp_1 agora

        self.opp_1.refresh_from_db()
        self.assertEqual(self.opp_1.stage, self.stage_qualificacao)

    def test_ajax_respects_active_filters_when_recomputing_summaries(self):
        """
        Os totais de origem/destino devolvidos respeitam os MESMOS filtros
        ativos no Kanban no momento do arraste (a querystring da própria
        URL de POST) — não os totais gerais sem filtro.
        """
        self.client.force_login(self.mover)
        url = f"/crm/oportunidades/{self.opp_1.pk}/etapa/?source={self.source_site.pk}"
        response = self._ajax_post(url, {"stage": self.stage_qualificacao.pk})

        data = response.json()
        self.assertTrue(data["ok"])
        # Filtrando por "Site": "Novo" tinha só a opp_1 (Site) — depois de
        # mover, zero. opp_2 (Indicação) nunca entra nesta conta filtrada.
        self.assertEqual(data["origin_stage"]["count"], 0)
        # "Qualificação" filtrado por Site: opp_3 (Site) + opp_1 (Site) = 2.
        self.assertEqual(data["destination_stage"]["count"], 2)

    def test_ajax_missing_loss_reason_returns_400_without_changing_stage(self):
        self.client.force_login(self.mover)
        url = f"/crm/oportunidades/{self.opp_1.pk}/etapa/"
        response = self._ajax_post(url, {"stage": self.stage_perdido.pk})

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertIn("Motivo de perda", data["error"])

        self.opp_1.refresh_from_db()
        self.assertEqual(self.opp_1.stage, self.stage_novo)  # nada mudou

    def test_ajax_with_loss_reason_marks_lost(self):
        self.client.force_login(self.mover)
        url = f"/crm/oportunidades/{self.opp_1.pk}/etapa/"
        response = self._ajax_post(
            url, {"stage": self.stage_perdido.pk, "loss_reason": self.loss_reason.pk, "loss_notes": "Cliente foi para o concorrente."}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.opp_1.refresh_from_db()
        self.assertEqual(self.opp_1.stage, self.stage_perdido)
        self.assertIsNotNone(self.opp_1.lost_at)
        self.assertEqual(self.opp_1.loss_reason, self.loss_reason)

    def test_ajax_same_stage_returns_400(self):
        self.client.force_login(self.mover)
        url = f"/crm/oportunidades/{self.opp_1.pk}/etapa/"
        response = self._ajax_post(url, {"stage": self.stage_novo.pk})

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertIn("já está nesta etapa", data["error"])

    def test_ajax_without_permission_is_denied_and_does_not_return_json_success(self):
        self.client.force_login(self.viewer)  # só view_opportunities, sem change_opportunity_stage
        url = f"/crm/oportunidades/{self.opp_1.pk}/etapa/"
        response = self._ajax_post(url, {"stage": self.stage_qualificacao.pk})

        self.assertEqual(response.status_code, 403)
        self.opp_1.refresh_from_db()
        self.assertEqual(self.opp_1.stage, self.stage_novo)

    def test_non_ajax_post_behaviour_is_unchanged(self):
        """
        O form inline da ficha da oportunidade (POST normal, sem
        X-Requested-With) continua exatamente como antes: redirect +
        framework de messages, nunca JSON — regressão explícita desta
        rodada, que só ADICIONOU o branch AJAX, sem tocar no existente.
        """
        self.client.force_login(self.mover)
        url = f"/crm/oportunidades/{self.opp_1.pk}/etapa/"
        response = self.client.post(url, {"stage": self.stage_qualificacao.pk})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"/crm/oportunidades/{self.opp_1.pk}/")
        self.opp_1.refresh_from_db()
        self.assertEqual(self.opp_1.stage, self.stage_qualificacao)

    def test_non_ajax_invalid_transition_still_redirects_with_messages(self):
        self.client.force_login(self.mover)
        url = f"/crm/oportunidades/{self.opp_1.pk}/etapa/"
        response = self.client.post(url, {"stage": self.stage_perdido.pk}, follow=True)

        self.assertEqual(response.status_code, 200)
        messages_texts = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("Motivo de perda" in m for m in messages_texts))
