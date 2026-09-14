"""
RODADA 3 DE REFINAMENTOS DO HUB DA OPORTUNIDADE (14/09/2026) — item 9-14
da especificação: `ActivityType` deixou de ser `TextChoices` fixo e virou
entidade configurável, mesmo padrão de `CommercialSource`/
`OpportunityStage`/`LossReason` (Origens/Etapas/Motivos de perda), com a
MESMA permissão já existente `crm.manage_commercial_settings` (nenhuma
permissão nova criada).

Cobre: criar tipo; editar nome; ativar/inativar; impedir exclusão
destrutiva de um tipo em uso (nunca existe rota de "excluir" — e no nível
do banco `CommercialActivity.activity_type` é `on_delete=PROTECT`);
gating de permissão nas 3 views; o campo técnico `code` nunca é exposto/
editável pelo form.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from apps.clients.models import Client
from apps.crm.models import ActivityType, BusinessType, CommercialSource, OpportunityStage
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


class ActivityTypeConfigPermissionTest(TestCase):
    """As 3 views exigem `crm.manage_commercial_settings` — nenhuma delas aceita `view_opportunities` sozinho."""

    def setUp(self):
        self.activity_type = ActivityType.objects.create(name="Videochamada", order=10)
        self.no_perm_user = _user_with_perms("sem_permissao")
        self.wrong_perm_user = _user_with_perms("permissao_errada", "view_opportunities")
        self.admin_user = _user_with_perms("gestor_config", "manage_commercial_settings")

    def test_list_requires_manage_commercial_settings(self):
        url = reverse("crm:activity_type_list")
        for user in (self.no_perm_user, self.wrong_perm_user):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Videochamada")

    def test_create_requires_manage_commercial_settings(self):
        url = reverse("crm:activity_type_create")
        for user in (self.no_perm_user, self.wrong_perm_user):
            self.client.force_login(user)
            self.assertEqual(self.client.post(url, {"name": "Bloqueado", "order": 0, "is_active": "on"}).status_code, 403)
        self.assertFalse(ActivityType.objects.filter(name="Bloqueado").exists())

    def test_update_requires_manage_commercial_settings(self):
        url = reverse("crm:activity_type_update", args=[self.activity_type.pk])
        for user in (self.no_perm_user, self.wrong_perm_user):
            self.client.force_login(user)
            resp = self.client.post(url, {"name": "Hackeado", "order": 0, "is_active": "on"})
            self.assertEqual(resp.status_code, 403)
        self.activity_type.refresh_from_db()
        self.assertEqual(self.activity_type.name, "Videochamada")


class ActivityTypeConfigCrudTest(TestCase):
    def setUp(self):
        self.admin_user = _user_with_perms("gestor_tipos", "manage_commercial_settings")
        self.client.force_login(self.admin_user)

    def test_creates_new_activity_type(self):
        resp = self.client.post(
            reverse("crm:activity_type_create"), {"name": "Videochamada", "order": 9, "is_active": "on"}
        )
        self.assertEqual(resp.status_code, 302)
        created = ActivityType.objects.get(name="Videochamada")
        self.assertEqual(created.order, 9)
        self.assertTrue(created.is_active)
        # Tipo criado pelo Administrador não tem `code` (só os 8 tipos
        # originais, semeados pela migration de dados, têm `code`
        # preenchido) — nunca exposto/preenchível pelo form.
        self.assertEqual(created.code, "")

    def test_edits_name_and_order(self):
        activity_type = ActivityType.objects.create(name="Nome antigo", order=1)
        url = reverse("crm:activity_type_update", args=[activity_type.pk])
        resp = self.client.post(url, {"name": "Nome novo", "order": 5, "is_active": "on"})
        self.assertEqual(resp.status_code, 302)
        activity_type.refresh_from_db()
        self.assertEqual(activity_type.name, "Nome novo")
        self.assertEqual(activity_type.order, 5)

    def test_deactivates_and_reactivates(self):
        activity_type = ActivityType.objects.create(name="Sazonal", order=1, is_active=True)
        url = reverse("crm:activity_type_update", args=[activity_type.pk])

        resp = self.client.post(url, {"name": "Sazonal", "order": 1})  # is_active ausente = desmarcado
        self.assertEqual(resp.status_code, 302)
        activity_type.refresh_from_db()
        self.assertFalse(activity_type.is_active)

        resp = self.client.post(url, {"name": "Sazonal", "order": 1, "is_active": "on"})
        self.assertEqual(resp.status_code, 302)
        activity_type.refresh_from_db()
        self.assertTrue(activity_type.is_active)

    def test_editing_never_exposes_or_changes_code(self):
        """
        `code` não está em `ActivityTypeForm.Meta.fields` — tentar
        injetá-lo via POST não tem nenhum efeito (o form nem olha esse
        campo).
        """
        seeded = ActivityType.objects.get(code="LIGACAO")
        url = reverse("crm:activity_type_update", args=[seeded.pk])
        resp = self.client.post(url, {"name": "Ligação", "order": 0, "is_active": "on", "code": "ADULTERADO"})
        self.assertEqual(resp.status_code, 302)
        seeded.refresh_from_db()
        self.assertEqual(seeded.code, "LIGACAO")

    def test_no_delete_route_exists(self):
        """
        Mesma convenção de Origem/Etapa/Motivo de perda: NUNCA existe uma
        URL de exclusão para `ActivityType` — só editar `is_active`.
        """
        with self.assertRaises(NoReverseMatch):
            reverse("crm:activity_type_delete")


class ActivityTypeInUseProtectionTest(TestCase):
    """Nível de banco: um tipo referenciado por uma `CommercialActivity` nunca pode ser apagado fisicamente."""

    def test_deleting_a_type_in_use_raises_protected_error(self):
        client_obj = Client.objects.create(company_name="Cliente Proteção")
        source = CommercialSource.objects.create(name="Indicação")
        stage = OpportunityStage.objects.create(name="Novo", order=1)
        owner = _user_with_perms("dono_oportunidade", "add_opportunities")
        opportunity = create_opportunity(
            NewOpportunityData(
                client=client_obj,
                title="Oportunidade com atividade",
                owner=owner,
                source=source,
                business_type=BusinessType.LOCACAO,
                stage=stage,
                created_by=owner,
            )
        )
        activity_type = ActivityType.objects.create(name="Tipo em uso", order=99)
        opportunity.activities.create(activity_type=activity_type, description="registro", created_by=owner)

        with self.assertRaises(ProtectedError):
            activity_type.delete()
