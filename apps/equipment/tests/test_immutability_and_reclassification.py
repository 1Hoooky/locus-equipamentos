"""
Testes da regra de imutabilidade e do procedimento de reclassificação —
especificação, seção 8 ("Imutabilidade e reclassificação de modelo").
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import NewEquipmentData, create_equipment, reclassify_model, supersede_equipment

User = get_user_model()


class PatrimonioImmutabilityTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        self.user = User.objects.create_user(username="tester", password="senha-forte-123")
        self.equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.user))

    def test_editing_patrimonio_directly_is_rejected(self):
        self.equipment.patrimonio = "LOC-NI23BT-9999"
        with self.assertRaises(ValidationError):
            self.equipment.full_clean()

    def test_editing_model_sequence_directly_is_rejected(self):
        self.equipment.model_sequence = 999
        with self.assertRaises(ValidationError):
            self.equipment.full_clean()

    def test_reclassify_model_keeps_patrimonio(self):
        wrong_patrimonio = self.equipment.patrimonio
        other_model = EquipmentModel.objects.create(category=self.category, name="NI23 Tanque Caixa", code="NI23TC")

        updated = reclassify_model(
            equipment=self.equipment, new_model=other_model, reason="Cadastrado com o modelo errado.", changed_by=self.user
        )

        self.assertEqual(updated.patrimonio, wrong_patrimonio, "Reclassificação não deve alterar o patrimônio.")
        self.assertEqual(updated.model_id, other_model.pk)
        self.assertEqual(updated.category_id, other_model.category_id)

    def test_reclassify_model_requires_reason(self):
        other_model = EquipmentModel.objects.create(category=self.category, name="NI23 Tanque Suporte", code="NI23TS")
        with self.assertRaises(ValueError):
            reclassify_model(equipment=self.equipment, new_model=other_model, reason="   ", changed_by=self.user)

    def test_supersede_equipment_creates_new_patrimonio_and_inactivates_old(self):
        old_patrimonio = self.equipment.patrimonio
        heater_category = Category.objects.create(name="Aquecedor")
        correct_model = EquipmentModel.objects.create(category=heater_category, name="Aquecedor Pirâmide", code="AQCP")

        new_equipment = supersede_equipment(
            equipment=self.equipment,
            new_model=correct_model,
            reason="Categoria errada, precisa reimprimir etiqueta.",
            changed_by=self.user,
        )

        self.equipment.refresh_from_db()
        self.assertFalse(self.equipment.is_active)
        self.assertEqual(self.equipment.superseded_by_id, new_equipment.pk)
        self.assertEqual(self.equipment.patrimonio, old_patrimonio, "O patrimônio antigo nunca é reescrito.")
        self.assertTrue(new_equipment.patrimonio.startswith("LOC-AQCP-"))
        self.assertNotEqual(new_equipment.patrimonio, old_patrimonio)


class EquipmentModelCodeLockTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="9 Pro", code="9PRO")
        self.user = User.objects.create_user(username="tester2", password="senha-forte-123")

    def test_code_editable_before_any_equipment_exists(self):
        self.model.code = "9PROX"
        self.model.full_clean()  # não deve levantar

    def test_code_locked_after_first_equipment(self):
        create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.user))
        self.model.refresh_from_db()

        self.model.code = "9PROX"
        with self.assertRaises(ValidationError):
            self.model.full_clean()
