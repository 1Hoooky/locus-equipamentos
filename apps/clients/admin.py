from django.contrib import admin

from apps.clients.models import Client


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("company_name", "trade_name", "city", "state", "is_active")
    search_fields = ("company_name", "trade_name", "document")
    list_filter = ("state", "is_active")
