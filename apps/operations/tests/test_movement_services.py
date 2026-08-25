"""
Testes de `apps.operations.services.create_movement()` — arquitetura v1.0
seção 8/9 + delta v1.1 seções 6-10 + a regra adicional de compatibilidade
destino×tipo de movimentação (autorizada junto com o início desta
implementação).

Cobre, entre outras, as validações obrigatórias #11 (todos os tipos de
movimentação e destinos incompatíveis), #12 (rollback integral) e #14
(snapshots após renomear Client/Location).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.forms import EquipmentUpdateForm
from apps.equipment.models import Equipment, Status
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import LocationType, Movement, MovementType
from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

User = get_user_model()


class MovementTestBase(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Torre", code="AQTM")
        self.user = User.objects.create_user(username="operador", password="senha-forte-123", role="OPERACIONAL")

        self.estoque = create_location(NewLocationData(name="Estoque Central", type=LocationType.ESTOQUE))
        self.manutencao = create_location(NewLocationData(name="Oficina Parceira", type=LocationType.MANUTENCAO))
        self.cliente = Client.objects.create(company_name="Cliente Movimentação LTDA")
        self.unidade_cliente = create_location(
            NewLocationData(name="Unidade Cliente A", type=LocationType.CLIENTE, client=self.cliente)
        )
        self.outro_cliente = Client.objects.create(company_name="Outro Cliente LTDA")
        self.unidade_outro_cliente = create_location(
            NewLocationData(name="Unidade Cliente B", type=LocationType.CLIENTE, client=self.outro_cliente)
        )

        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.user))

    def _move(self, movement_type, destination, reason=""):
        return create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=movement_type,
                created_by=self.user,
                destination_location=destination,
                reason=reason,
            )
        )


class HappyPathTransitionsTest(MovementTestBase):
    """Cada um dos seis tipos de movimentação com tela autorizada, no caminho feliz."""

    def test_instalacao(self):
        movement = self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.EM_OPERACAO)
        self.assertEqual(self.equipment.current_location, self.unidade_cliente)
        self.assertEqual(self.equipment.current_client, self.cliente)
        self.assertEqual(movement.origin_location, None)
        self.assertEqual(movement.destination_location, self.unidade_cliente)

    def test_retirada(self):
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self._move(MovementType.RETIRADA, self.estoque)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        self.assertEqual(self.equipment.current_location, self.estoque)
        self.assertIsNone(self.equipment.current_client)

    def test_transferencia_entre_clientes(self):
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self._move(MovementType.TRANSFERENCIA, self.unidade_outro_cliente)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.EM_OPERACAO)  # sem mudança
        self.assertEqual(self.equipment.current_location, self.unidade_outro_cliente)
        self.assertEqual(self.equipment.current_client, self.outro_cliente)

    def test_transferencia_para_outra_unidade_do_mesmo_cliente(self):
        outra_unidade = create_location(
            NewLocationData(name="Unidade Cliente A2", type=LocationType.CLIENTE, client=self.cliente)
        )
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self._move(MovementType.TRANSFERENCIA, outra_unidade)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.current_location, outra_unidade)
        self.assertEqual(self.equipment.current_client, self.cliente)

    def test_retorno_ao_estoque_a_partir_de_em_operacao(self):
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self._move(MovementType.RETORNO_ESTOQUE, self.estoque)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        self.assertEqual(self.equipment.current_location, self.estoque)
        self.assertIsNone(self.equipment.current_client)

    def test_retorno_ao_estoque_a_partir_de_manutencao(self):
        self._move(MovementType.ENVIO_MANUTENCAO, self.manutencao)
        self._move(MovementType.RETORNO_ESTOQUE, self.estoque)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)

    def test_envio_manutencao_a_partir_de_disponivel(self):
        self._move(MovementType.ENVIO_MANUTENCAO, self.manutencao)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.MANUTENCAO)
        self.assertEqual(self.equipment.current_location, self.manutencao)
        self.assertIsNone(self.equipment.current_client)

    def test_envio_manutencao_a_partir_de_em_operacao(self):
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self._move(MovementType.ENVIO_MANUTENCAO, self.manutencao)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.MANUTENCAO)

    def test_retorno_manutencao_sempre_para_estoque(self):
        self._move(MovementType.ENVIO_MANUTENCAO, self.manutencao)
        self._move(MovementType.RETORNO_MANUTENCAO, self.estoque)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        self.assertEqual(self.equipment.current_location, self.estoque)


class StatusTransitionRejectionTest(MovementTestBase):
    def test_instalacao_requires_disponivel(self):
        self._move(MovementType.INSTALACAO, self.unidade_cliente)  # agora EM_OPERACAO
        with self.assertRaises(ValueError):
            self._move(MovementType.INSTALACAO, self.unidade_outro_cliente)

    def test_retirada_requires_em_operacao(self):
        with self.assertRaises(ValueError):
            self._move(MovementType.RETIRADA, self.estoque)  # ainda DISPONIVEL

    def test_transferencia_requires_em_operacao(self):
        with self.assertRaises(ValueError):
            self._move(MovementType.TRANSFERENCIA, self.unidade_cliente)

    def test_retorno_manutencao_requires_manutencao_status(self):
        with self.assertRaises(ValueError):
            self._move(MovementType.RETORNO_MANUTENCAO, self.estoque)  # ainda DISPONIVEL

    def test_invalid_transition_leaves_no_partial_write(self):
        """Validação obrigatória #12: rollback integral — nem Movement, nem StatusHistory, nem current_location mudam."""
        movements_before = Movement.objects.count()
        status_history_before = self.equipment.status_history.count()

        with self.assertRaises(ValueError):
            self._move(MovementType.RETIRADA, self.estoque)  # equipamento ainda DISPONIVEL

        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        self.assertIsNone(self.equipment.current_location)
        self.assertEqual(Movement.objects.count(), movements_before)
        self.assertEqual(self.equipment.status_history.count(), status_history_before)


class DestinationTypeCompatibilityTest(MovementTestBase):
    """
    Regra explícita acrescentada na autorização desta etapa: o tipo da
    Location de destino tem que ser compatível com o tipo de movimentação
    — testes positivos e negativos para cada uma das seis combinações.
    """

    def test_instalacao_rejects_non_cliente_destination(self):
        with self.assertRaises(ValueError):
            self._move(MovementType.INSTALACAO, self.estoque)

    def test_retirada_rejects_non_estoque_destination(self):
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        with self.assertRaises(ValueError):
            self._move(MovementType.RETIRADA, self.manutencao)

    def test_transferencia_rejects_non_cliente_destination(self):
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        with self.assertRaises(ValueError):
            self._move(MovementType.TRANSFERENCIA, self.estoque)

    def test_retorno_estoque_rejects_non_estoque_destination(self):
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        with self.assertRaises(ValueError):
            self._move(MovementType.RETORNO_ESTOQUE, self.manutencao)

    def test_envio_manutencao_rejects_non_manutencao_destination(self):
        with self.assertRaises(ValueError):
            self._move(MovementType.ENVIO_MANUTENCAO, self.estoque)

    def test_retorno_manutencao_rejects_non_estoque_destination(self):
        self._move(MovementType.ENVIO_MANUTENCAO, self.manutencao)
        with self.assertRaises(ValueError):
            self._move(MovementType.RETORNO_MANUTENCAO, self.unidade_cliente)

    def test_destination_required_for_all_six_types(self):
        for movement_type in (
            MovementType.INSTALACAO,
            MovementType.RETIRADA,
            MovementType.TRANSFERENCIA,
            MovementType.RETORNO_ESTOQUE,
            MovementType.ENVIO_MANUTENCAO,
            MovementType.RETORNO_MANUTENCAO,
        ):
            with self.subTest(movement_type=movement_type):
                with self.assertRaises(ValueError):
                    self._move(movement_type, None)


class TransferToSameLocationRejectionTest(MovementTestBase):
    """
    Regressão do bug relatado (#7): era possível registrar
    `Unidade 1 → Unidade 1` como TRANSFERENCIA — não é uma movimentação
    real. `create_movement()` rejeita quando `destination_location ==
    equipment.current_location` para TRANSFERENCIA, com mensagem clara.
    """

    def test_transferencia_to_current_location_is_rejected(self):
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        with self.assertRaises(ValueError) as ctx:
            self._move(MovementType.TRANSFERENCIA, self.unidade_cliente)
        self.assertIn("já está nesta unidade", str(ctx.exception))

    def test_transferencia_to_a_different_location_still_works(self):
        """A rejeição é só para a MESMA localização — transferir para outra continua funcionando normalmente."""
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self._move(MovementType.TRANSFERENCIA, self.unidade_outro_cliente)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.current_location, self.unidade_outro_cliente)

    def test_rejection_leaves_no_partial_write(self):
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        movements_before = Movement.objects.count()

        with self.assertRaises(ValueError):
            self._move(MovementType.TRANSFERENCIA, self.unidade_cliente)

        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.current_location, self.unidade_cliente)
        self.assertEqual(Movement.objects.count(), movements_before)


class OutroReasonRequirementTest(MovementTestBase):
    def test_outro_without_reason_is_rejected(self):
        with self.assertRaises(ValueError):
            self._move(MovementType.OUTRO, None, reason="")

    def test_outro_with_reason_succeeds_without_changing_location(self):
        movement = self._move(MovementType.OUTRO, None, reason="Equipamento avariado durante transporte.")
        self.equipment.refresh_from_db()
        self.assertIsNone(self.equipment.current_location)
        self.assertEqual(movement.reason, "Equipamento avariado durante transporte.")

    def test_database_check_constraint_rejects_outro_without_reason(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Movement.objects.create(
                    equipment=self.equipment, movement_type=MovementType.OUTRO, reason="", created_by=self.user
                )


class SnapshotImmutabilityTest(MovementTestBase):
    """Validação obrigatória #14: renomear Location/Client depois não altera o snapshot já gravado."""

    def test_snapshot_survives_location_and_client_rename(self):
        movement = self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self.assertEqual(movement.destination_location_name, "Unidade Cliente A")
        self.assertEqual(movement.destination_client_name, "Cliente Movimentação LTDA")

        self.unidade_cliente.name = "Unidade Renomeada 2027"
        self.unidade_cliente._change_reason = "Renomeação de teste."
        self.unidade_cliente.save()

        self.cliente.company_name = "Cliente Renomeado 2027 LTDA"
        self.cliente._change_reason = "Renomeação de teste."
        self.cliente.save()

        movement.refresh_from_db()
        self.assertEqual(movement.destination_location_name, "Unidade Cliente A")
        self.assertEqual(movement.destination_client_name, "Cliente Movimentação LTDA")


class CurrentClientInvariantTest(MovementTestBase):
    """
    Validação obrigatória: `current_client == current_location.client` (ou
    None) sempre — incluindo após TRANSFERENCIA para local sem cliente e
    para local com cliente.
    """

    def test_invariant_holds_through_a_full_sequence(self):
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.current_client_id, self.equipment.current_location.client_id)

        self._move(MovementType.TRANSFERENCIA, self.unidade_outro_cliente)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.current_client_id, self.equipment.current_location.client_id)

        self._move(MovementType.RETIRADA, self.estoque)
        self.equipment.refresh_from_db()
        self.assertIsNone(self.equipment.current_client_id)
        self.assertIsNone(self.equipment.current_location.client_id)

    def test_current_client_field_is_not_editable_in_any_form(self):
        """Teste negativo de superfície: current_client nunca aparece em nenhum form de edição de equipamento."""
        self.assertNotIn("current_client", EquipmentUpdateForm.base_fields)
        self.assertFalse(Equipment._meta.get_field("current_client").editable)
