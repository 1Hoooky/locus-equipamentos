"""
Teste de concorrência real para P0-05/OPS-001 (especificação de
implementação, ponto 5 e ponto 11): `update_location()` alterando
`client` de uma Location X concorrentemente com `create_movement()`
instalando um Equipment nessa MESMA Location X.

`TransactionTestCase` (não `TestCase`) pelo mesmo motivo de
`test_movement_concurrency.py`/`test_patrimonio_generation.py`: threads
precisam de conexões e transações reais, e isso só é confiável em
PostgreSQL de verdade (`select_for_update()`).

Resultados válidos (especificação, ponto 5) — SÓ estes dois:
  A) "edição vence primeiro" → `update_location()` comita a troca de
     cliente (ainda não havia equipamento na Location no momento do seu
     commit) → `create_movement()` relê a Location já fresca (client
     novo) → `Equipment.current_client` = cliente novo.
  B) "movement vence primeiro" → `create_movement()` comita a instalação
     primeiro → `update_location()`, ao obter o lock, vê o equipamento já
     presente → recusa a alteração estrutural → `Location.client`
     permanece o original.

NUNCA aceitável: `Location.client` = novo E `Equipment.current_client` =
original ao mesmo tempo (a dessincronização que originou o OPS-001). O
teste não força uma ordem específica — usa uma `threading.Barrier` só
para maximizar a chance de contenção real, e depois aceita QUALQUER UMA
das duas ordens, mas verifica a invariante em ambos os casos. Inclui
timeout no `join()` para nunca travar o teste indefinidamente caso algum
deadlock inesperado apareça (não deveria: a ordem de locks é sempre
Equipment→Location em `create_movement()`, e só Location em
`update_location()` — proibição de ciclo comprovada na investigação).
"""

import threading

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import LocationType, MovementType
from apps.operations.services import (
    LocationUpdateData,
    NewLocationData,
    NewMovementData,
    create_location,
    create_movement,
    update_location,
)

User = get_user_model()

JOIN_TIMEOUT_SECONDS = 30  # guarda contra deadlock/hang — nunca deveria disparar (ordem de locks é livre de ciclo).


class LocationUpdateVersusCreateMovementRaceTest(TransactionTestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Corrida OPS-001", code="AQCR")
        self.user = User.objects.create_user(username="ops_001_corrida", password="senha-forte-123", role="OPERACIONAL")

        self.cliente_a = Client.objects.create(company_name="Cliente Corrida A LTDA")
        self.cliente_b = Client.objects.create(company_name="Cliente Corrida B LTDA")
        # Location X — ainda SEM equipamento no início do teste: é a
        # corrida em si que decide se o equipamento chega antes ou
        # depois da edição de cliente.
        self.location_x = create_location(
            NewLocationData(name="Unidade Corrida X", type=LocationType.CLIENTE, client=self.cliente_a)
        )
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.user))

    def test_invariant_holds_regardless_of_which_operation_wins(self):
        barrier = threading.Barrier(2)
        outcomes: dict[str, object] = {}
        errors: dict[str, Exception] = {}
        lock = threading.Lock()

        def run_update_location():
            try:
                barrier.wait(timeout=JOIN_TIMEOUT_SECONDS)
                update_location(
                    location=self.location_x,
                    data=LocationUpdateData(name=self.location_x.name, type=LocationType.CLIENTE, client=self.cliente_b),
                )
                with lock:
                    outcomes["update_location"] = "comitou"
            except Exception as exc:  # pragma: no cover - diagnóstico do teste
                with lock:
                    errors["update_location"] = exc
            finally:
                connection.close()

        def run_create_movement():
            try:
                barrier.wait(timeout=JOIN_TIMEOUT_SECONDS)
                create_movement(
                    NewMovementData(
                        equipment_id=self.equipment.pk,
                        movement_type=MovementType.INSTALACAO,
                        created_by=self.user,
                        destination_location=self.location_x,
                    )
                )
                with lock:
                    outcomes["create_movement"] = "comitou"
            except Exception as exc:  # pragma: no cover - diagnóstico do teste
                with lock:
                    errors["create_movement"] = exc
            finally:
                connection.close()

        t_update = threading.Thread(target=run_update_location)
        t_move = threading.Thread(target=run_create_movement)
        t_update.start()
        t_move.start()
        t_update.join(timeout=JOIN_TIMEOUT_SECONDS)
        t_move.join(timeout=JOIN_TIMEOUT_SECONDS)

        self.assertFalse(t_update.is_alive(), "update_location() não terminou dentro do timeout — possível deadlock.")
        self.assertFalse(t_move.is_alive(), "create_movement() não terminou dentro do timeout — possível deadlock.")

        # create_movement() tem que ter sucesso sempre — instalar não é
        # bloqueado por esta proteção (só a EDIÇÃO da Location é).
        self.assertEqual(outcomes.get("create_movement"), "comitou", f"errors={errors}")

        self.location_x.refresh_from_db()
        self.equipment.refresh_from_db()

        # Invariante central do OPS-001: o cache nunca pode divergir do
        # estado real da Location apontada, em NENHUMA das duas ordens.
        self.assertEqual(self.equipment.current_location_id, self.location_x.pk)
        self.assertEqual(self.equipment.current_client_id, self.location_x.client_id)

        if "update_location" in outcomes:
            # Ordem A — "edição venceu primeiro": a troca de cliente foi
            # aceita (não havia equipamento no momento do seu commit) e o
            # movement, ao reler a Location sob lock, já viu o cliente novo.
            self.assertEqual(self.location_x.client_id, self.cliente_b.pk)
            self.assertEqual(self.equipment.current_client_id, self.cliente_b.pk)
        else:
            # Ordem B — "movement venceu primeiro": update_location() viu
            # o equipamento já presente e recusou a alteração estrutural.
            self.assertIn("update_location", errors)
            self.assertIsInstance(errors["update_location"], ValueError)
            self.assertIn("Movimente os equipamentos primeiro", str(errors["update_location"]))
            self.assertEqual(self.location_x.client_id, self.cliente_a.pk)
            self.assertEqual(self.equipment.current_client_id, self.cliente_a.pk)

        # Nunca a mistura proibida: Location.client != Equipment.current_client.
        self.assertEqual(self.location_x.client_id, self.equipment.current_client_id)
