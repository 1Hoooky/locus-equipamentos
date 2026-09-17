"""
Testes HTTP/permissões/UI da Tabela de Preços V1 (16/09/2026) — seções 33
(matriz de permissões: sem login, sem `view`, com `view`, com `view` sem
`change`, com `change`, acesso direto por URL, botão escondido ≠ bloqueio
no backend) e 35 (UI: item novo aparece "Sem valor", busca, filtro "Sem
valor", edição inline via htmx, salvamento, atualização da linha).
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client as DjangoTestClient
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Category, EquipmentModel
from apps.crm.models import BusinessType, PriceTableItem, ServiceCatalogItem
from apps.crm.services import PriceTableItemData, set_price_table_item

User = get_user_model()


def _user_with_perms(username, *codenames):
    user = User.objects.create_user(username=username, password="senha-forte-123")
    if codenames:
        perms = Permission.objects.filter(codename__in=codenames, content_type__app_label="crm")
        group, _ = Group.objects.get_or_create(name=f"perm-{username}")
        group.permissions.set(perms)
        user.groups.add(group)
    return user


class PriceTableViewsTestBase(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(code="NI23BT", name="NI23 Big Tank", category=self.category)
        self.service = ServiceCatalogItem.objects.create(name="Diária de operador", unit_label="hora")
        self.viewer = _user_with_perms("viewer_price_table", "view_price_table")
        self.editor = _user_with_perms("editor_price_table", "view_price_table", "change_price_table")
        self.no_perm_user = _user_with_perms("no_perm_price_table")

    def _login(self, user):
        client = DjangoTestClient()
        client.force_login(user)
        return client


class PriceTableViewPermissionTest(PriceTableViewsTestBase):
    url_name = "crm:price_table"

    def test_anonymous_is_redirected_to_login(self):
        client = DjangoTestClient()
        resp = client.get(reverse(self.url_name))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp.url)

    def test_user_without_view_permission_is_forbidden(self):
        client = self._login(self.no_perm_user)
        resp = client.get(reverse(self.url_name))
        self.assertEqual(resp.status_code, 403)

    def test_user_with_view_permission_can_see_page(self):
        client = self._login(self.viewer)
        resp = client.get(reverse(self.url_name))
        self.assertEqual(resp.status_code, 200)

    def test_editor_can_see_page(self):
        client = self._login(self.editor)
        resp = client.get(reverse(self.url_name))
        self.assertEqual(resp.status_code, 200)

    def test_viewer_without_change_does_not_see_edit_button(self):
        client = self._login(self.viewer)
        resp = client.get(reverse(self.url_name))
        self.assertNotContains(resp, "Editar preço de")

    def test_editor_sees_edit_button(self):
        client = self._login(self.editor)
        resp = client.get(reverse(self.url_name))
        self.assertContains(resp, "Editar preço de")


class PriceTableItemRowViewPermissionTest(PriceTableViewsTestBase):
    def _row_url(self, kind, target_id):
        return reverse("crm:price_table_item_row", args=[kind, target_id])

    def test_view_mode_get_requires_view_permission(self):
        client = self._login(self.no_perm_user)
        resp = client.get(self._row_url("equipamento", self.model.pk), {"tipo": BusinessType.LOCACAO})
        self.assertEqual(resp.status_code, 403)

    def test_view_mode_get_allowed_for_viewer(self):
        client = self._login(self.viewer)
        resp = client.get(self._row_url("equipamento", self.model.pk), {"tipo": BusinessType.LOCACAO})
        self.assertEqual(resp.status_code, 200)

    def test_edit_mode_get_blocked_for_viewer_without_change(self):
        # Acesso direto por URL com ?modo=editar, sem botão nenhum — seção 33.
        client = self._login(self.viewer)
        resp = client.get(self._row_url("equipamento", self.model.pk), {"tipo": BusinessType.LOCACAO, "modo": "editar"})
        self.assertEqual(resp.status_code, 403)

    def test_edit_mode_get_allowed_for_editor(self):
        client = self._login(self.editor)
        resp = client.get(self._row_url("equipamento", self.model.pk), {"tipo": BusinessType.LOCACAO, "modo": "editar"})
        self.assertEqual(resp.status_code, 200)

    def test_post_blocked_for_viewer_without_change_backend_enforced(self):
        # "Botão escondido ≠ bloqueio no backend": mesmo sem o lápis
        # renderizado na tela, um POST direto precisa ser recusado.
        client = self._login(self.viewer)
        resp = client.post(
            self._row_url("equipamento", self.model.pk),
            {"tipo": BusinessType.LOCACAO, "unit_price": "900.00"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(PriceTableItem.objects.exists())

    def test_post_allowed_for_editor(self):
        client = self._login(self.editor)
        resp = client.post(
            self._row_url("equipamento", self.model.pk),
            {"tipo": BusinessType.LOCACAO, "unit_price": "900.00"},
        )
        self.assertEqual(resp.status_code, 200)
        item = PriceTableItem.objects.get()
        self.assertEqual(item.unit_price, Decimal("900.00"))
        self.assertEqual(item.updated_by, self.editor)

    def test_anonymous_is_redirected_to_login(self):
        client = DjangoTestClient()
        resp = client.post(self._row_url("equipamento", self.model.pk), {"tipo": BusinessType.LOCACAO, "unit_price": "900"})
        self.assertEqual(resp.status_code, 302)


class PriceTableUiTest(PriceTableViewsTestBase):
    """Seção 35 — comportamento da tela em si."""

    def test_new_active_equipment_model_appears_as_missing_price(self):
        # RODADA 1 (16/09/2026): a aba Locação passou a mostrar a matriz de
        # plano×prazo (ver `MatrixUiTest` em `test_commercial_plans.py`)
        # — o texto "Sem valor" e a lista simples de equipamentos
        # continuam existindo EXATAMENTE como na V1, só que agora nas
        # abas Venda/Serviço (nunca alteradas por esta rodada).
        new_model = EquipmentModel.objects.create(code="NOVO01", name="Modelo Novo", category=self.category)
        client = self._login(self.viewer)
        resp = client.get(reverse("crm:price_table"), {"tipo": BusinessType.VENDA})
        self.assertContains(resp, "Modelo Novo")
        self.assertContains(resp, "Sem valor")

    def test_new_active_service_appears_as_missing_price(self):
        new_service = ServiceCatalogItem.objects.create(name="Instalação", unit_label="un")
        client = self._login(self.viewer)
        resp = client.get(reverse("crm:price_table"), {"tipo": BusinessType.LOCACAO})
        self.assertContains(resp, "Instalação")

    def test_search_filters_rows(self):
        client = self._login(self.viewer)
        resp = client.get(reverse("crm:price_table"), {"tipo": BusinessType.LOCACAO, "q": "NI23BT"})
        self.assertContains(resp, "NI23 Big Tank")

    def test_only_missing_filter_hides_configured_item(self):
        # RODADA 1: mesma nota do teste acima — "sem_valor" sobre a lista
        # simples de equipamentos só existe nas abas Venda/Serviço agora;
        # o equivalente para a matriz de Locação é testado em
        # `test_commercial_plans.py` (linha sem NENHUMA célula
        # preenchida).
        set_price_table_item(
            data=PriceTableItemData(
                business_type=BusinessType.VENDA, equipment_model=self.model, unit_price=Decimal("900.00")
            ),
            user=self.editor,
        )
        client = self._login(self.viewer)
        resp = client.get(reverse("crm:price_table"), {"tipo": BusinessType.VENDA, "sem_valor": "1"})
        self.assertNotContains(resp, "NI23 Big Tank")

    def test_edit_then_save_updates_row_value(self):
        client = self._login(self.editor)
        edit_resp = client.get(
            reverse("crm:price_table_item_row", args=["equipamento", self.model.pk]),
            {"tipo": BusinessType.LOCACAO, "modo": "editar"},
        )
        self.assertContains(edit_resp, "Salvar")
        self.assertContains(edit_resp, "Cancelar")

        save_resp = client.post(
            reverse("crm:price_table_item_row", args=["equipamento", self.model.pk]),
            {"tipo": BusinessType.LOCACAO, "unit_price": "900.00"},
        )
        self.assertContains(save_resp, "900,00")
        self.assertNotContains(save_resp, "Sem valor")

    def test_invalid_price_shows_error_and_does_not_save(self):
        client = self._login(self.editor)
        resp = client.post(
            reverse("crm:price_table_item_row", args=["equipamento", self.model.pk]),
            {"tipo": BusinessType.LOCACAO, "unit_price": "-10.00"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "não pode ser negativo", status_code=400)
        self.assertFalse(PriceTableItem.objects.exists())

    def test_row_reflects_updated_value_after_second_save(self):
        client = self._login(self.editor)
        client.post(
            reverse("crm:price_table_item_row", args=["equipamento", self.model.pk]),
            {"tipo": BusinessType.LOCACAO, "unit_price": "900.00"},
        )
        resp = client.post(
            reverse("crm:price_table_item_row", args=["equipamento", self.model.pk]),
            {"tipo": BusinessType.LOCACAO, "unit_price": "950.00"},
        )
        self.assertContains(resp, "950,00")
        self.assertEqual(PriceTableItem.objects.count(), 1)

    def test_service_row_can_be_edited_and_saved(self):
        client = self._login(self.editor)
        resp = client.post(
            reverse("crm:price_table_item_row", args=["servico", self.service.pk]),
            {"tipo": BusinessType.LOCACAO, "unit_price": "150.00"},
        )
        self.assertContains(resp, "150,00")
        item = PriceTableItem.objects.get()
        self.assertEqual(item.service, self.service)

    def test_invalid_kind_returns_404(self):
        client = self._login(self.viewer)
        resp = client.get(
            reverse("crm:price_table_item_row", args=["invalido", self.model.pk]), {"tipo": BusinessType.LOCACAO}
        )
        self.assertEqual(resp.status_code, 404)

    def test_invalid_business_type_returns_404(self):
        client = self._login(self.viewer)
        resp = client.get(
            reverse("crm:price_table_item_row", args=["equipamento", self.model.pk]), {"tipo": "INVALIDO"}
        )
        self.assertEqual(resp.status_code, 404)


class SidebarVisibilityTest(PriceTableViewsTestBase):
    """
    Seção 19 — "Tabela de preços" aparece na sidebar só com
    `crm.view_price_table`, e nunca quebra a lógica de "grupo CRM vazio
    nunca aparece" já existente (`templates/base.html`).
    """

    def test_link_visible_for_user_with_permission(self):
        client = self._login(self.viewer)
        resp = client.get(reverse("dashboard:home"))
        self.assertContains(resp, "Tabela de preços")
        self.assertContains(resp, reverse("crm:price_table"))

    def test_link_hidden_for_user_without_permission(self):
        client = self._login(self.no_perm_user)
        resp = client.get(reverse("dashboard:home"))
        self.assertNotContains(resp, "Tabela de preços")

    def test_crm_group_still_appears_for_price_table_only_permission(self):
        # Usuário só com view_price_table (nenhuma outra permissão de CRM)
        # precisa continuar vendo o grupo "CRM" na sidebar.
        client = self._login(self.viewer)
        resp = client.get(reverse("dashboard:home"))
        self.assertContains(resp, ">CRM<")
