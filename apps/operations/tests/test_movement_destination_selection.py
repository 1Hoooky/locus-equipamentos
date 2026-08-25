"""
Regressão dos bugs relatados #4 e #5 (seleção de destino na tela de
movimentação) e cobertura HTTP do #7 (transferência para a mesma unidade).

#4 — o select de destino mostrava só `location.name` (ex.: "Maringá"),
insuficiente porque clientes diferentes podem ter unidades com o mesmo
nome: destinos do tipo Cliente agora aparecem como "Cliente — Unidade".

#5 — o select oferecia todos os destinos ativos, inclusive tipos
incompatíveis com o `movement_type` escolhido (ex.: unidades de cliente
para "Retirada"). A queryset do form agora é filtrada pelo tipo já
submetido — testado aqui tanto pelo HTML renderizado quanto pela rejeição
de um destino incompatível manipulado direto no POST (antes mesmo de
chegar no service).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import LocationType, Movement, MovementType
from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

User = get_user_model()


class MovementDestinationSelectionTestBase(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Seleção", code="AQSL")
        self.user = User.objects.create_user(username="selecao_operador", password="senha-forte-123", role="OPERACIONAL")
        self.client.login(username="selecao_operador", password="senha-forte-123")

        self.estoque = create_location(NewLocationData(name="Estoque Central", type=LocationType.ESTOQUE))
        self.manutencao = create_location(NewLocationData(name="Oficina Parceira", type=LocationType.MANUTENCAO))

        self.modema = Client.objects.create(company_name="Modema Automóveis LTDA", trade_name="Modema Automóveis")
        self.unidade_modema = create_location(
            NewLocationData(name="Maringá", type=LocationType.CLIENTE, client=self.modema)
        )
        self.outro_cliente = Client.objects.create(company_name="Outra Empresa LTDA", trade_name="Outra Empresa")
        # Mesmo nome de unidade que a de "Modema" — prova real do bug #4:
        # sem qualificar pelo cliente, as duas ficam indistinguíveis.
        self.unidade_outro_cliente = create_location(
            NewLocationData(name="Maringá", type=LocationType.CLIENTE, client=self.outro_cliente)
        )

        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.user))


class DestinationLabelShowsClientAndUnitTest(MovementDestinationSelectionTestBase):
    """Bug #4: destinos do tipo Cliente mostram 'Cliente — Unidade', não só o nome da unidade."""

    def test_form_page_shows_client_qualified_labels_for_client_locations(self):
        response = self.client.get(f"/operacao/movimentar/{self.equipment.patrimonio}/")
        content = response.content.decode()

        self.assertIn("Modema Automóveis — Maringá", content)
        self.assertIn("Outra Empresa — Maringá", content)
        # As duas unidades homônimas precisam estar visualmente distintas —
        # "Maringá" sozinho (sem o cliente na frente) não pode aparecer
        # como TEXTO COMPLETO de uma opção (checagem por ">Maringá<" exato,
        # não substring — "...— Maringá</option>" contém "Maringá<" mas
        # não ">Maringá<").
        self.assertNotIn(">Maringá<", content)

    def test_non_client_destination_keeps_plain_name(self):
        response = self.client.get(f"/operacao/movimentar/{self.equipment.patrimonio}/")
        content = response.content.decode()
        self.assertIn("Estoque Central", content)


class DestinationFilteredByMovementTypeTest(MovementDestinationSelectionTestBase):
    """Bug #5: o select de destino só oferece localizações compatíveis com o tipo de movimentação."""

    def test_initial_page_load_offers_all_active_destinations_for_js_to_refine(self):
        """
        Carregamento inicial (form NÃO vinculado, GET): ainda não há
        `movement_type` submetido, então a queryset mantém todos os
        destinos ativos — é o JS do template (movement_form.html) que
        refina a exibição para o tipo pré-selecionado assim que a página
        carrega, e que re-filtra ao trocar de tipo. Filtrar demais já no
        GET (server-side) deixaria o JS sem opções para re-exibir depois
        de trocar de tipo (o `<select>` só teria os options já filtrados).
        A filtragem que garante SEGURANÇA é a de `action=POST`, coberta
        pelos testes abaixo.
        """
        response = self.client.get(f"/operacao/movimentar/{self.equipment.patrimonio}/")
        queryset = response.context["form"].fields["destination_location"].queryset
        self.assertIn(self.unidade_modema, queryset)
        self.assertIn(self.unidade_outro_cliente, queryset)
        self.assertIn(self.estoque, queryset)
        self.assertIn(self.manutencao, queryset)

    def test_posting_retirada_filters_queryset_to_estoque_locations(self):
        create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.user,
                destination_location=self.unidade_modema,
            )
        )
        response = self.client.post(
            f"/operacao/movimentar/{self.equipment.patrimonio}/",
            {"movement_type": MovementType.RETIRADA, "destination_location": self.unidade_modema.pk, "reason": ""},
        )
        # Destino incompatível (unidade de cliente) rejeitado JÁ NO FORM —
        # nem chega a chamar o service.
        self.assertEqual(response.status_code, 200)
        self.assertIn("destination_location", response.context["form"].errors)
        self.assertFalse(Movement.objects.filter(movement_type=MovementType.RETIRADA).exists())

    def test_posting_retirada_with_compatible_estoque_destination_succeeds(self):
        create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.user,
                destination_location=self.unidade_modema,
            )
        )
        response = self.client.post(
            f"/operacao/movimentar/{self.equipment.patrimonio}/",
            {"movement_type": MovementType.RETIRADA, "destination_location": self.estoque.pk, "reason": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Movement.objects.filter(movement_type=MovementType.RETIRADA).exists())

    def test_manipulated_post_with_manutencao_location_for_instalacao_is_rejected_by_form(self):
        """Mesmo manipulando o POST direto (sem passar pelo select), o form rejeita — não é só o service que protege."""
        response = self.client.post(
            f"/operacao/movimentar/{self.equipment.patrimonio}/",
            {"movement_type": MovementType.INSTALACAO, "destination_location": self.manutencao.pk, "reason": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("destination_location", response.context["form"].errors)
        self.assertFalse(Movement.objects.exists())


class TransferToSameLocationHttpTest(MovementDestinationSelectionTestBase):
    """Cobertura HTTP do bug #7 — 'Unidade 1 → Unidade 1' via TRANSFERENCIA."""

    def setUp(self):
        super().setUp()
        create_movement(
            NewMovementData(
                equipment_id=self.equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.user,
                destination_location=self.unidade_modema,
            )
        )

    def test_current_location_is_excluded_from_destination_queryset(self):
        response = self.client.post(
            f"/operacao/movimentar/{self.equipment.patrimonio}/",
            {"movement_type": MovementType.TRANSFERENCIA, "destination_location": "", "reason": ""},
        )
        queryset = response.context["form"].fields["destination_location"].queryset
        self.assertNotIn(self.unidade_modema, queryset)
        self.assertIn(self.unidade_outro_cliente, queryset)

    def test_transferencia_to_same_unit_is_rejected_via_http(self):
        response = self.client.post(
            f"/operacao/movimentar/{self.equipment.patrimonio}/",
            {
                "movement_type": MovementType.TRANSFERENCIA,
                "destination_location": self.unidade_modema.pk,
                "reason": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertTrue(
            "já está nesta unidade" in content or "destination_location" in response.context["form"].errors
        )
        self.assertFalse(Movement.objects.filter(movement_type=MovementType.TRANSFERENCIA).exists())

    def test_transferencia_to_a_different_unit_still_works_via_http(self):
        response = self.client.post(
            f"/operacao/movimentar/{self.equipment.patrimonio}/",
            {
                "movement_type": MovementType.TRANSFERENCIA,
                "destination_location": self.unidade_outro_cliente.pk,
                "reason": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.current_location, self.unidade_outro_cliente)
