"""
Views do fluxo de importação assistida de clientes do Auvo — LocusHub,
08/09/2026. Upload → revisão → confirmação → resumo, restrito a
Administrador (`CAN_IMPORT_CLIENTS`), mesmo padrão de três telas de
`apps.equipment.views_import` (a permissão é checada no backend em cada
view via `RoleRequiredMixin` — nunca só escondendo o botão no template).

Estado entre as telas fica na sessão do usuário (mesmo raciocínio do
importador de equipamentos: volume de algumas centenas de linhas, feito uma
vez por um Administrador, não justifica uma tabela temporária no banco).

Nada além do resumo transitório em sessão registra "quem/quando/quantos"
desta importação hoje — decisão explícita do usuário (08/09/2026): não criar
uma arquitetura grande de auditoria de importações agora. O rastro por
cliente fica no `_change_reason` de cada `HistoricalClient` criado (mesma
disciplina já usada em todo o projeto). Se um histórico de importações
(quem/quando/arquivo/contagens) for necessário no futuro, o ponto de
extensão é `ClientImportReviewView.post()` — o parser em
`apps.clients.import_auvo` não precisa mudar para isso.
"""

import logging

from django.core.exceptions import ValidationError
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from apps.accounts.permissions import CAN_IMPORT_CLIENTS, RoleRequiredMixin
from apps.clients.import_auvo import (
    INVALIDO,
    JA_EXISTENTE,
    NOVO,
    POSSIVEL_DUPLICADO,
    ClientImportError,
    ParsedClientRow,
    parse_client_workbook,
)
from apps.clients.services import NewClientData, create_client
from apps.core.services import AddressData

logger = logging.getLogger(__name__)

SESSION_KEY_ROWS = "clients_import_auvo_rows"
SESSION_KEY_FILENAME = "clients_import_auvo_filename"
SESSION_KEY_SUMMARY = "clients_import_auvo_summary"

# Só para o limite de tamanho pedido explicitamente ("definir limite
# razoável de tamanho") — a planilha real de homologação (716 clientes) tem
# ~155 KB; 10 MB dá folga generosa para exportações bem maiores sem abrir
# mão de um teto.
MAX_IMPORT_FILE_SIZE_BYTES = 10 * 1024 * 1024


def _row_label(row: ParsedClientRow) -> str:
    return row.razao_social or row.nome or row.documento_display or f"linha {row.row_number}"


class ClientImportUploadView(RoleRequiredMixin, View):
    allowed_roles = CAN_IMPORT_CLIENTS

    def get(self, request):
        return render(request, "clients/import_upload.html")

    def post(self, request):
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            messages.error(request, "Selecione um arquivo .xlsx para importar.")
            return render(request, "clients/import_upload.html")

        # Nunca confiar no nome do arquivo para decidir formato — só a
        # extensão é checada aqui como primeiro filtro rápido; o conteúdo
        # real é validado abaixo tentando abrir como planilha Excel de
        # verdade (é isso que rejeita um arquivo renomeado só pela extensão).
        if not uploaded_file.name.lower().endswith(".xlsx"):
            messages.error(request, "Envie um arquivo no formato .xlsx.")
            return render(request, "clients/import_upload.html")

        if uploaded_file.size > MAX_IMPORT_FILE_SIZE_BYTES:
            messages.error(
                request,
                f"Arquivo maior que o limite permitido ({MAX_IMPORT_FILE_SIZE_BYTES // (1024 * 1024)} MB).",
            )
            return render(request, "clients/import_upload.html")

        try:
            parsed_rows = parse_client_workbook(uploaded_file)
        except ClientImportError as exc:
            messages.error(request, str(exc))
            return render(request, "clients/import_upload.html")

        if not parsed_rows:
            messages.warning(request, "Nenhuma linha com dado de cliente foi encontrada na planilha.")
            return render(request, "clients/import_upload.html")

        request.session[SESSION_KEY_ROWS] = [row.to_session_dict() for row in parsed_rows]
        request.session[SESSION_KEY_FILENAME] = uploaded_file.name
        return redirect("clients:import_review")


class ClientImportReviewView(RoleRequiredMixin, View):
    allowed_roles = CAN_IMPORT_CLIENTS

    def get(self, request):
        raw_rows = request.session.get(SESSION_KEY_ROWS)
        if not raw_rows:
            messages.info(request, "Nenhuma planilha em revisão no momento — envie um arquivo primeiro.")
            return redirect("clients:import_upload")

        rows = [ParsedClientRow.from_session_dict(r) for r in raw_rows]

        counts = {
            NOVO: sum(1 for r in rows if r.classification == NOVO),
            JA_EXISTENTE: sum(1 for r in rows if r.classification == JA_EXISTENTE),
            POSSIVEL_DUPLICADO: sum(1 for r in rows if r.classification == POSSIVEL_DUPLICADO),
            INVALIDO: sum(1 for r in rows if r.classification == INVALIDO),
        }

        categoria = request.GET.get("categoria", "").strip().upper()
        visible_rows = [r for r in rows if r.classification == categoria] if categoria in counts else rows

        return render(
            request,
            "clients/import_review.html",
            {
                "filename": request.session.get(SESSION_KEY_FILENAME, ""),
                "rows": visible_rows,
                "total": len(rows),
                "counts": counts,
                "categoria_ativa": categoria if categoria in counts else "",
            },
        )

    def post(self, request):
        raw_rows = request.session.get(SESSION_KEY_ROWS)
        if not raw_rows:
            messages.error(request, "A sessão de importação expirou. Envie a planilha novamente.")
            return redirect("clients:import_upload")

        filename = request.session.get(SESSION_KEY_FILENAME, "")
        rows = [ParsedClientRow.from_session_dict(r) for r in raw_rows]

        created: list[dict] = []
        failed: list[dict] = []
        not_imported: list[dict] = []

        change_reason = (
            f"Importado do Auvo em {timezone.now():%d/%m/%Y %H:%M} por "
            f"{request.user} (arquivo {filename or 'sem nome'})."
        )

        for row in rows:
            if row.classification != NOVO:
                not_imported.append(
                    {
                        "row_number": row.row_number,
                        "label": _row_label(row),
                        "classification": row.classification,
                        "reason": row.reason,
                    }
                )
                continue

            payload = row.payload
            assert payload is not None  # NOVO sempre tem payload — garantido por parse_client_workbook

            # Revalidação no momento da confirmação (defesa em profundidade —
            # o estado do banco pode ter mudado desde a prévia: outra
            # importação, cadastro manual, etc.). `create_client()` já checa
            # documento/`auvo_code` duplicados por conta própria; aqui só
            # tratamos o resultado dessa checagem.
            try:
                client = create_client(
                    NewClientData(
                        client_type=payload.client_type,
                        company_name=payload.company_name,
                        document=payload.document,
                        trade_name=payload.trade_name,
                        registration_status=payload.registration_status,
                        state_registration=payload.state_registration,
                        phone=payload.phone,
                        email=payload.email,
                        contact_name=payload.contact_name,
                        notes=payload.notes,
                        auvo_code=payload.auvo_code,
                        external_code=payload.external_code,
                        municipal_registration=payload.municipal_registration,
                        icms_taxpayer=payload.icms_taxpayer,
                        billing_email=payload.billing_email,
                        fiscal_address=AddressData(
                            cep=payload.fiscal_cep,
                            logradouro=payload.fiscal_logradouro,
                            numero=payload.fiscal_numero,
                            complemento=payload.fiscal_complemento,
                            bairro=payload.fiscal_bairro,
                            cidade=payload.fiscal_cidade,
                            uf=payload.fiscal_uf,
                        ),
                        change_reason=change_reason,
                    ),
                    require_document=False,
                )
            except (ValueError, ValidationError) as exc:
                # Duplicidade detectada só agora (corrida entre a prévia e a
                # confirmação) ou qualquer outra rejeição de validação —
                # a linha simplesmente não é importada; as demais continuam.
                reason = str(exc.message) if isinstance(exc, ValidationError) else str(exc)
                failed.append({"row_number": row.row_number, "label": _row_label(row), "reason": reason})
                not_imported.append(
                    {"row_number": row.row_number, "label": _row_label(row), "classification": "FALHA", "reason": reason}
                )
                continue
            except Exception as exc:  # nunca deixar uma linha ruim derrubar as demais
                # `str(exc)` aqui pode ser um IntegrityError/erro interno
                # técnico (às vezes em inglês) — fica só no log; a tela de
                # revisão mostra uma mensagem genérica em português
                # (auditoria de idioma, ago/2026). O detalhe completo
                # continua disponível no log técnico para investigação.
                logger.exception(
                    "Falha inesperada ao importar linha %s da planilha de clientes.", row.row_number
                )
                reason = "Falha inesperada ao importar esta linha. Veja o log do servidor para detalhes."
                failed.append({"row_number": row.row_number, "label": _row_label(row), "reason": reason})
                not_imported.append(
                    {"row_number": row.row_number, "label": _row_label(row), "classification": "FALHA", "reason": reason}
                )
                continue

            created.append({"pk": client.pk, "label": client.display_name()})

        counts = {
            NOVO: sum(1 for r in rows if r.classification == NOVO),
            JA_EXISTENTE: sum(1 for r in rows if r.classification == JA_EXISTENTE),
            POSSIVEL_DUPLICADO: sum(1 for r in rows if r.classification == POSSIVEL_DUPLICADO),
            INVALIDO: sum(1 for r in rows if r.classification == INVALIDO),
        }

        summary = {
            "filename": filename,
            "total": len(rows),
            "created": created,
            "created_count": len(created),
            "ja_existente_count": counts[JA_EXISTENTE],
            "possivel_duplicado_count": counts[POSSIVEL_DUPLICADO],
            "invalido_count": counts[INVALIDO],
            "failed_count": len(failed),
            "not_imported": not_imported,
        }

        del request.session[SESSION_KEY_ROWS]
        request.session.pop(SESSION_KEY_FILENAME, None)
        request.session[SESSION_KEY_SUMMARY] = summary
        return redirect("clients:import_summary")


class ClientImportSummaryView(RoleRequiredMixin, View):
    allowed_roles = CAN_IMPORT_CLIENTS

    def get(self, request):
        summary = request.session.get(SESSION_KEY_SUMMARY)
        if not summary:
            messages.info(request, "Nenhuma importação recente para mostrar.")
            return redirect("clients:import_upload")

        return render(request, "clients/import_summary.html", summary)
