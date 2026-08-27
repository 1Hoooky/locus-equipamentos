"""
Testes da limpeza TEMPORÁRIA de Locations duplicadas SEM referências
(`apps.operations.services.plan_duplicate_location_cleanup` /
`execute_duplicate_location_cleanup` e a view
`apps.operations.views.DuplicateLocationsCleanupView`).

Cenário real que motivou o pedido: no relatório de diagnóstico, a única
duplicata dos grupos de teste ("TESTE", "TESTE3", "teste2") com Movement
referenciando era a Location #2 "TESTE" — todas as demais estavam SEM
REFERÊNCIAS. Aqui replicamos esse mesmo formato (um grupo com uma
Location referenciada e outra não) sem depender do pk literal `2`, que é
específico do banco real e não é garantido em teste.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import Location, LocationType, MovementType
from apps.operations.services import (
    NewLocationData,
    NewMovementData,
    create_location,
    create_movement,
    execute_duplicate_location_cleanup,
    plan_duplicate_location_cleanup,
)

User = get_user_model()


def _equipment(created_by):
    category = Category.objects.create(name=f"Categoria {Category.objects.count()}")
    model = EquipmentModel.objects.create(category=category, name=f"Modelo {EquipmentModel.objects.count()}", code=f"MD{EquipmentModel.objects.count()}")
    return create_equipment(NewEquipmentData(model_id=model.pk, created_by=created_by))


class PlanDuplicateLocationCleanupTest(TestCase):
    """A função de domínio que calcula o plano — sem apagar nada."""

    def setUp(self):
        self.admin = User.objects.create_user(username="plan_admin", password="senha-forte-123", role="ADMIN")

    def test_only_target_group_names_are_considered(self):
        # Duplicata legítima fora do escopo ("Unidade Legítima") — mesmo
        # sem referência, NUNCA deve entrar no plano de limpeza.
        cliente = Client.objects.create(company_name="Cliente Fora Do Escopo LTDA")
        create_location(NewLocationData(name="Unidade Legítima", type=LocationType.CLIENTE, client=cliente))
        create_location(NewLocationData(name="Unidade Legítima", type=LocationType.CLIENTE, client=cliente))

        plan = plan_duplicate_location_cleanup()

        self.assertEqual(plan.to_remove, [])
        self.assertEqual(plan.preserved_with_references, [])

    def test_teste_group_with_one_referenced_and_one_unreferenced(self):
        """Reproduz o cenário real: grupo "TESTE" com uma Location #referenciada (preservada) e outra sem referência (candidata)."""
        cliente = Client.objects.create(company_name="Cliente Teste Plan LTDA")
        sem_ref = create_location(NewLocationData(name="TESTE", type=LocationType.CLIENTE, client=cliente))
        com_ref = create_location(NewLocationData(name="TESTE", type=LocationType.CLIENTE, client=cliente))
        equipment = _equipment(self.admin)
        create_movement(
            NewMovementData(
                equipment_id=equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.admin,
                destination_location=com_ref,
            )
        )

        plan = plan_duplicate_location_cleanup()

        self.assertEqual([c.location.pk for c in plan.to_remove], [sem_ref.pk])
        self.assertEqual([c.location.pk for c in plan.preserved_with_references], [com_ref.pk])

    def test_teste3_and_teste2_groups_are_also_in_scope(self):
        for name in ("TESTE3", "teste2"):
            with self.subTest(name=name):
                create_location(NewLocationData(name=name, type=LocationType.ESTOQUE))
                create_location(NewLocationData(name=name, type=LocationType.ESTOQUE))

        plan = plan_duplicate_location_cleanup()
        group_names = {c.group_name for c in plan.to_remove}
        self.assertEqual(group_names, {"TESTE3", "teste2"})


class ExecuteDuplicateLocationCleanupTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="exec_admin", password="senha-forte-123", role="ADMIN")

    def test_location_without_references_is_removed(self):
        sem_ref = create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))
        create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))  # completa o grupo (>1 ativa)

        report = execute_duplicate_location_cleanup(performed_by=self.admin)

        self.assertIn(sem_ref.pk, [loc.pk for loc in report.removed])
        sem_ref.refresh_from_db()
        self.assertFalse(sem_ref.is_active)

    def test_location_with_references_is_never_removed(self):
        """Representa a Location #2 "TESTE" do caso real: tem Movement referenciando, nunca pode ser apagada."""
        cliente = Client.objects.create(company_name="Cliente Teste Exec LTDA")
        com_ref = create_location(NewLocationData(name="TESTE", type=LocationType.CLIENTE, client=cliente))
        create_location(NewLocationData(name="TESTE", type=LocationType.CLIENTE, client=cliente))
        equipment = _equipment(self.admin)
        create_movement(
            NewMovementData(
                equipment_id=equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.admin,
                destination_location=com_ref,
            )
        )

        report = execute_duplicate_location_cleanup(performed_by=self.admin)

        self.assertNotIn(com_ref.pk, [loc.pk for loc in report.removed])
        self.assertIn(com_ref.pk, [loc.pk for loc in report.preserved_with_references])
        com_ref.refresh_from_db()
        self.assertTrue(com_ref.is_active)

    def test_location_that_gains_reference_between_plan_and_execution_is_skipped_not_removed(self):
        """Corrida: a Location era candidata no plano, mas ganhou uma Movement antes da execução de fato revalidar."""
        cliente = Client.objects.create(company_name="Cliente Teste Corrida LTDA")
        candidate = create_location(NewLocationData(name="TESTE", type=LocationType.CLIENTE, client=cliente))
        create_location(NewLocationData(name="TESTE", type=LocationType.CLIENTE, client=cliente))
        equipment = _equipment(self.admin)

        original_plan = plan_duplicate_location_cleanup
        # Simula a corrida: entre o cálculo do plano (dentro de execute_) e
        # a revalidação individual, uma Movement passa a referenciar a
        # Location candidata.
        def racy_plan():
            plan = original_plan()
            create_movement(
                NewMovementData(
                    equipment_id=equipment.pk,
                    movement_type=MovementType.INSTALACAO,
                    created_by=self.admin,
                    destination_location=candidate,
                )
            )
            return plan

        with patch("apps.operations.services.plan_duplicate_location_cleanup", side_effect=racy_plan):
            report = execute_duplicate_location_cleanup(performed_by=self.admin)

        self.assertNotIn(candidate.pk, [loc.pk for loc in report.removed])
        self.assertIn(candidate.pk, [loc.pk for loc in report.skipped_race])
        candidate.refresh_from_db()
        self.assertTrue(candidate.is_active)  # nunca apagada, apesar de ter sido candidata no plano

    def test_rollback_if_error_occurs_mid_loop(self):
        """Erro no meio do laço reverte TUDO — nenhuma remoção parcial fica gravada (transaction.atomic)."""
        loc_a = create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))
        loc_b = create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))
        loc_c = create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))

        original_save = Location.save
        calls = {"n": 0}

        def flaky_save(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("Falha simulada no meio da limpeza")
            return original_save(self, *args, **kwargs)

        with patch.object(Location, "save", flaky_save):
            with self.assertRaises(RuntimeError):
                execute_duplicate_location_cleanup(performed_by=self.admin)

        for loc in (loc_a, loc_b, loc_c):
            loc.refresh_from_db()
            self.assertTrue(loc.is_active, f"Location #{loc.pk} não deveria ter sido apagada após rollback.")

    def test_locations_outside_target_groups_are_untouched(self):
        cliente = Client.objects.create(company_name="Cliente Real LTDA")
        real1 = create_location(NewLocationData(name="Unidade Real", type=LocationType.CLIENTE, client=cliente))
        real2 = create_location(NewLocationData(name="Unidade Real", type=LocationType.CLIENTE, client=cliente))

        report = execute_duplicate_location_cleanup(performed_by=self.admin)

        self.assertEqual(report.removed, [])
        real1.refresh_from_db()
        real2.refresh_from_db()
        self.assertTrue(real1.is_active)
        self.assertTrue(real2.is_active)

    def test_internal_locations_are_never_touched(self):
        # "Estoque Locus"/"Manutenção Locus" (seed da migração 0003) nunca
        # podem ser tocadas por esta limpeza, mesmo hipoteticamente.
        estoque_interno = Location.objects.get(name="Estoque Locus")
        manutencao_interna = Location.objects.get(name="Manutenção Locus")

        create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))
        create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))

        execute_duplicate_location_cleanup(performed_by=self.admin)

        estoque_interno.refresh_from_db()
        manutencao_interna.refresh_from_db()
        self.assertTrue(estoque_interno.is_active)
        self.assertTrue(manutencao_interna.is_active)


class DuplicateLocationsCleanupPermissionTest(TestCase):
    URL = "/operacao/diagnostico/locations-duplicadas/limpar/"

    def setUp(self):
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            User.objects.create_user(username=f"cleanup_{role.lower()}", password="senha-forte-123", role=role)

    def test_only_admin_can_view_confirmation_screen(self):
        for role, expected in (("ADMIN", 200), ("ADMINISTRATIVO", 403), ("OPERACIONAL", 403), ("CONSULTA", 403)):
            with self.subTest(role=role):
                self.client.login(username=f"cleanup_{role.lower()}", password="senha-forte-123")
                response = self.client.get(self.URL)
                self.assertEqual(response.status_code, expected)
                self.client.logout()

    def test_only_admin_can_post_to_execute(self):
        # Token forjado (sem GET prévio) — para ADMIN isso é bloqueado como
        # reenvio inválido (302, nada é apagado, ver DuplicateLocationsCleanupHttpFlowTest);
        # para os demais perfis, a permissão barra ANTES disso, com 403.
        for role, expected in (("ADMIN", 302), ("ADMINISTRATIVO", 403), ("OPERACIONAL", 403), ("CONSULTA", 403)):
            with self.subTest(role=role):
                self.client.login(username=f"cleanup_{role.lower()}", password="senha-forte-123")
                response = self.client.post(self.URL, {"submission_token": "forjado"})
                self.assertEqual(response.status_code, expected)
                self.client.logout()

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.url)


class DuplicateLocationsCleanupHttpFlowTest(TestCase):
    URL = "/operacao/diagnostico/locations-duplicadas/limpar/"

    def setUp(self):
        self.admin = User.objects.create_user(username="flow_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="flow_admin", password="senha-forte-123")

    def test_post_without_prior_confirmation_get_is_blocked_and_removes_nothing(self):
        sem_ref = create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))
        create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))

        # POST direto, sem nunca ter feito o GET de confirmação — não há
        # token válido na sessão, então nada pode ser apagado.
        response = self.client.post(self.URL, {"submission_token": "qualquer-coisa"})

        self.assertEqual(response.status_code, 302)
        sem_ref.refresh_from_db()
        self.assertTrue(sem_ref.is_active)
        self.assertEqual(Location.objects.filter(name="TESTE", is_active=True).count(), 2)

    def test_post_with_wrong_token_after_get_is_blocked(self):
        create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))
        create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))

        self.client.get(self.URL)  # emite o token real na sessão
        response = self.client.post(self.URL, {"submission_token": "token-errado"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Location.objects.filter(name="TESTE", is_active=True).count(), 2)

    def test_confirmation_screen_lists_exact_ids_before_anything_is_removed(self):
        sem_ref = create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))
        create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))

        response = self.client.get(self.URL)
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"#{sem_ref.pk}", content)
        # Nada foi apagado só de exibir a tela de confirmação.
        sem_ref.refresh_from_db()
        self.assertTrue(sem_ref.is_active)

    def test_full_confirm_flow_removes_only_the_safe_location_and_reports_correctly(self):
        cliente = Client.objects.create(company_name="Cliente Teste HTTP LTDA")
        sem_ref = create_location(NewLocationData(name="TESTE", type=LocationType.CLIENTE, client=cliente))
        com_ref = create_location(NewLocationData(name="TESTE", type=LocationType.CLIENTE, client=cliente))
        equipment = _equipment(self.admin)
        create_movement(
            NewMovementData(
                equipment_id=equipment.pk,
                movement_type=MovementType.INSTALACAO,
                created_by=self.admin,
                destination_location=com_ref,
            )
        )

        token = self.client.get(self.URL).context["submission_token"]
        response = self.client.post(self.URL, {"submission_token": token})
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"#{sem_ref.pk}", content)  # removida — aparece na lista de removidas
        self.assertIn(f"#{com_ref.pk}", content)  # preservada — aparece na lista de preservadas

        sem_ref.refresh_from_db()
        com_ref.refresh_from_db()
        self.assertFalse(sem_ref.is_active)
        self.assertTrue(com_ref.is_active)

    def test_reusing_the_same_token_twice_only_executes_once(self):
        create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))
        create_location(NewLocationData(name="TESTE", type=LocationType.ESTOQUE))

        token = self.client.get(self.URL).context["submission_token"]
        first = self.client.post(self.URL, {"submission_token": token})
        second = self.client.post(self.URL, {"submission_token": token})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 302)  # reenvio — bloqueado, sem token válido de novo
