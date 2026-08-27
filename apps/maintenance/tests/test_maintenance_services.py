"""
Testes de domínio de `apps.maintenance.services` (fundação aprovada em
27/08/2026) — cobrem as Matrizes 1 e 2 documentadas no topo de
`apps.maintenance.services`: abertura/fechamento/cancelamento de
`Maintenance`, a estratégia de restauração determinística de status
(`status_before`), e a integração opcional/unidirecional com `Movement`.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.permissions import CAN_VIEW_MAINTENANCE, CAN_VIEW_MOVEMENTS
from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.models import Condition, Equipment, Status
from apps.equipment.services import NewEquipmentData, change_status, create_equipment
from apps.maintenance.models import Cleaning, Maintenance, MaintenanceStatus, MaintenanceType
from apps.maintenance.services import (
    CloseMaintenanceData,
    NewCleaningData,
    NewMaintenanceData,
    cancel_cleaning,
    cancel_maintenance,
    close_maintenance,
    create_cleaning,
    open_maintenance,
)
from apps.operations.models import LocationType, MovementType
from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

User = get_user_model()


class MaintenanceTestBase(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Torre", code="AQTM")
        self.tecnico = User.objects.create_user(username="tecnico", password="senha-forte-123", role=Role.OPERACIONAL)
        self.admin = User.objects.create_user(username="admin_mnt", password="senha-forte-123", role=Role.ADMIN)

        self.estoque = create_location(NewLocationData(name="Estoque Central", type=LocationType.ESTOQUE))
        self.oficina = create_location(NewLocationData(name="Oficina Parceira", type=LocationType.MANUTENCAO))
        self.cliente = Client.objects.create(company_name="Cliente Manutenção LTDA")
        self.unidade_cliente = create_location(
            NewLocationData(name="Unidade Cliente A", type=LocationType.CLIENTE, client=self.cliente)
        )

        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))

    def _move(self, movement_type, destination, equipment=None):
        return create_movement(
            NewMovementData(
                equipment_id=(equipment or self.equipment).pk,
                movement_type=movement_type,
                created_by=self.admin,
                destination_location=destination,
            )
        )

    def _open(self, **overrides):
        data = dict(
            equipment_id=self.equipment.pk,
            maintenance_type=MaintenanceType.CORRETIVA,
            responsible=self.tecnico,
            created_by=self.tecnico,
            diagnosis="Ruído incomum no motor.",
        )
        data.update(overrides)
        return open_maintenance(NewMaintenanceData(**data))


class LinhaAEstoqueSemMovementTest(MaintenanceTestBase):
    """Matriz 1, linha A: manutenção em estoque, sem Movement. DISPONIVEL → MANUTENCAO → DISPONIVEL."""

    def test_abertura_muda_status_e_grava_snapshot(self):
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        maintenance = self._open()

        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.MANUTENCAO)
        self.assertEqual(maintenance.status, MaintenanceStatus.ABERTA)
        self.assertEqual(maintenance.status_before, Status.DISPONIVEL)
        self.assertEqual(maintenance.condition_before, self.equipment.condition)
        self.assertIsNone(maintenance.departure_movement)
        self.assertIsNone(maintenance.closed_at)

    def test_fechamento_restaura_status_anterior(self):
        maintenance = self._open()
        closed = close_maintenance(
            maintenance=maintenance,
            data=CloseMaintenanceData(service_performed="Troca de rolamento.", closed_by=self.tecnico),
        )

        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        self.assertEqual(closed.status, MaintenanceStatus.CONCLUIDA)
        self.assertIsNotNone(closed.closed_at)
        self.assertEqual(closed.service_performed, "Troca de rolamento.")

    def test_fechamento_com_condition_after_atualiza_condicao_via_service(self):
        maintenance = self._open()
        close_maintenance(
            maintenance=maintenance,
            data=CloseMaintenanceData(
                service_performed="Troca de rolamento.", closed_by=self.tecnico, condition_after=Condition.MEDIO
            ),
        )
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.condition, Condition.MEDIO)
        self.assertEqual(self.equipment.condition_history.count(), 1)
        self.assertEqual(self.equipment.condition_history.first().reason, f"Registrado ao concluir manutenção #{maintenance.pk}.")


class LinhaBClienteSemMovementTest(MaintenanceTestBase):
    """Matriz 1, linha B: manutenção em cliente, sem Movement. EM_OPERACAO → MANUTENCAO → EM_OPERACAO."""

    def test_restaura_em_operacao(self):
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.EM_OPERACAO)

        maintenance = self._open()
        self.equipment.refresh_from_db()
        self.assertEqual(maintenance.status_before, Status.EM_OPERACAO)
        self.assertEqual(self.equipment.status, Status.MANUTENCAO)

        close_maintenance(
            maintenance=maintenance,
            data=CloseMaintenanceData(service_performed="Ajuste em campo.", closed_by=self.tecnico),
        )
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.EM_OPERACAO)


class LinhaCComEnvioManutencaoTest(MaintenanceTestBase):
    """Matriz 1, linha C: manutenção COM departure_movement (ENVIO_MANUTENCAO já rodou)."""

    def test_abertura_nao_duplica_mudanca_de_status(self):
        movimento_envio = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.MANUTENCAO)
        eventos_antes = self.equipment.status_history.count()

        maintenance = self._open(departure_movement=movimento_envio)

        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.MANUTENCAO)
        # Nenhum StatusHistory novo — o Movement já tinha gravado o dele.
        self.assertEqual(self.equipment.status_history.count(), eventos_antes)
        self.assertEqual(maintenance.departure_movement, movimento_envio)
        # Snapshot é só informativo aqui, não usado para restauração.
        self.assertEqual(maintenance.status_before, Status.MANUTENCAO)

    def test_fechamento_sem_return_movement_nao_altera_status(self):
        movimento_envio = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina)
        maintenance = self._open(departure_movement=movimento_envio)

        close_maintenance(
            maintenance=maintenance,
            data=CloseMaintenanceData(service_performed="Serviço concluído na oficina.", closed_by=self.tecnico),
        )
        self.equipment.refresh_from_db()
        # Equipamento fisicamente ainda fora — status continua MANUTENCAO.
        self.assertEqual(self.equipment.status, Status.MANUTENCAO)

    def test_fechamento_com_return_movement_apenas_vincula(self):
        movimento_envio = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina)
        maintenance = self._open(departure_movement=movimento_envio)
        movimento_retorno = self._move(MovementType.RETORNO_MANUTENCAO, self.estoque)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        eventos_antes = self.equipment.status_history.count()

        closed = close_maintenance(
            maintenance=maintenance,
            data=CloseMaintenanceData(
                service_performed="Serviço concluído.", closed_by=self.tecnico, return_movement=movimento_retorno
            ),
        )
        self.equipment.refresh_from_db()
        self.assertEqual(closed.return_movement, movimento_retorno)
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        self.assertEqual(self.equipment.status_history.count(), eventos_antes)

    def test_departure_movement_tipo_errado_rejeitado(self):
        movimento_retorno_invalido = self._move(MovementType.INSTALACAO, self.unidade_cliente)
        with self.assertRaises(ValueError):
            self._open(departure_movement=movimento_retorno_invalido)

    def test_departure_movement_de_outro_equipamento_rejeitado(self):
        outro = create_equipment(NewEquipmentData(model_id=self.equipment.model_id, created_by=self.admin))
        movimento_outro = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina, equipment=outro)
        with self.assertRaises(ValueError):
            self._open(departure_movement=movimento_outro)

    def test_departure_movement_ja_vinculado_rejeitado(self):
        movimento_envio = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina)
        self._open(departure_movement=movimento_envio)

        outro = create_equipment(NewEquipmentData(model_id=self.equipment.model_id, created_by=self.admin))
        with self.assertRaises(ValueError):
            open_maintenance(
                NewMaintenanceData(
                    equipment_id=outro.pk,
                    maintenance_type=MaintenanceType.CORRETIVA,
                    responsible=self.tecnico,
                    created_by=self.tecnico,
                    departure_movement=movimento_envio,
                )
            )


class LinhaECancelamentoTest(MaintenanceTestBase):
    def test_cancelamento_sem_movement_restaura_status(self):
        maintenance = self._open()
        cancelled = cancel_maintenance(maintenance=maintenance, cancelled_by=self.tecnico, reason="Aberta por engano.")

        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        self.assertEqual(cancelled.status, MaintenanceStatus.CANCELADA)
        self.assertIsNotNone(cancelled.closed_at)
        self.assertIn("Aberta por engano.", cancelled.notes)

    def test_cancelamento_com_movement_nao_altera_status(self):
        movimento_envio = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina)
        maintenance = self._open(departure_movement=movimento_envio)
        cancel_maintenance(maintenance=maintenance, cancelled_by=self.tecnico)

        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.MANUTENCAO)

    def test_cancelamento_de_maintenance_nao_aberta_rejeitado(self):
        maintenance = self._open()
        close_maintenance(
            maintenance=maintenance, data=CloseMaintenanceData(service_performed="Concluído.", closed_by=self.tecnico)
        )
        with self.assertRaises(ValueError):
            cancel_maintenance(maintenance=maintenance, cancelled_by=self.tecnico)


class RegrasDeAberturaTest(MaintenanceTestBase):
    def test_status_incompativel_sem_movement_rejeitado(self):
        change_status(equipment=self.equipment, new_status=Status.INATIVO, reason="Baixa.", changed_by=self.admin)
        with self.assertRaises(ValueError):
            self._open()

    def test_duas_manutencoes_abertas_simultaneas_rejeitadas_pelo_service(self):
        self._open()
        with self.assertRaises(ValueError):
            self._open()

    def test_duas_manutencoes_abertas_simultaneas_rejeitadas_pelo_banco(self):
        """Segunda camada: mesmo pulando a checagem do service, o banco rejeita (UniqueConstraint condicional)."""
        self._open()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Maintenance.objects.create(
                    equipment=self.equipment,
                    maintenance_type=MaintenanceType.CORRETIVA,
                    status=MaintenanceStatus.ABERTA,
                    status_before=Status.DISPONIVEL,
                    responsible=self.tecnico,
                    created_by=self.tecnico,
                )

    def test_tipo_invalido_rejeitado(self):
        with self.assertRaises(ValueError):
            self._open(maintenance_type="INVALIDO")


class RegrasDeFechamentoTest(MaintenanceTestBase):
    def test_fechar_sem_service_performed_rejeitado(self):
        maintenance = self._open()
        with self.assertRaises(ValueError):
            close_maintenance(maintenance=maintenance, data=CloseMaintenanceData(service_performed="   ", closed_by=self.tecnico))

    def test_fechar_maintenance_nao_aberta_rejeitado(self):
        maintenance = self._open()
        close_maintenance(
            maintenance=maintenance, data=CloseMaintenanceData(service_performed="Concluído.", closed_by=self.tecnico)
        )
        with self.assertRaises(ValueError):
            close_maintenance(
                maintenance=maintenance, data=CloseMaintenanceData(service_performed="De novo?", closed_by=self.tecnico)
            )

    def test_return_movement_tipo_errado_rejeitado(self):
        movimento_envio = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina)
        maintenance = self._open(departure_movement=movimento_envio)

        # OUTRO não exige status/destino específico — o único jeito de
        # produzir, com o equipamento ainda em MANUTENCAO, um Movement REAL
        # de um tipo que _validate_return_movement precisa rejeitar (só
        # RETORNO_MANUTENCAO/RETORNO_ESTOQUE são aceitos como retorno).
        movimento_outro = create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=MovementType.OUTRO,
                created_by=self.admin,
                reason="Anotação qualquer, sem efeito de status.",
            )
        )
        with self.assertRaises(ValueError):
            close_maintenance(
                maintenance=maintenance,
                data=CloseMaintenanceData(
                    service_performed="Concluído.", closed_by=self.tecnico, return_movement=movimento_outro
                ),
            )

    def test_conclusao_bloqueada_no_banco_sem_service_performed(self):
        """Constraint de banco (dupla camada) — bypassando o service."""
        maintenance = self._open()
        maintenance.status = MaintenanceStatus.CONCLUIDA
        maintenance.closed_at = timezone.now()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                maintenance.save()


class IdempotenciaRestauracaoTest(MaintenanceTestBase):
    """
    Regra de corrida documentada na Matriz 1/2: um Movement externo pode
    trazer o equipamento de volta (RETORNO_ESTOQUE aceita MANUTENCAO como
    precondição) enquanto a Maintenance ainda está ABERTA. Fechar depois
    não pode lançar erro nem tentar restaurar por cima do valor já correto.
    """

    def test_fechar_apos_retorno_estoque_externo_nao_falha_nem_duplica(self):
        maintenance = self._open()  # sem movement — Maintenance é dona do status
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.MANUTENCAO)

        # Alguém devolve o equipamento fisicamente sem fechar a manutenção ainda.
        self._move(MovementType.RETORNO_ESTOQUE, self.estoque)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        eventos_antes = self.equipment.status_history.count()

        closed = close_maintenance(
            maintenance=maintenance,
            data=CloseMaintenanceData(service_performed="Concluído após retorno antecipado.", closed_by=self.tecnico),
        )
        self.equipment.refresh_from_db()
        self.assertEqual(closed.status, MaintenanceStatus.CONCLUIDA)
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        # Nenhuma tentativa de "restaurar" gerou um StatusHistory extra.
        self.assertEqual(self.equipment.status_history.count(), eventos_antes)


class PermissoesTest(TestCase):
    def test_can_view_maintenance_existe_com_mesmos_perfis_de_can_view_movements(self):
        self.assertEqual(set(CAN_VIEW_MAINTENANCE), set(CAN_VIEW_MOVEMENTS))
