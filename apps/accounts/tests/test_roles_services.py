"""
`apps/accounts/services.py` — único caminho suportado para atribuir
cargo a um usuário e para criar/editar/excluir um cargo. O ponto central
destes testes é a invariante de "um cargo por usuário" (adjustment #1 da
aprovação da arquitetura, 09/09/2026): `set_user_cargo()` deve sempre
SUBSTITUIR, nunca acumular.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from django.test import TestCase

from apps.accounts.models import RoleProfile
from apps.accounts.services import (
    CargoData,
    CargoError,
    create_cargo,
    delete_cargo,
    set_user_cargo,
    update_cargo,
)

User = get_user_model()


class SetUserCargoTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="cargo_user", password="senha-forte-123")
        self.cargo_a = Group.objects.get(name="Administrativo")
        self.cargo_b = Group.objects.get(name="Operacional")

    def test_assigns_a_single_cargo(self):
        set_user_cargo(self.user, self.cargo_a)
        self.assertEqual(list(self.user.groups.all()), [self.cargo_a])

    def test_reassigning_replaces_instead_of_accumulating(self):
        set_user_cargo(self.user, self.cargo_a)
        set_user_cargo(self.user, self.cargo_b)
        self.assertEqual(list(self.user.groups.all()), [self.cargo_b])
        self.assertEqual(self.user.groups.count(), 1)

    def test_assigning_the_same_cargo_twice_stays_single(self):
        set_user_cargo(self.user, self.cargo_a)
        set_user_cargo(self.user, self.cargo_a)
        self.assertEqual(self.user.groups.count(), 1)

    def test_none_clears_the_cargo(self):
        set_user_cargo(self.user, self.cargo_a)
        set_user_cargo(self.user, None)
        self.assertEqual(self.user.groups.count(), 0)

    def test_user_cargo_property_reflects_the_single_group(self):
        self.assertIsNone(self.user.cargo)
        set_user_cargo(self.user, self.cargo_a)
        self.assertEqual(self.user.cargo, self.cargo_a)


class CreateCargoTest(TestCase):
    def test_creates_group_and_profile(self):
        cargo = create_cargo(CargoData(name="Suporte", description="Equipe de suporte", permission_codenames=["view_clients"]))
        self.assertTrue(Group.objects.filter(name="Suporte").exists())
        profile = RoleProfile.objects.get(group=cargo)
        self.assertEqual(profile.description, "Equipe de suporte")
        self.assertFalse(profile.is_protected)
        self.assertEqual(list(cargo.permissions.values_list("codename", flat=True)), ["view_clients"])

    def test_rejects_duplicate_name_case_insensitive(self):
        create_cargo(CargoData(name="Suporte"))
        with self.assertRaises(CargoError):
            create_cargo(CargoData(name="suporte"))

    def test_rejects_blank_name(self):
        with self.assertRaises(CargoError):
            create_cargo(CargoData(name="   "))

    def test_rejects_unknown_permission_codename(self):
        with self.assertRaises(CargoError):
            create_cargo(CargoData(name="Suporte", permission_codenames=["add_user"]))  # perm automática do Django, fora do catálogo

    def test_new_cargo_is_never_protected(self):
        cargo = create_cargo(CargoData(name="Suporte"))
        self.assertFalse(cargo.profile.is_protected)


class UpdateCargoTest(TestCase):
    def test_updates_name_description_and_permissions(self):
        cargo = create_cargo(CargoData(name="Suporte", permission_codenames=["view_clients"]))
        update_cargo(
            cargo,
            CargoData(name="Suporte N2", description="Atualizado", permission_codenames=["view_clients", "manage_clients"]),
        )
        cargo.refresh_from_db()
        self.assertEqual(cargo.name, "Suporte N2")
        self.assertEqual(cargo.profile.description, "Atualizado")
        self.assertEqual(
            set(cargo.permissions.values_list("codename", flat=True)), {"view_clients", "manage_clients"}
        )

    def test_rejects_editing_protected_cargo(self):
        admin_cargo = Group.objects.get(name="Administrador")
        with self.assertRaises(CargoError):
            update_cargo(admin_cargo, CargoData(name="Administrador Renomeado"))
        admin_cargo.refresh_from_db()
        self.assertEqual(admin_cargo.name, "Administrador")

    def test_rejects_renaming_to_an_existing_name(self):
        create_cargo(CargoData(name="Suporte"))
        other = create_cargo(CargoData(name="Outro"))
        with self.assertRaises(CargoError):
            update_cargo(other, CargoData(name="suporte"))


class DeleteCargoTest(TestCase):
    def test_deletes_an_empty_unprotected_cargo(self):
        cargo = create_cargo(CargoData(name="Descartável"))
        delete_cargo(cargo)
        self.assertFalse(Group.objects.filter(name="Descartável").exists())

    def test_rejects_deleting_protected_cargo(self):
        admin_cargo = Group.objects.get(name="Administrador")
        with self.assertRaises(CargoError):
            delete_cargo(admin_cargo)
        self.assertTrue(Group.objects.filter(name="Administrador").exists())

    def test_rejects_deleting_cargo_with_users_assigned(self):
        cargo = create_cargo(CargoData(name="Com usuário"))
        user = User.objects.create_user(username="cargo_delete_user", password="senha-forte-123")
        set_user_cargo(user, cargo)
        with self.assertRaises(CargoError):
            delete_cargo(cargo)
        self.assertTrue(Group.objects.filter(name="Com usuário").exists())
