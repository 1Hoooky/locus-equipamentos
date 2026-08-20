"""
Views do fluxo de importação assistida da planilha legada — especificação,
seção 13 (fluxo D): upload → revisão/curadoria → confirmação. Restrito a
Administrador (seção 11).

O estado entre as três telas (upload, revisão, resumo) fica na sessão do
usuário — não existe persistência intermediária no banco. Isso é
suficiente para o volume desta importação (algumas centenas de linhas,
feita uma vez por um Administrador) e evita criar uma tabela temporária
só para isso.
"""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views import View

from apps.accounts.permissions import CAN_IMPORT_LEGACY_SPREADSHEET, RoleRequiredMixin
from apps.catalog.models import EquipmentModel
from apps.equipment.legacy_import import (
    LegacyImportError,
    ParsedRow,
    parse_legacy_workbook,
)
from apps.equipment.services import NewEquipmentData, create_equipment

SESSION_KEY_ROWS = "legacy_import_rows"
SESSION_KEY_SUMMARY = "legacy_import_summary"


class LegacyImportUploadView(RoleRequiredMixin, View):
    allowed_roles = CAN_IMPORT_LEGACY_SPREADSHEET

    def get(self, request):
        return render(request, "equipment/import_upload.html")

    def post(self, request):
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            messages.error(request, "Selecione um arquivo .xlsx para importar.")
            return render(request, "equipment/import_upload.html")

        try:
            parsed_rows = parse_legacy_workbook(uploaded_file)
        except LegacyImportError as exc:
            messages.error(request, str(exc))
            return render(request, "equipment/import_upload.html")

        if not parsed_rows:
            messages.warning(request, "Nenhuma linha com dado foi encontrada na aba 'TOTAL EQUIPAMENTOS'.")
            return render(request, "equipment/import_upload.html")

        request.session[SESSION_KEY_ROWS] = [row.to_session_dict() for row in parsed_rows]
        return redirect("equipment:import_review")


class LegacyImportReviewView(RoleRequiredMixin, View):
    allowed_roles = CAN_IMPORT_LEGACY_SPREADSHEET

    def get(self, request):
        raw_rows = request.session.get(SESSION_KEY_ROWS)
        if not raw_rows:
            messages.info(request, "Nenhuma planilha em revisão no momento — envie um arquivo primeiro.")
            return redirect("equipment:import_upload")

        rows = [ParsedRow.from_session_dict(r) for r in raw_rows]
        # Linhas com problema aparecem primeiro — são as que precisam de atenção do Administrador.
        rows_with_index = sorted(enumerate(rows), key=lambda pair: not pair[1].has_issues)

        return render(
            request,
            "equipment/import_review.html",
            {
                "rows_with_index": rows_with_index,
                "total": len(rows),
                "total_with_issues": sum(1 for r in rows if r.has_issues),
            },
        )

    def post(self, request):
        raw_rows = request.session.get(SESSION_KEY_ROWS)
        if not raw_rows:
            messages.error(request, "A sessão de importação expirou. Envie a planilha novamente.")
            return redirect("equipment:import_upload")

        rows = [ParsedRow.from_session_dict(r) for r in raw_rows]
        valid_model_ids = set(EquipmentModel.objects.filter(is_active=True).values_list("pk", flat=True))

        created = []
        skipped = []

        for index, row in enumerate(rows):
            raw_choice = request.POST.get(f"model_{index}", "").strip()

            if not raw_choice:
                skipped.append({"row_number": row.row_number, "legacy_code": row.legacy_code, "reason": "Sem modelo selecionado (linha pulada)."})
                continue

            model_id = int(raw_choice)
            if model_id not in valid_model_ids:
                skipped.append({"row_number": row.row_number, "legacy_code": row.legacy_code, "reason": "Modelo selecionado é inválido."})
                continue

            # Segunda linha de defesa contra duplicidade (a primeira é o aviso
            # já mostrado na tela de revisão): checa de novo aqui, com o
            # estado do banco no momento exato da confirmação — cobre o caso
            # de duas revisões da mesma planilha rodando em paralelo, ou de
            # o admin confirmar uma sessão de revisão antiga.
            from apps.equipment.models import Equipment

            if row.legacy_code and Equipment.objects.filter(legacy_code=row.legacy_code).exists():
                skipped.append(
                    {
                        "row_number": row.row_number,
                        "legacy_code": row.legacy_code,
                        "reason": "Já existe um equipamento com este código legado — pulado para evitar duplicidade.",
                    }
                )
                continue

            notes_parts = []
            if row.geracao:
                notes_parts.append(f"Geração (planilha legada): {row.geracao}.")
            if row.descricao_sistema:
                notes_parts.append(f"Descrição do sistema (planilha legada): {row.descricao_sistema}.")
            notes_parts.append("Importado da planilha legada — status/condição definidos como padrão (Disponível/Bom); confirmar manualmente.")

            equipment = create_equipment(
                NewEquipmentData(
                    model_id=model_id,
                    created_by=request.user,
                    legacy_code=row.legacy_code,
                    supplier=row.fornecedor,
                    acquisition_date=row.data_aquisicao,
                    acquisition_value=row.valor,
                    notes=" ".join(notes_parts),
                )
            )
            created.append(equipment.patrimonio)

        del request.session[SESSION_KEY_ROWS]
        request.session[SESSION_KEY_SUMMARY] = {"created": created, "skipped": skipped}
        return redirect("equipment:import_summary")


class LegacyImportSummaryView(RoleRequiredMixin, View):
    allowed_roles = CAN_IMPORT_LEGACY_SPREADSHEET

    def get(self, request):
        summary = request.session.get(SESSION_KEY_SUMMARY)
        if not summary:
            messages.info(request, "Nenhuma importação recente para mostrar.")
            return redirect("equipment:import_upload")

        return render(
            request,
            "equipment/import_summary.html",
            {
                "created": summary["created"],
                "skipped": summary["skipped"],
                "created_count": len(summary["created"]),
                "skipped_count": len(summary["skipped"]),
            },
        )
