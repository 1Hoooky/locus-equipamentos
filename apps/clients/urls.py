from django.urls import path

from apps.clients import views, views_import

app_name = "clients"

urlpatterns = [
    path("", views.ClientListView.as_view(), name="list"),
    path("novo/", views.ClientCreateView.as_view(), name="create"),
    path("importar/", views_import.ClientImportUploadView.as_view(), name="import_upload"),
    path("importar/revisar/", views_import.ClientImportReviewView.as_view(), name="import_review"),
    path("importar/resumo/", views_import.ClientImportSummaryView.as_view(), name="import_summary"),
    path("<int:pk>/", views.ClientDetailView.as_view(), name="detail"),
    path("<int:pk>/editar/", views.ClientUpdateView.as_view(), name="update"),
    path("<int:pk>/endereco-fiscal/", views.ClientFiscalAddressUpdateView.as_view(), name="fiscal_address_update"),
    path("<int:pk>/excluir-definitivamente/", views.ClientHardDeleteView.as_view(), name="hard_delete"),
]
