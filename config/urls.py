"""
URLs raiz do projeto. Cada app tem seu próprio urls.py, incluído aqui com
namespace — mantém a modularidade descrita na especificação (seção 9).
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("contas/", include("apps.accounts.urls")),
    path("qrcodes/", include("apps.qrcodes.urls")),
    path("catalogo/", include("apps.catalog.urls")),
    path("equipamentos/", include("apps.equipment.urls")),
    path("clientes/", include("apps.clients.urls")),
    path("operacao/", include("apps.operations.urls")),
    path("manutencao/", include("apps.maintenance.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
