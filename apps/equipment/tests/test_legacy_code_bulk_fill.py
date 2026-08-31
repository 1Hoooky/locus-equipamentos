"""
Preenchimento sequencial de código legado em lote — ferramenta
ADMINISTRATIVA pedida em 31/08/2026.

Cobre os 20 cenários mínimos exigidos pelo pedido: sequência simples,
sequência de 25 unidades, ordenação por model_sequence (nunca id/
created_at), isolamento estrito por modelo, idempotência de
"já preenchido", bloqueio por conflito, bloqueio por duplicidade externa,
prévia sem efeito colateral, CSRF, permissões (403), execução bem
sucedida, duplo-submit, rollback completo numa falha no meio, patrimônio
não-ordenável, código inicial inválido, primeiro/último corretos na
prévia, revalidação no servidor na confirmação, histórico/auditoria
preservados, e nenhum campo/model novo criado por esta feature.
"""

from django.contrib.auth import get_user_model
from django.db import models as django_models
from django.test import Client, TestCase, TransactionTestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.legacy_code_bulk import (
    LegacyCodeBulkBlocked,
    STATE_JA_PREENCHIDO,
    STATE_SEM_CODIGO,
    apply_legacy_code_bulk_fill,
    build_legacy_code_bulk_preview,
)
from apps.equipment.models import Equipment
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()


def _make_units(model, user, quantity):
    return [create_equipment(NewEquipmentData(model_id=model.pk, created_by=user)) for _ in range(quantity)]


class LegacyCodeBulkPreviewServiceTest(TestCase):
    """Cenários 1, 2, 6, 7, 8, 9, 15, 16, 17, 20."""

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        self.user = User.objects.create_user(username="legado_admin", password="senha-forte-123", role=Role.ADMIN)

    # --- cenário 1: sequência simples de 3 -------------------------------
    def test_simple_three_unit_sequence(self):
        _make_units(self.model, self.user, 3)
        preview = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="26101622101001")
        self.assertFalse(preview.blocked)
        codes = [row.predicted_code for row in preview.rows]
        self.assertEqual(codes, ["26101622101001", "26101622101002", "26101622101003"])

    # --- cenário 2: sequência de 25 ---------------------------------------
    def test_twenty_five_unit_sequence(self):
        _make_units(self.model, self.user, 25)
        preview = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="26101622101001")
        self.assertFalse(preview.blocked)
        self.assertEqual(preview.total, 25)
        self.assertEqual(preview.first_code, "26101622101001")
        self.assertEqual(preview.last_code, "26101622101025")

    # --- cenário 17: primeiro/último corretos na prévia --------------------
    def test_preview_first_and_last_match_the_rows(self):
        equipments = _make_units(self.model, self.user, 4)
        preview = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="0100")
        self.assertEqual(preview.first_code, "0100")
        self.assertEqual(preview.last_code, "0103")
        self.assertEqual(preview.rows[0].patrimonio, equipments[0].patrimonio)
        self.assertEqual(preview.rows[-1].patrimonio, equipments[-1].patrimonio)

    def test_leading_zeros_are_preserved(self):
        """Não trata o código como inteiro puro na saída — largura vem do próprio código informado."""
        _make_units(self.model, self.user, 3)
        preview = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="0007")
        self.assertEqual([r.predicted_code for r in preview.rows], ["0007", "0008", "0009"])

    # --- cenário 6: já preenchido com o valor previsto = idempotente ------
    def test_already_filled_with_predicted_value_is_idempotent_not_conflict(self):
        equipments = _make_units(self.model, self.user, 3)
        equipments[0].legacy_code = "26101622101001"
        equipments[0].save(update_fields=["legacy_code"])

        preview = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="26101622101001")
        self.assertFalse(preview.blocked)
        self.assertEqual(preview.rows[0].state, STATE_JA_PREENCHIDO)
        self.assertEqual(preview.rows[1].state, STATE_SEM_CODIGO)

    # --- cenário 7: código existente diferente do previsto bloqueia -------
    def test_existing_code_different_from_predicted_blocks(self):
        equipments = _make_units(self.model, self.user, 3)
        equipments[1].legacy_code = "26101622109999"
        equipments[1].save(update_fields=["legacy_code"])

        preview = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="26101622101001")
        self.assertTrue(preview.blocked)
        self.assertEqual(len(preview.conflicts), 1)
        conflict = preview.conflicts[0]
        self.assertEqual(conflict.patrimonio, equipments[1].patrimonio)
        self.assertEqual(conflict.current_legacy_code, "26101622109999")
        self.assertEqual(conflict.predicted_code, "26101622101002")

    # --- cenário 8: código já pertence a outro equipamento (outro modelo) -
    def test_code_belonging_to_another_equipment_blocks(self):
        other_model = EquipmentModel.objects.create(category=self.category, name="NI23 Tanque Caixa", code="NI23TC")
        other = create_equipment(NewEquipmentData(model_id=other_model.pk, created_by=self.user))
        other.legacy_code = "26101622101002"
        other.save(update_fields=["legacy_code"])

        _make_units(self.model, self.user, 3)
        preview = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="26101622101001")
        self.assertTrue(preview.blocked)
        self.assertEqual(len(preview.external_duplicates), 1)
        dup = preview.external_duplicates[0]
        self.assertEqual(dup.code, "26101622101002")
        self.assertEqual(dup.existing_patrimonio, other.patrimonio)

    # --- cenário 9: prévia nunca altera o banco ----------------------------
    def test_preview_never_writes_to_the_database(self):
        _make_units(self.model, self.user, 5)
        build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="26101622101001")
        self.assertTrue(all(e.legacy_code == "" for e in Equipment.objects.filter(model=self.model)))

    # --- cenário 15: patrimônio/sequência não-ordenável bloqueia -----------
    def test_broken_sequence_blocks_with_exact_equipment_reported(self):
        equipments = _make_units(self.model, self.user, 3)
        broken = equipments[1]
        Equipment.objects.filter(pk=broken.pk).update(model_sequence=0, patrimonio="")

        preview = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="1001")
        self.assertTrue(preview.blocked)
        self.assertEqual(len(preview.ordering_errors), 1)
        err = preview.ordering_errors[0]
        self.assertEqual(err.equipment_id, broken.pk)
        # Nenhum código é calculado quando a ordenação não é confiável.
        self.assertEqual(preview.rows, [])

    # --- cenário 16: código inicial inválido --------------------------------
    def test_empty_seed_code_is_rejected(self):
        _make_units(self.model, self.user, 2)
        preview = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="")
        self.assertTrue(preview.blocked)
        self.assertIn("Informe o código inicial", preview.seed_error)

    def test_non_numeric_seed_code_is_rejected(self):
        _make_units(self.model, self.user, 2)
        preview = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="26AB1622101001")
        self.assertTrue(preview.blocked)
        self.assertIn("dígitos", preview.seed_error)

    def test_seed_code_overflowing_its_own_width_is_rejected(self):
        """seed=99 com 3 equipamentos geraria 99/100/101 — perderia a largura original (2 dígitos)."""
        _make_units(self.model, self.user, 3)
        preview = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="99")
        self.assertTrue(preview.blocked)
        self.assertTrue(preview.seed_error)

    def test_seed_code_longer_than_field_max_length_is_rejected(self):
        _make_units(self.model, self.user, 1)
        preview = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="1" * 101)
        self.assertTrue(preview.blocked)
        self.assertTrue(preview.seed_error)

    # --- cenário 3: ordenação por model_sequence, NUNCA id/created_at ------
    def test_ordering_follows_model_sequence_not_id_or_creation_order(self):
        eq1, eq2, eq3 = _make_units(self.model, self.user, 3)
        self.assertEqual([eq1.model_sequence, eq2.model_sequence, eq3.model_sequence], [1, 2, 3])

        # Troca as sequências de eq1 e eq3 (mantendo eq2 no meio), sem
        # tocar em id/created_at — se o código ordenasse por id, o
        # resultado seria diferente do esperado abaixo.
        Equipment.objects.filter(pk=eq1.pk).update(model_sequence=99)
        Equipment.objects.filter(pk=eq3.pk).update(model_sequence=1)
        Equipment.objects.filter(pk=eq1.pk).update(model_sequence=3)

        preview = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="1001")
        self.assertFalse(preview.blocked)
        ordered_patrimonios = [row.patrimonio for row in preview.rows]
        # Ordem esperada por model_sequence: eq3 (seq 1), eq2 (seq 2), eq1 (seq 3).
        self.assertEqual(ordered_patrimonios, [eq3.patrimonio, eq2.patrimonio, eq1.patrimonio])
        codes_by_patrimonio = {row.patrimonio: row.predicted_code for row in preview.rows}
        self.assertEqual(codes_by_patrimonio[eq3.patrimonio], "1001")
        self.assertEqual(codes_by_patrimonio[eq2.patrimonio], "1002")
        self.assertEqual(codes_by_patrimonio[eq1.patrimonio], "1003")

    # --- cenários 4/5: isolamento estrito por modelo ------------------------
    def test_only_the_selected_model_is_included_in_the_preview(self):
        other_model = EquipmentModel.objects.create(category=self.category, name="NI23 Tanque Caixa", code="NI23TC")
        _make_units(self.model, self.user, 3)
        _make_units(other_model, self.user, 3)

        preview = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="1001")
        self.assertEqual(preview.total, 3)
        self.assertTrue(all(row.patrimonio.startswith("LOC-NI23BT-") for row in preview.rows))

    # --- cenário 20: nenhum campo/model novo (documentação executável) -----
    def test_reuses_the_existing_legacy_code_field_no_new_field(self):
        field = Equipment._meta.get_field("legacy_code")
        self.assertIsInstance(field, django_models.CharField)
        self.assertEqual(field.max_length, 100)


class LegacyCodeBulkApplyServiceTest(TestCase):
    """Cenários 6 (execução), 7/8 (bloqueio na execução), 14, 18, 19."""

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        self.user = User.objects.create_user(username="legado_exec", password="senha-forte-123", role=Role.ADMIN)

    def test_apply_writes_predicted_codes_and_reports_updated_count(self):
        equipments = _make_units(self.model, self.user, 3)
        preview = apply_legacy_code_bulk_fill(model_id=self.model.pk, seed_code="26101622101001", changed_by=self.user)
        self.assertEqual(preview.updated_count, 3)
        for equipment, expected in zip(equipments, ["26101622101001", "26101622101002", "26101622101003"]):
            equipment.refresh_from_db()
            self.assertEqual(equipment.legacy_code, expected)

    def test_apply_is_idempotent_when_rerun_with_already_filled_codes(self):
        _make_units(self.model, self.user, 3)
        apply_legacy_code_bulk_fill(model_id=self.model.pk, seed_code="26101622101001", changed_by=self.user)

        # Rodar de novo com o MESMO código inicial: tudo já está
        # JA_PREENCHIDO, nada é reescrito, nada quebra.
        second = apply_legacy_code_bulk_fill(model_id=self.model.pk, seed_code="26101622101001", changed_by=self.user)
        self.assertEqual(second.updated_count, 0)
        self.assertFalse(second.blocked)

    def test_apply_raises_and_writes_nothing_on_conflict(self):
        equipments = _make_units(self.model, self.user, 3)
        equipments[2].legacy_code = "26101622109999"
        equipments[2].save(update_fields=["legacy_code"])

        with self.assertRaises(LegacyCodeBulkBlocked):
            apply_legacy_code_bulk_fill(model_id=self.model.pk, seed_code="26101622101001", changed_by=self.user)

        for equipment in equipments[:2]:
            equipment.refresh_from_db()
            self.assertEqual(equipment.legacy_code, "", "Bloqueio precisa impedir gravação de QUALQUER unidade do lote.")

    def test_apply_raises_and_writes_nothing_on_external_duplicate(self):
        other_model = EquipmentModel.objects.create(category=self.category, name="NI23 Tanque Caixa", code="NI23TC")
        other = create_equipment(NewEquipmentData(model_id=other_model.pk, created_by=self.user))
        other.legacy_code = "26101622101002"
        other.save(update_fields=["legacy_code"])

        equipments = _make_units(self.model, self.user, 3)
        with self.assertRaises(LegacyCodeBulkBlocked):
            apply_legacy_code_bulk_fill(model_id=self.model.pk, seed_code="26101622101001", changed_by=self.user)

        for equipment in equipments:
            equipment.refresh_from_db()
            self.assertEqual(equipment.legacy_code, "")

    # --- cenário 14: falha no meio causa rollback completo -------------------
    def test_full_rollback_when_a_save_fails_midway(self):
        from unittest import mock

        equipments = _make_units(self.model, self.user, 5)
        real_save = Equipment.save
        call_count = {"n": 0}

        def flaky_save(self, *args, **kwargs):
            if "legacy_code" in (kwargs.get("update_fields") or []):
                call_count["n"] += 1
                if call_count["n"] == 3:
                    raise RuntimeError("Falha simulada no meio da gravação.")
            return real_save(self, *args, **kwargs)

        with mock.patch.object(Equipment, "save", flaky_save), self.assertRaises(RuntimeError):
            apply_legacy_code_bulk_fill(model_id=self.model.pk, seed_code="1001", changed_by=self.user)

        for equipment in equipments:
            equipment.refresh_from_db()
            self.assertEqual(equipment.legacy_code, "", "Uma falha no meio precisa desfazer TODAS as gravações já feitas.")

    # --- cenário 18: confirmação sempre recalcula no servidor ---------------
    def test_apply_revalidates_fresh_even_if_a_conflict_appeared_after_the_preview_was_shown(self):
        equipments = _make_units(self.model, self.user, 3)
        # Simula: a prévia foi gerada e mostrada ao usuário (sem conflito
        # neste momento)...
        preview_shown = build_legacy_code_bulk_preview(model_id=self.model.pk, seed_code="26101622101001")
        self.assertFalse(preview_shown.blocked)

        # ...mas ENTRE a prévia e o clique em confirmar, outra pessoa
        # preencheu manualmente um código que colide com o previsto.
        equipments[1].legacy_code = "26101622109999"
        equipments[1].save(update_fields=["legacy_code"])

        with self.assertRaises(LegacyCodeBulkBlocked):
            apply_legacy_code_bulk_fill(model_id=self.model.pk, seed_code="26101622101001", changed_by=self.user)

    # --- cenário 19: histórico/auditoria continua sendo gerado ---------------
    def test_history_records_are_created_for_each_updated_equipment(self):
        equipments = _make_units(self.model, self.user, 3)
        history_counts_before = {e.pk: e.history.count() for e in equipments}

        apply_legacy_code_bulk_fill(model_id=self.model.pk, seed_code="1001", changed_by=self.user)

        for equipment in equipments:
            equipment.refresh_from_db()
            self.assertEqual(equipment.history.count(), history_counts_before[equipment.pk] + 1)
            latest = equipment.history.first()
            self.assertIn(equipment.legacy_code, latest.history_change_reason)
            self.assertEqual(latest.legacy_code, equipment.legacy_code)

    def test_history_is_not_created_for_already_filled_rows(self):
        """JA_PREENCHIDO não é gravado de novo — não deve gerar um evento de histórico artificial."""
        equipments = _make_units(self.model, self.user, 2)
        apply_legacy_code_bulk_fill(model_id=self.model.pk, seed_code="1001", changed_by=self.user)
        counts_after_first_run = {e.pk: e.history.count() for e in equipments}

        apply_legacy_code_bulk_fill(model_id=self.model.pk, seed_code="1001", changed_by=self.user)
        for equipment in equipments:
            equipment.refresh_from_db()
            self.assertEqual(
                equipment.history.count(),
                counts_after_first_run[equipment.pk],
                "Reexecutar com o mesmo código inicial não deve criar histórico novo (nada mudou).",
            )


class LegacyCodeBulkViewPermissionTest(TestCase):
    """Cenário 11: CONSULTA/OPERACIONAL não veem/executam; ADMIN/ADMINISTRATIVO sim."""

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        User.objects.create_user(username="legado_admin", password="senha-forte-123", role=Role.ADMIN)
        User.objects.create_user(username="legado_administrativo", password="senha-forte-123", role=Role.ADMINISTRATIVO)
        User.objects.create_user(username="legado_operacional", password="senha-forte-123", role=Role.OPERACIONAL)
        User.objects.create_user(username="legado_consulta", password="senha-forte-123", role=Role.CONSULTA)
        self.url = f"/equipamentos/modelo/{self.model.pk}/codigos-legados/"

    def test_admin_can_access(self):
        self.client.login(username="legado_admin", password="senha-forte-123")
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_administrativo_can_access(self):
        self.client.login(username="legado_administrativo", password="senha-forte-123")
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_operacional_cannot_access(self):
        self.client.login(username="legado_operacional", password="senha-forte-123")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_consulta_cannot_access(self):
        self.client.login(username="legado_consulta", password="senha-forte-123")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_operacional_cannot_post_directly(self):
        """Esconder o botão não é segurança: a URL de POST precisa validar no backend mesmo assim."""
        self.client.login(username="legado_operacional", password="senha-forte-123")
        response = self.client.post(self.url, {"codigo_inicial": "1001", "submission_token": "forjado"})
        self.assertEqual(response.status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/contas/login/", response.url)


class LegacyCodeBulkViewFlowTest(TestCase):
    """Cenários 10, 12, 13, 17 (via view)."""

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        self.user = User.objects.create_user(username="legado_fluxo", password="senha-forte-123", role=Role.ADMIN)
        self.equipments = _make_units(self.model, self.user, 3)
        self.url = f"/equipamentos/modelo/{self.model.pk}/codigos-legados/"
        self.client.login(username="legado_fluxo", password="senha-forte-123")

    def _get_token(self):
        response = self.client.get(self.url)
        return response.context["submission_token"]

    # --- cenário 12: usuário autorizado executa com sucesso -----------------
    def test_authorized_user_can_preview_then_confirm_successfully(self):
        preview_response = self.client.get(self.url, {"codigo_inicial": "26101622101001"})
        self.assertEqual(preview_response.status_code, 200)
        preview = preview_response.context["preview"]
        self.assertFalse(preview.blocked)
        self.assertEqual(preview.total, 3)

        token = preview_response.context["submission_token"]
        confirm_response = self.client.post(
            self.url, {"codigo_inicial": "26101622101001", "submission_token": token}
        )
        self.assertEqual(confirm_response.status_code, 200)
        self.assertTemplateUsed(confirm_response, "equipment/legacy_code_bulk_fill_result.html")

        for equipment, expected in zip(self.equipments, ["26101622101001", "26101622101002", "26101622101003"]):
            equipment.refresh_from_db()
            self.assertEqual(equipment.legacy_code, expected)

    # --- cenário 13: duplo-submit não executa duas vezes ---------------------
    def test_double_submit_does_not_run_twice(self):
        token = self._get_token()
        first = self.client.post(self.url, {"codigo_inicial": "1001", "submission_token": token})
        self.assertEqual(first.status_code, 200)
        self.assertTemplateUsed(first, "equipment/legacy_code_bulk_fill_result.html")

        second = self.client.post(self.url, {"codigo_inicial": "1001", "submission_token": token})
        self.assertEqual(second.status_code, 400)
        self.assertTemplateUsed(second, "equipment/legacy_code_bulk_fill.html")

        # O lote foi preenchido exatamente uma vez.
        for equipment, expected in zip(self.equipments, ["1001", "1002", "1003"]):
            equipment.refresh_from_db()
            self.assertEqual(equipment.legacy_code, expected)

    def test_blocked_preview_does_not_offer_a_confirm_action(self):
        self.equipments[0].legacy_code = "9999"
        self.equipments[0].save(update_fields=["legacy_code"])
        response = self.client.get(self.url, {"codigo_inicial": "1001"})
        self.assertNotContains(response, "Confirmar preenchimento")

    # --- cenário 10: POST sem CSRF é rejeitado --------------------------------
    def test_post_without_csrf_token_is_rejected(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username="legado_fluxo", password="senha-forte-123")
        token = csrf_client.get(self.url).context["submission_token"]
        response = csrf_client.post(self.url, {"codigo_inicial": "1001", "submission_token": token})
        self.assertEqual(response.status_code, 403)
        for equipment in self.equipments:
            equipment.refresh_from_db()
            self.assertEqual(equipment.legacy_code, "")

    def test_result_screen_shows_expected_summary_and_return_link(self):
        token = self._get_token()
        response = self.client.post(self.url, {"codigo_inicial": "26101622101001", "submission_token": token})
        self.assertContains(response, "Códigos legados preenchidos com sucesso")
        self.assertContains(response, "26101622101001")
        self.assertContains(response, "26101622101003")
        self.assertContains(response, f"?model={self.model.pk}")


class LegacyCodeBulkConcurrencyTest(TransactionTestCase):
    """Duas confirmações concorrentes do MESMO modelo nunca duplicam/corrompem nem correm entre prévia e confirmação."""

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        self.user = User.objects.create_user(username="legado_concorrencia", password="senha-forte-123", role=Role.ADMIN)
        self.equipments = _make_units(self.model, self.user, 5)

    def test_concurrent_confirmations_of_the_same_model_serialize_safely(self):
        import threading

        from django.db import connection

        errors = []
        lock = threading.Lock()

        def worker():
            try:
                apply_legacy_code_bulk_fill(model_id=self.model.pk, seed_code="1001", changed_by=self.user)
            except Exception as exc:  # pragma: no cover - só diagnóstico
                with lock:
                    errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Erros durante a concorrência: {errors}")

        codes = list(
            Equipment.objects.filter(model=self.model).order_by("model_sequence").values_list("legacy_code", flat=True)
        )
        self.assertEqual(codes, ["1001", "1002", "1003", "1004", "1005"], "Execuções concorrentes não podem corromper o resultado final.")
