"""
Testes da ferramenta TEMPORÁRIA de diagnóstico "Locations duplicadas"
(`apps.operations.services.find_duplicate_location_groups`,
`apps.operations.management.commands.report_duplicate_locations` e
`apps.operations.views.DuplicateLocationsReportView`) — criada porque o
Render Free não dá acesso a Shell.

Cobre: (1) a função de domínio compartilhada retorna os grupos/contagens
corretos; (2) o management command continua funcionando após o refactor
(reaproveita a mesma função, não uma cópia); (3) a matriz de permissões da
tela HTTP — só Administrador; (4) o conteúdo renderizado tem todos os
campos pedidos e a marcação SEM/COM REFERÊNCIAS correta; (5) a tela não
expõe NENHUMA ação destrutiva (sem POST, sem link de apagar/editar/
consolidar).
"""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.clients.models import Client
from apps.operations.models import Location, LocationType, MovementType
from apps.operations.services import (
    NewLocationData,
    NewMovementData,
    create_location,
    create_movement,
    find_duplicate_location_groups,
)

User = get_user_model()


class FindDuplicateLocationGroupsTest(TestCase):
    """A função de domínio reaproveitada pelo command e pela view."""

    def test_no_duplicates_returns_empty_list(self):
        create_location(NewLocationData(name="Estoque Único", type=LocationType.ESTOQUE))
        self.assertEqual(find_duplicate_location_groups(), [])

    def test_same_name_different_clients_is_not_a_duplicate(self):
        # Decisão de projeto: sem UNIQUE(name) — unidades homônimas de
        # clientes DIFERENTES são legítimas e não entram no relatório.
        cliente_a = Client.objects.create(company_name="Cliente A LTDA")
        cliente_b = Client.objects.create(company_name="Cliente B LTDA")
        create_location(NewLocationData(name="Unidade Homônima", type=LocationType.CLIENTE, client=cliente_a))
        create_location(NewLocationData(name="Unidade Homônima", type=LocationType.CLIENTE, client=cliente_b))
        self.assertEqual(find_duplicate_location_groups(), [])

    def test_same_name_type_client_twice_is_one_group_with_two_entries(self):
        cliente = Client.objects.create(company_name="Cliente Duplicado LTDA")
        loc1 = create_location(NewLocationData(name="Unidade Repetida", type=LocationType.CLIENTE, client=cliente))
        loc2 = create_location(NewLocationData(name="Unidade Repetida", type=LocationType.CLIENTE, client=cliente))

        groups = find_duplicate_location_groups()

        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group.name, "Unidade Repetida")
        self.assertEqual(group.type, LocationType.CLIENTE)
        self.assertEqual(group.owner_label, cliente.display_name())
        self.assertEqual([entry.location.pk for entry in group.entries], [loc1.pk, loc2.pk])

    def test_inactive_duplicate_is_excluded(self):
        cliente = Client.objects.create(company_name="Cliente Inativo Dup LTDA")
        create_location(NewLocationData(name="Unidade X", type=LocationType.CLIENTE, client=cliente))
        segunda = create_location(NewLocationData(name="Unidade X", type=LocationType.CLIENTE, client=cliente))
        segunda.is_active = False
        segunda.save(update_fields=["is_active"])

        self.assertEqual(find_duplicate_location_groups(), [])

    def test_movement_reference_counts_and_marker(self):
        admin = User.objects.create_user(username="dup_ref_admin", password="senha-forte-123", role="ADMIN")
        from apps.catalog.models import Category, EquipmentModel
        from apps.equipment.services import NewEquipmentData, create_equipment

        cliente = Client.objects.create(company_name="Cliente Ref LTDA")
        sem_ref = create_location(NewLocationData(name="Unidade Ref", type=LocationType.CLIENTE, client=cliente))
        com_ref = create_location(NewLocationData(name="Unidade Ref", type=LocationType.CLIENTE, client=cliente))

        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Dup", code="AQDP")
        equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=admin))
        create_movement(
            NewMovementData(
                equipment_id=equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=admin,
                destination_location=com_ref,
            )
        )

        groups = find_duplicate_location_groups()
        self.assertEqual(len(groups), 1)
        entries_by_pk = {entry.location.pk: entry for entry in groups[0].entries}

        sem_ref_entry = entries_by_pk[sem_ref.pk]
        self.assertEqual(sem_ref_entry.movements_as_origin, 0)
        self.assertEqual(sem_ref_entry.movements_as_destination, 0)
        self.assertFalse(sem_ref_entry.has_references)

        com_ref_entry = entries_by_pk[com_ref.pk]
        self.assertEqual(com_ref_entry.movements_as_destination, 1)
        self.assertEqual(com_ref_entry.movements_as_origin, 0)
        self.assertTrue(com_ref_entry.has_references)


class ReportDuplicateLocationsCommandTest(TestCase):
    """O command continua funcionando (mesma saída) depois do refactor para reaproveitar a função de serviço."""

    def test_no_duplicates_prints_success_message(self):
        out = StringIO()
        call_command("report_duplicate_locations", stdout=out)
        self.assertIn("Nenhuma Location duplicada encontrada.", out.getvalue())

    def test_duplicates_are_listed_with_marker(self):
        cliente = Client.objects.create(company_name="Cliente Command LTDA")
        loc1 = create_location(NewLocationData(name="Unidade Command", type=LocationType.CLIENTE, client=cliente))
        loc2 = create_location(NewLocationData(name="Unidade Command", type=LocationType.CLIENTE, client=cliente))

        out = StringIO()
        call_command("report_duplicate_locations", stdout=out)
        output = out.getvalue()

        self.assertIn("1 grupo(s) de duplicatas encontrados", output)
        self.assertIn(f"Location #{loc1.pk}", output)
        self.assertIn(f"Location #{loc2.pk}", output)
        self.assertIn("sem referências", output)
        self.assertIn("Nada foi apagado.", output)


class DuplicateLocationsReportViewPermissionTest(TestCase):
    URL = "/operacao/diagnostico/locations-duplicadas/"

    def setUp(self):
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            User.objects.create_user(username=f"diag_{role.lower()}", password="senha-forte-123", role=role)

    def test_only_admin_can_access(self):
        for role, expected in (("ADMIN", 200), ("ADMINISTRATIVO", 403), ("OPERACIONAL", 403), ("CONSULTA", 403)):
            with self.subTest(role=role):
                self.client.login(username=f"diag_{role.lower()}", password="senha-forte-123")
                response = self.client.get(self.URL)
                self.assertEqual(response.status_code, expected)
                self.client.logout()

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.url)

    def test_post_is_not_allowed(self):
        # Somente-leitura: nem o próprio Admin pode enviar POST para esta
        # tela — não existe nenhuma ação de escrita aqui.
        self.client.login(username="diag_admin", password="senha-forte-123")
        response = self.client.post(self.URL)
        self.assertEqual(response.status_code, 405)


class DuplicateLocationsReportViewContentTest(TestCase):
    URL = "/operacao/diagnostico/locations-duplicadas/"

    def setUp(self):
        User.objects.create_user(username="diag_content_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="diag_content_admin", password="senha-forte-123")

    def test_no_duplicates_shows_empty_state(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nenhuma Location duplicada encontrada.")

    def test_duplicate_group_renders_required_fields_and_sem_referencias_marker(self):
        cliente = Client.objects.create(company_name="Cliente Tela LTDA")
        loc1 = create_location(NewLocationData(name="Unidade Tela", type=LocationType.CLIENTE, client=cliente))
        loc2 = create_location(NewLocationData(name="Unidade Tela", type=LocationType.CLIENTE, client=cliente))

        response = self.client.get(self.URL)
        content = response.content.decode()

        for location in (loc1, loc2):
            self.assertIn(f"#{location.pk}", content)
            self.assertIn(location.created_at.strftime("%d/%m/%Y"), content)
        self.assertIn("Unidade Tela", content)
        self.assertIn(cliente.display_name(), content)
        self.assertIn("Cliente", content)  # get_type_display()
        self.assertIn("SEM REFERÊNCIAS", content)
        # A explicação textual no rodapé da página menciona "COM REFERÊNCIAS"
        # em prosa mesmo quando nenhuma Location do grupo tem referência —
        # o que importa é que o BADGE vermelho (bg-red-100) não apareça.
        self.assertNotIn("bg-red-100", content)

    def test_referenced_location_shows_com_referencias_marker_and_counts(self):
        admin = User.objects.get(username="diag_content_admin")
        from apps.catalog.models import Category, EquipmentModel
        from apps.equipment.services import NewEquipmentData, create_equipment

        cliente = Client.objects.create(company_name="Cliente Tela Ref LTDA")
        create_location(NewLocationData(name="Unidade Tela Ref", type=LocationType.CLIENTE, client=cliente))
        com_ref = create_location(NewLocationData(name="Unidade Tela Ref", type=LocationType.CLIENTE, client=cliente))

        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Tela", code="AQTE")
        equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=admin))
        create_movement(
            NewMovementData(
                equipment_id=equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=admin,
                destination_location=com_ref,
            )
        )

        response = self.client.get(self.URL)
        content = response.content.decode()
        self.assertIn("COM REFERÊNCIAS", content)
        self.assertIn("SEM REFERÊNCIAS", content)  # a outra Location do grupo continua sem referências

    def test_page_exposes_no_destructive_action(self):
        cliente = Client.objects.create(company_name="Cliente Sem Ação LTDA")
        create_location(NewLocationData(name="Unidade Sem Ação", type=LocationType.CLIENTE, client=cliente))
        create_location(NewLocationData(name="Unidade Sem Ação", type=LocationType.CLIENTE, client=cliente))

        response = self.client.get(self.URL)
        content = response.content.decode()

        # O único <form> da página inteira é o "Sair" do cabeçalho global
        # (base.html, presente em TODA página do sistema) — o conteúdo da
        # tela de diagnóstico em si não tem nenhum form, método POST/DELETE
        # ou link/rótulo de apagar/editar/consolidar.
        self.assertEqual(content.count("<form"), 1)
        self.assertIn('action="/contas/logout/"', content)
        # "Remover" fica de fora da lista: aparece só na prosa explicando que
        # esta TELA (o código) será removida depois da limpeza — não é uma
        # ação oferecida ao usuário nesta página.
        for forbidden in ("Apagar", "Excluir", "Deletar", "Editar", "Consolidar"):
            self.assertNotIn(forbidden, content)
        self.assertEqual(content.count("<button"), 1)  # só o botão "Sair" do cabeçalho global


class DuplicateLocationsReportRegressionTest(TestCase):
    """Blindagem extra: `Location.objects.count()` e a lista de Unidades continuam intactos — a tela é só leitura."""

    def test_viewing_the_report_does_not_change_location_count(self):
        User.objects.create_user(username="diag_regression_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="diag_regression_admin", password="senha-forte-123")
        cliente = Client.objects.create(company_name="Cliente Regressão LTDA")
        create_location(NewLocationData(name="Unidade Regressão", type=LocationType.CLIENTE, client=cliente))
        create_location(NewLocationData(name="Unidade Regressão", type=LocationType.CLIENTE, client=cliente))

        before = Location.objects.count()
        self.client.get("/operacao/diagnostico/locations-duplicadas/")
        after = Location.objects.count()

        self.assertEqual(before, after)
