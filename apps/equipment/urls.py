from django.urls import path

from apps.equipment import views

app_name = "equipment"

urlpatterns = [
    path("", views.EquipmentListView.as_view(), name="list"),
    # Precisa vir antes do catch-all abaixo, senão "exportar" seria
    # interpretado como um patrimônio.
    path("exportar/", views.EquipmentExportView.as_view(), name="export"),
    path("<str:patrimonio>/", views.EquipmentDetailView.as_view(), name="detail"),
]
