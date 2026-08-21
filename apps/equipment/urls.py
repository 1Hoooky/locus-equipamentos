from django.urls import path

from apps.equipment import views, views_import

app_name = "equipment"

urlpatterns = [
    path("", views.EquipmentListView.as_view(), name="list"),
    # Precisam vir antes do catch-all abaixo, senão seriam interpretados
    # como um patrimônio (ex.: "exportar" viraria patrimonio="exportar").
    path("novo/", views.EquipmentCreateView.as_view(), name="create"),
    path("exportar/", views.EquipmentExportView.as_view(), name="export"),
    path("importar/", views_import.LegacyImportUploadView.as_view(), name="import_upload"),
    path("importar/revisar/", views_import.LegacyImportReviewView.as_view(), name="import_review"),
    path("importar/resumo/", views_import.LegacyImportSummaryView.as_view(), name="import_summary"),
    path("<str:patrimonio>/", views.EquipmentDetailView.as_view(), name="detail"),
    path("<str:patrimonio>/editar/", views.EquipmentUpdateView.as_view(), name="update"),
    path("<str:patrimonio>/status/", views.EquipmentChangeStatusView.as_view(), name="change_status"),
    path("<str:patrimonio>/condicao/", views.EquipmentChangeConditionView.as_view(), name="change_condition"),
    path("<str:patrimonio>/reclassificar/", views.EquipmentReclassifyView.as_view(), name="reclassify"),
    path("<str:patrimonio>/reemitir/", views.EquipmentSupersedeView.as_view(), name="supersede"),
]
