"""
Testes de domínio de `apps.maintenance.services` para `Cleaning` (decisão
5 da arquitetura aprovada em 27/08/2026): evento técnico ATÔMICO, sem
ciclo aberta/concluída, que nunca altera `Equipment.status`/`condition`
automaticamente, e cuja correção de registro incorreto segue a estratégia
de soft-delete do projeto (nunca `UPDATE` silencioso).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.models import Condition, Status
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.maintenance.services import NewCleaningData, cancel_cleaning, create_cleaning
from apps.operations.models import LocationType, MovementType
from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

User = get_user_model()


class CleaningTestBase(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Bebedouro")
        model = EquipmentModel.objects.create(category=category, name="Bebedouro Compacto", code="BBCP")
        self.tecnico = User.objects.create_user(username="tecnico_hig", password="senha-forte-123", role=Role.OPERACIONAL)
        self.admin = User.objects.create_user(username="admin_hig", password="senha-forte-123", role=Role.ADMIN)
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))
        self.estoque = create_location(NewLocationData(name="Estoque Higienização", type=LocationType.ESTOQUE))


class CreateCleaningTest(CleaningTestBase):
    def test_criacao_basica(self):
        cleaning = create_cleaning(
            NewCleaningData(
                equipment_id=self.equipment.pk,
                responsible=self.tecnico,
                created_by=self.admin,
                notes="Higienização de rotina.",
            )
        )
        self.assertEqual(cleaning.equipment, self.equipment)
        self.assertTrue(cleaning.is_active)
        self.assertIsNotNone(cleaning.performed_at)
        self.assertIsNone(cleaning.movement)

    def test_performed_at_explicito_e_respeitado(self):
        quando = timezone.now() - timezone.timedelta(days=3)
        cleaning = create_cleaning(
            NewCleaningData(
                equipment_id=self.equipment.pk, responsible=self.tecnico, created_by=self.admin, performed_at=quando
            )
        )
        self.assertEqual(cleaning.performed_at, quando)

    def test_next_due_at_opcional(self):
        daqui_90_dias = (timezone.now() + timezone.timedelta(days=90)).date()
        cleaning = create_cleaning(
            NewCleaningData(
                equipment_id=self.equipment.pk,
                responsible=self.tecnico,
                created_by=self.admin,
                next_due_at=daqui_90_dias,
            )
        )
        self.assertEqual(cleaning.next_due_at, daqui_90_dias)

    def test_nao_altera_status_nem_condicao(self):
        status_antes, condition_antes = self.equipment.status, self.equipment.condition
        create_cleaning(NewCleaningData(equipment_id=self.equipment.pk, responsible=self.tecnico, created_by=self.admin))

        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, status_antes)
        self.assertEqual(self.equipment.condition, condition_antes)

    def test_movement_associado_quando_relevante(self):
        movimento = self._retorno_estoque_movement()

        cleaning = create_cleaning(
            NewCleaningData(
                equipment_id=self.equipment.pk, responsible=self.tecnico, created_by=self.admin, movement=movimento
            )
        )
        self.assertEqual(cleaning.movement, movimento)

    def _retorno_estoque_movement(self):
        # Equipamento recém-criado está DISPONIVEL/sem location — usa
        # ENVIO_MANUTENCAO->RETORNO_ESTOQUE só para produzir um Movement
        # real e válido para associar à higienização (RETORNO_ESTOQUE
        # aceita MANUTENCAO como precondição de status).
        oficina = create_location(NewLocationData(name="Oficina Higienização", type=LocationType.MANUTENCAO))
        create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=MovementType.ENVIO_MANUTENCAO,
                created_by=self.admin,
                destination_location=oficina,
            )
        )
        return create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=MovementType.RETORNO_ESTOQUE,
                created_by=self.admin,
                destination_location=self.estoque,
            )
        )

    def test_movement_de_outro_equipamento_rejeitado(self):
        outro_equipment = create_equipment(NewEquipmentData(model_id=self.equipment.model_id, created_by=self.admin))
        movimento = self._retorno_estoque_movement()
        with self.assertRaises(ValueError):
            create_cleaning(
                NewCleaningData(
                    equipment_id=outro_equipment.pk, responsible=self.tecnico, created_by=self.admin, movement=movimento
                )
            )


class CancelCleaningTest(CleaningTestBase):
    def test_cancelamento_marca_inativo_sem_editar_outros_campos(self):
        cleaning = create_cleaning(
            NewCleaningData(equipment_id=self.equipment.pk, responsible=self.tecnico, created_by=self.admin, notes="Original.")
        )
        original_notes = cleaning.notes
        original_performed_at = cleaning.performed_at

        cancelled = cancel_cleaning(cleaning=cleaning)

        cleaning.refresh_from_db()
        self.assertFalse(cleaning.is_active)
        self.assertEqual(cleaning.notes, original_notes)
        self.assertEqual(cleaning.performed_at, original_performed_at)
        self.assertFalse(cancelled.is_active)

    def test_cancelar_ja_cancelado_rejeitado(self):
        cleaning = create_cleaning(
            NewCleaningData(equipment_id=self.equipment.pk, responsible=self.tecnico, created_by=self.admin)
        )
        cancel_cleaning(cleaning=cleaning)
        with self.assertRaises(ValueError):
            cancel_cleaning(cleaning=cleaning)
