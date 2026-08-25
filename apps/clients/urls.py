from django.urls import path

from apps.clients import views

app_name = "clients"

urlpatterns = [
    path("", views.ClientListView.as_view(), name="list"),
    path("novo/", views.ClientCreateView.as_view(), name="create"),
    path("<int:pk>/", views.ClientDetailView.as_view(), name="detail"),
    path("<int:pk>/editar/", views.ClientUpdateView.as_view(), name="update"),
    path("<int:pk>/endereco-fiscal/", views.ClientFiscalAddressUpdateView.as_view(), name="fiscal_address_update"),
]
