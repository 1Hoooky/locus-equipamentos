"""
Listagem de Equipamentos agrupada por modelo — melhoria de UX/consulta
(rodada pós-homologação). `EquipmentListView` (área principal) passou a
mostrar grupos por `EquipmentModel` com contadores agregados; os
equipamentos individuais de cada grupo são carregados sob demanda por
`EquipmentModelItemsView` (fragmento HTMX). Nenhum model/migration/regra
de domínio foi alterado — só a consulta e a apresentação.
"""

import re

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.models import Condition, Status
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()


class ModelGroupingCorrectnessTest(TestCase):
    """Itens 1-6 do briefing: agrupamento e contadores corretos por EquipmentModel real."""

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Climatizador")
        cls.model_a = EquipmentModel.objects.create(category=category, name="NI23BT", code="NI23BT")
        cls.model_b = EquipmentModel.objects.create(category=category, name="NI23TC", code="NI23TC")
        cls.user = User.objects.create_user(username="grouping_user", password="senha-forte-123")

        # Modelo A: 4 disponíveis, 2 em operação, 1 manutenção, 1 inativo -> total 8.
        for _ in range(4):
            create_equipment(NewEquipmentData(model_id=cls.model_a.pk, created_by=cls.user, status=Status.DISPONIVEL))
        for _ in range(2):
            create_equipment(NewEquipmentData(model_id=cls.model_a.pk, created_by=cls.user, status=Status.EM_OPERACAO))
        create_equipment(NewEquipmentData(model_id=cls.model_a.pk, created_by=cls.user, status=Status.MANUTENCAO))
        create_equipment(NewEquipmentData(model_id=cls.model_a.pk, created_by=cls.user, status=Status.INATIVO))

        # Modelo B: só 2 disponíveis (nenhum outro status) -> total 2, sem os demais badges.
        for _ in range(2):
            create_equipment(NewEquipmentData(model_id=cls.model_b.pk, created_by=cls.user, status=Status.DISPONIVEL))

    def setUp(self):
        self.client.login(username="grouping_user", password="senha-forte-123")

    def _groups_by_model_id(self):
        response = self.client.get("/equipamentos/")
        return {group.model_id: group for group in response.context["model_groups"]}

    def test_groups_use_real_equipment_model_never_invented(self):
        groups = self._groups_by_model_id()
        self.assertEqual(set(groups.keys()), {self.model_a.pk, self.model_b.pk})
        self.assertEqual(groups[self.model_a.pk].model_name, "NI23BT")
        self.assertEqual(groups[self.model_b.pk].model_name, "NI23TC")

    def test_total_count_per_model_is_correct(self):
        groups = self._groups_by_model_id()
        self.assertEqual(groups[self.model_a.pk].total, 8)
        self.assertEqual(groups[self.model_b.pk].total, 2)

    def test_available_count_is_correct(self):
        groups = self._groups_by_model_id()
        badges = dict((label, count) for label, count, _ in groups[self.model_a.pk].status_badges)
        self.assertEqual(badges["disponíveis"], 4)

    def test_in_operation_count_is_correct(self):
        groups = self._groups_by_model_id()
        badges = dict((label, count) for label, count, _ in groups[self.model_a.pk].status_badges)
        self.assertEqual(badges["em operação"], 2)

    def test_maintenance_count_is_correct(self):
        groups = self._groups_by_model_id()
        badges = dict((label, count) for label, count, _ in groups[self.model_a.pk].status_badges)
        self.assertEqual(badges["manutenção"], 1)

    def test_inactive_count_is_correct(self):
        groups = self._groups_by_model_id()
        badges = dict((label, count) for label, count, _ in groups[self.model_a.pk].status_badges)
        self.assertEqual(badges["inativo"], 1)

    def test_zero_value_badges_are_omitted(self):
        """Modelo B só tem DISPONIVEL (2 unidades) — nenhum badge de em operação/manutenção/inativo deve existir."""
        groups = self._groups_by_model_id()
        badges = dict((label, count) for label, count, _ in groups[self.model_b.pk].status_badges)
        self.assertEqual(badges, {"disponíveis": 2})  # plural: count == 2
        self.assertNotIn("em operação", badges)
        self.assertNotIn("manutenção", badges)
        self.assertNotIn("inativo", badges)


class ModelGroupingRespectsFiltersTest(TestCase):
    """Itens 7-10 do briefing: agrupamento respeita filtros/busca já existentes."""

    @classmethod
    def setUpTestData(cls):
        cls.category_a = Category.objects.create(name="Climatizador")
        cls.category_b = Category.objects.create(name="Aquecedor")
        cls.model_a = EquipmentModel.objects.create(category=cls.category_a, name="NI23BT", code="NI23BT")
        cls.model_b = EquipmentModel.objects.create(category=cls.category_b, name="Torre", code="AQTR")
        cls.user = User.objects.create_user(username="filter_grouping_user", password="senha-forte-123")

        cls.eq_a_disponivel = create_equipment(
            NewEquipmentData(model_id=cls.model_a.pk, created_by=cls.user, status=Status.DISPONIVEL)
        )
        cls.eq_a_manutencao = create_equipment(
            NewEquipmentData(model_id=cls.model_a.pk, created_by=cls.user, status=Status.MANUTENCAO)
        )
        cls.eq_b_disponivel = create_equipment(
            NewEquipmentData(model_id=cls.model_b.pk, created_by=cls.user, status=Status.DISPONIVEL)
        )

    def setUp(self):
        self.client.login(username="filter_grouping_user", password="senha-forte-123")

    def _group_ids(self, params=None):
        response = self.client.get("/equipamentos/", params or {})
        return {group.model_id for group in response.context["model_groups"]}

    def test_model_with_no_result_after_filter_disappears(self):
        # Filtrando por categoria A, o modelo B (categoria diferente) some.
        group_ids = self._group_ids({"category": self.category_a.pk})
        self.assertEqual(group_ids, {self.model_a.pk})

    def test_status_filter_changes_counters_correctly(self):
        response = self.client.get("/equipamentos/", {"status": Status.MANUTENCAO})
        groups = {g.model_id: g for g in response.context["model_groups"]}
        # Só o modelo A tem equipamento em manutenção -> só ele aparece,
        # e o total reflete SÓ o subconjunto filtrado (1), não os 2 totais do modelo.
        self.assertEqual(set(groups.keys()), {self.model_a.pk})
        self.assertEqual(groups[self.model_a.pk].total, 1)
        badges = dict((label, count) for label, count, _ in groups[self.model_a.pk].status_badges)
        self.assertEqual(badges, {"manutenção": 1})

    def test_category_filter_works(self):
        group_ids = self._group_ids({"category": self.category_b.pk})
        self.assertEqual(group_ids, {self.model_b.pk})

    def test_search_by_patrimonio_narrows_to_matching_model_only(self):
        response = self.client.get("/equipamentos/", {"q": self.eq_a_disponivel.patrimonio})
        groups = {g.model_id: g for g in response.context["model_groups"]}
        self.assertEqual(set(groups.keys()), {self.model_a.pk})
        self.assertEqual(groups[self.model_a.pk].total, 1)

    def test_search_active_marks_groups_for_auto_expand(self):
        response = self.client.get("/equipamentos/", {"q": self.eq_a_disponivel.patrimonio})
        self.assertTrue(response.context["auto_expand_groups"])
        content = response.content.decode()
        self.assertIn('data-model-group-auto-expand="true"', content)

    def test_no_search_does_not_auto_expand(self):
        # A string 'data-model-group-auto-expand' aparece SEMPRE no HTML,
        # dentro do <script> de bootstrap (o seletor JS que dispara o
        # clique simulado) — isso não indica que algum grupo está
        # marcado. O que importa é se algum <button> do grupo carrega o
        # atributo com valor "true"; sem busca ativa, nenhum deve.
        response = self.client.get("/equipamentos/")
        self.assertFalse(response.context["auto_expand_groups"])
        content = response.content.decode()
        self.assertIsNone(re.search(r'<button[^>]*data-model-group-auto-expand="true"', content))


class ModelItemsPartialCorrectnessTest(TestCase):
    """Itens 11-14 do briefing: fragmento HTMX isolado por modelo, com permissão e paginação."""

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Climatizador")
        cls.model_a = EquipmentModel.objects.create(category=category, name="Modelo A", code="MDXA")
        cls.model_b = EquipmentModel.objects.create(category=category, name="Modelo B", code="MDXB")
        cls.user = User.objects.create_user(username="items_partial_user", password="senha-forte-123")

        cls.eq_a = create_equipment(NewEquipmentData(model_id=cls.model_a.pk, created_by=cls.user))
        cls.eq_b = create_equipment(NewEquipmentData(model_id=cls.model_b.pk, created_by=cls.user))

    def test_expanding_a_group_returns_only_that_models_equipment(self):
        self.client.login(username="items_partial_user", password="senha-forte-123")
        response = self.client.get(f"/equipamentos/modelo/{self.model_a.pk}/itens/")
        items = list(response.context["page_obj"].object_list)
        self.assertEqual(items, [self.eq_a])

    def test_other_model_equipment_never_appears_in_the_partial(self):
        self.client.login(username="items_partial_user", password="senha-forte-123")
        response = self.client.get(f"/equipamentos/modelo/{self.model_a.pk}/itens/")
        content = response.content.decode()
        self.assertIn(self.eq_a.patrimonio, content)
        self.assertNotIn(self.eq_b.patrimonio, content)

    def test_endpoint_requires_authentication(self):
        response = self.client.get(f"/equipamentos/modelo/{self.model_a.pk}/itens/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/contas/login/", response.url)

    def test_endpoint_404s_for_unknown_model(self):
        self.client.login(username="items_partial_user", password="senha-forte-123")
        response = self.client.get("/equipamentos/modelo/999999/itens/")
        self.assertEqual(response.status_code, 404)

    def test_internal_pagination_works(self):
        """Complementa test_list_pagination_filters.py — aqui só confirma o comportamento básico."""
        category = Category.objects.create(name="Aquecedor (paginação)")
        model = EquipmentModel.objects.create(category=category, name="Paginado", code="PGND")
        for _ in range(25):
            create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.user))

        self.client.login(username="items_partial_user", password="senha-forte-123")
        response = self.client.get(f"/equipamentos/modelo/{model.pk}/itens/")
        self.assertEqual(len(response.context["page_obj"].object_list), 20)
        self.assertTrue(response.context["is_paginated"])

        response_page_2 = self.client.get(f"/equipamentos/modelo/{model.pk}/itens/", {"page": 2})
        self.assertEqual(len(response_page_2.context["page_obj"].object_list), 5)


class GroupedListingPermissionMatrixTest(TestCase):
    """Item 18 do briefing: ações existentes (QR/etiqueta, criar, exportar) continuam restritas exatamente como hoje."""

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Climatizador")
        cls.model = EquipmentModel.objects.create(category=category, name="Modelo Perm", code="MDPM")
        creator = User.objects.create_user(username="perm_creator", password="senha-forte-123", role=Role.ADMIN)
        cls.equipment = create_equipment(NewEquipmentData(model_id=cls.model.pk, created_by=creator))

        for role in (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA):
            User.objects.create_user(username=f"perm_{role.lower()}", password="senha-forte-123", role=role)

    def test_all_four_roles_can_see_the_grouped_listing(self):
        for role in (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA):
            self.client.login(username=f"perm_{role.lower()}", password="senha-forte-123")
            response = self.client.get("/equipamentos/")
            self.assertEqual(response.status_code, 200)
            self.client.logout()

    def test_qr_and_label_actions_hidden_from_operacional_and_consulta_in_partial(self):
        for role in (Role.OPERACIONAL, Role.CONSULTA):
            self.client.login(username=f"perm_{role.lower()}", password="senha-forte-123")
            content = self.client.get(f"/equipamentos/modelo/{self.model.pk}/itens/").content.decode()
            self.assertNotIn(f'href="/qrcodes/{self.equipment.patrimonio}/', content)
            self.client.logout()

    def test_qr_and_label_actions_visible_to_administrativo_and_admin_in_partial(self):
        for role in (Role.ADMIN, Role.ADMINISTRATIVO):
            self.client.login(username=f"perm_{role.lower()}", password="senha-forte-123")
            content = self.client.get(f"/equipamentos/modelo/{self.model.pk}/itens/").content.decode()
            self.assertIn("Ver QR Code de", content)
            self.assertIn("Baixar etiqueta de", content)
            self.client.logout()

    def test_create_and_export_actions_still_present_for_administrativo(self):
        # Checamos os hrefs (não o texto "Exportar CSV" solto): esse texto
        # também aparece dentro de um comentário CSS em
        # _design_tokens.html (exemplo de uso de `.icon-inline`), então
        # `assertIn`/`assertNotIn` no texto puro dariam falso positivo
        # nos dois sentidos.
        self.client.login(username="perm_administrativo", password="senha-forte-123")
        content = self.client.get("/equipamentos/").content.decode()
        self.assertIn("Novo equipamento", content)
        self.assertIn("Adicionar equipamentos em lote", content)
        self.assertIn("format=csv", content)
        self.assertIn("format=xlsx", content)
        self.assertIn("Exportar QR Codes", content)
        self.assertIn("Exportar Etiquetas", content)

    def test_create_and_export_actions_hidden_for_consulta(self):
        self.client.login(username="perm_consulta", password="senha-forte-123")
        content = self.client.get("/equipamentos/").content.decode()
        self.assertNotIn("Novo equipamento", content)
        self.assertNotIn("Adicionar equipamentos em lote", content)
        self.assertNotIn("format=csv", content)
        self.assertNotIn("format=xlsx", content)
        self.assertNotIn("Exportar QR Codes", content)
        self.assertNotIn("Exportar Etiquetas", content)


class GroupedListingMobileMarkupTest(TestCase):
    """Item 17 do briefing: markup mobile continua acessível (não é a tabela desktop espremida)."""

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Climatizador")
        cls.model = EquipmentModel.objects.create(category=category, name="Modelo Mobile", code="MDMB")
        cls.user = User.objects.create_user(username="mobile_markup_user", password="senha-forte-123", role=Role.ADMIN)
        cls.equipment = create_equipment(NewEquipmentData(model_id=cls.model.pk, created_by=cls.user))

    def setUp(self):
        self.client.login(username="mobile_markup_user", password="senha-forte-123")

    def test_group_toggle_is_a_real_button_with_aria_attributes(self):
        content = self.client.get("/equipamentos/").content.decode()
        self.assertIn("<button", content)
        self.assertIn("aria-expanded=", content)
        self.assertIn(f'aria-controls="model-group-items-{self.model.pk}"', content)

    def test_items_partial_renders_both_desktop_table_and_mobile_cards(self):
        content = self.client.get(f"/equipamentos/modelo/{self.model.pk}/itens/").content.decode()
        self.assertIn('class="hidden sm:block table-wrap"', content)
        self.assertIn('class="sm:hidden flex flex-col gap-2"', content)
        # Nenhuma tabela sem o wrapper "hidden sm:block" (não é a mesma
        # tabela desktop mostrada crua no mobile com scroll horizontal).
        self.assertNotIn("<table", content.split('class="hidden sm:block table-wrap"', 1)[0])

    def test_mobile_card_shows_patrimonio_status_condition(self):
        content = self.client.get(f"/equipamentos/modelo/{self.model.pk}/itens/").content.decode()
        mobile_section = content.split('class="sm:hidden flex flex-col gap-2"', 1)[1]
        self.assertIn(self.equipment.patrimonio, mobile_section)
        self.assertIn(self.equipment.get_status_display(), mobile_section)
        self.assertIn(self.equipment.get_condition_display(), mobile_section)


class GroupedListingQueryBudgetTest(TestCase):
    """
    Itens 15-16 do briefing: número de queries FIXO, não cresce com a
    quantidade de modelos (página de grupos) nem com a quantidade de
    equipamentos dentro de um grupo (fragmento HTMX).
    """

    def setUp(self):
        self.user = User.objects.create_user(username="budget_user", password="senha-forte-123")
        self.client.login(username="budget_user", password="senha-forte-123")

    def _seed_models(self, count, category, equipment_per_model=2):
        # `code` de EquipmentModel é único (CODE_VALIDATOR) — usamos a
        # contagem já existente de modelos como offset, para que uma
        # segunda chamada (ex.: 10 modelos, depois +90) nunca gere um
        # `code` duplicado com a primeira leva.
        start = EquipmentModel.objects.count()
        for i in range(start, start + count):
            model = EquipmentModel.objects.create(category=category, name=f"Modelo Budget {i}", code=f"MB{i:03d}")
            for _ in range(equipment_per_model):
                create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.user))

    def test_top_level_query_count_does_not_grow_with_number_of_models(self):
        category = Category.objects.create(name="Categoria Budget")
        self._seed_models(10, category)
        with CaptureQueriesContext(connection) as small:
            self.client.get("/equipamentos/")

        self._seed_models(90, category)  # 10 -> 100 modelos no total
        with CaptureQueriesContext(connection) as large:
            self.client.get("/equipamentos/")

        self.assertEqual(len(small.captured_queries), len(large.captured_queries))

    def test_partial_query_count_does_not_grow_with_number_of_equipment(self):
        category = Category.objects.create(name="Categoria Budget Item")
        model = EquipmentModel.objects.create(category=category, name="Modelo Budget Item", code="MBI001")
        for _ in range(3):
            create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.user))
        with CaptureQueriesContext(connection) as small:
            self.client.get(f"/equipamentos/modelo/{model.pk}/itens/")

        for _ in range(30):
            create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.user))
        with CaptureQueriesContext(connection) as large:
            self.client.get(f"/equipamentos/modelo/{model.pk}/itens/")

        self.assertEqual(len(small.captured_queries), len(large.captured_queries))
