"""
Testes de concorrência real (decisão 3, fechamento de 27/08/2026). A
corrida que a revisão pediu para eliminar: "verifica que não existe
Maintenance ABERTA → outra request abre/fecha a Maintenance → o Movement
prossegue com base numa leitura desatualizada". `TransactionTestCase`
(não `TestCase`) pelo mesmo motivo de
`apps.operations.tests.test_movement_concurrency`: threads precisam de
conexões e transações reais, e `select_for_update()` só é confiável em
PostgreSQL de verdade.

`open_maintenance()` e `create_movement()` tomam `Equipment` como ÚNICO
lock (`select_for_update()`, sempre a primeira operação de banco de cada
função) antes de ler/escrever qualquer coisa em `Maintenance`/`Movement`
— mesma ordem nos dois, o que serializa totalmente as duas operações sem
risco de deadlock (nenhuma das duas jamais segura um segundo lock
esperando o outro).
"""

import threading

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.models import Status
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.maintenance.models import MaintenanceStatus
from apps.maintenance.services import CloseMaintenanceData, NewMaintenanceData, close_maintenance, open_maintenance
from apps.operations.models import LocationType, MovementType
from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

User = get_user_model()


class AbrirManutencaoVersusInstalarConcurrencyTest(TransactionTestCase):
    """
    Cenário pedido explicitamente na revisão: tentativa simultânea de
    ABRIR uma Maintenance e de INSTALAR o mesmo equipamento, os dois a
    partir de DISPONIVEL (os dois são elegíveis nesse status). As duas
    disputam o mesmo lock de `Equipment` como primeira operação — o
    resultado final tem que corresponder inteiramente a QUALQUER UMA das
    duas ordens possíveis, nunca uma mistura das duas.
    """

    def setUp(self):
        category = Category.objects.create(name="Motobomba")
        model = EquipmentModel.objects.create(category=category, name="Motobomba 3CV", code="MTB3")
        self.tecnico = User.objects.create_user(username="tecnico_abrir", password="senha-forte-123", role="OPERACIONAL")
        self.admin = User.objects.create_user(username="admin_abrir", password="senha-forte-123", role="ADMIN")

        self.cliente = Client.objects.create(company_name="Cliente Abrir LTDA")
        self.unidade_cliente = create_location(
            NewLocationData(name="Unidade Abrir A", type=LocationType.CLIENTE, client=self.cliente)
        )

        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)

    def test_abertura_e_instalacao_simultaneas_terminam_em_estado_consistente(self):
        results: dict[str, object] = {}
        errors: dict[str, Exception] = {}
        lock = threading.Lock()

        def abrir():
            try:
                maintenance = open_maintenance(
                    NewMaintenanceData(
                        equipment_id=self.equipment.pk,
                        maintenance_type="CORRETIVA",
                        responsible=self.tecnico,
                        created_by=self.tecnico,
                    )
                )
                with lock:
                    results["abertura"] = maintenance
            except Exception as exc:  # pragma: no cover - diagnóstico do teste
                with lock:
                    errors["abertura"] = exc
            finally:
                connection.close()

        def instalar():
            try:
                movement = create_movement(
                    NewMovementData(
                        equipment_id=self.equipment.pk,
                        movement_type=MovementType.INSTALACAO,
                        created_by=self.admin,
                        destination_location=self.unidade_cliente,
                    )
                )
                with lock:
                    results["instalacao"] = movement
            except Exception as exc:  # pragma: no cover - diagnóstico do teste
                with lock:
                    errors["instalacao"] = exc
            finally:
                connection.close()

        t_abrir = threading.Thread(target=abrir)
        t_instalar = threading.Thread(target=instalar)
        t_abrir.start()
        t_instalar.start()
        t_abrir.join()
        t_instalar.join()

        self.equipment.refresh_from_db()

        if "abertura" in results and "instalacao" in errors:
            # ORDEM 1 — abrir venceu: a Maintenance existe ABERTA, e a
            # instalação tem que ter sido rejeitada EXATAMENTE pela
            # checagem nova (nunca por outro motivo) — status virou
            # MANUTENCAO antes da instalação sequer tentar.
            self.assertNotIn("abertura", errors)
            self.assertNotIn("instalacao", results)
            self.assertIsInstance(errors["instalacao"], ValueError)
            self.assertIn("manutenção técnica ainda aberta", str(errors["instalacao"]))
            self.assertEqual(self.equipment.status, Status.MANUTENCAO)
            self.assertEqual(
                self.equipment.maintenances.filter(status=MaintenanceStatus.ABERTA, is_active=True).count(), 1
            )
            self.assertEqual(self.equipment.movements.filter(movement_type=MovementType.INSTALACAO).count(), 0)

        elif "instalacao" in results and "abertura" in results:
            # ORDEM 2 — instalar venceu primeiro: status virou EM_OPERACAO,
            # que AINDA é um status válido para abrir manutenção em campo
            # (sem movimento) — a abertura, ao rodar DEPOIS, sucede
            # normalmente (não é um bug: é o comportamento correto para
            # essa ordem) e muda o status mais uma vez, para MANUTENCAO —
            # esse é o valor final, já que a abertura roda por último
            # nesta ordem. `current_location`/`current_client` continuam
            # os da instalação (Maintenance nunca mexe nesses dois campos).
            self.assertEqual(self.equipment.status, Status.MANUTENCAO)
            self.assertEqual(self.equipment.current_location_id, self.unidade_cliente.pk)
            self.assertEqual(self.equipment.current_client_id, self.cliente.pk)
            self.assertEqual(self.equipment.movements.filter(movement_type=MovementType.INSTALACAO).count(), 1)
            self.assertEqual(results["abertura"].status_before, Status.EM_OPERACAO)
            self.assertEqual(
                self.equipment.maintenances.filter(status=MaintenanceStatus.ABERTA, is_active=True).count(), 1
            )

        else:  # pragma: no cover - não deveria acontecer com o locking correto
            self.fail(f"Resultado inesperado — results={results}, errors={errors}")

        # Em qualquer ordem: nunca mais de uma Maintenance ABERTA ativa, e
        # nunca mais de um Movement INSTALACAO — nenhuma mistura das duas
        # ordens possíveis.
        self.assertLessEqual(
            self.equipment.maintenances.filter(status=MaintenanceStatus.ABERTA, is_active=True).count(), 1
        )
        self.assertLessEqual(self.equipment.movements.filter(movement_type=MovementType.INSTALACAO).count(), 1)


class FecharManutencaoVersusInstalarConcurrencyTest(TransactionTestCase):
    """
    Cenário complementar: a Maintenance já está ABERTA (status do
    equipamento já voltou a DISPONIVEL "por fora", via RETORNO_ESTOQUE,
    sem fechar a ficha — o cenário relatado no início desta revisão).
    Disputa simultânea entre FECHAR a ficha e INSTALAR o equipamento.
    """

    def setUp(self):
        category = Category.objects.create(name="Gerador")
        model = EquipmentModel.objects.create(category=category, name="Gerador Portátil", code="GRPT")
        self.tecnico = User.objects.create_user(username="tecnico_fechar", password="senha-forte-123", role="OPERACIONAL")
        self.admin = User.objects.create_user(username="admin_fechar", password="senha-forte-123", role="ADMIN")

        self.estoque = create_location(NewLocationData(name="Estoque Concorrência", type=LocationType.ESTOQUE))
        self.cliente = Client.objects.create(company_name="Cliente Concorrência LTDA")
        self.unidade_cliente = create_location(
            NewLocationData(name="Unidade Concorrência A", type=LocationType.CLIENTE, client=self.cliente)
        )

        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))

        self.maintenance = open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type="CORRETIVA",
                responsible=self.tecnico,
                created_by=self.tecnico,
            )
        )
        create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=MovementType.RETORNO_ESTOQUE,
                created_by=self.admin,
                destination_location=self.estoque,
            )
        )
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)
        self.maintenance.refresh_from_db()
        self.assertEqual(self.maintenance.status, MaintenanceStatus.ABERTA)

    def test_instalacao_e_fechamento_da_manutencao_nunca_coexistem_inconsistentes(self):
        results: dict[str, object] = {}
        errors: dict[str, Exception] = {}
        lock = threading.Lock()

        def instalar():
            try:
                movement = create_movement(
                    NewMovementData(
                        equipment_id=self.equipment.pk,
                        movement_type=MovementType.INSTALACAO,
                        created_by=self.admin,
                        destination_location=self.unidade_cliente,
                    )
                )
                with lock:
                    results["instalacao"] = movement
            except Exception as exc:  # pragma: no cover - diagnóstico do teste
                with lock:
                    errors["instalacao"] = exc
            finally:
                connection.close()

        def fechar():
            try:
                closed = close_maintenance(
                    maintenance=self.maintenance,
                    data=CloseMaintenanceData(service_performed="Concluído durante teste de corrida.", closed_by=self.tecnico),
                )
                with lock:
                    results["fechamento"] = closed
            except Exception as exc:  # pragma: no cover - diagnóstico do teste
                with lock:
                    errors["fechamento"] = exc
            finally:
                connection.close()

        t_instalar = threading.Thread(target=instalar)
        t_fechar = threading.Thread(target=fechar)
        t_instalar.start()
        t_fechar.start()
        t_instalar.join()
        t_fechar.join()

        # O fechamento NUNCA deveria falhar neste cenário — é sempre uma
        # operação válida independente da corrida (só a instalação pode
        # ou não vencer, dependendo da ordem).
        self.assertIn("fechamento", results, f"Fechamento falhou inesperadamente: {errors.get('fechamento')}")
        self.assertEqual(results["fechamento"].status, MaintenanceStatus.CONCLUIDA)

        self.equipment.refresh_from_db()

        if "instalacao" in results:
            self.assertNotIn("instalacao", errors)
            self.assertEqual(self.equipment.status, Status.EM_OPERACAO)
            self.assertEqual(self.equipment.current_location_id, self.unidade_cliente.pk)
            self.assertEqual(self.equipment.movements.filter(movement_type=MovementType.INSTALACAO).count(), 1)
        else:
            self.assertIn("instalacao", errors)
            self.assertIsInstance(errors["instalacao"], ValueError)
            self.assertIn("manutenção técnica ainda aberta", str(errors["instalacao"]))
            self.assertEqual(self.equipment.status, Status.DISPONIVEL)
            self.assertEqual(self.equipment.movements.filter(movement_type=MovementType.INSTALACAO).count(), 0)

        self.assertEqual(self.equipment.maintenances.filter(status=MaintenanceStatus.CONCLUIDA).count(), 1)
