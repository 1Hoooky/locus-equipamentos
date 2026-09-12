"""
Exclusão definitiva (hard delete) de `Client` — rodada "AMBIENTE EM
DESENVOLVIMENTO / HARD DELETE DURANTE DESENVOLVIMENTO / NÃO FAZER
CASCADE CEGO", 11/09/2026.

Cobre exatamente o que o pedido do usuário exige verificado por teste:
  - autoridade máxima (superusuário) CONSEGUE excluir de verdade;
  - usuário comum (mesmo Role.ADMIN/CAN_MANAGE_CLIENTS) NÃO consegue —
    bloqueado no backend, não só escondido na tela (view E service);
  - dependente exclusivo (`fiscal_address`) É removido junto;
  - registro compartilhado NUNCA é removido/apagado por engano: um
    Equipamento que só teve relação com o cliente continua existindo
    (`current_client` só é zerado, `SET_NULL` — pedido explícito do
    usuário); uma Location/Oportunidade ainda vinculada BLOQUEIA a
    exclusão em vez de ser arrastada;
  - snapshot histórico (`django-simple-history`) também é purgado.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client, ClientType
from apps.clients.services import (
    HardDeleteAuthorizationError,
    HardDeleteBlocked,
    hard_delete_client,
    preview_client_hard_delete,
)
from apps.core.models import Address
from apps.equipment.models import Equipment
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import Location, LocationType

User = get_user_model()

VALID_CNPJ = "11.222.333/0001-81"


class ClientHardDeleteServiceTest(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_user(
            username="hd_super", password="senha-forte-123", is_superuser=True
        )
        self.admin = User.objects.create_user(username="hd_admin", password="senha-forte-123", role=Role.ADMIN)
        self.client_obj = Client.objects.create(
            client_type=ClientType.PJ, company_name="Cliente Exclusão LTDA", document=VALID_CNPJ
        )

    def test_superuser_can_hard_delete_client_without_dependents(self):
        client_id = self.client_obj.pk
        result = hard_delete_client(client_id=client_id, actor=self.superuser)
        self.assertEqual(result.total_dependents, 0)
        self.assertFalse(Client.objects.filter(pk=client_id).exists())

    def test_non_superuser_actor_is_rejected_even_with_role_admin(self):
        """Defesa em profundidade: o service em si recusa, nunca só a view."""
        with self.assertRaises(HardDeleteAuthorizationError):
            hard_delete_client(client_id=self.client_obj.pk, actor=self.admin)
        self.assertTrue(Client.objects.filter(pk=self.client_obj.pk).exists())

    def test_fiscal_address_is_removed_together_as_exclusive_dependent(self):
        address = Address.objects.create(logradouro="Rua Um", cidade="São Paulo", uf="SP")
        self.client_obj.fiscal_address = address
        self.client_obj.save(update_fields=["fiscal_address"])
        address_id = address.pk

        preview = preview_client_hard_delete(self.client_obj)
        self.assertEqual(preview.dependents.get("endereço fiscal"), 1)

        result = hard_delete_client(client_id=self.client_obj.pk, actor=self.superuser)
        self.assertEqual(result.total_dependents, 1)
        self.assertFalse(Address.objects.filter(pk=address_id).exists())

    def test_equipment_with_relation_to_client_is_never_deleted_only_unlinked(self):
        """Pedido explícito: excluir um Cliente NÃO deve excluir um Equipamento só porque teve relação com ele."""
        category = Category.objects.create(name="Categoria Teste HD")
        model = EquipmentModel.objects.create(category=category, name="Modelo HD", code="HDX")
        equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.superuser))
        equipment.current_client = self.client_obj
        equipment.save(update_fields=["current_client"])
        equipment_id = equipment.pk

        hard_delete_client(client_id=self.client_obj.pk, actor=self.superuser)

        self.assertTrue(Equipment.objects.filter(pk=equipment_id).exists())
        equipment.refresh_from_db()
        self.assertIsNone(equipment.current_client_id)


class ClientHardDeleteBlockedTest(TestCase):
    """Registro COMPARTILHADO nunca é arrastado — a exclusão é BLOQUEADA (não é 'bloqueio excessivo': o Admin decide o que fazer primeiro)."""

    def setUp(self):
        self.superuser = User.objects.create_user(
            username="hd_super2", password="senha-forte-123", is_superuser=True
        )
        self.client_obj = Client.objects.create(
            client_type=ClientType.PJ, company_name="Cliente Bloqueado LTDA", document=VALID_CNPJ
        )

    def test_active_location_blocks_client_hard_delete(self):
        Location.objects.create(name="Unidade Teste", type=LocationType.CLIENTE, client=self.client_obj)
        with self.assertRaises(HardDeleteBlocked):
            hard_delete_client(client_id=self.client_obj.pk, actor=self.superuser)
        self.assertTrue(Client.objects.filter(pk=self.client_obj.pk).exists())

    def test_opportunity_still_linked_blocks_client_hard_delete(self):
        from apps.crm.models import BusinessType, CommercialSource, Opportunity, OpportunityStage

        source = CommercialSource.objects.create(name="Origem Teste")
        stage = OpportunityStage.objects.create(name="Novo", order=1)
        Opportunity.objects.create(
            client=self.client_obj,
            title="Oportunidade vinculada",
            owner=self.superuser,
            source=source,
            business_type=BusinessType.LOCACAO,
            stage=stage,
            created_by=self.superuser,
        )
        with self.assertRaises(HardDeleteBlocked):
            hard_delete_client(client_id=self.client_obj.pk, actor=self.superuser)
        self.assertTrue(Client.objects.filter(pk=self.client_obj.pk).exists())


class ClientHardDeleteViewTest(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_user(
            username="hd_super_view", password="senha-forte-123", is_superuser=True
        )
        self.admin = User.objects.create_user(username="hd_admin_view", password="senha-forte-123", role=Role.ADMIN)
        self.client_obj = Client.objects.create(
            client_type=ClientType.PJ, company_name="Cliente View LTDA", document=VALID_CNPJ
        )
        self.url = f"/clientes/{self.client_obj.pk}/excluir-definitivamente/"

    def test_get_requires_superuser_not_just_admin_role(self):
        self.client.login(username="hd_admin_view", password="senha-forte-123")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.client.login(username="hd_super_view", password="senha-forte-123")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Excluir definitivamente")

    def test_post_without_confirmation_checkbox_does_not_delete(self):
        self.client.login(username="hd_super_view", password="senha-forte-123")
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Client.objects.filter(pk=self.client_obj.pk).exists())

    def test_post_with_confirmation_deletes_and_redirects_to_list(self):
        self.client.login(username="hd_super_view", password="senha-forte-123")
        response = self.client.post(self.url, {"confirm": "on"})
        self.assertRedirects(response, "/clientes/")
        self.assertFalse(Client.objects.filter(pk=self.client_obj.pk).exists())

    def test_non_superuser_post_is_forbidden_and_client_survives(self):
        self.client.login(username="hd_admin_view", password="senha-forte-123")
        response = self.client.post(self.url, {"confirm": "on"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Client.objects.filter(pk=self.client_obj.pk).exists())

    def test_blocked_deletion_shows_error_and_redirects_to_detail(self):
        Location.objects.create(name="Unidade Bloqueio", type=LocationType.CLIENTE, client=self.client_obj)
        self.client.login(username="hd_super_view", password="senha-forte-123")
        response = self.client.post(self.url, {"confirm": "on"}, follow=True)
        self.assertTrue(Client.objects.filter(pk=self.client_obj.pk).exists())
        messages = list(response.context["messages"])
        self.assertTrue(any("Não é possível excluir" in str(m) for m in messages))
