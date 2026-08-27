"""
Matriz Maintenance(ABERTA) × MovementType, revisada em 27/08/2026 (decisão
1): confirma que `apps.operations.services._validate_transition()` bloqueia
INSTALACAO/RETIRADA/TRANSFERENCIA/ENVIO_MANUTENCAO sempre que existe uma
`Maintenance` ABERTA E ATIVA para o equipamento — mesmo quando
`Equipment.status` sozinho já permitiria (o cenário do relatório: status
volta a DISPONIVEL via RETORNO_ESTOQUE/RETORNO_MANUTENCAO "por fora" da
Maintenance, sem fechar a ficha). RETORNO_ESTOQUE/RETORNO_MANUTENCAO/OUTRO
continuam permitidos mesmo com a ficha aberta.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.models import Status
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.maintenance.services import NewMaintenanceData, cancel_maintenance, close_maintenance, open_maintenance
from apps.maintenance.services import CloseMaintenanceData
from apps.operations.models import LocationType, MovementType
from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

User = get_user_model()


class MaintenanceMovementCompatibilityTestBase(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Refrigerador")
        model = EquipmentModel.objects.create(category=category, name="Refrigerador Torre", code="REFT")
        self.tecnico = User.objects.create_user(username="tecnico_mm", password="senha-forte-123", role="OPERACIONAL")
        self.admin = User.objects.create_user(username="admin_mm", password="senha-forte-123", role="ADMIN")

        self.estoque = create_location(NewLocationData(name="Estoque MM", type=LocationType.ESTOQUE))
        self.oficina = create_location(NewLocationData(name="Oficina MM", type=LocationType.MANUTENCAO))
        self.cliente = Client.objects.create(company_name="Cliente MM LTDA")
        self.unidade_cliente = create_location(
            NewLocationData(name="Unidade MM A", type=LocationType.CLIENTE, client=self.cliente)
        )

        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))

    def _move(self, movement_type, destination):
        return create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=movement_type,
                created_by=self.admin,
                destination_location=destination,
            )
        )

    def _open_and_return_via_retorno_estoque(self):
        """
        Reproduz o cenário exato relatado: abre manutenção SEM movimento
        (status_before=DISPONIVEL), depois um RETORNO_ESTOQUE traz o
        status de volta a DISPONIVEL "por fora", SEM fechar a ficha.
        """
        maintenance = open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type="CORRETIVA",
                responsible=self.tecnico,
                created_by=self.tecnico,
            )
        )
        self._move(MovementType.RETORNO_ESTOQUE, self.estoque)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        return maintenance


class BloqueadosComManutencaoAbertaTest(MaintenanceMovementCompatibilityTestBase):
    """INSTALACAO/RETIRADA/TRANSFERENCIA/ENVIO_MANUTENCAO — sempre bloqueados com Maintenance ABERTA ativa."""

    def test_instalacao_bloqueada_mesmo_com_status_disponivel(self):
        self._open_and_return_via_retorno_estoque()
        with self.assertRaisesMessage(ValueError, "manutenção técnica ainda aberta"):
            self._move(MovementType.INSTALACAO, self.unidade_cliente)

    def test_envio_manutencao_bloqueado_mesmo_com_status_disponivel(self):
        self._open_and_return_via_retorno_estoque()
        with self.assertRaisesMessage(ValueError, "manutenção técnica ainda aberta"):
            self._move(MovementType.ENVIO_MANUTENCAO, self.oficina)

    def test_retirada_bloqueada_mesmo_com_status_em_operacao(self):
        # Instala primeiro (sem Maintenance aberta) para chegar em EM_OPERACAO.
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        maintenance = open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type="CORRETIVA",
                responsible=self.tecnico,
                created_by=self.tecnico,
            )
        )
        # Maintenance sem movement, aberta a partir de EM_OPERACAO — status agora MANUTENCAO.
        # RETORNO_ESTOQUE traz de volta a DISPONIVEL "por fora" (não EM_OPERACAO, mas o
        # teste de TRANSFERENCIA abaixo cobre a exigência EM_OPERACAO separadamente).
        self._move(MovementType.RETORNO_ESTOQUE, self.estoque)
        with self.assertRaisesMessage(ValueError, "manutenção técnica ainda aberta"):
            self._move(MovementType.RETIRADA, self.estoque)

    def test_transferencia_bloqueada_com_manutencao_aberta_em_campo(self):
        self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.EM_OPERACAO)

        # Manutenção em campo (sem movimentação) — status vira MANUTENCAO.
        open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type="CORRETIVA",
                responsible=self.tecnico,
                created_by=self.tecnico,
            )
        )
        outro_cliente = Client.objects.create(company_name="Outro Cliente MM LTDA")
        outra_unidade = create_location(
            NewLocationData(name="Unidade MM B", type=LocationType.CLIENTE, client=outro_cliente)
        )
        # TRANSFERENCIA exige EM_OPERACAO — já bloqueado pelo status (MANUTENCAO), sem
        # nem precisar da checagem nova. Cobrimos aqui só para registrar o caso na matriz.
        with self.assertRaises(ValueError):
            self._move(MovementType.TRANSFERENCIA, outra_unidade)

    def test_fechando_a_manutencao_libera_os_bloqueados(self):
        maintenance = self._open_and_return_via_retorno_estoque()
        close_maintenance(
            maintenance=maintenance, data=CloseMaintenanceData(service_performed="Concluído.", closed_by=self.tecnico)
        )
        # Sem Maintenance ABERTA — INSTALACAO volta a ser permitida.
        movement = self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.EM_OPERACAO)
        self.assertEqual(movement.movement_type, MovementType.INSTALACAO)

    def test_cancelando_a_manutencao_libera_os_bloqueados(self):
        maintenance = self._open_and_return_via_retorno_estoque()
        cancel_maintenance(maintenance=maintenance, cancelled_by=self.tecnico)
        movement = self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self.assertEqual(movement.movement_type, MovementType.INSTALACAO)


class PermitidosComManutencaoAbertaTest(MaintenanceMovementCompatibilityTestBase):
    """RETORNO_ESTOQUE/RETORNO_MANUTENCAO/OUTRO — nunca bloqueados pela Maintenance aberta."""

    def test_retorno_estoque_permitido_com_manutencao_aberta(self):
        open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type="CORRETIVA",
                responsible=self.tecnico,
                created_by=self.tecnico,
            )
        )
        movement = self._move(MovementType.RETORNO_ESTOQUE, self.estoque)
        self.assertEqual(movement.movement_type, MovementType.RETORNO_ESTOQUE)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)

    def test_retorno_manutencao_permitido_com_manutencao_aberta(self):
        movimento_envio = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina)
        open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type="CORRETIVA",
                responsible=self.tecnico,
                created_by=self.tecnico,
                departure_movement=movimento_envio,
            )
        )
        movement = self._move(MovementType.RETORNO_MANUTENCAO, self.estoque)
        self.assertEqual(movement.movement_type, MovementType.RETORNO_MANUTENCAO)

    def test_outro_permitido_com_manutencao_aberta(self):
        open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type="CORRETIVA",
                responsible=self.tecnico,
                created_by=self.tecnico,
            )
        )
        movement = create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=MovementType.OUTRO,
                created_by=self.admin,
                reason="Anotação durante a manutenção.",
            )
        )
        self.assertEqual(movement.movement_type, MovementType.OUTRO)


class SemManutencaoAbertaNaoAfetaNadaTest(MaintenanceMovementCompatibilityTestBase):
    def test_instalacao_normal_sem_nenhuma_manutencao(self):
        movement = self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self.assertEqual(movement.movement_type, MovementType.INSTALACAO)

    def test_manutencao_concluida_nao_bloqueia(self):
        maintenance = open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type="CORRETIVA",
                responsible=self.tecnico,
                created_by=self.tecnico,
            )
        )
        close_maintenance(
            maintenance=maintenance, data=CloseMaintenanceData(service_performed="Concluído.", closed_by=self.tecnico)
        )
        movement = self._move(MovementType.INSTALACAO, self.unidade_cliente)
        self.assertEqual(movement.movement_type, MovementType.INSTALACAO)
