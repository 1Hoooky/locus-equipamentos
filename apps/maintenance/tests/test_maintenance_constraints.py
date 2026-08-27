"""
Constraint de banco `uniq_maintenance_aberta_ativa_por_equipamento`
(ajuste de 27/08/2026, decisão 4): só uma `Maintenance` ATIVA
(`is_active=True`) E `ABERTA` bloqueia outra. Uma ficha ABERTA porém
INATIVA (soft-deletada) nunca deve prender o equipamento indefinidamente
atrás de uma constraint de banco.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.equipment.models import Status
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.maintenance.models import Maintenance, MaintenanceStatus, MaintenanceType
from apps.maintenance.services import NewMaintenanceData, open_maintenance

User = get_user_model()


class MaintenanceConstraintTestBase(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Compressor")
        model = EquipmentModel.objects.create(category=category, name="Compressor XT", code="COXT")
        self.tecnico = User.objects.create_user(username="tecnico_ct", password="senha-forte-123", role="OPERACIONAL")
        self.admin = User.objects.create_user(username="admin_ct", password="senha-forte-123", role="ADMIN")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))


class MaintenanceAtivaAbertaBloqueiaSegundaTest(MaintenanceConstraintTestBase):
    def test_banco_rejeita_segunda_maintenance_ativa_aberta(self):
        open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type=MaintenanceType.CORRETIVA,
                responsible=self.tecnico,
                created_by=self.tecnico,
            )
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Maintenance.objects.create(
                    equipment=self.equipment,
                    maintenance_type=MaintenanceType.CORRETIVA,
                    status=MaintenanceStatus.ABERTA,
                    is_active=True,
                    status_before=Status.DISPONIVEL,
                    responsible=self.tecnico,
                    created_by=self.tecnico,
                )


class MaintenanceAbertaInativaNaoBloqueiaTest(MaintenanceConstraintTestBase):
    def test_maintenance_aberta_porem_inativa_nao_bloqueia_nova_ativa(self):
        primeira = open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type=MaintenanceType.CORRETIVA,
                responsible=self.tecnico,
                created_by=self.tecnico,
            )
        )
        # Simula soft-delete direto (nenhum service expõe isto ainda — só
        # o inerente de SoftDeleteModel/is_active, testado no nível certo:
        # o banco, não um caminho de service que não existe nesta etapa).
        primeira.is_active = False
        primeira.save(update_fields=["is_active"])

        # Não pode existir service para abrir uma segunda enquanto o
        # equipamento segue com status MANUTENCAO (a primeira nunca fechou
        # de verdade) — então este teste confirma a constraint NO BANCO
        # diretamente, sem passar por open_maintenance() (que também
        # exigiria um status compatível, ortogonal ao que queremos provar
        # aqui: que a constraint em si não impede a segunda linha).
        segunda = Maintenance.objects.create(
            equipment=self.equipment,
            maintenance_type=MaintenanceType.CORRETIVA,
            status=MaintenanceStatus.ABERTA,
            is_active=True,
            status_before=Status.DISPONIVEL,
            responsible=self.tecnico,
            created_by=self.tecnico,
        )
        self.assertTrue(Maintenance.objects.filter(pk=segunda.pk, status=MaintenanceStatus.ABERTA, is_active=True).exists())
        self.assertEqual(
            Maintenance.objects.filter(equipment=self.equipment, status=MaintenanceStatus.ABERTA).count(), 2
        )
        self.assertEqual(
            Maintenance.objects.filter(equipment=self.equipment, status=MaintenanceStatus.ABERTA, is_active=True).count(), 1
        )

    def test_has_open_maintenance_ignora_ficha_inativa(self):
        from apps.maintenance.services import has_open_maintenance

        maintenance = open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type=MaintenanceType.CORRETIVA,
                responsible=self.tecnico,
                created_by=self.tecnico,
            )
        )
        self.assertTrue(has_open_maintenance(self.equipment))

        maintenance.is_active = False
        maintenance.save(update_fields=["is_active"])
        self.assertFalse(has_open_maintenance(self.equipment))
