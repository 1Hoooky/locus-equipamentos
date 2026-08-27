from django.urls import path

from apps.maintenance import views

app_name = "maintenance"

urlpatterns = [
    path("manutencoes/", views.MaintenanceListView.as_view(), name="maintenance_list"),
    path("manutencoes/abrir/", views.MaintenanceOpenView.as_view(), name="maintenance_open"),
    path(
        "manutencoes/abrir/movimentos-envio/",
        views.DepartureMovementOptionsView.as_view(),
        name="departure_movement_options",
    ),
    path("manutencoes/<int:pk>/", views.MaintenanceDetailView.as_view(), name="maintenance_detail"),
    path("manutencoes/<int:pk>/concluir/", views.MaintenanceCloseView.as_view(), name="maintenance_close"),
    path("manutencoes/<int:pk>/cancelar/", views.MaintenanceCancelView.as_view(), name="maintenance_cancel"),
    path("higienizacoes/", views.CleaningListView.as_view(), name="cleaning_list"),
    path("higienizacoes/registrar/", views.CleaningCreateView.as_view(), name="cleaning_create"),
    path("higienizacoes/<int:pk>/", views.CleaningDetailView.as_view(), name="cleaning_detail"),
    path("higienizacoes/<int:pk>/cancelar/", views.CleaningCancelView.as_view(), name="cleaning_cancel"),
]
