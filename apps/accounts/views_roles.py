"""
Gestão de Cargos (Grupos + Permissões) — arquitetura aprovada em
09/09/2026 (ver apps/accounts/permission_catalog.py e apps/accounts/
services.py). Tela restrita a SUPERUSUÁRIO (`SuperuserRequiredMixin`,
Nível C de sensibilidade) — não a Administrador (`Role.ADMIN`/CAN_*), de
propósito: gerenciar quem tem quais permissões é a própria "chave mestra"
do sistema de autorização, então fica fora do que uma Permission pode
conceder (ver docstring de `SuperuserRequiredMixin`).

Cargo "protegido" (hoje só Administrador) não pode ser editado/excluído
por aqui — a tela mostra a mensagem "acesso total" e desabilita o
formulário em vez de aceitar o POST (a garantia de fato está em
`apps.accounts.services`, chamada aqui, não só escondida no template).
"""

from django.contrib import messages
from django.contrib.auth.models import Group
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.accounts.forms import CargoForm, permission_catalog_queryset
from apps.accounts.permission_catalog import MODULE_LABELS, PERMISSION_CATALOG
from apps.accounts.permissions import SuperuserRequiredMixin
from apps.accounts.services import CargoData, CargoError, create_cargo, delete_cargo, update_cargo


def _build_permission_groups(checked_ids: set[int]) -> list[dict]:
    """
    Monta o checklist agrupado por módulo (nome amigável em
    `MODULE_LABELS`, ordem/composição de `PERMISSION_CATALOG`) para o
    template renderizar manualmente — deliberadamente NÃO usa
    `{{ form.permissions }}` (o widget `CheckboxSelectMultiple` padrão
    renderiza tudo numa lista plana, sem seções). Cada item leva
    `name="permissions"` no template, então o Django processa o POST do
    mesmo jeito que processaria o widget padrão — só a apresentação
    muda, a validação continua 100% em `CargoForm`.
    """
    permissions_by_codename = {p.codename: p for p in permission_catalog_queryset()}
    module_order = list(dict.fromkeys(spec.app_label for spec in PERMISSION_CATALOG))

    grouped = []
    for app_label in module_order:
        items = []
        for spec in PERMISSION_CATALOG:
            if spec.app_label != app_label:
                continue
            permission = permissions_by_codename.get(spec.codename)
            if permission is None:
                continue
            items.append(
                {
                    "id": permission.pk,
                    "codename": spec.codename,
                    "label": permission.name,
                    "checked": permission.pk in checked_ids,
                }
            )
        if items:
            grouped.append({"module_label": MODULE_LABELS.get(app_label, app_label), "items": items})
    return grouped


class RoleListView(SuperuserRequiredMixin, ListView):
    model = Group
    template_name = "accounts/role_list.html"
    context_object_name = "cargos"

    def get_queryset(self):
        return Group.objects.select_related("profile").order_by("name")


class RoleCreateView(SuperuserRequiredMixin, View):
    def get(self, request):
        form = CargoForm()
        context = {"form": form, "is_new": True, "permission_groups": _build_permission_groups(set())}
        return render(request, "accounts/role_form.html", context)

    def post(self, request):
        form = CargoForm(request.POST)
        if form.is_valid():
            try:
                cargo = create_cargo(
                    CargoData(
                        name=form.cleaned_data["name"],
                        description=form.cleaned_data["description"],
                        permission_codenames=[p.codename for p in form.cleaned_data["permissions"]],
                    )
                )
            except CargoError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, f'Cargo "{cargo.name}" criado com sucesso.')
                return redirect("accounts:role_list")

        # Re-renderiza com os checkboxes que o usuário tinha marcado
        # antes do erro — os IDs vêm crus do POST (strings), sem
        # depender do form já ter validado/limpo o campo.
        try:
            checked_ids = {int(pk) for pk in request.POST.getlist("permissions")}
        except (TypeError, ValueError):
            checked_ids = set()
        context = {"form": form, "is_new": True, "permission_groups": _build_permission_groups(checked_ids)}
        return render(request, "accounts/role_form.html", context)


class RoleUpdateView(SuperuserRequiredMixin, View):
    def get(self, request, pk):
        group = get_object_or_404(Group.objects.select_related("profile"), pk=pk)
        is_protected = getattr(group, "profile", None) and group.profile.is_protected
        form = CargoForm(
            initial={
                "name": group.name,
                "description": getattr(group, "profile", None) and group.profile.description or "",
            }
        )
        checked_ids = set(group.permissions.values_list("pk", flat=True))
        context = {
            "form": form,
            "is_new": False,
            "cargo": group,
            "is_protected": is_protected,
            "permission_groups": _build_permission_groups(checked_ids),
        }
        return render(request, "accounts/role_form.html", context)

    def post(self, request, pk):
        group = get_object_or_404(Group.objects.select_related("profile"), pk=pk)
        is_protected = getattr(group, "profile", None) and group.profile.is_protected
        if is_protected:
            messages.error(request, f'O cargo "{group.name}" é protegido pelo sistema e não pode ser editado.')
            return redirect("accounts:role_list")

        form = CargoForm(request.POST)
        if form.is_valid():
            try:
                update_cargo(
                    group,
                    CargoData(
                        name=form.cleaned_data["name"],
                        description=form.cleaned_data["description"],
                        permission_codenames=[p.codename for p in form.cleaned_data["permissions"]],
                    ),
                )
            except CargoError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, f'Cargo "{form.cleaned_data["name"]}" atualizado.')
                return redirect("accounts:role_list")

        try:
            checked_ids = {int(pk_) for pk_ in request.POST.getlist("permissions")}
        except (TypeError, ValueError):
            checked_ids = set()
        context = {
            "form": form,
            "is_new": False,
            "cargo": group,
            "is_protected": is_protected,
            "permission_groups": _build_permission_groups(checked_ids),
        }
        return render(request, "accounts/role_form.html", context)


class RoleDeleteView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        group = get_object_or_404(Group.objects.select_related("profile"), pk=pk)
        try:
            delete_cargo(group)
        except CargoError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f'Cargo "{group.name}" excluído.')
        return redirect("accounts:role_list")
