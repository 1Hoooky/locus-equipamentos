"""
Testes da limpeza TEMPORÁRIA de Locations duplicadas SEM referências, EM
LOTES pequenos (`apps.operations.services.plan_duplicate_location_cleanup`
/ `execute_duplicate_location_cleanup_batch` /
`count_duplicate_location_cleanup_processed_total` e a view
`apps.operations.views.DuplicateLocationsCleanupView`).

Pedido explícito do usuário: nada de `time.sleep()` dentro de uma
requisição/transação — cada POST processa no máximo
`DUPLICATE_CLEANUP_BATCH_SIZE` (5) Locations, numa transação curta e
independente, e responde imediatamente. Quem espaça os lotes (1-2s) é o
CLIENTE (botão "Processar próximos 5" ou auto-continuação via JS), nunca
o servidor. Se um lote falhar no meio, só ELE é revertido — lotes
anteriores, já commitados em requisições passadas, permanecem concluídos.

Cenário real que motivou o pedido: no relatório de diagnóstico, a única
duplicata dos grupos de teste ("TESTE", "TESTE3", "teste2") com Movement
referenciando era a Location "TESTE" citada pelo usuário como #2 — aqui
replicamos esse formato sem depender do pk literal `2`, que é específico
do banco real.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import Location, LocationType, MovementType
from apps.operations.services import (
    DUPLICATE_CLEANUP_BATCH_SIZE,
    NewLocationData,
    NewMovementData,
    count_duplicate_location_cleanup_processed_total,
    create_location,
    create_movement,
    execute_duplicate_location_cleanup_batch,
    plan_duplicate_location_cleanup,
)

User = get_user_model()


def _equipment(created_by):
    n = Category.objects.count()
    category = Category.objects.create(name=f"Categoria {n}")
    model = EquipmentModel.objects.create(category=category, name=f"Modelo {n}", code=f"MD{n}")
    return create_equipment(NewEquipmentData(model_id=model.pk, created_by=created_by))


def _teste_location(name="TESTE", client=None):
    if client is None:
        client = Client.objects.create(company_name=f"Cliente {name} {Location.objects.count()} LTDA")
    return create_location(NewLocationData(name=name, type=LocationType.CLIENTE, client=client))


class PlanDuplicateLocationCleanupTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="plan_admin", password="senha-forte-123", role="ADMIN")

    def test_only_target_group_names_are_considered(self):
        cliente = Client.objects.create(company_name="Cliente Fora Do Escopo LTDA")
        create_location(NewLocationData(name="Unidade Legítima", type=LocationType.CLIENTE, client=cliente))
        create_location(NewLocationData(name="Unidade Legítima", type=LocationType.CLIENTE, client=cliente))

        plan = plan_duplicate_location_cleanup()

        self.assertEqual(plan.to_remove, [])
        self.assertEqual(plan.preserved_with_references, [])

    def test_teste_group_with_one_referenced_and_one_unreferenced(self):
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
            create_location(NewLocationData(name=name, type=LocationType.ESTOQUE))

        plan = plan_duplicate_location_cleanup()
        group_names = {c.group_name for c in plan.to_remove}
        self.assertEqual(group_names, {"TESTE3", "teste2"})

    def test_referenced_survivor_stays_preserved_even_after_its_group_shrinks_to_one(self):
        """
        Regressão do motivo pelo qual o plano NÃO usa find_duplicate_location_groups()
        para a limpeza: depois que os outros membros do grupo "TESTE" são
        removidos, só sobra a Location referenciada — ela deixaria de ser
        "duplicata" (quantidade=1), mas TEM que continuar aparecendo como
        preservada, nunca sumir do relatório de progresso.
        """
        cliente = Client.objects.create(company_name="Cliente Sobrevivente LTDA")
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
        # Nenhuma outra Location "TESTE" nesta base — com_ref é a ÚNICA,
        # não forma "grupo duplicado" nenhum, mas ainda pertence ao
        # allowlist de nomes de teste.
        plan = plan_duplicate_location_cleanup()

        self.assertEqual(plan.to_remove, [])
        self.assertEqual([c.location.pk for c in plan.preserved_with_references], [com_ref.pk])

    def test_internal_locations_are_never_candidates(self):
        plan = plan_duplicate_location_cleanup()
        candidate_names = {c.location.name for c in plan.to_remove} | {c.location.name for c in plan.preserved_with_references}
        self.assertNotIn("Estoque Locus", candidate_names)
        self.assertNotIn("Manutenção Locus", candidate_names)


class ExecuteDuplicateLocationCleanupBatchTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="batch_admin", password="senha-forte-123", role="ADMIN")

    def test_location_without_references_is_removed(self):
        sem_ref = _teste_location()

        report = execute_duplicate_location_cleanup_batch(performed_by=self.admin)

        self.assertIn(sem_ref.pk, [loc.pk for loc in report.removed])
        sem_ref.refresh_from_db()
        self.assertFalse(sem_ref.is_active)

    def test_location_with_references_is_never_removed(self):
        """Representa a Location "TESTE" #2 do caso real: tem Movement referenciando, nunca é apagada."""
        cliente = Client.objects.create(company_name="Cliente Teste Exec LTDA")
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

        report = execute_duplicate_location_cleanup_batch(performed_by=self.admin)

        self.assertNotIn(com_ref.pk, [loc.pk for loc in report.removed])
        self.assertEqual(report.preserved_count, 1)
        com_ref.refresh_from_db()
        self.assertTrue(com_ref.is_active)

    def test_batch_processes_at_most_batch_size_and_leaves_the_rest_for_next_call(self):
        total = DUPLICATE_CLEANUP_BATCH_SIZE + 2
        locations = [_teste_location(name="TESTE3") for _ in range(total)]

        first_report = execute_duplicate_location_cleanup_batch(performed_by=self.admin)

        self.assertEqual(len(first_report.removed), DUPLICATE_CLEANUP_BATCH_SIZE)
        self.assertEqual(first_report.remaining_count, 2)

        second_report = execute_duplicate_location_cleanup_batch(performed_by=self.admin)

        self.assertEqual(len(second_report.removed), 2)
        self.assertEqual(second_report.remaining_count, 0)
        for location in locations:
            location.refresh_from_db()
            self.assertFalse(location.is_active)

    def test_processed_total_accumulates_across_independent_batch_calls(self):
        for _ in range(3):
            _teste_location(name="teste2")
        self.assertEqual(count_duplicate_location_cleanup_processed_total(), 0)

        first = execute_duplicate_location_cleanup_batch(performed_by=self.admin)
        self.assertEqual(first.processed_total, 3)
        self.assertEqual(count_duplicate_location_cleanup_processed_total(), 3)

        # Mais candidatas aparecem depois (ex.: nova rodada de teste manual)
        # — o total cumulativo soma em cima do que já foi processado antes,
        # nunca reinicia.
        _teste_location(name="teste2")
        second = execute_duplicate_location_cleanup_batch(performed_by=self.admin)
        self.assertEqual(second.processed_total, 4)

    def test_location_that_gains_reference_between_plan_and_execution_is_skipped_not_removed(self):
        cliente = Client.objects.create(company_name="Cliente Teste Corrida LTDA")
        candidate = create_location(NewLocationData(name="TESTE", type=LocationType.CLIENTE, client=cliente))
        equipment = _equipment(self.admin)

        import apps.operations.services as services_module

        original_plan = services_module.plan_duplicate_location_cleanup
        # execute_duplicate_location_cleanup_batch() chama plan_duplicate_location_cleanup()
        # DUAS vezes (antes do lote e depois, para o relatório) — a corrida
        # só deve ser injetada na PRIMEIRA chamada (a que decide o lote);
        # a segunda deve só refletir o estado já mudado, sem criar outra
        # Movement (o equipamento já não estaria mais DISPONÍVEL).
        already_raced = {"done": False}

        def racy_plan():
            plan = original_plan()
            if not already_raced["done"]:
                already_raced["done"] = True
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
            report = execute_duplicate_location_cleanup_batch(performed_by=self.admin)

        self.assertNotIn(candidate.pk, [loc.pk for loc in report.removed])
        self.assertIn(candidate.pk, [loc.pk for loc in report.skipped_race])
        candidate.refresh_from_db()
        self.assertTrue(candidate.is_active)

    def test_rollback_only_affects_the_failing_batch_not_previous_committed_batches(self):
        """
        Se um lote falhar no meio, os lotes ANTERIORES (já commitados em
        chamadas passadas, cada uma sua própria transação curta)
        permanecem concluídos — só o lote que falhou é revertido.
        """
        first_batch = [_teste_location(name="TESTE3") for _ in range(DUPLICATE_CLEANUP_BATCH_SIZE)]
        first_report = execute_duplicate_location_cleanup_batch(performed_by=self.admin)
        self.assertEqual(len(first_report.removed), DUPLICATE_CLEANUP_BATCH_SIZE)
        for location in first_batch:
            location.refresh_from_db()
            self.assertFalse(location.is_active)

        second_batch = [_teste_location(name="TESTE3") for _ in range(3)]

        original_save = Location.save
        calls = {"n": 0}

        def flaky_save(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("Falha simulada no meio do segundo lote")
            return original_save(self, *args, **kwargs)

        with patch.object(Location, "save", flaky_save):
            with self.assertRaises(RuntimeError):
                execute_duplicate_location_cleanup_batch(performed_by=self.admin)

        # O primeiro lote, commitado ANTES da falha simulada, continua
        # intacto — a transação do segundo lote não tem nenhum efeito
        # sobre commits de chamadas anteriores.
        for location in first_batch:
            location.refresh_from_db()
            self.assertFalse(location.is_active)
        # O segundo lote (que falhou) foi revertido por completo.
        for location in second_batch:
            location.refresh_from_db()
            self.assertTrue(location.is_active)

        # O usuário pode continuar depois: uma nova chamada processa o que
        # sobrou normalmente.
        recovery_report = execute_duplicate_location_cleanup_batch(performed_by=self.admin)
        self.assertEqual(len(recovery_report.removed), 3)
        for location in second_batch:
            location.refresh_from_db()
            self.assertFalse(location.is_active)

    def test_locations_outside_target_groups_are_untouched(self):
        cliente = Client.objects.create(company_name="Cliente Real LTDA")
        real1 = create_location(NewLocationData(name="Unidade Real", type=LocationType.CLIENTE, client=cliente))
        real2 = create_location(NewLocationData(name="Unidade Real", type=LocationType.CLIENTE, client=cliente))

        report = execute_duplicate_location_cleanup_batch(performed_by=self.admin)

        self.assertEqual(report.removed, [])
        real1.refresh_from_db()
        real2.refresh_from_db()
        self.assertTrue(real1.is_active)
        self.assertTrue(real2.is_active)

    def test_internal_locations_are_never_touched(self):
        estoque_interno = Location.objects.get(name="Estoque Locus")
        manutencao_interna = Location.objects.get(name="Manutenção Locus")

        _teste_location(name="TESTE")

        execute_duplicate_location_cleanup_batch(performed_by=self.admin)

        estoque_interno.refresh_from_db()
        manutencao_interna.refresh_from_db()
        self.assertTrue(estoque_interno.is_active)
        self.assertTrue(manutencao_interna.is_active)


class DuplicateLocationsCleanupPermissionTest(TestCase):
    URL = "/operacao/diagnostico/locations-duplicadas/limpar/"

    def setUp(self):
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            User.objects.create_user(username=f"cleanup_{role.lower()}", password="senha-forte-123", role=role)

    def test_only_admin_can_view_progress_screen(self):
        for role, expected in (("ADMIN", 200), ("ADMINISTRATIVO", 403), ("OPERACIONAL", 403), ("CONSULTA", 403)):
            with self.subTest(role=role):
                self.client.login(username=f"cleanup_{role.lower()}", password="senha-forte-123")
                response = self.client.get(self.URL)
                self.assertEqual(response.status_code, expected)
                self.client.logout()

    def test_only_admin_can_post_a_batch(self):
        # Token forjado (sem GET prévio) — para ADMIN é bloqueado como
        # reenvio inválido (302, nada é apagado); para os demais perfis a
        # permissão barra ANTES disso, com 403.
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
        sem_ref = _teste_location()

        response = self.client.post(self.URL, {"submission_token": "qualquer-coisa"})

        self.assertEqual(response.status_code, 302)
        sem_ref.refresh_from_db()
        self.assertTrue(sem_ref.is_active)

    def test_post_with_wrong_token_after_get_is_blocked(self):
        _teste_location()
        self.client.get(self.URL)  # emite o token real na sessão
        response = self.client.post(self.URL, {"submission_token": "token-errado"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Location.objects.filter(name="TESTE", is_active=True).count(), 1)

    def test_progress_screen_shows_next_batch_ids_before_anything_is_removed(self):
        sem_ref = _teste_location()

        response = self.client.get(self.URL)
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"#{sem_ref.pk}", content)
        sem_ref.refresh_from_db()
        self.assertTrue(sem_ref.is_active)

    def test_progress_labels_show_processadas_restantes_preservadas(self):
        _teste_location(name="TESTE3")
        response = self.client.get(self.URL)
        content = response.content.decode()
        self.assertIn("Processadas:", content)
        self.assertIn("Restantes:", content)
        self.assertIn("Preservadas:", content)

    def test_single_post_processes_only_one_batch_and_more_remain_for_next_post(self):
        total = DUPLICATE_CLEANUP_BATCH_SIZE + 2
        for _ in range(total):
            _teste_location(name="TESTE3")

        token = self.client.get(self.URL).context["submission_token"]
        first = self.client.post(self.URL, {"submission_token": token})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.context["remaining_count"], 2)
        self.assertEqual(first.context["processed_total"], DUPLICATE_CLEANUP_BATCH_SIZE)
        self.assertEqual(Location.objects.filter(name="TESTE3", is_active=True).count(), 2)

        second_token = first.context["submission_token"]
        second = self.client.post(self.URL, {"submission_token": second_token})

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.context["remaining_count"], 0)
        self.assertEqual(second.context["processed_total"], total)
        self.assertEqual(Location.objects.filter(name="TESTE3", is_active=True).count(), 0)

    def test_reusing_the_same_token_twice_only_executes_one_batch(self):
        _teste_location(name="TESTE3")

        token = self.client.get(self.URL).context["submission_token"]
        first = self.client.post(self.URL, {"submission_token": token})
        second = self.client.post(self.URL, {"submission_token": token})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 302)  # reenvio — bloqueado, sem token válido de novo

    def test_referenced_location_is_preserved_across_the_whole_http_flow(self):
        """Representa a Location "TESTE" citada como #2 no caso real."""
        cliente = Client.objects.create(company_name="Cliente Preservado HTTP LTDA")
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

        self.assertIn(f"#{com_ref.pk}", content)  # aparece na lista de preservadas
        sem_ref.refresh_from_db()
        com_ref.refresh_from_db()
        self.assertFalse(sem_ref.is_active)
        self.assertTrue(com_ref.is_active)

    def test_auto_continue_checkbox_embeds_a_client_side_delayed_resubmit_no_server_sleep(self):
        # Mais candidatas do que cabem num lote — depois deste POST ainda
        # sobra pelo menos 1, então o form/script de auto-continuação
        # precisa aparecer na resposta (senão a tela mostraria "Concluído").
        for _ in range(DUPLICATE_CLEANUP_BATCH_SIZE + 2):
            _teste_location(name="TESTE3")
        token = self.client.get(self.URL).context["submission_token"]

        response = self.client.post(self.URL, {"submission_token": token, "auto_continue": "1"})
        content = response.content.decode()

        # Continuação automática é JS puro no navegador (setTimeout), nunca
        # um sleep do lado do servidor — a view já respondeu neste ponto.
        self.assertIn("setTimeout", content)
        self.assertIn("next-batch-form", content)
        self.assertIn('checked', content)  # checkbox permanece marcado para o próximo form

    def test_batch_failure_does_not_lose_previously_completed_batches(self):
        """View-level: uma falha simulada num lote não desfaz o que um POST anterior já concluiu."""
        first_batch = [_teste_location(name="TESTE3") for _ in range(2)]
        token = self.client.get(self.URL).context["submission_token"]
        first = self.client.post(self.URL, {"submission_token": token})
        self.assertEqual(first.status_code, 200)
        for location in first_batch:
            location.refresh_from_db()
            self.assertFalse(location.is_active)

        second_batch = [_teste_location(name="TESTE3") for _ in range(2)]
        second_token = first.context["submission_token"]

        original_save = Location.save

        def always_fail_save(self, *args, **kwargs):
            raise RuntimeError("Falha simulada")

        with patch.object(Location, "save", always_fail_save):
            with self.assertRaises(RuntimeError):
                self.client.post(self.URL, {"submission_token": second_token})

        # O primeiro lote continua concluído.
        for location in first_batch:
            location.refresh_from_db()
            self.assertFalse(location.is_active)
        # O segundo (que falhou) não foi tocado — o usuário pode continuar depois.
        for location in second_batch:
            location.refresh_from_db()
            self.assertTrue(location.is_active)
