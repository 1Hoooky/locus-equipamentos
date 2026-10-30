"""
Testes do `LocationAdmin` — P0-05/OPS-001 (especificação de implementação,
pontos 6 e 11): o admin do Django NÃO pode ser um segundo caminho de
escrita que altera `client`/`type` de uma `Location` com `Equipment`
presente sem passar pela MESMA regra aplicada por `update_location()`.

Usa o `Client` de testes do Django contra as URLs reais do admin
(`/admin/operations/location/<pk>/change/`), não chama
`LocationAdmin.save_model()` diretamente — cobre o fluxo ponta a ponta,
inclusive a mensagem de erro amigável (nunca um traceback/500 cru).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import LocationType, MovementType
from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

User = get_user_model()


class LocationAdminBypassTest(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="admin_p0_05", email="admin_p0_05@example.com", password="senha-forte-123"
        )
        self.client.force_login(self.admin_user)

        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Admin", code="AQAD")
        self.operador = User.objects.create_user(
            username="operador_admin_p0_05", password="senha-forte-123", role="OPERACIONAL"
        )

        self.cliente_a = Client.objects.create(company_name="Cliente Admin A LTDA")
        self.cliente_b = Client.objects.create(company_name="Cliente Admin B LTDA")
        self.unidade = create_location(
            NewLocationData(name="Unidade Admin A", type=LocationType.CLIENTE, client=self.cliente_a)
        )
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.operador))
        create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.operador,
                destination_location=self.unidade,
            )
        )
        self.equipment.refresh_from_db()

    def _change_url(self, pk):
        return reverse("admin:operations_location_change", args=[pk])

    def _post_change(self, location, **overrides):
        data = {
            "name": location.name,
            "type": location.type,
            "client": location.client_id or "",
            "address": location.address_id or "",
            "is_active": "on",
        }
        data.update(overrides)
        return self.client.post(self._change_url(location.pk), data, follow=True)

    def test_admin_cannot_change_client_while_equipment_present(self):
        response = self._post_change(self.unidade, client=self.cliente_b.pk)

        self.unidade.refresh_from_db()
        self.equipment.refresh_from_db()
        self.assertEqual(self.unidade.client_id, self.cliente_a.pk)
        self.assertEqual(self.equipment.current_client_id, self.cliente_a.pk)
        self.assertContains(response, "Movimente os equipamentos primeiro")

    def test_admin_cannot_change_type_while_equipment_present(self):
        response = self._post_change(self.unidade, type=LocationType.ESTOQUE, client="")

        self.unidade.refresh_from_db()
        self.equipment.refresh_from_db()
        self.assertEqual(self.unidade.type, LocationType.CLIENTE)
        self.assertEqual(self.unidade.client_id, self.cliente_a.pk)
        self.assertEqual(self.equipment.current_location_id, self.unidade.pk)
        self.assertContains(response, "Movimente os equipamentos primeiro")

    def test_admin_can_still_rename_location_with_equipment_present(self):
        self._post_change(self.unidade, name="Unidade Admin A Renomeada")

        self.unidade.refresh_from_db()
        self.assertEqual(self.unidade.name, "Unidade Admin A Renomeada")
        # client/type continuam intocados — só o nome mudou.
        self.assertEqual(self.unidade.client_id, self.cliente_a.pk)
        self.assertEqual(self.unidade.type, LocationType.CLIENTE)

    def test_admin_can_change_client_when_location_has_no_equipment(self):
        vazia = create_location(
            NewLocationData(name="Unidade Admin Vazia", type=LocationType.CLIENTE, client=self.cliente_a)
        )

        self._post_change(vazia, client=self.cliente_b.pk)

        vazia.refresh_from_db()
        self.assertEqual(vazia.client_id, self.cliente_b.pk)

    def test_admin_rejection_does_not_create_misleading_history_entry(self):
        """
        `update_location()` recusou — nenhum `save()` estrutural ocorreu —
        então o admin não deve registrar um LogEntry "Changed client and
        type" para algo que, de fato, não mudou (ponto 7 da especificação:
        a pessoa precisa ver o estado real, nunca uma mensagem
        contraditória "alterado com sucesso" + erro).
        """
        from django.contrib.admin.models import LogEntry

        before = LogEntry.objects.count()
        self._post_change(self.unidade, client=self.cliente_b.pk)
        after = LogEntry.objects.count()
        self.assertEqual(before, after)
