from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.operations.models import Location, Movement


@admin.register(Location)
class LocationAdmin(SimpleHistoryAdmin):
    list_display = ("name", "type", "client", "is_active")
    list_filter = ("type", "is_active")
    search_fields = ("name",)


@admin.register(Movement)
class MovementAdmin(admin.ModelAdmin):
    list_display = ("equipment", "movement_type", "origin_location", "destination_location", "created_by", "created_at")
    list_filter = ("movement_type",)
    search_fields = ("equipment__patrimonio",)
    readonly_fields = [f.name for f in Movement._meta.get_fields() if hasattr(f, "name")]

    def has_add_permission(self, request):
        # Movement só é criado por create_movement() — nunca pelo admin.
        return False

    def has_delete_permission(self, request, obj=None):
        return False
