from django.urls import path

from apps.operations import views

app_name = "operations"

urlpatterns = [
    path("unidades/", views.LocationListView.as_view(), name="location_list"),
    path("unidades/novo/", views.LocationCreateView.as_view(), name="location_create"),
    path("unidades/<int:pk>/", views.LocationDetailView.as_view(), name="location_detail"),
    path("unidades/<int:pk>/editar/", views.LocationUpdateView.as_view(), name="location_update"),
    path("unidades/<int:pk>/endereco/", views.LocationAddressUpdateView.as_view(), name="location_address_update"),
    path("movimentar/<str:patrimonio>/", views.MovementCreateView.as_view(), name="movement_create"),
    # Ferramenta TEMPORÁRIA (ver DuplicateLocationsReportView) — remover
    # esta rota junto com a view/template depois da limpeza dos dados de
    # teste.
    path(
        "diagnostico/locations-duplicadas/",
        views.DuplicateLocationsReportView.as_view(),
        name="duplicate_locations_report",
    ),
]
