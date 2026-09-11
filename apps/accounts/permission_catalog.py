"""
Catálogo de Permissões "reais" (`django.contrib.auth.models.Permission`)
da nova arquitetura de Cargos — aprovada em 09/09/2026, auditoria de
Roles/Permissions.

As primeiras 18 entradas correspondem, 1 para 1, às constantes CAN_*
legadas de `apps/accounts/permissions.py` (`legacy_constant` preenchido).
A partir de 10/09/2026, o catálogo também passou a incluir módulos
nascidos direto na arquitetura nova, sem nenhum CAN_* equivalente — hoje
as 7 entradas do CRM (`legacy_constant=None`, ver bloco "CRM" abaixo).
Toda entrada foi declarada via `Meta.permissions` no modelo indicado
(ver comentários nesse mesmo arquivo e nos modelos referenciados). O
motivo de existir um catálogo Python separado, em vez de simplesmente
ler `Permission.objects.all()` direto do banco, é dar UM lugar estável e
ordenado para:

1. A migration de seed (`apps/accounts/migrations/000X_seed_cargos.py`),
   que cria os Cargos iniciais com as Permissions espelhando exatamente
   os CAN_* de hoje.
2. A tela de gestão de cargos (`apps/accounts/views_roles.py`), que só
   pode mostrar/marcar permissões deste catálogo — nunca os
   `add_`/`change_`/`delete_`/`view_` automáticos que o Django cria para
   TODO modelo (esses ainda não são checados por nenhuma view nesta
   rodada; expô-los na tela seria sugerir um controle que não existe de
   verdade).
3. Rastreabilidade explícita: qual CAN_* legado cada Permission nova
   representa, e o rótulo do módulo (agrupamento na tela).

IMPORTANTE — isto NÃO substitui `apps/accounts/permissions.py` nesta
rodada. Os `CAN_*` e o `RoleRequiredMixin` continuam sendo a autorização
de fato em toda view existente. Este catálogo é fundação aditiva para a
migração futura, app por app (ver relatório de aprovação da
arquitetura).

Classificação de sensibilidade (3 níveis, adjustment #3 da aprovação):
  (A) Permissões operacionais configuráveis — a maioria das entradas
      abaixo; hoje concedidas a vários perfis legados.
  (B) Permissões sensíveis — hoje só Administrador tem (marcadas
      `legacy_admin_only=True` abaixo), mas continuam sendo Permission
      normais, elegíveis para o checklist da tela de cargos (podem, no
      futuro, ser concedidas a outro cargo pela própria interface, sem
      mudança de código).
  (C) Ações de segurança do sistema — NÃO estão neste catálogo. São as
      ações da própria tela de gestão de cargos/permissões (criar
      cargo, editar permissões de um cargo, proteger Administrador,
      etc.) — permanecem exclusivamente `is_superuser` no código
      (`apps/accounts/views_roles.py`), nunca uma Permission
      concedível, para não abrir caminho de auto-escalação de
      privilégio.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionSpec:
    codename: str
    app_label: str
    model: str  # nome do modelo (minúsculo) onde o Meta.permissions foi declarado
    # constante CAN_* correspondente, só para rastreabilidade/documentação.
    # `None` == a permissão NÃO tem equivalente legado (nasceu direto na
    # arquitetura nova — caso do CRM, ver apps/crm/models.py): não é
    # espelhada para nenhum Cargo legado na migration de seed
    # (0003_seed_cargos.py `codenames_for_role()` pula essas entradas),
    # só passa a valer para um Cargo quando um Administrador marcar
    # explicitamente pela tela de gestão de cargos.
    legacy_constant: str | None = None
    legacy_admin_only: bool = False  # True == hoje só Role.ADMIN tem (tier B); False == vários perfis legados já têm (tier A)

    @property
    def full_codename(self) -> str:
        return f"{self.app_label}.{self.codename}"


# Ordem = ordem de exibição na tela de cargos, agrupada por módulo
# (MODULE_LABELS abaixo). Mantida na mesma ordem em que os CAN_*
# aparecem em apps/accounts/permissions.py.
PERMISSION_CATALOG: tuple[PermissionSpec, ...] = (
    PermissionSpec("manage_users", "accounts", "user", "CAN_MANAGE_USERS", legacy_admin_only=True),
    PermissionSpec("manage_catalog", "catalog", "equipmentmodel", "CAN_MANAGE_CATALOG", legacy_admin_only=False),
    PermissionSpec(
        "reclassify_equipment_model", "catalog", "equipmentmodel", "CAN_RECLASSIFY_EQUIPMENT_MODEL", legacy_admin_only=True
    ),
    PermissionSpec("manage_equipment", "equipment", "equipment", "CAN_MANAGE_EQUIPMENT", legacy_admin_only=False),
    PermissionSpec(
        "view_acquisition_value", "equipment", "equipment", "CAN_VIEW_ACQUISITION_VALUE", legacy_admin_only=False
    ),
    PermissionSpec(
        "change_status_condition", "equipment", "equipment", "CAN_CHANGE_STATUS_CONDITION", legacy_admin_only=False
    ),
    PermissionSpec("add_photos", "equipment", "equipment", "CAN_ADD_PHOTOS", legacy_admin_only=False),
    PermissionSpec("export_data", "equipment", "equipment", "CAN_EXPORT_DATA", legacy_admin_only=False),
    PermissionSpec(
        "import_legacy_spreadsheet",
        "equipment",
        "equipment",
        "CAN_IMPORT_LEGACY_SPREADSHEET",
        legacy_admin_only=True,
    ),
    PermissionSpec("supersede_equipment", "equipment", "equipment", "CAN_SUPERSEDE_EQUIPMENT", legacy_admin_only=True),
    PermissionSpec("register_operations", "operations", "movement", "CAN_REGISTER_OPERATIONS", legacy_admin_only=False),
    PermissionSpec("view_diagnostics", "operations", "location", "CAN_VIEW_DIAGNOSTICS", legacy_admin_only=True),
    PermissionSpec("manage_locations", "operations", "location", "CAN_MANAGE_LOCATIONS", legacy_admin_only=False),
    PermissionSpec("view_movements", "operations", "movement", "CAN_VIEW_MOVEMENTS", legacy_admin_only=False),
    PermissionSpec("view_clients", "clients", "client", "CAN_VIEW_CLIENTS", legacy_admin_only=False),
    PermissionSpec("manage_clients", "clients", "client", "CAN_MANAGE_CLIENTS", legacy_admin_only=False),
    PermissionSpec("import_clients", "clients", "client", "CAN_IMPORT_CLIENTS", legacy_admin_only=True),
    PermissionSpec(
        "view_maintenance_and_cleaning", "maintenance", "maintenance", "CAN_VIEW_MAINTENANCE", legacy_admin_only=False
    ),
    # ------------------------------------------------------------------
    # CRM (LocusHub, Etapa 1 — 10/09/2026). Único módulo do catálogo sem
    # nenhum CAN_* legado correspondente (`legacy_constant` usa o default
    # `None`): nasceu 100% na arquitetura nova, por pedido explícito —
    # nenhuma destas 7 é espelhada para nenhum Cargo legado pela
    # migration de seed (ver 0003_seed_cargos.py `codenames_for_role()`).
    # `legacy_admin_only` também fica no default (`False`) nas 7 — o
    # campo documenta quem tinha a permissão no sistema LEGADO, e não
    # existe "hoje" nenhum Role legado com acesso a CRM para comparar;
    # NÃO deve ser lido como "estas permissões podem ser dadas a
    # qualquer cargo sem restrição adicional" (ver decisão pendente
    # sobre `manage_commercial_settings` no relatório final).
    PermissionSpec("view_opportunities", "crm", "opportunity"),
    PermissionSpec("add_opportunities", "crm", "opportunity"),
    PermissionSpec("change_opportunities", "crm", "opportunity"),
    PermissionSpec("change_opportunity_stage", "crm", "opportunity"),
    PermissionSpec("view_commercial_activities", "crm", "commercialactivity"),
    PermissionSpec("add_commercial_activities", "crm", "commercialactivity"),
    PermissionSpec("manage_commercial_settings", "crm", "commercialsource"),
)

# Nome amigável do módulo (app) para agrupar a tela de cargos —
# dicionário simples, não uma tabela nova no banco (decisão explícita da
# aprovação: só criar tabela nova se comprovadamente necessário).
MODULE_LABELS: dict[str, str] = {
    "accounts": "Usuários",
    "catalog": "Catálogo",
    "equipment": "Equipamentos",
    "operations": "Operações",
    "clients": "Clientes",
    "maintenance": "Manutenção",
    "crm": "CRM",
}


def get_spec_by_full_codename(full_codename: str) -> PermissionSpec | None:
    for spec in PERMISSION_CATALOG:
        if spec.full_codename == full_codename:
            return spec
    return None
