"""
Cadastro de equipamentos em lote — melhoria operacional da Fase 1, pedida
em 25/08/2026 (depois do congelamento original), última antes da Fase 2.

Estes testes cobrem a camada de serviço (`create_equipment_batch()`):
reuso do gerador atômico de patrimônio existente (nenhum contador
paralelo), atomicidade real da operação inteira (tudo ou nada), e
concorrência — o mesmo tipo de prova já exigida para o cadastro
individual em `test_patrimonio_generation.py`, agora também misturando
lote e cadastro individual do MESMO modelo ao mesmo tempo.
"""

import threading
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment import services as services_module
from apps.equipment.models import Equipment, EquipmentBatch
from apps.equipment.services import (
    MAX_BATCH_QUANTITY,
    NewEquipmentBatchData,
    NewEquipmentData,
    create_equipment,
    create_equipment_batch,
)

User = get_user_model()


class CreateEquipmentBatchTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        self.user = User.objects.create_user(username="lote_admin", password="senha-forte-123", role=Role.ADMIN)

    def test_creates_a_single_unit(self):
        batch = create_equipment_batch(
            NewEquipmentBatchData(model_id=self.model.pk, quantity=1, created_by=self.user)
        )
        self.assertEqual(batch.quantity, 1)
        self.assertEqual(batch.first_patrimonio, "LOC-NI23BT-0001")
        self.assertEqual(batch.last_patrimonio, "LOC-NI23BT-0001")
        self.assertEqual(Equipment.objects.filter(batch=batch).count(), 1)

    def test_creates_several_units_as_independent_equipment_records(self):
        batch = create_equipment_batch(
            NewEquipmentBatchData(model_id=self.model.pk, quantity=87, created_by=self.user)
        )
        self.assertEqual(batch.quantity, 87)
        self.assertEqual(batch.first_patrimonio, "LOC-NI23BT-0001")
        self.assertEqual(batch.last_patrimonio, "LOC-NI23BT-0087")

        equipment_qs = Equipment.objects.filter(batch=batch)
        self.assertEqual(equipment_qs.count(), 87)
        # Cada unidade é um Equipment independente com patrimônio próprio —
        # não existe "um equipamento com quantidade 87".
        patrimonios = set(equipment_qs.values_list("patrimonio", flat=True))
        self.assertEqual(len(patrimonios), 87)
        expected = {f"LOC-NI23BT-{i:04d}" for i in range(1, 88)}
        self.assertEqual(patrimonios, expected)

    def test_sequence_continues_correctly_when_equipment_already_exists(self):
        for _ in range(23):
            create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.user))

        batch = create_equipment_batch(
            NewEquipmentBatchData(model_id=self.model.pk, quantity=10, created_by=self.user)
        )
        self.assertEqual(batch.first_patrimonio, "LOC-NI23BT-0024")
        self.assertEqual(batch.last_patrimonio, "LOC-NI23BT-0033")

    def test_patrimonios_are_unique_across_the_batch(self):
        batch = create_equipment_batch(
            NewEquipmentBatchData(model_id=self.model.pk, quantity=50, created_by=self.user)
        )
        patrimonios = list(Equipment.objects.filter(batch=batch).values_list("patrimonio", flat=True))
        self.assertEqual(len(patrimonios), len(set(patrimonios)))

    def test_two_successive_batches_of_the_same_model_do_not_collide(self):
        first_batch = create_equipment_batch(
            NewEquipmentBatchData(model_id=self.model.pk, quantity=5, created_by=self.user)
        )
        second_batch = create_equipment_batch(
            NewEquipmentBatchData(model_id=self.model.pk, quantity=5, created_by=self.user)
        )

        self.assertEqual(first_batch.first_patrimonio, "LOC-NI23BT-0001")
        self.assertEqual(first_batch.last_patrimonio, "LOC-NI23BT-0005")
        self.assertEqual(second_batch.first_patrimonio, "LOC-NI23BT-0006")
        self.assertEqual(second_batch.last_patrimonio, "LOC-NI23BT-0010")

        self.model.refresh_from_db()
        self.assertEqual(self.model.last_sequence, 10)

    def test_common_optional_fields_are_copied_to_every_equipment(self):
        batch = create_equipment_batch(
            NewEquipmentBatchData(
                model_id=self.model.pk,
                quantity=3,
                created_by=self.user,
                condition="RUIM",
                supplier="Fornecedor do Lote LTDA",
                acquisition_date=None,
                acquisition_value=Decimal("999.90"),
                notes="Lote de reposição de estoque.",
            )
        )
        for equipment in Equipment.objects.filter(batch=batch):
            self.assertEqual(equipment.condition, "RUIM")
            self.assertEqual(equipment.supplier, "Fornecedor do Lote LTDA")
            self.assertEqual(equipment.acquisition_value, Decimal("999.90"))
            self.assertEqual(equipment.notes, "Lote de reposição de estoque.")

    def test_no_artificial_serial_number_or_legacy_code_is_generated(self):
        """
        Serial do fabricante e código legado são identificadores
        individuais por unidade física — o cadastro em lote nunca os
        pede nem os preenche artificialmente (nem repetidos, nem vazios
        "inventados"): ficam em branco, para preenchimento manual depois
        se for o caso.
        """
        batch = create_equipment_batch(
            NewEquipmentBatchData(model_id=self.model.pk, quantity=5, created_by=self.user)
        )
        for equipment in Equipment.objects.filter(batch=batch):
            self.assertEqual(equipment.serial_number, "")
            self.assertEqual(equipment.legacy_code, "")

    def test_zero_quantity_is_rejected(self):
        with self.assertRaises(ValueError):
            create_equipment_batch(NewEquipmentBatchData(model_id=self.model.pk, quantity=0, created_by=self.user))
        self.assertEqual(Equipment.objects.filter(model=self.model).count(), 0)

    def test_negative_quantity_is_rejected(self):
        with self.assertRaises(ValueError):
            create_equipment_batch(NewEquipmentBatchData(model_id=self.model.pk, quantity=-5, created_by=self.user))
        self.assertEqual(Equipment.objects.filter(model=self.model).count(), 0)

    def test_quantity_above_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            create_equipment_batch(
                NewEquipmentBatchData(model_id=self.model.pk, quantity=MAX_BATCH_QUANTITY + 1, created_by=self.user)
            )
        self.assertEqual(Equipment.objects.filter(model=self.model).count(), 0)

    def test_quantity_at_the_limit_is_accepted(self):
        """Não testamos MAX_BATCH_QUANTITY inteiro por custo de teste, mas o limite exato precisa passar, não falhar por 'off-by-one'."""
        with mock.patch("apps.equipment.services.MAX_BATCH_QUANTITY", 3):
            batch = create_equipment_batch(
                NewEquipmentBatchData(model_id=self.model.pk, quantity=3, created_by=self.user)
            )
        self.assertEqual(batch.quantity, 3)

    def test_inactive_model_is_rejected(self):
        self.model.is_active = False
        self.model.save(update_fields=["is_active"])

        with self.assertRaises(ValueError):
            create_equipment_batch(
                NewEquipmentBatchData(model_id=self.model.pk, quantity=5, created_by=self.user)
            )
        self.assertEqual(Equipment.objects.filter(model=self.model).count(), 0)

    def test_full_rollback_when_a_creation_fails_midway(self):
        """
        Falha simulada na 5ª de 10 unidades — o lote inteiro precisa ser
        revertido: nenhum Equipment, nenhum EquipmentBatch, e o contador
        `last_sequence` do modelo de volta ao valor de antes da tentativa.
        """
        real_create_equipment = services_module.create_equipment
        call_count = {"n": 0}

        def flaky_create_equipment(data):
            call_count["n"] += 1
            if call_count["n"] == 5:
                raise RuntimeError("Falha simulada no meio do lote.")
            return real_create_equipment(data)

        with mock.patch("apps.equipment.services.create_equipment", side_effect=flaky_create_equipment), self.assertRaises(RuntimeError):
            create_equipment_batch(NewEquipmentBatchData(model_id=self.model.pk, quantity=10, created_by=self.user))

        self.assertEqual(Equipment.objects.filter(model=self.model).count(), 0, "Lote não foi revertido por completo.")
        self.assertEqual(EquipmentBatch.objects.count(), 0, "Registro do lote não foi revertido.")
        self.model.refresh_from_db()
        self.assertEqual(self.model.last_sequence, 0, "Contador de sequência não foi revertido.")

    def test_subsequent_batch_after_a_rollback_starts_from_the_correct_sequence(self):
        """Depois de uma falha revertida, o próximo lote/cadastro não pode repetir nem pular números."""
        real_create_equipment = services_module.create_equipment
        call_count = {"n": 0}

        def flaky_create_equipment(data):
            call_count["n"] += 1
            if call_count["n"] == 3:
                raise RuntimeError("Falha simulada.")
            return real_create_equipment(data)

        with mock.patch("apps.equipment.services.create_equipment", side_effect=flaky_create_equipment), self.assertRaises(RuntimeError):
            create_equipment_batch(NewEquipmentBatchData(model_id=self.model.pk, quantity=5, created_by=self.user))

        batch = create_equipment_batch(
            NewEquipmentBatchData(model_id=self.model.pk, quantity=3, created_by=self.user)
        )
        self.assertEqual(batch.first_patrimonio, "LOC-NI23BT-0001")
        self.assertEqual(batch.last_patrimonio, "LOC-NI23BT-0003")


class BatchCreationConcurrencyTest(TransactionTestCase):
    """
    Mesma exigência de `test_patrimonio_generation.py` (seção 8), agora
    também para o cadastro em lote: `TransactionTestCase` com threads e
    conexões reais e independentes — `TestCase` mascararia justamente o
    tipo de corrida que este teste existe para pegar.
    """

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        self.user = User.objects.create_user(username="lote_concorrencia", password="senha-forte-123")

    def test_concurrent_batches_of_the_same_model_never_duplicate_or_skip_sequence(self):
        """3 threads criando lotes de 5 unidades cada, simultaneamente, do MESMO modelo."""
        n_batches = 3
        units_per_batch = 5
        results: list[list[str]] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker():
            try:
                batch = create_equipment_batch(
                    NewEquipmentBatchData(model_id=self.model.pk, quantity=units_per_batch, created_by=self.user)
                )
                patrimonios = list(Equipment.objects.filter(batch=batch).values_list("patrimonio", flat=True))
                with lock:
                    results.append(patrimonios)
            except Exception as exc:  # pragma: no cover - só para diagnóstico do teste
                with lock:
                    errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(n_batches)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Erros durante a concorrência: {errors}")
        self.assertEqual(len(results), n_batches)

        all_patrimonios = [p for batch_result in results for p in batch_result]
        self.assertEqual(len(all_patrimonios), n_batches * units_per_batch)
        self.assertEqual(len(set(all_patrimonios)), n_batches * units_per_batch, "Patrimônios duplicados entre lotes concorrentes!")

        expected = {f"LOC-NI23BT-{i:04d}" for i in range(1, n_batches * units_per_batch + 1)}
        self.assertEqual(set(all_patrimonios), expected, "Sequência final tem lacunas ou números fora do esperado.")

        self.model.refresh_from_db()
        self.assertEqual(self.model.last_sequence, n_batches * units_per_batch)

    def test_batch_and_individual_creation_of_the_same_model_never_collide(self):
        """Um lote e cadastros individuais do MESMO modelo, disparados ao mesmo tempo."""
        results: list[str] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def batch_worker():
            try:
                batch = create_equipment_batch(
                    NewEquipmentBatchData(model_id=self.model.pk, quantity=5, created_by=self.user)
                )
                patrimonios = list(Equipment.objects.filter(batch=batch).values_list("patrimonio", flat=True))
                with lock:
                    results.extend(patrimonios)
            except Exception as exc:  # pragma: no cover
                with lock:
                    errors.append(exc)
            finally:
                connection.close()

        def individual_worker():
            try:
                equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.user))
                with lock:
                    results.append(equipment.patrimonio)
            except Exception as exc:  # pragma: no cover
                with lock:
                    errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=batch_worker)] + [
            threading.Thread(target=individual_worker) for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Erros durante a concorrência: {errors}")
        self.assertEqual(len(results), 10)
        self.assertEqual(len(set(results)), 10, "Patrimônios duplicados entre lote e cadastro individual concorrentes!")

        self.model.refresh_from_db()
        self.assertEqual(self.model.last_sequence, 10)
