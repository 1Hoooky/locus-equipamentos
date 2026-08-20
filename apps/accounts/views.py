"""
Gestão de usuários pela interface — especificação, seção 12 (tela
"Gestão de usuários"), substituindo o admin/shell do primeiro passo da
Fase 1. Restrita a Administrador (matriz da seção 11).
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.accounts.forms import UserCreateForm, UserUpdateForm
from apps.accounts.models import User
from apps.accounts.permissions import CAN_MANAGE_USERS, RoleRequiredMixin


class UserListView(RoleRequiredMixin, ListView):
    allowed_roles = CAN_MANAGE_USERS
    model = User
    template_name = "accounts/user_list.html"
    context_object_name = "users"

    def get_queryset(self):
        return User.objects.all().order_by("username")


class UserCreateView(RoleRequiredMixin, View):
    allowed_roles = CAN_MANAGE_USERS

    def get(self, request):
        return render(request, "accounts/user_form.html", {"form": UserCreateForm(), "is_new": True})

    def post(self, request):
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"Usuário {user.username} criado com sucesso.")
            return redirect("accounts:user_list")
        return render(request, "accounts/user_form.html", {"form": form, "is_new": True})


class UserUpdateView(RoleRequiredMixin, View):
    allowed_roles = CAN_MANAGE_USERS

    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        return render(request, "accounts/user_form.html", {"form": UserUpdateForm(instance=user), "is_new": False, "target_user": user})

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)

        if user.pk == request.user.pk and request.POST.get("is_active") != "on":
            messages.error(request, "Você não pode desativar a si mesmo.")
            return render(
                request,
                "accounts/user_form.html",
                {"form": UserUpdateForm(request.POST, instance=user), "is_new": False, "target_user": user},
            )

        form = UserUpdateForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f"Usuário {user.username} atualizado.")
            return redirect("accounts:user_list")
        return render(request, "accounts/user_form.html", {"form": form, "is_new": False, "target_user": user})
