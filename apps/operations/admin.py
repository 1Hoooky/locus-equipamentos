from django.contrib import admin

from apps.operations.models import Location


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "client", "is_active")
    list_filter = ("type", "is_active")
    search_fields = ("name",)
