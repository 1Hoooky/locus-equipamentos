"""
Exclusão definitiva (hard delete) de `Equipment` — rodada "AMBIENTE EM
DESENVOLVIMENTO / HARD DELETE DURANTE DESENVOLVIMENTO / NÃO FAZER
CASCADE CEGO", 11/09/2026.

Este é o caso mais denso dos três (Cliente/Equipamento/Oportunidade):
`Movement`/`Maintenance`/`Cleaning` são hoje `PROTECT` no schema (não
`CASCADE`), então sem este service NENHUM equipamento com histórico
operacional real poderia ser excluído. Cobre:
  - autoridade máxima consegue excluir, mesmo com histórico completo
    (StatusHistory/ConditionHistory automáticos + Movement/Maintenance/
    Cleaning removidos explicitamente, NA ORDEM CERTA — Maintenance.
    departure_movement/return_movement e Cleaning.movement apontam para
    Movement);
  - usuário comum é bloqueado (view E service);
  - registros COMPARTILHADOS nunca são tocados: EquipmentModel/Category/
    EquipmentBatch continuam existindo e com as contagens intactas;
    Location/Client só têm a referência zerada (SET_NULL) quando
    aplicável, nunca são excluídos;
  - `superseded_by` (self-FK) de outro equipamento é zerado (SET_NULL),
    o outro equipamento em si nunca é excluído.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client, ClientType
from apps.equipment.models import ConditionHistory, Equipment, EquipmentBatch, StatusHistory
from apps.equipment.services import (
    HardDeleteAuthorizationError,
    HardDeleteBlocked,
    NewEquipmentData,
    change_condition,
    change_status,
    create_equipment,
    hard_delete_equipment,
    preview_equipment_hard_delete,
)
from apps.maintenance.models import Cleaning, Maintenance, MaintenanceStatus, MaintenanceType
from apps.operations.models import Location, LocationType, Movement, MovementType

User = get_user_model()


def _make_equipment(actor, *, code="HDEQ"):
    category = Category.objects.create(name=f"Categoria {code}")
    model = EquipmentModel.objects.create(category=category, name=f"Modelo {code}", code=code)
    return create_equipment(NewEquipmentData(model_id=model.pk, created_by=actor)), category, model


class EquipmentHardDeleteServiceTest(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_user(
            username="eqhd_super", password="senha-forte-123", is_superuser=True
        )
        self.admin = User.objects.create_user(username="eqhd_admin", password="senha-forte-123", role=Role.ADMIN)
        self.equipment, self.category, self.model = _make_equipment(self.superuser, code="EQHD1")

    def test_superuser_can_hard_delete_equipment_without_history(self):
        equipment_id = self.equipment.pk
        result = hard_delete_equipment(equipment_id=equipment_id, actor=self.superuser)
        self.assertEqual(result.total_dependents, 0)
        self.assertFalse(Equipment.objects.filter(pk=equipment_id).exists())

    def test_non_superuser_actor_is_rejected_even_with_role_admin(self):
        with self.assertRaises(HardDeleteAuthorizationError):
            hard_delete_equipment(equipment_id=self.equipment.pk, actor=self.admin)
        self.assertTrue(Equipment.objects.filter(pk=self.equipment.pk).exists())

    def test_status_and_condition_history_cascade_automatically(self):
        change_status(equipment=self.equipment, new_status="MANUTENCAO", reason="teste", changed_by=self.superuser)
        change_condition(equipment=self.equipment, new_condition="RUIM", reason="teste", changed_by=self.superuser)
        equipment_id = self.equipment.pk
        self.assertTrue(StatusHistory.objects.filter(equipment_id=equipment_id).exists())
        self.assertTrue(ConditionHistory.objects.filter(equipment_id=equipment_id).exists())

        hard_delete_equipment(equipment_id=equipment_id, actor=self.superuser)

        self.assertFalse(StatusHistory.objects.filter(equipment_id=equipment_id).exists())
        self.assertFalse(ConditionHistory.objects.filter(equipment_id=equipment_id).exists())

    def test_movement_maintenance_and_cleaning_are_removed_together_in_correct_order(self):
        """
        O caso arquiteturalmente crítico: Movement/Maintenance/Cleaning são
        hoje PROTECT (não CASCADE), e Maintenance.departure_movement/
        return_movement + Cleaning.movement apontam PARA Movement — sem a
        ordem certa (Cleaning/Maintenance antes de Movement), a exclusão
        levantaria ProtectedError.
        """
        stock = Location.objects.create(name="Estoque HD", type=LocationType.ESTOQUE)
        departure = Movement.objects.create(
            equipment=self.equipment,
            movement_type=MovementType.ENVIO_MANUTENCAO,
            origin_location=stock,
            destination_location=None,
            created_by=self.superuser,
        )
        return_movement = Movement.objects.create(
            equipment=self.equipment,
            movement_type=MovementType.RETORNO_ESTOQUE,
            origin_location=None,
            destination_location=stock,
            created_by=self.superuser,
        )
        maintenance = Maintenance.objects.create(
            equipment=self.equipment,
            maintenance_type=MaintenanceType.CORRETIVA,
            status=MaintenanceStatus.CONCLUIDA,
            departure_movement=departure,
            return_movement=return_movement,
            service_performed="Troca de peça",
            responsible=self.superuser,
            created_by=self.superuser,
            closed_at=timezone.now(),
        )
        cleaning = Cleaning.objects.create(
            equipment=self.equipment,
            performed_at=timezone.now(),
            responsible=self.superuser,
            created_by=self.superuser,
        )
        equipment_id = self.equipment.pk
        preview = preview_equipment_hard_delete(self.equipment)
        self.assertEqual(preview.dependents.get("movimentações"), 2)
        self.assertEqual(preview.dependents.get("manutenções"), 1)
        self.assertEqual(preview.dependents.get("higienizações"), 1)

        result = hard_delete_equipment(equipment_id=equipment_id, actor=self.superuser)

        self.assertEqual(result.total_dependents, 4)
        self.assertFalse(Equipment.objects.filter(pk=equipment_id).exists())
        self.assertFalse(Movement.objects.filter(pk__in=[departure.pk, return_movement.pk]).exists())
        self.assertFalse(Maintenance.objects.filter(pk=maintenance.pk).exists())
        self.assertFalse(Cleaning.objects.filter(pk=cleaning.pk).exists())
        # Location é REGISTRO COMPARTILHADO — nunca tocada.
        self.assertTrue(Location.objects.filter(pk=stock.pk).exists())

    def test_shared_configuration_is_never_touched(self):
        model_id = self.model.pk
        category_id = self.category.pk
        hard_delete_equipment(equipment_id=self.equipment.pk, actor=self.superuser)
        self.assertTrue(EquipmentModel.objects.filter(pk=model_id).exists())
        self.assertTrue(Category.objects.filter(pk=category_id).exists())

    def test_client_relation_is_unlinked_not_client_deleted(self):
        client = Client.objects.create(client_type=ClientType.PJ, company_name="Cliente EQ HD", document="11.222.333/0001-81")
        self.equipment.current_client = client
        self.equipment.save(update_fields=["current_client"])

        hard_delete_equipment(equipment_id=self.equipment.pk, actor=self.superuser)

        self.assertTrue(Client.objects.filter(pk=client.pk).exists())

    def test_superseded_by_reference_on_another_equipment_is_cleared_not_the_equipment_itself(self):
        old_equipment, _, _ = _make_equipment(self.superuser, code="EQHDOLD")
        old_equipment.superseded_by = self.equipment
        old_equipment.save(update_fields=["superseded_by"])
        old_equipment_id = old_equipment.pk

        hard_delete_equipment(equipment_id=self.equipment.pk, actor=self.superuser)

        self.assertTrue(Equipment.objects.filter(pk=old_equipment_id).exists())
        old_equipment.refresh_from_db()
        self.assertIsNone(old_equipment.superseded_by_id)

    def test_equipment_batch_shared_by_other_equipment_is_never_touched(self):
        batch = EquipmentBatch.objects.create(
            model=self.model,
            quantity=2,
            condition="BOM",
            first_patrimonio="LOC-EQHD1-0001",
            last_patrimonio="LOC-EQHD1-0002",
            created_by=self.superuser,
        )
        self.equipment.batch = batch
        self.equipment.save(update_fields=["batch"])
        batch_id = batch.pk

        hard_delete_equipment(equipment_id=self.equipment.pk, actor=self.superuser)

        self.assertTrue(EquipmentBatch.objects.filter(pk=batch_id).exists())


class EquipmentHardDeleteViewTest(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_user(
            username="eqhd_super_view", password="senha-forte-123", is_superuser=True
        )
        self.admin = User.objects.create_user(
            username="eqhd_admin_view", password="senha-forte-123", role=Role.ADMIN
        )
        self.equipment, _, _ = _make_equipment(self.superuser, code="EQHDVIEW")
        self.url = f"/equipamentos/{self.equipment.patrimonio}/excluir-definitivamente/"

    def test_get_requires_superuser_not_just_admin_role(self):
        self.client.login(username="eqhd_admin_view", password="senha-forte-123")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.client.login(username="eqhd_super_view", password="senha-forte-123")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Excluir definitivamente")

    def test_post_with_confirmation_deletes_and_redirects_to_list(self):
        self.client.login(username="eqhd_super_view", password="senha-forte-123")
        response = self.client.post(self.url, {"confirm": "on"})
        self.assertRedirects(response, "/equipamentos/")
        self.assertFalse(Equipment.objects.filter(pk=self.equipment.pk).exists())

    def test_non_superuser_post_is_forbidden_and_equipment_survives(self):
        self.client.login(username="eqhd_admin_view", password="senha-forte-123")
        response = self.client.post(self.url, {"confirm": "on"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Equipment.objects.filter(pk=self.equipment.pk).exists())

    def test_hard_delete_link_only_visible_to_superuser_on_detail_page(self):
        detail_url = f"/equipamentos/{self.equipment.patrimonio}/"
        self.client.login(username="eqhd_admin_view", password="senha-forte-123")
        response = self.client.get(detail_url)
        self.assertNotContains(response, "excluir-definitivamente")

        self.client.login(username="eqhd_super_view", password="senha-forte-123")
        response = self.client.get(detail_url)
        self.assertContains(response, "excluir-definitivamente")
