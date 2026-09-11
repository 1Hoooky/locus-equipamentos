"""
Drawer lateral de "Nova oportunidade" no Funil Kanban — rodada "CRIAÇÃO
RÁPIDA SEM SAIR DO FUNIL", 11/09/2026.

Cobre exatamente os 16 cenários mínimos pedidos (ver RELATORIO_CRIACAO_
RAPIDA_OPORTUNIDADE_DRAWER.md) mais os detalhes específicos do drawer
(marcação embutida no Kanban, etapa inicial sugerida, resposta AJAX de
sucesso/erro, respeito aos filtros ativos ao decidir se o card aparece
imediatamente). A integridade de `change_opportunity_stage`/ganho-perda/
concorrência já é coberta por test_services.py/test_stage_change_
concurrency.py — aqui o foco é SÓ o novo caminho de criação (drawer +
rota tradicional, que são o MESMO endpoint/form/service).
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client as DjangoTestClient
from django.test import TestCase

from apps.clients.models import Client
from apps.crm.models import BusinessType, CommercialSource, LossReason, Opportunity, OpportunityStage, OpportunityStageChange
from apps.crm.services import NewOpportunityData, create_opportunity

User = get_user_model()

AJAX_HEADERS = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


def _user_with_perms(username, *codenames):
    user = User.objects.create_user(username=username, password="senha-forte-123")
    if codenames:
        perms = Permission.objects.filter(codename__in=codenames, content_type__app_label="crm")
        group, _ = Group.objects.get_or_create(name=f"perm-{username}")
        group.permissions.set(perms)
        user.groups.add(group)
    return user


class QuickCreateDrawerTestBase(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(company_name="Cliente Drawer")
        self.other_client = Client.objects.create(company_name="Cliente Drawer Outro")
        self.source = CommercialSource.objects.create(name="Site", order=1)
        self.other_source = CommercialSource.objects.create(name="Indicação", order=2)
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_qualificacao = OpportunityStage.objects.create(name="Qualificação", order=2)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho", order=3, is_won=True)
        self.stage_perdido = OpportunityStage.objects.create(name="Perdido", order=4, is_lost=True)
        self.stage_inativa = OpportunityStage.objects.create(name="Descontinuada", order=0, is_active=False)
        self.loss_reason = LossReason.objects.create(name="Preço")

        # `view_opportunities` também é necessário para os testes que
        # carregam o Kanban (GET) ou seguem o redirect até a ficha da
        # oportunidade — a CRIAÇÃO em si (`add_opportunities`) é uma
        # permissão distinta, mas um usuário real precisa das duas para
        # usar o fluxo completo do drawer (ver View/etapa da oportunidade).
        self.creator = _user_with_perms("drawer_creator", "add_opportunities", "view_opportunities")
        self.viewer = _user_with_perms("drawer_viewer", "view_opportunities")
        self.stranger = _user_with_perms("drawer_stranger")  # nenhuma permissão

    def _valid_payload(self, **overrides):
        payload = {
            "client": self.client_obj.pk,
            "title": "Oportunidade via drawer",
            "owner": self.creator.pk,
            "source": self.source.pk,
            "business_type": BusinessType.LOCACAO,
            "stage": self.stage_novo.pk,
            "expected_close_date": "",
            "estimated_value": "",
            "notes": "",
        }
        payload.update(overrides)
        return payload


# ---------------------------------------------------------------------------
# 1-2) Permissão — botão/drawer não aparecem sem permissão; POST AJAX bloqueado.
# ---------------------------------------------------------------------------


class DrawerPermissionTest(QuickCreateDrawerTestBase):
    def test_button_and_drawer_markup_absent_without_permission(self):
        self.client.force_login(self.viewer)
        content = self.client.get("/crm/oportunidades/").content.decode()
        self.assertNotIn('id="opportunity-quick-create-open"', content)
        self.assertNotIn('id="opportunity-quick-create-drawer"', content)
        self.assertNotIn('id="opportunity-quick-create-form"', content)

    def test_button_and_drawer_markup_present_with_permission(self):
        self.client.force_login(self.creator)
        content = self.client.get("/crm/oportunidades/").content.decode()
        self.assertIn('id="opportunity-quick-create-open"', content)
        self.assertIn('id="opportunity-quick-create-drawer"', content)
        self.assertIn('id="opportunity-quick-create-form"', content)
        # A ação POST do drawer é a MESMA rota tradicional — nunca uma
        # URL nova/paralela.
        self.assertIn('action="/crm/oportunidades/nova/"', content)

    def test_ajax_post_without_permission_is_blocked(self):
        self.client.force_login(self.stranger)
        before = Opportunity.objects.count()
        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload(), **AJAX_HEADERS)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Opportunity.objects.count(), before)

    def test_ajax_post_with_only_view_permission_is_blocked(self):
        self.client.force_login(self.viewer)
        before = Opportunity.objects.count()
        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload(), **AJAX_HEADERS)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Opportunity.objects.count(), before)

    def test_direct_traditional_route_also_blocked_without_permission(self):
        """"NADA SAI SEM PERMISSÃO" vale para os dois caminhos — o drawer
        não pode ser burlado tentando a rota tradicional direto."""
        self.client.force_login(self.stranger)
        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Opportunity.objects.count(), 0)


# ---------------------------------------------------------------------------
# 3) Usuário autorizado consegue criar (caminho AJAX do drawer).
# ---------------------------------------------------------------------------


class DrawerSuccessfulCreationTest(QuickCreateDrawerTestBase):
    def test_authorized_user_creates_opportunity_via_ajax(self):
        self.client.force_login(self.creator)
        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload(), **AJAX_HEADERS)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIn("Oportunidade via drawer", data["message"])
        self.assertEqual(data["stage_id"], self.stage_novo.pk)
        self.assertTrue(data["matches_current_filters"])
        self.assertIn("Oportunidade via drawer", data["card_html"])
        self.assertIn(str(self.stage_novo.pk), str(data["destination_stage"]["id"]))
        self.assertEqual(data["destination_stage"]["count"], 1)

        opportunity = Opportunity.objects.get(title="Oportunidade via drawer")
        self.assertEqual(opportunity.client_id, self.client_obj.pk)
        self.assertEqual(opportunity.stage_id, self.stage_novo.pk)

    def test_card_html_reflects_matches_current_filters_false_when_filtered_out(self):
        """Criada com Origem A, mas a tela está filtrada por Origem B —
        a oportunidade existe no banco, mas não deve ser inserida
        visualmente sob o filtro ativo (o backend informa isso via
        `matches_current_filters`, nunca uma lógica de filtro duplicada
        em JS)."""
        self.client.force_login(self.creator)
        url = f"/crm/oportunidades/nova/?source={self.other_source.pk}"
        response = self.client.post(url, self._valid_payload(source=self.source.pk), **AJAX_HEADERS)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["matches_current_filters"])
        # A contagem/total da coluna respeita o MESMO filtro — a
        # oportunidade recém-criada não deveria entrar na conta.
        self.assertEqual(data["destination_stage"]["count"], 0)


# ---------------------------------------------------------------------------
# 4) CSRF
# ---------------------------------------------------------------------------


class DrawerCsrfTest(QuickCreateDrawerTestBase):
    def test_ajax_post_without_csrf_token_is_rejected(self):
        strict_client = DjangoTestClient(enforce_csrf_checks=True)
        strict_client.force_login(self.creator)
        response = strict_client.post("/crm/oportunidades/nova/", self._valid_payload(), **AJAX_HEADERS)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Opportunity.objects.count(), 0)


# ---------------------------------------------------------------------------
# 5-9) Validação de campo — cliente/responsável/etapa/valor inválidos.
# ---------------------------------------------------------------------------


class DrawerValidationTest(QuickCreateDrawerTestBase):
    def test_invalid_client_is_rejected_without_creating_partial_state(self):
        self.client.force_login(self.creator)
        before = Opportunity.objects.count()
        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload(client=999999), **AJAX_HEADERS)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"field-error", response.content)
        self.assertEqual(Opportunity.objects.count(), before)

    def test_ineligible_owner_is_rejected(self):
        """Responsável elegível é decidido por `eligible_owner_queryset()`
        no backend — um usuário sem `add_opportunities` (o stranger) não
        pode virar owner nem manipulando o PK à mão no POST."""
        self.client.force_login(self.creator)
        before = Opportunity.objects.count()
        response = self.client.post(
            "/crm/oportunidades/nova/", self._valid_payload(owner=self.stranger.pk), **AJAX_HEADERS
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Opportunity.objects.count(), before)

    def test_stage_outside_eligible_queryset_is_rejected(self):
        """Etapa inválida — PK que não existe."""
        self.client.force_login(self.creator)
        before = Opportunity.objects.count()
        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload(stage=999999), **AJAX_HEADERS)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Opportunity.objects.count(), before)

    def test_won_stage_is_blocked_at_creation(self):
        """Ganho/perda continuam bloqueados na criação: `stage` do form
        só aceita etapas is_won=False/is_lost=False — postar o PK de uma
        etapa de GANHO é rejeitado pela própria validação do campo
        (nem chega a `create_opportunity`, que também rejeitaria)."""
        self.client.force_login(self.creator)
        before = Opportunity.objects.count()
        response = self.client.post(
            "/crm/oportunidades/nova/", self._valid_payload(stage=self.stage_ganho.pk), **AJAX_HEADERS
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Opportunity.objects.count(), before)

    def test_lost_stage_is_blocked_at_creation(self):
        self.client.force_login(self.creator)
        before = Opportunity.objects.count()
        response = self.client.post(
            "/crm/oportunidades/nova/", self._valid_payload(stage=self.stage_perdido.pk), **AJAX_HEADERS
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Opportunity.objects.count(), before)

    def test_inactive_stage_is_blocked_at_creation(self):
        self.client.force_login(self.creator)
        before = Opportunity.objects.count()
        response = self.client.post(
            "/crm/oportunidades/nova/", self._valid_payload(stage=self.stage_inativa.pk), **AJAX_HEADERS
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Opportunity.objects.count(), before)

    def test_negative_estimated_value_is_rejected(self):
        self.client.force_login(self.creator)
        before = Opportunity.objects.count()
        response = self.client.post(
            "/crm/oportunidades/nova/", self._valid_payload(estimated_value="-100.00"), **AJAX_HEADERS
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Opportunity.objects.count(), before)

    def test_missing_required_title_is_rejected_and_keeps_other_values(self):
        """Erro de validação nunca fecha o drawer nem perde os dados —
        o fragmento devolvido é o MESMO form, bound, reexibindo o que
        já tinha sido preenchido nos outros campos."""
        self.client.force_login(self.creator)
        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload(title=""), **AJAX_HEADERS)
        self.assertEqual(response.status_code, 400)
        content = response.content.decode()
        self.assertIn("field-error", content)
        # Cliente selecionado continua marcado no <select> reexibido.
        self.assertIn(f'value="{self.client_obj.pk}" selected', content)


# ---------------------------------------------------------------------------
# 10-13) Criação válida — exatamente UMA Opportunity, histórico, created_by,
# Client nunca modificado.
# ---------------------------------------------------------------------------


class DrawerCreationIntegrityTest(QuickCreateDrawerTestBase):
    def test_valid_creation_produces_exactly_one_opportunity_and_one_history_row(self):
        self.client.force_login(self.creator)
        before_opportunities = Opportunity.objects.count()
        before_history = OpportunityStageChange.objects.count()

        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload(), **AJAX_HEADERS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Opportunity.objects.count(), before_opportunities + 1)
        self.assertEqual(OpportunityStageChange.objects.count(), before_history + 1)

        change = OpportunityStageChange.objects.latest("changed_at")
        self.assertIsNone(change.from_stage)
        self.assertEqual(change.to_stage, self.stage_novo)
        self.assertEqual(change.changed_by, self.creator)

    def test_created_by_is_the_authenticated_user(self):
        self.client.force_login(self.creator)
        self.client.post("/crm/oportunidades/nova/", self._valid_payload(), **AJAX_HEADERS)
        opportunity = Opportunity.objects.get(title="Oportunidade via drawer")
        self.assertEqual(opportunity.created_by, self.creator)

    def test_client_record_is_never_modified_by_quick_creation(self):
        original = {
            "company_name": self.client_obj.company_name,
            "trade_name": self.client_obj.trade_name,
            "document": self.client_obj.document,
        }
        self.client.force_login(self.creator)
        self.client.post("/crm/oportunidades/nova/", self._valid_payload(), **AJAX_HEADERS)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.company_name, original["company_name"])
        self.assertEqual(self.client_obj.trade_name, original["trade_name"])
        self.assertEqual(self.client_obj.document, original["document"])


# ---------------------------------------------------------------------------
# 15) Rota tradicional — mesma lógica segura, continua funcionando sem AJAX.
# ---------------------------------------------------------------------------


class TraditionalRouteStillWorksTest(QuickCreateDrawerTestBase):
    def test_traditional_get_renders_full_page_with_stage_preselected(self):
        self.client.force_login(self.creator)
        response = self.client.get("/crm/oportunidades/nova/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Etapa inicial sugerida: primeira etapa ativa não-ganho/não-perda
        # pela ordem (`stage_novo`, order=1) — mesma regra usada pelo
        # drawer (_default_new_opportunity_stage), nunca hardcoded.
        self.assertIn(f'value="{self.stage_novo.pk}" selected', content)

    def test_traditional_post_without_ajax_header_redirects_with_message(self):
        self.client.force_login(self.creator)
        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload())
        opportunity = Opportunity.objects.get(title="Oportunidade via drawer")
        self.assertRedirects(response, f"/crm/oportunidades/{opportunity.pk}/")

    def test_traditional_post_invalid_without_ajax_header_rerenders_full_page(self):
        self.client.force_login(self.creator)
        response = self.client.post("/crm/oportunidades/nova/", self._valid_payload(title=""))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"field-error", response.content)
        self.assertEqual(Opportunity.objects.count(), 0)


# ---------------------------------------------------------------------------
# Etapa inicial sugerida no drawer (mesma regra da rota tradicional).
# ---------------------------------------------------------------------------


class DefaultStagePreselectionTest(QuickCreateDrawerTestBase):
    def test_drawer_form_preselects_first_eligible_active_stage_by_order(self):
        self.client.force_login(self.creator)
        content = self.client.get("/crm/oportunidades/").content.decode()
        # stage_novo tem order=1 e é a primeira ativa não-ganho/não-perda
        # (stage_inativa tem order=0 mas está desativada — não conta).
        self.assertIn(f'value="{self.stage_novo.pk}" selected', content)
        self.assertNotIn(f'value="{self.stage_qualificacao.pk}" selected', content)
