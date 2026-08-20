from django.urls import path

from apps.equipment import views

app_name = "equipment"

urlpatterns = [
    path("", views.EquipmentListView.as_view(), name="list"),
    path("<str:patrimonio>/", views.EquipmentDetailView.as_view(), name="detail"),
]
