"""
Formulários de gestão de usuários — especificação, seção 12 (tela
"Gestão de usuários": criar usuário, definir perfil, ativar/desativar),
restrita a Administrador (seção 11).

`CargoForm` (arquitetura de Cargos/Permissões, 09/09/2026) é um
`forms.Form` simples, não um `ModelForm` de `Group` — o checklist de
permissões nunca expõe o catálogo automático `add_`/`change_`/`delete_`/
`view_` do Django, só as Permissions de `PERMISSION_CATALOG`
(apps/accounts/permission_catalog.py). A view (`apps/accounts/
views_roles.py`) monta os dados agrupados por módulo para o template a
partir do MESMO catálogo, na mesma ordem.
"""

from functools import reduce
from operator import or_

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group, Permission
from django.db.models import Q

from apps.accounts.models import User
from apps.accounts.permission_catalog import PERMISSION_CATALOG


def permission_catalog_queryset():
    """
    Filtra por (app_label, model, codename) — não só `codename` — para
    nunca depender da coincidência de o catálogo hoje ter codenames sem
    colisão entre si; a unicidade real de uma `Permission` no Django é
    (content_type, codename), então é essa combinação que precisamos
    espelhar aqui.
    """
    filters = [
        Q(codename=spec.codename, content_type__app_label=spec.app_label, content_type__model=spec.model)
        for spec in PERMISSION_CATALOG
    ]
    return Permission.objects.filter(reduce(or_, filters)) if filters else Permission.objects.none()


TEXT_INPUT_CLASS = "field-input"

CARGO_FIELD_HELP_TEXT = (
    "Cargo (grupo de permissões) do usuário — arquitetura nova de Cargos/Permissões, em "
    "paralelo ao Perfil acima nesta rodada. Escolher um cargo aqui SUBSTITUI qualquer cargo "
    "anterior do usuário (nunca acumula mais de um)."
)


class _CargoAssignmentMixin(forms.Form):
    """
    Campo de atribuição de Cargo, compartilhado por `UserCreateForm` e
    `UserUpdateForm`. Deliberadamente um único `ModelChoiceField` (não
    `ModelMultipleChoiceField`) — a interface do LocusHub nunca oferece
    escolher mais de um cargo por usuário, mesmo o `Group` M2M do Django
    tecnicamente permitindo (ver `apps.accounts.services.set_user_cargo`,
    o único caminho que de fato grava essa escolha).
    """

    cargo = forms.ModelChoiceField(
        queryset=Group.objects.all().order_by("name"),
        required=False,
        label="Cargo",
        help_text=CARGO_FIELD_HELP_TEXT,
    )


class UserCreateForm(_CargoAssignmentMixin, UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "role")
        labels = {"role": "Perfil"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)


class UserUpdateForm(_CargoAssignmentMixin, forms.ModelForm):
    """
    Edição de um usuário existente: perfil e ativo/inativo (desligamento
    de acesso sem apagar o registro nem seu histórico de autoria — a
    mesma lógica de soft delete do resto do sistema, especificação
    seção 5). Troca de senha continua pelo fluxo de "esqueci minha senha"
    (apps/accounts/urls.py), não por aqui.
    """

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "role", "is_active")
        labels = {"role": "Perfil"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["cargo"].initial = self.instance.cargo
        for name, field in self.fields.items():
            if name != "is_active":
                field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)


class CargoForm(forms.Form):
    """
    Criar/editar um Cargo (`Group` + `RoleProfile`) — tela restrita a
    superusuário (`SuperuserRequiredMixin`, Nível C). O checklist de
    permissões só mostra o catálogo oficial (`PERMISSION_CATALOG`),
    agrupado por módulo pela própria view — nunca os `add_`/`change_`/
    `delete_`/`view_` automáticos do Django.
    """

    name = forms.CharField(label="Nome do cargo", max_length=150, widget=forms.TextInput(attrs={"class": TEXT_INPUT_CLASS}))
    description = forms.CharField(
        label="Descrição",
        required=False,
        widget=forms.Textarea(attrs={"class": TEXT_INPUT_CLASS, "rows": 3}),
    )
    permissions = forms.ModelMultipleChoiceField(
        label="Permissões",
        required=False,
        queryset=permission_catalog_queryset(),
        widget=forms.CheckboxSelectMultiple,
    )
