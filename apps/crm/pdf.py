"""
Geração de PDF de Proposta Comercial/Contrato — segue exatamente o mesmo
padrão já usado em `apps.qrcodes.services` (único gerador de PDF que já
existia no projeto antes desta rodada): `render_to_string()` de um
template HTML comum + `weasyprint.HTML(string=...).write_pdf()`. Nenhuma
biblioteca nova, nenhum padrão novo.

Só LÊ campos já congelados (`ProposalVersion.*_snapshot`,
`ProposalItem.description_snapshot`, etc.) — nunca consulta
`Client`/`CompanyProfile`/`EquipmentModel` ao vivo para montar o PDF de
uma versão já emitida (seção 62, "PDF NÃO CONSULTA DADOS MUTÁVEIS").
"""

import base64
from decimal import Decimal
from functools import lru_cache

from django.conf import settings
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.crm.extenso import valor_por_extenso
from apps.crm.models import BusinessType, Contract, ProposalItemType, ProposalVersion

_MESES_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

# REDESENHO VISUAL DA PROPOSTA (24/09/2026): fonte Quicksand (mais
# arredondada, aprovada na Etapa 1 do processo colaborativo) embutida no
# CSS como `data:` URI (base64) — nunca via `{% static %}`/`base_url` do
# WeasyPrint, que o resto do projeto nunca usou (ver `apps/qrcodes/
# services.py`, mesmo padrão `HTML(string=...).write_pdf()` sem
# `base_url`). Isso funciona igual em dev/produção, com ou sem
# `collectstatic` rodado. Arquivos `.woff2` ficam versionados em
# `static/crm/fonts/quicksand/`.
_QUICKSAND_FILES = {
    400: "Quicksand-Regular.woff2",
    600: "Quicksand-SemiBold.woff2",
    700: "Quicksand-Bold.woff2",
}


@lru_cache(maxsize=1)
def _quicksand_font_face_css() -> str:
    fonts_dir = settings.BASE_DIR / "static" / "crm" / "fonts" / "quicksand"
    rules = []
    for weight, filename in _QUICKSAND_FILES.items():
        encoded = base64.b64encode((fonts_dir / filename).read_bytes()).decode("ascii")
        rules.append(
            '@font-face { font-family: "Quicksand"; '
            f'src: url(data:font/woff2;base64,{encoded}) format("woff2"); '
            f"font-weight: {weight}; font-style: normal; }}"
        )
    return "\n".join(rules)


def _period_label(proposal_version: ProposalVersion, *, is_venda: bool) -> str:
    """
    "Período" na tabela de Produtos e Serviços (Etapa 4 do redesenho): em
    vez de mostrar as duas datas contratadas, mostra a DURAÇÃO calculada
    (retirada − entrega), ex. "6 dias" — pedido explícito do usuário no
    processo colaborativo. Sempre "—" em Venda (nunca há período de
    locação) ou quando as datas não estão preenchidas.
    """
    if is_venda:
        return "—"
    start = proposal_version.contracted_start_date
    end = proposal_version.contracted_end_date
    if not start or not end:
        return "—"
    days = (end - start).days
    if days <= 0:
        return "—"
    return "1 dia" if days == 1 else f"{days} dias"


def _section_numbers(proposal_version: ProposalVersion, *, is_venda: bool) -> dict:
    """
    Numeração das seções ("1 —", "2 —", ...) calculada em Python — nunca
    hardcoded no template — porque várias seções são condicionais
    (Condições Comerciais só se preenchida; Entrega/Operação só fora de
    Venda; Informações Complementares só se algum dos 3 campos estiver
    preenchido). Numeração fixa no template criaria buracos quando uma
    seção condicional some (ex.: pular do "5" direto pro "7").
    """
    keys = ["contratado", "contratante"]
    if proposal_version.price_table_label or proposal_version.payment_condition:
        keys.append("condicoes_comerciais")
    keys += ["produtos_servicos", "resumo_financeiro", "pagamento"]
    if not is_venda:
        keys.append("entrega_operacao")
    if proposal_version.special_clauses or proposal_version.payment_info_notes or proposal_version.general_notes:
        keys.append("informacoes_complementares")
    return {key: index + 1 for index, key in enumerate(keys)}


def _cidade_data_extenso(proposal_version: ProposalVersion) -> str:
    """
    "Maringá, 23 de setembro de 2026" (seção 33) — construído em Python
    (nunca via filtro `|date` do template) para nunca depender da
    localidade ativa do Django (o projeto não usa `{% load l10n %}` em
    nenhum PDF, ver docstring de `proposal.html`); a data usada é sempre
    `issued_at` (a emissão REAL do documento), nunca `timezone.now()` —
    um PDF histórico nunca muda de data ao ser reaberto/reimpresso.
    """
    cidade = (proposal_version.company_city_snapshot or "").strip()
    uf = (proposal_version.company_uf_snapshot or "").strip()
    local = f"{cidade} - {uf}" if cidade and uf else cidade

    issued_at = proposal_version.issued_at
    if issued_at is None:
        return local
    mes = _MESES_PT[issued_at.month - 1]
    data = f"{issued_at.day} de {mes} de {issued_at.year}"
    return f"{local}, {data}" if local else data


def render_proposal_pdf(proposal_version: ProposalVersion) -> bytes:
    # FECHAMENTO DA PROPOSTA COMERCIAL (23/09/2026, seção 13/25): "valor
    # por extenso" e a tabela de parcelas entram no MESMO contexto
    # existente — nunca uma segunda função/rota de renderização. O valor
    # por extenso é sempre DERIVADO aqui (nunca lido de um campo
    # persistido) a partir do `total` já congelado da versão. Os
    # subtotais de equipamento/serviço (seção 11) também são somados aqui
    # em Python/Decimal — nunca com aritmética no template, que arrisca
    # comparação de string em vez de soma numérica.
    items = list(proposal_version.items.all())
    equipment_total = sum(
        (item.line_total for item in items if item.item_type == ProposalItemType.EQUIPAMENTO), Decimal("0.00")
    )
    services_total = sum(
        (item.line_total for item in items if item.item_type == ProposalItemType.SERVICO), Decimal("0.00")
    )
    is_venda = proposal_version.proposal.opportunity.business_type == BusinessType.VENDA
    html_string = render_to_string(
        "crm/pdf/proposal.html",
        {
            "proposal": proposal_version.proposal,
            "version": proposal_version,
            "items": items,
            "installments": proposal_version.installments.all(),
            "valor_extenso": valor_por_extenso(proposal_version.total),
            "equipment_total": equipment_total,
            "services_total": services_total,
            "is_venda": is_venda,
            "cidade_data_extenso": _cidade_data_extenso(proposal_version),
            # REDESENHO VISUAL DA PROPOSTA (24/09/2026):
            "quicksand_font_face": _quicksand_font_face_css(),
            "period_label": _period_label(proposal_version, is_venda=is_venda),
            "section_number": _section_numbers(proposal_version, is_venda=is_venda),
        },
    )
    return HTML(string=html_string).write_pdf()


def render_contract_pdf(contract: Contract) -> bytes:
    version = contract.proposal_version
    html_string = render_to_string(
        "crm/pdf/contract.html",
        {
            "contract": contract,
            "proposal": version.proposal,
            "version": version,
            "items": version.items.all(),
        },
    )
    return HTML(string=html_string).write_pdf()
