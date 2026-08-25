"""
Teste de concorrência real de `create_movement()` — validação obrigatória
#13, exatamente o cenário descrito na arquitetura aprovada (delta v1.1,
seção 9): equipamento em DISPONIVEL/estoque; duas threads disparadas ao
mesmo tempo tentando INSTALACAO em clientes diferentes. Exatamente uma
deve suceder; a outra falha com `ValueError` (porque, quando finalmente
obtém o lock, o equipamento já está `EM_OPERACAO`); o estado final tem que
corresponder inteiramente à movimentação que venceu a corrida.

`TransactionTestCase` (não `TestCase`) pelo mesmo motivo de
`test_patrimonio_generation.py`: threads precisam de conexões e
transações reais, e isso só é confiável em PostgreSQL de verdade
(`select_for_update()`).
"""

import threading

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.models import Status
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import LocationType, MovementType
from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

User = get_user_model()


class MovementConcurrencyTest(TransactionTestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Concorrente", code="AQCC")
        self.user = User.objects.create_user(username="operador_concorrente", password="senha-forte-123", role="OPERACIONAL")

        self.cliente_a = Client.objects.create(company_name="Cliente A LTDA")
        self.cliente_b = Client.objects.create(company_name="Cliente B LTDA")
        self.unidade_a = create_location(NewLocationData(name="Unidade A", type=LocationType.CLIENTE, client=self.cliente_a))
        self.unidade_b = create_location(NewLocationData(name="Unidade B", type=LocationType.CLIENTE, client=self.cliente_b))

        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.user))
        self.assertEqual(self.equipment.status, Status.DISPONIVEL)

    def test_exactly_one_installation_wins_the_race(self):
        results: dict[str, object] = {}
        errors: dict[str, Exception] = {}
        lock = threading.Lock()

        def worker(label, destination):
            try:
                movement = create_movement(
                    NewMovementData(
                        equipment_id=self.equipment.pk,
                        movement_type=MovementType.INSTALACAO,
                        created_by=self.user,
                        destination_location=destination,
                    )
                )
                with lock:
                    results[label] = movement
            except Exception as exc:  # pragma: no cover - diagnóstico do teste
                with lock:
                    errors[label] = exc
            finally:
                connection.close()

        t_a = threading.Thread(target=worker, args=("A", self.unidade_a))
        t_b = threading.Thread(target=worker, args=("B", self.unidade_b))
        t_a.start()
        t_b.start()
        t_a.join()
        t_b.join()

        self.assertEqual(len(results), 1, f"Esperado exatamente 1 sucesso, obtido {len(results)}. Erros: {errors}")
        self.assertEqual(len(errors), 1, f"Esperado exatamente 1 falha, obtido {len(errors)}. Resultados: {results}")

        winner_label = next(iter(results))
        loser_label = next(iter(errors))
        self.assertNotEqual(winner_label, loser_label)
        self.assertIsInstance(errors[loser_label], ValueError)

        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.EM_OPERACAO)

        expected_location = self.unidade_a if winner_label == "A" else self.unidade_b
        expected_client = self.cliente_a if winner_label == "A" else self.cliente_b
        self.assertEqual(self.equipment.current_location_id, expected_location.pk)
        self.assertEqual(self.equipment.current_client_id, expected_client.pk)

        # Nenhuma mistura: só existe UM Movement gravado para este equipamento.
        self.assertEqual(self.equipment.movements.count(), 1)
