"""
RODADA 3 DE REFINAMENTOS DO HUB DA OPORTUNIDADE (14/09/2026) — seção
60-68: aba "Equipamentos", vínculo Oportunidade↔patrimônio REAL via
`apps.operations.services.create_movement()` (nunca um "estoque
paralelo", nunca `apps.equipment.services.change_status()` chamado
direto). Ver docstring de `apps.crm.models.OpportunityEquipment` e de
`apps.crm.services.link_equipment_to_opportunity()`/
`unlink_equipment_from_opportunity()` para o raciocínio completo.

Convenções desta suíte: `_user_with_perms` aceita códigos COMPLETOS
("app_label.codename") — diferente do helper `crm`-only já usado em
outras suítes deste round — porque a ação de vincular/desvincular exige
DUAS Permissions de apps diferentes ao mesmo tempo
(`crm.view_opportunities` para alcançar a página + `operations.
register_operations`, reaproveitada de `CAN_REGISTER_OPERATIONS`, para
a escrita em si).
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client as DjangoTestClient
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.crm.models import BusinessType, CommercialSource, Opportunity, OpportunityEquipment, OpportunityStage
from apps.crm.services import (
    LinkEquipmentData,
    UnlinkEquipmentData,
    hard_delete_opportunity,
    link_equipment_to_opportunity,
    linked_equipment_for,
    unlink_equipment_from_opportunity,
)
from apps.equipment.models import Equipment, Status
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import LocationType, Movement, MovementType
from apps.operations.services import NewLocationData, create_location

User = get_user_model()


def _user_with_perms(username, *full_codenames):
    """`full_codenames` como `"crm.view_opportunities"`/`"operations.register_operations"` — permissão completa, app cruzado."""
    user = User.objects.create_user(username=username, password="senha-forte-123")
    if full_codenames:
        perms = []
        for full in full_codenames:
            app_label, codename = full.split(".", 1)
            perms.append(Permission.objects.get(codename=codename, content_type__app_label=app_label))
        group, _ = Group.objects.get_or_create(name=f"perm-{username}")
        group.permissions.set(perms)
        user.groups.add(group)
    return user


VIEW = "crm.view_opportunities"
REGISTER_OPERATIONS = "operations.register_operations"


class EquipmentLinkingTestBase(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(company_name="Cliente Equipamentos LTDA")
        self.other_client = Client.objects.create(company_name="Outro Cliente LTDA")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)

        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(code="NI23TC", name="NI23 Big Tank", category=self.category)

        self.operador = _user_with_perms("operador_equip", VIEW, REGISTER_OPERATIONS)

        self.estoque = create_location(NewLocationData(name="Estoque Central", type=LocationType.ESTOQUE))
        self.unidade_cliente = create_location(
            NewLocationData(name="Sede", type=LocationType.CLIENTE, client=self.client_obj)
        )
        self.unidade_outro_cliente = create_location(
            NewLocationData(name="Sede B", type=LocationType.CLIENTE, client=self.other_client)
        )

        self.equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.operador))

        self.opportunity = Opportunity.objects.create(
            client=self.client_obj,
            title="Oportunidade Equipamentos",
            owner=self.operador,
            source=self.source,
            business_type=BusinessType.LOCACAO,
            stage=self.stage_novo,
            created_by=self.operador,
        )
        self.detail_url = f"/crm/oportunidades/{self.opportunity.pk}/"
        self.search_url = f"/crm/oportunidades/{self.opportunity.pk}/equipamentos/buscar/"
        self.link_url = f"/crm/oportunidades/{self.opportunity.pk}/equipamentos/vincular/"

    def _login(self, user):
        client = DjangoTestClient()
        client.force_login(user)
        return client

    def _unlink_url(self, link_pk):
        return f"/crm/oportunidades/{self.opportunity.pk}/equipamentos/{link_pk}/desvincular/"


# 1. Visibilidade do botão "+ Vincular equipamento" -----------------------


class ButtonVisibilityTest(EquipmentLinkingTestBase):
    def test_link_button_hidden_without_register_operations_permission(self):
        viewer = _user_with_perms("so_view_equip", VIEW)
        client = self._login(viewer)
        resp = client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"Vincular equipamento", resp.content)

    def test_link_button_visible_with_permission_and_client_location(self):
        client = self._login(self.operador)
        resp = client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Vincular equipamento".encode(), resp.content)
        self.assertIn(b'id="opp-equipment-link-modal"', resp.content)

    def test_link_button_hidden_when_client_has_no_location(self):
        self.unidade_cliente.is_active = False
        self.unidade_cliente.save(update_fields=["is_active"])
        client = self._login(self.operador)
        resp = client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b'id="opp-equipment-link-modal"', resp.content)
        self.assertIn(b"Nenhuma unidade cadastrada", resp.content)

    def test_no_equipment_linked_shows_empty_state(self):
        client = self._login(self.operador)
        resp = client.get(self.detail_url)
        self.assertContains(resp, "Nenhum equipamento vinculado.")


# 2. Endpoint de busca ------------------------------------------------------


class SearchEndpointTest(EquipmentLinkingTestBase):
    def test_search_returns_available_equipment(self):
        client = self._login(self.operador)
        resp = client.get(self.search_url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        ids = [r["id"] for r in data["results"]]
        self.assertIn(self.equipment.pk, ids)

    def test_search_excludes_unavailable_equipment(self):
        self.equipment.status = Status.MANUTENCAO
        self.equipment.save(update_fields=["status"])
        client = self._login(self.operador)
        resp = client.get(self.search_url)
        ids = [r["id"] for r in resp.json()["results"]]
        self.assertNotIn(self.equipment.pk, ids)

    def test_search_filters_by_patrimonio_query(self):
        other = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.operador))
        client = self._login(self.operador)
        resp = client.get(self.search_url, {"q": self.equipment.patrimonio})
        ids = [r["id"] for r in resp.json()["results"]]
        self.assertIn(self.equipment.pk, ids)
        self.assertNotIn(other.pk, ids)

    def test_search_requires_register_operations_permission(self):
        viewer = _user_with_perms("busca_sem_permissao", VIEW)
        client = self._login(viewer)
        resp = client.get(self.search_url)
        self.assertEqual(resp.status_code, 403)


# 3. Fluxo "Vincular" -------------------------------------------------------


class LinkFlowTest(EquipmentLinkingTestBase):
    def test_link_creates_movement_and_updates_equipment(self):
        link_equipment_to_opportunity(
            LinkEquipmentData(
                opportunity=self.opportunity,
                equipment=self.equipment,
                destination_location=self.unidade_cliente,
                actor=self.operador,
            )
        )
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.EM_OPERACAO)
        self.assertEqual(self.equipment.current_location, self.unidade_cliente)
        self.assertEqual(self.equipment.current_client, self.client_obj)

        movement = Movement.objects.filter(equipment=self.equipment).latest("created_at")
        self.assertEqual(movement.movement_type, MovementType.INSTALACAO)
        self.assertEqual(movement.destination_location, self.unidade_cliente)

    def test_link_creates_opportunity_equipment_row(self):
        link = link_equipment_to_opportunity(
            LinkEquipmentData(
                opportunity=self.opportunity,
                equipment=self.equipment,
                destination_location=self.unidade_cliente,
                actor=self.operador,
            )
        )
        self.assertEqual(link.opportunity, self.opportunity)
        self.assertEqual(link.equipment, self.equipment)
        self.assertEqual(link.linked_by, self.operador)
        self.assertIsNotNone(link.linked_movement)
        self.assertIsNone(link.unlinked_at)

    def test_link_rejects_destination_from_another_client(self):
        with self.assertRaises(ValueError):
            link_equipment_to_opportunity(
                LinkEquipmentData(
                    opportunity=self.opportunity,
                    equipment=self.equipment,
                    destination_location=self.unidade_outro_cliente,
                    actor=self.operador,
                )
            )
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)

    def test_link_rejects_destination_of_wrong_type(self):
        with self.assertRaises(ValueError):
            link_equipment_to_opportunity(
                LinkEquipmentData(
                    opportunity=self.opportunity,
                    equipment=self.equipment,
                    destination_location=self.estoque,
                    actor=self.operador,
                )
            )

    def test_link_rejects_equipment_not_disponivel(self):
        self.equipment.status = Status.MANUTENCAO
        self.equipment.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            link_equipment_to_opportunity(
                LinkEquipmentData(
                    opportunity=self.opportunity,
                    equipment=self.equipment,
                    destination_location=self.unidade_cliente,
                    actor=self.operador,
                )
            )

    def test_link_rejects_equipment_already_linked_elsewhere(self):
        """O MESMO patrimônio não pode ficar ativamente vinculado a duas Oportunidades — nem via create_movement (status), nem via UniqueConstraint."""
        other_opportunity = Opportunity.objects.create(
            client=self.client_obj, title="Outra Oportunidade", owner=self.operador, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage_novo, created_by=self.operador,
        )
        link_equipment_to_opportunity(
            LinkEquipmentData(
                opportunity=self.opportunity, equipment=self.equipment, destination_location=self.unidade_cliente, actor=self.operador
            )
        )
        with self.assertRaises(ValueError):
            link_equipment_to_opportunity(
                LinkEquipmentData(
                    opportunity=other_opportunity,
                    equipment=self.equipment,
                    destination_location=self.unidade_cliente,
                    actor=self.operador,
                )
            )

    def test_link_via_post_end_to_end(self):
        client = self._login(self.operador)
        resp = client.post(
            self.link_url,
            {"equipment": self.equipment.pk, "destination_location": self.unidade_cliente.pk, "reason": ""},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(OpportunityEquipment.objects.filter(opportunity=self.opportunity, equipment=self.equipment).exists())
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.EM_OPERACAO)

    def test_link_via_post_without_permission_is_blocked(self):
        viewer = _user_with_perms("post_sem_permissao", VIEW)
        client = self._login(viewer)
        resp = client.post(
            self.link_url,
            {"equipment": self.equipment.pk, "destination_location": self.unidade_cliente.pk, "reason": ""},
        )
        self.assertEqual(resp.status_code, 403)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        self.assertFalse(OpportunityEquipment.objects.filter(opportunity=self.opportunity).exists())


# 4. Fluxo "Desvincular" -----------------------------------------------------


class UnlinkFlowTest(EquipmentLinkingTestBase):
    def _link(self):
        return link_equipment_to_opportunity(
            LinkEquipmentData(
                opportunity=self.opportunity, equipment=self.equipment, destination_location=self.unidade_cliente, actor=self.operador
            )
        )

    def test_unlink_creates_movement_and_returns_equipment_to_stock(self):
        link = self._link()
        unlink_equipment_from_opportunity(
            UnlinkEquipmentData(link=link, destination_location=self.estoque, actor=self.operador)
        )
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        self.assertEqual(self.equipment.current_location, self.estoque)

        movement = Movement.objects.filter(equipment=self.equipment).latest("created_at")
        self.assertEqual(movement.movement_type, MovementType.RETIRADA)

    def test_unlink_closes_link_without_deleting_row(self):
        link = self._link()
        before_count = OpportunityEquipment.objects.count()
        closed = unlink_equipment_from_opportunity(
            UnlinkEquipmentData(link=link, destination_location=self.estoque, actor=self.operador)
        )
        self.assertEqual(OpportunityEquipment.objects.count(), before_count)  # nunca DELETE
        self.assertIsNotNone(closed.unlinked_at)
        self.assertEqual(closed.unlinked_by, self.operador)
        self.assertIsNotNone(closed.unlinked_movement)

    def test_unlink_already_closed_link_is_rejected(self):
        link = self._link()
        unlink_equipment_from_opportunity(UnlinkEquipmentData(link=link, destination_location=self.estoque, actor=self.operador))
        link.refresh_from_db()
        with self.assertRaises(ValueError):
            unlink_equipment_from_opportunity(UnlinkEquipmentData(link=link, destination_location=self.estoque, actor=self.operador))

    def test_unlink_rejects_non_estoque_destination(self):
        link = self._link()
        with self.assertRaises(ValueError):
            unlink_equipment_from_opportunity(
                UnlinkEquipmentData(link=link, destination_location=self.unidade_cliente, actor=self.operador)
            )

    def test_unlink_via_post_end_to_end(self):
        link = self._link()
        client = self._login(self.operador)
        resp = client.post(self._unlink_url(link.pk), {"destination_location": self.estoque.pk, "reason": ""})
        self.assertEqual(resp.status_code, 302)
        link.refresh_from_db()
        self.assertIsNotNone(link.unlinked_at)

    def test_unlink_via_post_without_permission_is_blocked(self):
        link = self._link()
        viewer = _user_with_perms("unlink_sem_permissao", VIEW)
        client = self._login(viewer)
        resp = client.post(self._unlink_url(link.pk), {"destination_location": self.estoque.pk, "reason": ""})
        self.assertEqual(resp.status_code, 403)
        link.refresh_from_db()
        self.assertIsNone(link.unlinked_at)

    def test_unlink_link_from_another_opportunity_404s(self):
        """IDOR: um `link_pk` de OUTRA Opportunity na URL desta nunca é aceito."""
        link = self._link()
        other_opportunity = Opportunity.objects.create(
            client=self.other_client, title="Outra Oportunidade", owner=self.operador, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage_novo, created_by=self.operador,
        )
        client = self._login(self.operador)
        resp = client.post(
            f"/crm/oportunidades/{other_opportunity.pk}/equipamentos/{link.pk}/desvincular/",
            {"destination_location": self.estoque.pk, "reason": ""},
        )
        self.assertEqual(resp.status_code, 404)
        link.refresh_from_db()
        self.assertIsNone(link.unlinked_at)

    def test_active_link_shows_unlink_button_closed_link_does_not(self):
        link = self._link()
        client = self._login(self.operador)
        resp = client.get(self.detail_url)
        self.assertContains(resp, f'id="opp-equipment-unlink-modal-{link.pk}"')

        unlink_equipment_from_opportunity(UnlinkEquipmentData(link=link, destination_location=self.estoque, actor=self.operador))
        resp = client.get(self.detail_url)
        self.assertNotContains(resp, f'id="opp-equipment-unlink-modal-{link.pk}"')
        self.assertContains(resp, "Desvinculado")


# 5. Hard delete da Oportunidade preserva o patrimônio -----------------------


class HardDeletePreservesEquipmentTest(EquipmentLinkingTestBase):
    def test_hard_delete_opportunity_removes_link_but_keeps_equipment_and_movement(self):
        superuser = User.objects.create_superuser(username="super_equip", password="senha-forte-123")
        link = link_equipment_to_opportunity(
            LinkEquipmentData(
                opportunity=self.opportunity, equipment=self.equipment, destination_location=self.unidade_cliente, actor=self.operador
            )
        )
        movement_pk = link.linked_movement.pk
        equipment_pk = self.equipment.pk

        hard_delete_opportunity(opportunity_id=self.opportunity.pk, actor=superuser)

        self.assertFalse(OpportunityEquipment.objects.filter(pk=link.pk).exists())
        self.assertTrue(Equipment.objects.filter(pk=equipment_pk).exists())
        self.assertTrue(Movement.objects.filter(pk=movement_pk).exists())
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.EM_OPERACAO)  # estado físico real, intocado


# 6. Histórico ----------------------------------------------------------------


class TimelineTest(EquipmentLinkingTestBase):
    def test_timeline_includes_link_and_unlink_events(self):
        from apps.crm.services import build_opportunity_timeline

        link = link_equipment_to_opportunity(
            LinkEquipmentData(
                opportunity=self.opportunity, equipment=self.equipment, destination_location=self.unidade_cliente, actor=self.operador
            )
        )
        unlink_equipment_from_opportunity(UnlinkEquipmentData(link=link, destination_location=self.estoque, actor=self.operador))

        labels = [entry.label for entry in build_opportunity_timeline(self.opportunity)]
        self.assertTrue(any("vinculado" in label for label in labels))
        self.assertTrue(any("desvinculado" in label for label in labels))


# 7. linked_equipment_for — leitura sem N+1 óbvio -----------------------------


class LinkedEquipmentForTest(EquipmentLinkingTestBase):
    def test_returns_all_links_most_recent_first(self):
        link1 = link_equipment_to_opportunity(
            LinkEquipmentData(
                opportunity=self.opportunity, equipment=self.equipment, destination_location=self.unidade_cliente, actor=self.operador
            )
        )
        unlink_equipment_from_opportunity(UnlinkEquipmentData(link=link1, destination_location=self.estoque, actor=self.operador))

        other_equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.operador))
        link2 = link_equipment_to_opportunity(
            LinkEquipmentData(
                opportunity=self.opportunity, equipment=other_equipment, destination_location=self.unidade_cliente, actor=self.operador
            )
        )

        links = list(linked_equipment_for(self.opportunity))
        self.assertEqual(links[0].pk, link2.pk)
        self.assertEqual(links[1].pk, link1.pk)
