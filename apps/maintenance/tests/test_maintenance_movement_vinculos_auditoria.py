"""
Testes da auditoria de vínculos Maintenance/Cleaning × Movement
(27/08/2026) — ver "AUDITORIA DE VÍNCULOS" no topo de
`apps.maintenance.services` para a lista completa das checagens novas.

Cobre exatamente os casos pedidos pela revisão que ainda não estavam
cobertos por testes existentes:

    - return_movement de outro equipamento
    - return_movement anterior ao departure_movement (e anterior à
      própria abertura da ficha, quando não há departure_movement)
    - return_movement já reclamado por outra Maintenance
    - RETORNO_MANUTENCAO sem departure_movement (cenário conceitualmente
      impossível — rejeitado) e RETORNO_ESTOQUE sem departure_movement
      (cenário válido — confirmação, não regressão)
    - corrida de duas tentativas de abrir Maintenance reivindicando o
      MESMO departure_movement

Casos já cobertos em `test_maintenance_services.py`/
`test_maintenance_movement_compatibility.py`/`test_cleaning_services.py`
(departure de outro equipamento, departure de tipo errado, departure já
vinculado, return de tipo errado, Cleaning de outro equipamento) não são
repetidos aqui.

Cada teste de rejeição confirma também que NENHUMA alteração parcial
ocorreu (rollback integral de `@transaction.atomic`): a Maintenance
continua ABERTA, sem `return_movement`, sem `closed_at`.
"""

import threading
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.models import Status
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.maintenance.models import MaintenanceStatus, MaintenanceType
from apps.maintenance.services import CloseMaintenanceData, NewMaintenanceData, close_maintenance, open_maintenance
from apps.operations.models import LocationType, Movement, MovementType
from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

User = get_user_model()


class VinculosAuditoriaTestBase(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Bomba Submersa")
        model = EquipmentModel.objects.create(category=category, name="Bomba Submersa X", code="BSUB")
        self.tecnico = User.objects.create_user(username="tecnico_vinc", password="senha-forte-123", role=Role.OPERACIONAL)
        self.admin = User.objects.create_user(username="admin_vinc", password="senha-forte-123", role=Role.ADMIN)

        self.estoque = create_location(NewLocationData(name="Estoque Vínculos", type=LocationType.ESTOQUE))
        self.oficina = create_location(NewLocationData(name="Oficina Vínculos", type=LocationType.MANUTENCAO))

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
        )
        data.update(overrides)
        return open_maintenance(NewMaintenanceData(**data))

    def _assert_sem_alteracao_parcial(self, maintenance):
        maintenance.refresh_from_db()
        self.assertEqual(maintenance.status, MaintenanceStatus.ABERTA)
        self.assertIsNone(maintenance.return_movement)
        self.assertIsNone(maintenance.closed_at)
        self.assertEqual(maintenance.service_performed, "")


class ReturnMovementDeOutroEquipamentoTest(VinculosAuditoriaTestBase):
    def test_return_movement_de_outro_equipamento_rejeitado(self):
        movimento_envio = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina)
        maintenance = self._open(departure_movement=movimento_envio)

        outro = create_equipment(NewEquipmentData(model_id=self.equipment.model_id, created_by=self.admin))
        self._move(MovementType.ENVIO_MANUTENCAO, self.oficina, equipment=outro)
        movimento_outro = self._move(MovementType.RETORNO_ESTOQUE, self.estoque, equipment=outro)

        with self.assertRaises(ValueError):
            close_maintenance(
                maintenance=maintenance,
                data=CloseMaintenanceData(
                    service_performed="Concluído.", closed_by=self.tecnico, return_movement=movimento_outro
                ),
            )
        self._assert_sem_alteracao_parcial(maintenance)


class ReturnAnteriorAoDepartureTest(VinculosAuditoriaTestBase):
    def test_return_anterior_ao_departure_rejeitado(self):
        movimento_envio = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina)
        maintenance = self._open(departure_movement=movimento_envio)
        movimento_retorno = self._move(MovementType.RETORNO_MANUTENCAO, self.estoque)

        # Backdata o retorno para antes do envio — `auto_now_add` só se
        # aplica na criação, então `update()` no manager (não `.save()`) é
        # o jeito correto de simular, em teste, um Movement "do passado".
        Movement.objects.filter(pk=movimento_retorno.pk).update(
            created_at=movimento_envio.created_at - timedelta(seconds=10)
        )
        movimento_retorno.refresh_from_db()

        with self.assertRaises(ValueError):
            close_maintenance(
                maintenance=maintenance,
                data=CloseMaintenanceData(
                    service_performed="Concluído.", closed_by=self.tecnico, return_movement=movimento_retorno
                ),
            )
        self._assert_sem_alteracao_parcial(maintenance)

    def test_return_anterior_a_abertura_sem_departure_rejeitado(self):
        maintenance = self._open()
        movimento_retorno = self._move(MovementType.RETORNO_ESTOQUE, self.estoque)

        Movement.objects.filter(pk=movimento_retorno.pk).update(
            created_at=maintenance.created_at - timedelta(seconds=10)
        )
        movimento_retorno.refresh_from_db()

        with self.assertRaises(ValueError):
            close_maintenance(
                maintenance=maintenance,
                data=CloseMaintenanceData(
                    service_performed="Concluído.", closed_by=self.tecnico, return_movement=movimento_retorno
                ),
            )
        self._assert_sem_alteracao_parcial(maintenance)


class ReturnMovementJaVinculadoTest(VinculosAuditoriaTestBase):
    def test_return_movement_ja_vinculado_a_outra_maintenance_rejeitado(self):
        movimento_envio_1 = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina)
        maintenance_1 = self._open(departure_movement=movimento_envio_1)
        movimento_retorno = self._move(MovementType.RETORNO_ESTOQUE, self.estoque)
        close_maintenance(
            maintenance=maintenance_1,
            data=CloseMaintenanceData(
                service_performed="Concluído.", closed_by=self.tecnico, return_movement=movimento_retorno
            ),
        )

        movimento_envio_2 = self._move(MovementType.ENVIO_MANUTENCAO, self.oficina)
        maintenance_2 = self._open(departure_movement=movimento_envio_2)

        with self.assertRaises(ValueError):
            close_maintenance(
                maintenance=maintenance_2,
                data=CloseMaintenanceData(
                    service_performed="Concluído.", closed_by=self.tecnico, return_movement=movimento_retorno
                ),
            )
        self._assert_sem_alteracao_parcial(maintenance_2)


class RetornoSemDepartureMovementTest(VinculosAuditoriaTestBase):
    """Cenário conceitualmente impossível (item 3 da revisão) — só RETORNO_MANUTENCAO é rejeitado sem departure."""

    def test_retorno_manutencao_sem_departure_movement_rejeitado(self):
        maintenance = self._open()  # sem departure_movement — manutenção em campo
        movimento_retorno = self._move(MovementType.RETORNO_MANUTENCAO, self.estoque)

        with self.assertRaises(ValueError):
            close_maintenance(
                maintenance=maintenance,
                data=CloseMaintenanceData(
                    service_performed="Concluído.", closed_by=self.tecnico, return_movement=movimento_retorno
                ),
            )
        self._assert_sem_alteracao_parcial(maintenance)

    def test_retorno_estoque_sem_departure_movement_aceito(self):
        """Confirmação (não regressão): RETORNO_ESTOQUE sem departure_movement continua válido."""
        maintenance = self._open()
        movimento_retorno = self._move(MovementType.RETORNO_ESTOQUE, self.estoque)

        closed = close_maintenance(
            maintenance=maintenance,
            data=CloseMaintenanceData(
                service_performed="Concluído.", closed_by=self.tecnico, return_movement=movimento_retorno
            ),
        )
        self.assertEqual(closed.status, MaintenanceStatus.CONCLUIDA)
        self.assertEqual(closed.return_movement, movimento_retorno)


class AbrirDuasVezesMesmoDepartureMovementConcurrencyTest(TransactionTestCase):
    """
    Corrida pedida explicitamente na revisão (item 7): duas tentativas de
    ABRIR uma Maintenance reivindicando o MESMO `departure_movement`
    simultaneamente. `open_maintenance()` toma `Equipment` como único lock
    (`select_for_update()`, sempre primeiro) — as duas disputam o MESMO
    lock, então são inteiramente serializadas: a segunda só prossegue
    depois que a primeira já comitou (ou já falhou), nunca lê um estado
    "no meio" da primeira. Resultado esperado: exatamente uma sucede,
    exatamente uma falha com `ValueError` (nunca `IntegrityError` cru,
    nunca as duas sucedendo, nunca as duas falhando).
    """

    def setUp(self):
        category = Category.objects.create(name="Motor Elétrico")
        model = EquipmentModel.objects.create(category=category, name="Motor Elétrico 5CV", code="MTE5")
        self.tecnico = User.objects.create_user(username="tecnico_race", password="senha-forte-123", role=Role.OPERACIONAL)
        self.admin = User.objects.create_user(username="admin_race", password="senha-forte-123", role=Role.ADMIN)
        self.oficina = create_location(NewLocationData(name="Oficina Corrida", type=LocationType.MANUTENCAO))

        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))
        self.movimento_envio = create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=MovementType.ENVIO_MANUTENCAO,
                created_by=self.admin,
                destination_location=self.oficina,
            )
        )
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.MANUTENCAO)

    def test_corrida_por_mesmo_departure_movement_termina_com_exatamente_um_vencedor(self):
        results = {}
        errors = {}
        lock = threading.Lock()

        def abrir(label):
            try:
                maintenance = open_maintenance(
                    NewMaintenanceData(
                        equipment_id=self.equipment.pk,
                        maintenance_type=MaintenanceType.CORRETIVA,
                        responsible=self.tecnico,
                        created_by=self.tecnico,
                        departure_movement=self.movimento_envio,
                    )
                )
                with lock:
                    results[label] = maintenance
            except Exception as exc:  # pragma: no cover - diagnóstico do teste
                with lock:
                    errors[label] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=abrir, args=("t1",))
        t2 = threading.Thread(target=abrir, args=("t2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exatamente um vencedor, exatamente um perdedor — nunca os dois.
        self.assertEqual(len(results), 1, f"results={results}, errors={errors}")
        self.assertEqual(len(errors), 1, f"results={results}, errors={errors}")

        vencedora = next(iter(results.values()))
        perdedor = next(iter(errors.values()))

        self.assertIsInstance(perdedor, ValueError)
        # Nunca IntegrityError cru vazando — ou a checagem de "já existe
        # manutenção aberta" pegou primeiro (mesmo lock, mesma corrida), ou
        # (defesa em profundidade) o catch de IntegrityError converteu.
        self.assertNotIsInstance(perdedor, type(None))

        self.assertEqual(vencedora.departure_movement_id, self.movimento_envio.pk)
        self.assertEqual(
            self.equipment.maintenances.filter(status=MaintenanceStatus.ABERTA, is_active=True).count(), 1
        )
        # Nenhuma segunda Maintenance foi criada pelo perdedor.
        self.assertEqual(self.equipment.maintenances.count(), 1)
