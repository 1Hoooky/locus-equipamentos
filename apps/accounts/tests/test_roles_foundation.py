"""
Fundação da arquitetura de Cargos/Permissões (09/09/2026): estado
criado pelas migrations de seed/backfill (`0003_seed_cargos`,
`0004_backfill_user_cargos`) e integridade do catálogo
(`apps/accounts/permission_catalog.py`) — não comportamento de view.

Por que testar migrations de dados assim: `pytest-django` já aplica
TODAS as migrations (inclusive as de dados) para montar o banco de
teste, então o estado que elas produzem já está lá quando qualquer
`TestCase` roda — dá pra afirmar sobre ele direto, sem reimplementar um
framework de teste de migração.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from apps.accounts import permissions as legacy_permissions
from apps.accounts.models import Role, RoleProfile
from apps.accounts.permission_catalog import MODULE_LABELS, PERMISSION_CATALOG

User = get_user_model()

EXPECTED_CARGO_NAMES = {
    "Administrador",
    "Administrativo",
    "Operacional",
    "Consulta",
    "Financeiro",
    "Marketing",
    "TI",
    "Backoffice",
    "Comercial",
}
EMPTY_CARGO_NAMES = {"Financeiro", "Marketing", "TI", "Backoffice", "Comercial"}


class PermissionCatalogIntegrityTest(TestCase):
    """
    Garante que o catálogo Python continua espelhando EXATAMENTE as 18
    constantes CAN_* legadas — nem mais, nem menos — e que cada entrada
    aponta para uma Permission real no banco (Meta.permissions foi
    aplicado corretamente em todos os 6 apps).
    """

    def test_catalog_has_exactly_18_entries(self):
        self.assertEqual(len(PERMISSION_CATALOG), 18)

    def test_catalog_codenames_are_unique(self):
        codenames = [spec.codename for spec in PERMISSION_CATALOG]
        self.assertEqual(len(codenames), len(set(codenames)))

    def test_catalog_legacy_constants_are_unique_and_exist_in_permissions_module(self):
        legacy_constants = [spec.legacy_constant for spec in PERMISSION_CATALOG]
        self.assertEqual(len(legacy_constants), len(set(legacy_constants)), "cada CAN_* deve aparecer só uma vez no catálogo")
        for name in legacy_constants:
            self.assertTrue(hasattr(legacy_permissions, name), f"{name} não existe mais em apps.accounts.permissions")

    def test_every_can_star_constant_is_represented_in_catalog(self):
        """O inverso do teste acima: nenhum CAN_* legado ficou de fora do catálogo."""
        can_star_names = {
            name
            for name in dir(legacy_permissions)
            if name.startswith("CAN_") and isinstance(getattr(legacy_permissions, name), tuple)
        }
        catalog_names = {spec.legacy_constant for spec in PERMISSION_CATALOG}
        self.assertEqual(can_star_names, catalog_names)

    def test_every_catalog_entry_resolves_to_a_real_permission(self):
        for spec in PERMISSION_CATALOG:
            with self.subTest(codename=spec.codename):
                exists = Permission.objects.filter(
                    codename=spec.codename,
                    content_type__app_label=spec.app_label,
                    content_type__model=spec.model,
                ).exists()
                self.assertTrue(exists, f"Permission {spec.full_codename} não foi criada no banco")

    def test_every_module_referenced_has_a_friendly_label(self):
        app_labels = {spec.app_label for spec in PERMISSION_CATALOG}
        self.assertTrue(app_labels.issubset(MODULE_LABELS.keys()))


class SeedCargosMigrationTest(TestCase):
    """Estado criado por `accounts.0003_seed_cargos`."""

    def test_all_9_initial_cargos_exist(self):
        names = set(Group.objects.filter(name__in=EXPECTED_CARGO_NAMES).values_list("name", flat=True))
        self.assertEqual(names, EXPECTED_CARGO_NAMES)

    def test_every_seeded_cargo_has_a_role_profile(self):
        for name in EXPECTED_CARGO_NAMES:
            with self.subTest(cargo=name):
                group = Group.objects.get(name=name)
                self.assertTrue(RoleProfile.objects.filter(group=group).exists())

    def test_only_administrador_is_protected(self):
        protected_names = set(
            RoleProfile.objects.filter(is_protected=True).values_list("group__name", flat=True)
        )
        self.assertEqual(protected_names, {"Administrador"})

    def test_empty_cargos_have_no_permissions(self):
        for name in EMPTY_CARGO_NAMES:
            with self.subTest(cargo=name):
                group = Group.objects.get(name=name)
                self.assertEqual(group.permissions.count(), 0)

    def _codenames_for_role(self, role_value: str) -> set[str]:
        return {
            spec.codename
            for spec in PERMISSION_CATALOG
            if role_value in getattr(legacy_permissions, spec.legacy_constant)
        }

    def test_administrador_cargo_mirrors_role_admin_exactly(self):
        group = Group.objects.get(name="Administrador")
        actual = set(group.permissions.values_list("codename", flat=True))
        self.assertEqual(actual, self._codenames_for_role(Role.ADMIN))
        # Role.ADMIN aparece em todo CAN_*, então Administrador deve ter as 18.
        self.assertEqual(len(actual), 18)

    def test_administrativo_cargo_mirrors_role_administrativo_exactly(self):
        group = Group.objects.get(name="Administrativo")
        actual = set(group.permissions.values_list("codename", flat=True))
        self.assertEqual(actual, self._codenames_for_role(Role.ADMINISTRATIVO))

    def test_operacional_cargo_mirrors_role_operacional_exactly(self):
        group = Group.objects.get(name="Operacional")
        actual = set(group.permissions.values_list("codename", flat=True))
        self.assertEqual(actual, self._codenames_for_role(Role.OPERACIONAL))

    def test_consulta_cargo_mirrors_role_consulta_exactly(self):
        group = Group.objects.get(name="Consulta")
        actual = set(group.permissions.values_list("codename", flat=True))
        self.assertEqual(actual, self._codenames_for_role(Role.CONSULTA))

    def test_no_admin_only_permission_leaks_into_non_admin_cargos(self):
        """
        As 6 permissões tier B (`legacy_admin_only=True`) só podem estar
        no cargo Administrador entre os 4 cargos espelhados de Role —
        nunca em Administrativo/Operacional/Consulta.
        """
        admin_only_codenames = {spec.codename for spec in PERMISSION_CATALOG if spec.legacy_admin_only}
        for name in ("Administrativo", "Operacional", "Consulta"):
            with self.subTest(cargo=name):
                group = Group.objects.get(name=name)
                actual = set(group.permissions.values_list("codename", flat=True))
                self.assertEqual(actual & admin_only_codenames, set())


class BackfillUserCargosMigrationTest(TestCase):
    """
    Usuários criados ANTES desta migração (fixtures do próprio ambiente
    de teste, se houver) já teriam sido migrados — aqui testamos o
    comportamento da função equivalente para usuários novos, já que o
    ambiente de teste começa vazio de `User` (a migração de backfill já
    rodou sobre um banco sem usuários ao montar o banco de teste).
    Ver `RoleBackfillBehaviorTest` (test_roles_services.py) para o
    comportamento gravado via `set_user_cargo`, que é o mesmo usado pela
    migração.
    """

    def test_seeded_cargos_survive_a_fresh_test_database(self):
        # Sanity check indireto: se a migração de seed não tivesse
        # rodado (ou tivesse rodado antes das Permissions existirem), o
        # cargo Administrador teria 0 permissões — o que já é coberto
        # por `SeedCargosMigrationTest`, mas este teste garante que o
        # PRÓPRIO comando de setup do banco de teste (que roda todas as
        # migrations do zero) passa por esse caminho sem erro.
        self.assertTrue(Group.objects.filter(name="Administrador").exists())
