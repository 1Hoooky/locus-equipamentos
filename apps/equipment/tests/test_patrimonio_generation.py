"""
Testes da geração atômica de patrimônio — especificação, seção 8:
"Testes automatizados obrigatórios: disparar N cadastros concorrentes do
mesmo modelo e verificar que todos os `model_sequence` gerados são
únicos e sequenciais, sem lacunas nem colisões."

Usamos `TransactionTestCase` (não `TestCase`) de propósito: `TestCase`
envolve cada teste numa transação que é revertida no final, o que
mascararia exatamente o tipo de problema de concorrência que este teste
existe para pegar — threads diferentes precisam de conexões e transações
de banco reais e independentes.

Isso só funciona de verdade em PostgreSQL (SQLite não tem SELECT FOR
UPDATE confiável sob concorrência) — reforça por que a especificação
(seção 8) exige Postgres em todos os ambientes, inclusive dev.
"""

import threading

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()


class PatrimonioGenerationConcurrencyTest(TransactionTestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Aquecedor")
        self.model = EquipmentModel.objects.create(category=self.category, name="Aquecedor Pirâmide", code="AQCP")
        self.user = User.objects.create_user(username="tester", password="senha-forte-123")

    def test_sequential_creation_increments_correctly(self):
        first = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.user))
        second = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.user))

        self.assertEqual(first.patrimonio, "LOC-AQCP-0001")
        self.assertEqual(second.patrimonio, "LOC-AQCP-0002")
        self.assertEqual(second.model_sequence, 2)

    def test_different_models_do_not_share_sequence(self):
        other_model = EquipmentModel.objects.create(category=self.category, name="Aquecedor Torre", code="AQCT")

        first = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.user))
        first_other = create_equipment(NewEquipmentData(model_id=other_model.pk, created_by=self.user))

        self.assertEqual(first.patrimonio, "LOC-AQCP-0001")
        self.assertEqual(first_other.patrimonio, "LOC-AQCT-0001")

    def test_concurrent_creation_never_duplicates_sequence(self):
        """
        N threads cadastrando o MESMO modelo ao mesmo tempo — nenhuma
        pode receber o mesmo model_sequence, e não pode haver lacunas.
        """
        n_threads = 12
        results: list[str] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker():
            try:
                # Cada thread precisa da sua própria conexão de banco —
                # conexões Django não são thread-safe.
                equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.user))
                with lock:
                    results.append(equipment.patrimonio)
            except Exception as exc:  # pragma: no cover - só para diagnóstico do teste
                with lock:
                    errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Erros durante a concorrência: {errors}")
        self.assertEqual(len(results), n_threads, "Nem todas as threads conseguiram criar um equipamento.")
        self.assertEqual(len(set(results)), n_threads, "Patrimônios duplicados detectados!")

        expected = {f"LOC-AQCP-{i:04d}" for i in range(1, n_threads + 1)}
        self.assertEqual(set(results), expected, "Sequência final tem lacunas ou números fora do esperado.")

        self.model.refresh_from_db()
        self.assertEqual(self.model.last_sequence, n_threads)
