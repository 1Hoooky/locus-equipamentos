from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.catalog.models import Category, EquipmentModel


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


@admin.register(EquipmentModel)
class EquipmentModelAdmin(SimpleHistoryAdmin):
    list_display = ("name", "code", "category", "manufacturer", "is_active", "equipment_count")
    list_filter = ("category", "is_active")
    search_fields = ("name", "code")
    readonly_fields = ("last_sequence",)

    @admin.display(description="Nº de equipamentos")
    def equipment_count(self, obj: EquipmentModel) -> int:
        return obj.equipment_set.count()

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        # Trava o campo `code` na interface assim que o modelo já tiver
        # equipamentos vinculados — espelha a regra de negócio no admin,
        # mas quem garante isso de fato é EquipmentModel.clean().
        if obj is not None and obj.has_equipment() and "code" not in readonly:
            readonly.append("code")
        return readonly
