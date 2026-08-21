from django.urls import path

from apps.catalog import views

app_name = "catalog"

urlpatterns = [
    path("categorias/", views.CategoryListView.as_view(), name="category_list"),
    path("categorias/nova/", views.CategoryCreateView.as_view(), name="category_create"),
    path("categorias/<int:pk>/editar/", views.CategoryUpdateView.as_view(), name="category_update"),
    path("modelos/", views.EquipmentModelListView.as_view(), name="model_list"),
    path("modelos/novo/", views.EquipmentModelCreateView.as_view(), name="model_create"),
    path("modelos/<int:pk>/editar/", views.EquipmentModelUpdateView.as_view(), name="model_update"),
]
