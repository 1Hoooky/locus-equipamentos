"""
Telas próprias de categoria/modelo — especificação, seção 12 ("Cadastro/
edição de categoria", "Cadastro/edição de modelo"). Fecham a Fase 1
substituindo o Django admin como interface operacional (Django admin
passa a ser só ferramenta técnica/contingência).
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.accounts.permissions import CAN_MANAGE_CATALOG, RoleRequiredMixin
from apps.catalog.forms import CategoryForm, EquipmentModelForm
from apps.catalog.models import Category, EquipmentModel


class CategoryListView(RoleRequiredMixin, ListView):
    allowed_roles = CAN_MANAGE_CATALOG
    model = Category
    template_name = "catalog/category_list.html"
    context_object_name = "categories"

    def get_queryset(self):
        return Category.objects.all().order_by("name")


class CategoryCreateView(RoleRequiredMixin, View):
    allowed_roles = CAN_MANAGE_CATALOG

    def get(self, request):
        return render(request, "catalog/category_form.html", {"form": CategoryForm(), "is_new": True})

    def post(self, request):
        form = CategoryForm(request.POST)
        if form.is_valid():
            category = form.save()
            messages.success(request, f"Categoria {category.name} criada.")
            return redirect("catalog:category_list")
        return render(request, "catalog/category_form.html", {"form": form, "is_new": True})


class CategoryUpdateView(RoleRequiredMixin, View):
    allowed_roles = CAN_MANAGE_CATALOG

    def get(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        return render(
            request, "catalog/category_form.html", {"form": CategoryForm(instance=category), "is_new": False, "category": category}
        )

    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, f"Categoria {category.name} atualizada.")
            return redirect("catalog:category_list")
        return render(
            request, "catalog/category_form.html", {"form": form, "is_new": False, "category": category}
        )


class EquipmentModelListView(RoleRequiredMixin, ListView):
    allowed_roles = CAN_MANAGE_CATALOG
    model = EquipmentModel
    template_name = "catalog/model_list.html"
    context_object_name = "models"

    def get_queryset(self):
        return EquipmentModel.objects.select_related("category").order_by("category__name", "name")


class EquipmentModelCreateView(RoleRequiredMixin, View):
    allowed_roles = CAN_MANAGE_CATALOG

    def get(self, request):
        return render(request, "catalog/model_form.html", {"form": EquipmentModelForm(), "is_new": True})

    def post(self, request):
        form = EquipmentModelForm(request.POST)
        if form.is_valid():
            model = form.save()
            messages.success(request, f"Modelo {model} criado.")
            return redirect("catalog:model_list")
        return render(request, "catalog/model_form.html", {"form": form, "is_new": True})


class EquipmentModelUpdateView(RoleRequiredMixin, View):
    allowed_roles = CAN_MANAGE_CATALOG

    def get(self, request, pk):
        model = get_object_or_404(EquipmentModel, pk=pk)
        return render(
            request, "catalog/model_form.html", {"form": EquipmentModelForm(instance=model), "is_new": False, "equipment_model": model}
        )

    def post(self, request, pk):
        model = get_object_or_404(EquipmentModel, pk=pk)
        form = EquipmentModelForm(request.POST, instance=model)
        if form.is_valid():
            form.save()
            messages.success(request, f"Modelo {model} atualizado.")
            return redirect("catalog:model_list")
        return render(
            request, "catalog/model_form.html", {"form": form, "is_new": False, "equipment_model": model}
        )
