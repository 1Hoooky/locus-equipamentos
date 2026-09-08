from django.urls import path

from apps.qrcodes import views

app_name = "qrcodes"

urlpatterns = [
    path("lote/etiquetas.pdf", views.LabelBatchDownloadView.as_view(), name="label_batch"),
    path("lote/qr.zip", views.QRCodeZipExportView.as_view(), name="qr_zip"),
    path("lote/etiquetas.zip", views.LabelZipExportView.as_view(), name="label_zip"),
    # Etiquetas 6x6 em lote por modelo (pedido de 08/09/2026) — precisa
    # vir antes do catch-all "<str:patrimonio>/..." abaixo, mesmo
    # raciocínio defensivo já usado para as rotas "lote/..." acima.
    path("modelo/<int:model_id>/etiquetas.pdf", views.ModelLabelBatchDownloadView.as_view(), name="model_label_batch"),
    path("<str:patrimonio>/qr.png", views.QRCodeDownloadView.as_view(), name="qr_png"),
    path("<str:patrimonio>/etiqueta.pdf", views.LabelDownloadView.as_view(), name="label_pdf"),
]
