"""
Context processors globais do projeto.

`commercial_links`: expõe as URLs comerciais configuráveis (etapa de
UX/UI, 28/08/2026 — ver AUDITORIA_UX_HOME_NAVEGACAO_QR.md, item [14]) para
qualquer template, sem repetir `settings.LOCUS_...` em cada view. Usado
hoje só pela landing pública (`templates/equipment/detail_public.html` e
`templates/base_public.html`), mas registrado globalmente (mesmo padrão de
`django.contrib.messages.context_processors.messages`) — nenhuma view
precisa passar isto manualmente no contexto.

Cada valor pode ser uma string vazia (default seguro, nenhuma URL foi
inventada) — é responsabilidade do TEMPLATE decidir não renderizar aquele
CTA quando o valor estiver vazio (`{% if commercial_links.instagram %}`),
nunca gerar `href="#"` ou um link vazio.
"""

from django.conf import settings


def commercial_links(request):
    return {
        "commercial_links": {
            "instagram": settings.LOCUS_INSTAGRAM_URL,
            "site": settings.LOCUS_SITE_URL,
            "whatsapp": settings.LOCUS_WHATSAPP_URL,
            "orcamento": settings.LOCUS_ORCAMENTO_URL,
            "equipamentos": settings.LOCUS_EQUIPAMENTOS_URL,
        }
    }
