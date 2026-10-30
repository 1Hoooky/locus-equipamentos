from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from simple_history.admin import SimpleHistoryAdmin

from apps.operations.models import Location, Movement
from apps.operations.services import LocationUpdateData, update_location


@admin.register(Location)
class LocationAdmin(SimpleHistoryAdmin):
    list_display = ("name", "type", "client", "is_active")
    list_filter = ("type", "is_active")
    search_fields = ("name",)

    def save_model(self, request, obj, form, change):
        """
        P0-05/OPS-001: o admin era um segundo caminho de escrita que
        alterava `client`/`type` de uma `Location` sem passar por
        `update_location()` — exatamente o bypass que esta rodada fecha.

        Criação (`change=False`): uma `Location` nova nunca tem
        `Equipment` apontando para ela ainda (não existe `pk` antes deste
        save) — a proteção de OPS-001 é sobre EDITAR client/type com
        equipamento já presente, o que é impossível numa criação. Mantém
        o comportamento padrão do admin para criação, como já era antes
        desta correção.

        Edição (`change=True`): delega 100% para `update_location()`, que
        decide — sob `select_for_update()` — se a alteração estrutural é
        permitida. Não duplica a regra de negócio aqui (especificação do
        P0-05, ponto 6) — e, de bônus, passa a respeitar também a
        validação pré-existente `type` ⟺ `client` (antes o admin só
        descobria essa inconsistência via `IntegrityError` cru do banco).

        `update_location()` faz `location.refresh_from_db()` no MESMO
        objeto (`obj`) para reler o estado persistido sob lock — isso
        sobrescreve qualquer valor ainda não salvo que o form já tenha
        colocado em `obj`, inclusive `is_active`/`address`, que não fazem
        parte da proteção (só name/type/client são). Por isso os valores
        novos desses dois campos são capturados ANTES da chamada e
        reaplicados depois, num segundo `save()` explícito só se algum
        dos dois realmente mudou.
        """
        if not change:
            super().save_model(request, obj, form, change)
            return

        new_is_active = obj.is_active
        new_address_id = obj.address_id

        try:
            update_location(
                location=obj,
                data=LocationUpdateData(name=obj.name, type=obj.type, client=obj.client),
            )
        except ValueError as exc:
            # Nunca um 500/traceback cru para quem está editando pelo
            # admin (especificação, ponto 7) — o erro é guardado NO
            # REQUEST (nunca em atributo de instância do ModelAdmin: a
            # instância é compartilhada entre requisições concorrentes)
            # para log_change()/message_user()/response_change() abaixo
            # tratarem. Nada foi persistido.
            request._p0_05_location_save_error = str(exc)
            return

        if obj.is_active != new_is_active or obj.address_id != new_address_id:
            obj.is_active = new_is_active
            obj.address_id = new_address_id
            obj._change_reason = "Edição de unidade/localização (endereço/ativo)."
            obj.save(update_fields=["is_active", "address", "updated_at"])

    def log_change(self, request, object, message):
        if getattr(request, "_p0_05_location_save_error", None):
            # update_location() rejeitou a alteração estrutural — nada foi
            # de fato alterado, então não registra um "changed" que não
            # ocorreu (LogEntry do admin, painel "Ações recentes").
            return
        super().log_change(request, object, message)

    def message_user(self, request, message, level=messages.INFO, extra_tags="", fail_silently=False):
        if getattr(request, "_p0_05_location_save_error", None):
            # Suprime a mensagem genérica de sucesso do admin — a real (de
            # erro) é mostrada por response_change() abaixo.
            return
        super().message_user(request, message, level, extra_tags, fail_silently)

    def response_change(self, request, obj):
        error = getattr(request, "_p0_05_location_save_error", None)
        if error:
            messages.error(request, error)
            return HttpResponseRedirect(request.path)
        return super().response_change(request, obj)


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
