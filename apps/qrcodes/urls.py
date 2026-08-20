from django.urls import path

from apps.qrcodes import views

app_name = "qrcodes"

urlpatterns = [
    path("lote/etiquetas.pdf", views.LabelBatchDownloadView.as_view(), name="label_batch"),
    path("<str:patrimonio>/qr.png", views.QRCodeDownloadView.as_view(), name="qr_png"),
    path("<str:patrimonio>/etiqueta.pdf", views.LabelDownloadView.as_view(), name="label_pdf"),
]
