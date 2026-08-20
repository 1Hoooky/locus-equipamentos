from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from simple_history.admin import SimpleHistoryAdmin

from apps.equipment.models import Equipment
from apps.equipment.services import NewEquipmentData, create_equipment


@admin.register(Equipment)
class EquipmentAdmin(SimpleHistoryAdmin):
    list_display = ("patrimonio", "model", "status", "condition", "is_active", "created_at", "qr_etiqueta_links")
    list_filter = ("status", "condition", "category", "is_active")
    search_fields = ("patrimonio", "serial_number", "legacy_code")
    readonly_fields = ("patrimonio", "model_sequence", "category", "created_by", "superseded_by")
    actions = ["download_labels_pdf"]

    @admin.display(description="QR / Etiqueta")
    def qr_etiqueta_links(self, obj: Equipment):
        qr_url = reverse("qrcodes:qr_png", kwargs={"patrimonio": obj.patrimonio})
        label_url = reverse("qrcodes:label_pdf", kwargs={"patrimonio": obj.patrimonio})
        return format_html('<a href="{}" target="_blank">QR</a> · <a href="{}" target="_blank">Etiqueta PDF</a>', qr_url, label_url)

    @admin.action(description="Baixar etiquetas em PDF (lote)")
    def download_labels_pdf(self, request, queryset):
        from django.http import HttpResponseRedirect
        from django.urls import reverse as url_reverse
        from urllib.parse import urlencode

        params = urlencode([("patrimonio", p) for p in queryset.values_list("patrimonio", flat=True)])
        return HttpResponseRedirect(f"{url_reverse('qrcodes:label_batch')}?{params}")

    fields = (
        "patrimonio",
        "model",
        "model_sequence",
        "category",
        "serial_number",
        "legacy_code",
        "supplier",
        "acquisition_date",
        "acquisition_value",
        "status",
        "condition",
        "current_location",
        "current_client",
        "notes",
        "is_active",
        "created_by",
        "superseded_by",
    )

    def save_model(self, request, obj, form, change):
        if change:
            # Edição normal: patrimônio/model_sequence continuam readonly
            # no form, então isto nunca toca neles — Equipment.clean()
            # também bloqueiaria a tentativa (defesa em profundidade).
            super().save_model(request, obj, form, change)
            return

        # Criação: nunca salvamos o objeto "cru" do ModelAdmin — sempre
        # passamos pelo serviço atômico, que é quem sabe gerar o
        # patrimônio corretamente (especificação, seção 8).
        data = NewEquipmentData(
            model_id=obj.model_id,
            created_by=request.user,
            serial_number=obj.serial_number,
            legacy_code=obj.legacy_code,
            supplier=obj.supplier,
            acquisition_date=obj.acquisition_date,
            acquisition_value=obj.acquisition_value,
            status=obj.status,
            condition=obj.condition,
            notes=obj.notes,
        )
        created = create_equipment(data)
        obj.pk = created.pk
        obj.patrimonio = created.patrimonio
        obj.model_sequence = created.model_sequence
        obj.category = created.category
