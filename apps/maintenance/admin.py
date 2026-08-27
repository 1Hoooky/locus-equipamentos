from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.maintenance.models import Cleaning, Maintenance


@admin.register(Maintenance)
class MaintenanceAdmin(SimpleHistoryAdmin):
    list_display = ("equipment", "maintenance_type", "status", "responsible", "created_at", "closed_at")
    list_filter = ("maintenance_type", "status")
    search_fields = ("equipment__patrimonio",)

    def has_add_permission(self, request):
        # Maintenance só é criada por open_maintenance() — nunca pelo admin.
        return False


@admin.register(Cleaning)
class CleaningAdmin(admin.ModelAdmin):
    list_display = ("equipment", "performed_at", "responsible", "is_active")
    list_filter = ("is_active",)
    search_fields = ("equipment__patrimonio",)
    readonly_fields = [f.name for f in Cleaning._meta.get_fields() if hasattr(f, "name")]

    def has_add_permission(self, request):
        # Cleaning só é criada por create_cleaning() — nunca pelo admin.
        return False

    def has_delete_permission(self, request, obj=None):
        # Nunca hard delete — "cancelar" é is_active=False via cancel_cleaning().
        return False
