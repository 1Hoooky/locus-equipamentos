from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.clients.models import Client


@admin.register(Client)
class ClientAdmin(SimpleHistoryAdmin):
    list_display = ("company_name", "trade_name", "document", "client_type", "is_active")
    search_fields = ("company_name", "trade_name", "document")
    list_filter = ("client_type", "is_active")
