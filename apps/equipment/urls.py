from django.urls import path

from apps.equipment import views, views_import

app_name = "equipment"

urlpatterns = [
    path("", views.EquipmentListView.as_view(), name="list"),
    # Precisam vir antes do catch-all abaixo, senão seriam interpretados
    # como um patrimônio (ex.: "exportar" viraria patrimonio="exportar").
    path("novo/", views.EquipmentCreateView.as_view(), name="create"),
    path("lote/novo/", views.EquipmentBatchCreateView.as_view(), name="batch_create"),
    path("lote/confirmar/", views.EquipmentBatchConfirmView.as_view(), name="batch_confirm"),
    path("lote/<uuid:batch_id>/", views.EquipmentBatchResultView.as_view(), name="batch_result"),
    path("modelo/<int:model_id>/itens/", views.EquipmentModelItemsView.as_view(), name="model_items"),
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
