"""
Matriz obrigatória de permissões do CRM (LocusHub, Etapa 1) — 4 perfis ×
13 ações, comportamento HTTP/backend real (nunca só "o botão aparece").

Perfis:
  A — sem cargo/permissão nenhuma.
  B — só `view_opportunities` (só-leitura de oportunidades).
  C — só a permissão ESPECÍFICA exigida por aquela ação (uma por ação,
      nunca uma permissão "genérica" que resolveria tudo).
  D — Administrador/superusuário (bypass automático do Django).

Cada ação é testada com os 4 perfis: A e B devem ser bloqueados (exceto
quando a própria ação É leitura, caso em que B passa); C deve ser
permitido; D sempre permitido.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from apps.clients.models import Client
from apps.crm.models import BusinessType, CommercialSource, LossReason, Opportunity, OpportunityStage
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


class PermissionMatrixTest(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(company_name="Cliente Matriz")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_outra = OpportunityStage.objects.create(name="Qualificação", order=2)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho", order=3, is_won=True)
        self.stage_perdido = OpportunityStage.objects.create(name="Perdido", order=4, is_lost=True)
        self.loss_reason = LossReason.objects.create(name="Preço")

        self.creator = _user_with_perms("criador_base", "add_opportunities")
        self.opportunity = create_opportunity(
            NewOpportunityData(
                client=self.client_obj,
                title="Oportunidade matriz",
                owner=self.creator,
                source=self.source,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.creator,
            )
        )

        self.user_a = _user_with_perms("perfil_a")  # sem nenhuma permissão
        self.user_b = _user_with_perms("perfil_b", "view_opportunities")  # só leitura
        self.admin = User.objects.create_superuser(username="perfil_d", password="senha-forte-123", email="d@d.com")

    def _assert_denied(self, response):
        self.assertIn(response.status_code, (302, 403), f"esperado bloqueio, obtido {response.status_code}")
        if response.status_code == 302:
            self.assertIn("/contas/login/", response.get("Location", ""))

    def _assert_allowed(self, response, *, expect_redirect=False):
        if expect_redirect:
            self.assertEqual(response.status_code, 302)
        else:
            self.assertIn(response.status_code, (200, 302))

    # 1. Listar oportunidades ------------------------------------------------

    def test_list_opportunities(self):
        url = "/crm/oportunidades/"
        self.client.force_login(self.user_a)
        self._assert_denied(self.client.get(url))

        self.client.force_login(self.user_b)
        self.assertEqual(self.client.get(url).status_code, 200)

        c = _user_with_perms("c_list", "view_opportunities")
        self.client.force_login(c)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)

    # 2/3. Ver detalhe / acesso direto por PK --------------------------------

    def test_view_detail_and_direct_pk_access(self):
        url = f"/crm/oportunidades/{self.opportunity.pk}/"
        self.client.force_login(self.user_a)
        self._assert_denied(self.client.get(url))

        self.client.force_login(self.user_b)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)

    # 4. Criar oportunidade ---------------------------------------------------

    def test_create_opportunity(self):
        url = "/crm/oportunidades/nova/"
        payload = {
            "client": self.client_obj.pk,
            "title": "Nova via matriz",
            "owner": self.creator.pk,
            "source": self.source.pk,
            "business_type": BusinessType.LOCACAO,
            "stage": self.stage_novo.pk,
            "notes": "",
        }

        self.client.force_login(self.user_a)
        self._assert_denied(self.client.get(url))
        self._assert_denied(self.client.post(url, payload))

        self.client.force_login(self.user_b)
        self._assert_denied(self.client.get(url))

        c = _user_with_perms("c_create", "add_opportunities")
        self.client.force_login(c)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)
        resp = self.client.post(url, payload)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Opportunity.objects.filter(title="Nova via matriz").exists())

    # 5. Editar oportunidade ---------------------------------------------------

    def test_edit_opportunity(self):
        url = f"/crm/oportunidades/{self.opportunity.pk}/editar/"
        payload = {
            "title": "Editada",
            "owner": self.creator.pk,
            "source": self.source.pk,
            "business_type": BusinessType.VENDA,
            "notes": "",
        }

        self.client.force_login(self.user_a)
        self._assert_denied(self.client.get(url))
        self._assert_denied(self.client.post(url, payload))

        self.client.force_login(self.user_b)
        self._assert_denied(self.client.get(url))

        c = _user_with_perms("c_edit", "change_opportunities")
        self.client.force_login(c)
        resp = self.client.post(url, payload)
        self.assertEqual(resp.status_code, 302)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.title, "Editada")

    # 6/7/8. Mudar etapa / marcar ganha / marcar perdida ------------------------

    def test_change_stage(self):
        url = f"/crm/oportunidades/{self.opportunity.pk}/etapa/"

        self.client.force_login(self.user_a)
        self._assert_denied(self.client.post(url, {"stage": self.stage_outra.pk}))

        self.client.force_login(self.user_b)
        self._assert_denied(self.client.post(url, {"stage": self.stage_outra.pk}))
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_novo)  # nada mudou

        c = _user_with_perms("c_stage", "view_opportunities", "change_opportunity_stage")
        self.client.force_login(c)
        resp = self.client.post(url, {"stage": self.stage_outra.pk})
        self.assertEqual(resp.status_code, 302)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage, self.stage_outra)

    def test_mark_won(self):
        url = f"/crm/oportunidades/{self.opportunity.pk}/etapa/"

        self.client.force_login(self.user_a)
        self._assert_denied(self.client.post(url, {"stage": self.stage_ganho.pk, "closed_value": "10.00"}))

        c = _user_with_perms("c_won", "view_opportunities", "change_opportunity_stage")
        self.client.force_login(c)
        resp = self.client.post(url, {"stage": self.stage_ganho.pk, "closed_value": "10.00"})
        self.assertEqual(resp.status_code, 302)
        self.opportunity.refresh_from_db()
        self.assertIsNotNone(self.opportunity.won_at)

    def test_mark_lost(self):
        url = f"/crm/oportunidades/{self.opportunity.pk}/etapa/"

        self.client.force_login(self.user_a)
        self._assert_denied(self.client.post(url, {"stage": self.stage_perdido.pk, "loss_reason": self.loss_reason.pk}))

        c = _user_with_perms("c_lost", "view_opportunities", "change_opportunity_stage")
        self.client.force_login(c)
        resp = self.client.post(url, {"stage": self.stage_perdido.pk, "loss_reason": self.loss_reason.pk})
        self.assertEqual(resp.status_code, 302)
        self.opportunity.refresh_from_db()
        self.assertIsNotNone(self.opportunity.lost_at)

    # 9. Registrar atividade -----------------------------------------------

    def test_register_activity(self):
        url = f"/crm/oportunidades/{self.opportunity.pk}/atividades/nova/"
        payload = {"activity_type": "LIGACAO", "description": "ligação de teste"}

        self.client.force_login(self.user_a)
        self._assert_denied(self.client.post(url, payload))

        self.client.force_login(self.user_b)  # só view_opportunities, não add_commercial_activities
        self._assert_denied(self.client.post(url, payload))

        c = _user_with_perms("c_activity", "view_opportunities", "add_commercial_activities")
        self.client.force_login(c)
        resp = self.client.post(url, payload)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self.opportunity.activities.filter(description="ligação de teste").exists())

    # 10. Ver atividades -----------------------------------------------------

    def test_view_activities(self):
        """
        `view_commercial_activities` é uma permissão PRÓPRIA — ter só
        `view_opportunities` não é suficiente para ver o conteúdo das
        atividades na página de detalhe (mesmo alcançando a página).
        """
        self.opportunity.activities.create(activity_type="LIGACAO", description="conteudo-sensivel-atividade", created_by=self.creator)
        url = f"/crm/oportunidades/{self.opportunity.pk}/"

        self.client.force_login(self.user_b)  # só view_opportunities
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"conteudo-sensivel-atividade", resp.content)

        c = _user_with_perms("c_view_activity", "view_opportunities", "view_commercial_activities")
        self.client.force_login(c)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"conteudo-sensivel-atividade", resp.content)

    # 11/12/13. Gerenciar origens/etapas/motivos de perda ------------------------

    def test_manage_origins(self):
        list_url = "/crm/configuracoes/origens/"
        create_url = "/crm/configuracoes/origens/nova/"

        self.client.force_login(self.user_a)
        self._assert_denied(self.client.get(list_url))

        self.client.force_login(self.user_b)  # view_opportunities não basta
        self._assert_denied(self.client.get(list_url))

        c = _user_with_perms("c_origins", "manage_commercial_settings")
        self.client.force_login(c)
        self.assertEqual(self.client.get(list_url).status_code, 200)
        resp = self.client.post(create_url, {"name": "Nova Origem X", "order": 1, "is_active": "on"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CommercialSource.objects.filter(name="Nova Origem X").exists())

    def test_manage_stages(self):
        list_url = "/crm/configuracoes/etapas/"
        create_url = "/crm/configuracoes/etapas/nova/"

        self.client.force_login(self.user_a)
        self._assert_denied(self.client.get(list_url))

        c = _user_with_perms("c_stages", "manage_commercial_settings")
        self.client.force_login(c)
        self.assertEqual(self.client.get(list_url).status_code, 200)
        resp = self.client.post(create_url, {"name": "Etapa Nova X", "order": 5})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(OpportunityStage.objects.filter(name="Etapa Nova X").exists())

    def test_manage_loss_reasons(self):
        list_url = "/crm/configuracoes/motivos-perda/"
        create_url = "/crm/configuracoes/motivos-perda/nova/"

        self.client.force_login(self.user_a)
        self._assert_denied(self.client.get(list_url))

        c = _user_with_perms("c_loss_reasons", "manage_commercial_settings")
        self.client.force_login(c)
        self.assertEqual(self.client.get(list_url).status_code, 200)
        resp = self.client.post(create_url, {"name": "Motivo Novo X", "order": 1, "is_active": "on"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(LossReason.objects.filter(name="Motivo Novo X").exists())

    # Anônimo ------------------------------------------------------------------

    def test_anonymous_user_is_redirected_to_login_for_every_view(self):
        urls = [
            "/crm/oportunidades/",
            f"/crm/oportunidades/{self.opportunity.pk}/",
            "/crm/oportunidades/nova/",
            f"/crm/oportunidades/{self.opportunity.pk}/editar/",
            "/crm/configuracoes/origens/",
            "/crm/configuracoes/etapas/",
            "/crm/configuracoes/motivos-perda/",
        ]
        for url in urls:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 302)
                self.assertIn("/contas/login/", resp.get("Location", ""))
