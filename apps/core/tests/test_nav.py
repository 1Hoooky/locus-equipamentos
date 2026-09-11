"""
Testes da função pura `active_nav_group` (REFINAMENTO DA SIDEBAR,
11/09/2026) — sem banco, sem client HTTP: só entrada/saída de string,
cobrindo cada grupo do menu e os apps que espalham rotas por mais de um
grupo (equipment/accounts/operations).
"""
from apps.core.nav import active_nav_group


class TestActiveNavGroup:
    def test_none_when_no_view_name(self):
        assert active_nav_group("", "dashboard") is None
        assert active_nav_group(None, None) is None

    def test_crm_app_always_crm_group(self):
        assert active_nav_group("crm:opportunity_list", "crm") == "crm"
        assert active_nav_group("crm:opportunity_detail", "crm") == "crm"
        assert active_nav_group("crm:commercial_source_list", "crm") == "crm"
        assert active_nav_group("crm:opportunity_stage_create", "crm") == "crm"
        assert active_nav_group("crm:loss_reason_update", "crm") == "crm"

    def test_equipment_operacao_by_default(self):
        assert active_nav_group("equipment:list", "equipment") == "operacao"
        assert active_nav_group("equipment:detail", "equipment") == "operacao"
        assert active_nav_group("equipment:update", "equipment") == "operacao"

    def test_equipment_import_is_configuracoes(self):
        assert active_nav_group("equipment:import_upload", "equipment") == "configuracoes"
        assert active_nav_group("equipment:import_review", "equipment") == "configuracoes"
        assert active_nav_group("equipment:import_summary", "equipment") == "configuracoes"

    def test_maintenance_always_operacao(self):
        assert active_nav_group("maintenance:maintenance_list", "maintenance") == "operacao"
        assert active_nav_group("maintenance:cleaning_list", "maintenance") == "operacao"
        assert active_nav_group("maintenance:cleaning_detail", "maintenance") == "operacao"

    def test_clients_always_cadastros(self):
        assert active_nav_group("clients:list", "clients") == "cadastros"
        assert active_nav_group("clients:detail", "clients") == "cadastros"

    def test_catalog_always_cadastros(self):
        assert active_nav_group("catalog:category_list", "catalog") == "cadastros"
        assert active_nav_group("catalog:model_list", "catalog") == "cadastros"

    def test_accounts_user_routes_are_cadastros(self):
        assert active_nav_group("accounts:user_list", "accounts") == "cadastros"
        assert active_nav_group("accounts:user_create", "accounts") == "cadastros"
        assert active_nav_group("accounts:user_update", "accounts") == "cadastros"

    def test_accounts_role_routes_are_configuracoes(self):
        assert active_nav_group("accounts:role_list", "accounts") == "configuracoes"
        assert active_nav_group("accounts:role_create", "accounts") == "configuracoes"
        assert active_nav_group("accounts:role_update", "accounts") == "configuracoes"
        assert active_nav_group("accounts:role_delete", "accounts") == "configuracoes"

    def test_accounts_login_has_no_group(self):
        assert active_nav_group("accounts:login", "accounts") is None
        assert active_nav_group("accounts:logout", "accounts") is None

    def test_operations_location_routes_are_cadastros(self):
        assert active_nav_group("operations:location_list", "operations") == "cadastros"
        assert active_nav_group("operations:location_detail", "operations") == "cadastros"
        assert active_nav_group("operations:location_update", "operations") == "cadastros"
        assert active_nav_group("operations:location_address_update", "operations") == "cadastros"

    def test_operations_duplicate_report_is_configuracoes(self):
        assert active_nav_group("operations:duplicate_locations_report", "operations") == "configuracoes"

    def test_operations_movement_has_no_group(self):
        # Não existe item de menu para "movimentar equipamento" (acessado
        # a partir da ficha do equipamento, não da sidebar) — não deve
        # forçar nenhum grupo a abrir.
        assert active_nav_group("operations:movement_create", "operations") is None

    def test_unknown_app_has_no_group(self):
        assert active_nav_group("dashboard:home", "dashboard") is None
        assert active_nav_group("qrcodes:something", "qrcodes") is None
