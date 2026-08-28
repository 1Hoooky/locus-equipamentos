"""
Tag genérica para ícones inline (SVG) do design system.

Contexto (auditoria de iconografia/apresentação de ações, aprovada em
28/08/2026 — ver AUDITORIA_ICONOGRAFIA_ACOES.md): o projeto não tem
pipeline de build de frontend (sem npm, sem bundler — só Tailwind via CDN
e htmx via <script> direto, ver templates/base.html). Por isso os ícones
não são instalados como pacote nem carregados de um CDN externo de
ícones: os SVGs efetivamente usados são vendorizados (copiados uma única
vez, path data do Heroicons — MIT License,
https://github.com/tailwindlabs/heroicons, conjunto "outline" 24x24,
stroke-width 1.5) e centralizados aqui. Cada tela usa `{% icon "nome" %}`
em vez de colar `<svg>` repetido.

Uso:
    {% load icons %}
    {% icon "eye" %}                          ícone "normal" (20x20)
    {% icon "eye" size="compact" %}            ícone "compacto/tabela" (16x16)
    {% icon "eye" extra_class="shrink-0" %}    classes extras opcionais

O SVG sempre sai com `aria-hidden="true" focusable="false"` — o ícone
nunca carrega o nome acessível sozinho; isso é responsabilidade do
elemento pai (`aria-label` no `<a>`/`<button>`, ver componentes
`.icon-btn-*` em templates/base.html). Nome de ícone desconhecido não
quebra a página: renderiza um comentário HTML inofensivo (fail-safe),
nunca uma exceção nem HTML não escapado.

Apenas os ícones realmente usados no sistema estão vendorizados aqui —
adicionar um novo ícone é copiar o `d` do Heroicons e adicionar uma
entrada neste dicionário, nunca colar um `<svg>` completo direto num
template (é exatamente o que a auditoria pediu para evitar).
"""

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

# name -> conteúdo interno do <svg> (um ou mais <path>), sem o <svg> em si.
_ICONS = {
    "eye": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 '
        '9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z" />'
        '<path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />'
    ),
    "qr-code": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M3.75 4.875c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 '
        '.621-.504 1.125-1.125 1.125h-4.5A1.125 1.125 0 0 1 3.75 9.375v-4.5ZM3.75 14.625c0-.621.504-1.125 '
        '1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5a1.125 1.125 0 '
        '0 1-1.125-1.125v-4.5ZM13.5 4.875c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 '
        '.621-.504 1.125-1.125 1.125h-4.5A1.125 1.125 0 0 1 13.5 9.375v-4.5Z" />'
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M6.75 6.75h.75v.75h-.75v-.75ZM6.75 16.5h.75v.75h-.75v-.75ZM16.5 6.75h.75v.75h-.75v-.75ZM13.5 '
        '13.5h.75v.75h-.75v-.75ZM13.5 19.5h.75v.75h-.75v-.75ZM19.5 13.5h.75v.75h-.75v-.75ZM19.5 19.5h.75v.75h-.75'
        'v-.75ZM16.5 16.5h.75v.75h-.75v-.75Z" />'
    ),
    "tag": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M9.568 3H5.25A2.25 2.25 0 0 0 3 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 '
        '1.78.872 2.607.33a18.095 18.095 0 0 0 5.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 3.66A2.25 '
        '2.25 0 0 0 9.568 3Z" />'
        '<path stroke-linecap="round" stroke-linejoin="round" d="M6 6h.008v.008H6V6Z" />'
    ),
    "pencil": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 '
        '1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125" />'
    ),
    "plus": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />'
    ),
    "wrench": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M21.75 6.75a4.5 4.5 0 0 1-4.884 4.484c-1.076-.091-2.264.071-2.95.904l-7.152 8.684a2.548 2.548 '
        '0 1 1-3.586-3.586l8.684-7.152c.833-.686.995-1.874.904-2.95a4.5 4.5 0 0 1 6.336-4.486l-3.276 '
        '3.276a3.004 3.004 0 0 0 2.25 2.25l3.276-3.276c.256.565.398 1.192.398 1.852Z" />'
        '<path stroke-linecap="round" stroke-linejoin="round" d="M4.867 19.125h.008v.008h-.008v-.008Z" />'
    ),
    "arrow-down-tray": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 '
        '0L7.5 12m4.5 4.5V3" />'
    ),
    "arrow-left": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18" />'
    ),
    "arrow-right": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />'
    ),
    "x-mark": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />'
    ),
    # ---------------------------------------------------------------------
    # Adicionados na etapa de UX/UI (28/08/2026 — landing pública, menu
    # mobile em drawer, navegação desktop por módulos). Mesma origem/
    # licença dos ícones acima (Heroicons "outline" 24x24, MIT License).
    # ---------------------------------------------------------------------
    "bars-3": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />'
    ),
    "home": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="m2.25 12 8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 '
        '1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 '
        '1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />'
    ),
    "users": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M15 19.128a9.38 9.38 0 0 0 2.625.372 9.337 9.337 0 0 0 4.121-.952 4.125 4.125 0 0 0-7.533-2.493M15 '
        '19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 0 1 8.624 21c-2.331 '
        '0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0 1 11.964-3.07M12 6.375a3.375 3.375 0 1 1-6.75 0 '
        '3.375 3.375 0 0 1 6.75 0Zm8.25 2.25a2.625 2.625 0 1 1-5.25 0 2.625 2.625 0 0 1 5.25 0Z" />'
    ),
    "archive-box": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="m20.25 7.5-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 '
        '7.5m6.25 3.75h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c'
        '-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z" />'
    ),
    "cog-6-tooth": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645'
        '.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 '
        '2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 '
        '.255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 '
        '1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644'
        '.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312'
        '-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 '
        '1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a7.775 '
        '7.775 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 '
        '1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495'
        '.644-.869l.214-1.28Z" />'
        '<path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />'
    ),
    "squares-2x2": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 '
        '2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 '
        '0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 '
        '20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 '
        '2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25A2.25 2.25 0 0 1 13.5 '
        '18v-2.25Z" />'
    ),
    "cube": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="m21 7.5-9-5.25L3 7.5m18 0-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9" />'
    ),
    "globe-alt": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M12 21a9.004 9.004 0 0 0 8.716-6.747M12 21a9.004 9.004 0 0 1-8.716-6.747M12 21c2.485 0 4.5-4.03 '
        '4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 0 1 7.843 4.582M12 '
        '3a8.997 8.997 0 0 0-7.843 4.582m15.686 0A11.953 11.953 0 0 1 12 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 '
        '0A8.959 8.959 0 0 1 21 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0 1 12 16.5c-3.162 '
        '0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 0 1 3 12c0-1.605.42-3.113 1.157-4.418" />'
    ),
    "document-text": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 '
        '3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 '
        '.621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />'
    ),
    "chat-bubble-left-right": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02'
        '.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 0 1-.825-.242m9.345-8.334a2.126 2.126 0 0 '
        '0-.476-.095 48.64 48.64 0 0 0-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 '
        '1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0 0 11.25 3c-2.115 0-4.198.137'
        '-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74'
        '.194V21l4.155-4.155" />'
    ),
    "phone": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M2.25 6.75c0 8.284 6.716 15 15 15h2.25a2.25 2.25 0 0 0 2.25-2.25v-1.372c0-.516-.351-.966-.852'
        '-1.091l-4.423-1.106c-.44-.11-.902.055-1.173.417l-.97 1.293c-.282.376-.769.542-1.21.38a12.035 12.035 0 '
        '0 1-7.143-7.143c-.162-.441.004-.928.38-1.21l1.293-.97c.363-.271.527-.734.417-1.173L6.963 3.102a1.125 '
        '1.125 0 0 0-1.091-.852H4.5A2.25 2.25 0 0 0 2.25 4.5v2.25Z" />'
    ),
    "chevron-down": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />'
    ),
    # ---------------------------------------------------------------------
    # Adicionados na rodada CORRETIVA de UX/UI (28/08/2026 — homologação no
    # Render): sidebar administrativa desktop colapsável + realinhamento do
    # drawer mobile à mesma taxonomia (Operação/Cadastros/Administração).
    # Mesma origem/licença dos ícones acima (Heroicons "outline" 24x24, MIT
    # License). "arrow-up-tray" também corrige uma inconsistência semântica
    # herdada da etapa anterior: "Importar planilha" (upload) usava
    # "arrow-down-tray" (ícone de download) — troca de ícone, nenhum
    # comportamento/permissão alterado.
    # ---------------------------------------------------------------------
    "arrow-up-tray": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 '
        '0 4.5 4.5M12 3v13.5" />'
    ),
    "building-office": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M3.75 21h16.5M4.5 3h15M5.25 3v18m13.5-18v18M9 6.75h1.5m-1.5 3h1.5m-1.5 3h1.5m3-6H15m-1.5 '
        '3H15m-1.5 3H15M9 21v-3.375c0-.621.504-1.125 1.125-1.125h3.75c.621 0 1.125.504 1.125 1.125V21" />'
    ),
    "user-group": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M18 18.72a9.094 9.094 0 0 0 3.741-.479 3 3 0 0 0-4.682-2.72m.94 3.198.001.031c0 '
        '.225-.012.447-.037.666A11.944 11.944 0 0 1 12 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 0 1 '
        '6 18.719m12 0a5.971 5.971 0 0 0-.941-3.197m0 0A5.995 5.995 0 0 0 12 12.75a5.995 5.995 0 0 '
        '0-5.058 2.772m0 0a3 3 0 0 0-4.681 2.72 8.986 8.986 0 0 0 3.74.477m.94-3.197a5.971 5.971 0 0 '
        '0-.94 3.197M15 6.75a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm6 3a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 '
        '4.5 0Zm-13.5 0a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 4.5 0Z" />'
    ),
    "magnifying-glass": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />'
    ),
    "sparkles": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 '
        '3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 '
        '3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 '
        '3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 '
        '3.375 0 0 0-2.456 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 '
        '18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 '
        '1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z" />'
    ),
}

# Vendorizado à parte de `_ICONS`: NÃO é um ícone Heroicons (stroke,
# outline) — é o único logotipo de marca de terceiro usado no projeto
# (identificação do Instagram no menu comercial da landing pública,
# auditoria item [11]). Preenchido (fill), não contornado, porque é assim
# que a marca é reconhecida — path do glifo público padrão do Instagram
# (mesmo formato usado por bibliotecas open-source de ícones de marca,
# ex. Simple Icons, MIT/CC0). Vendorizado uma única vez aqui — nenhuma
# biblioteca de ícones de marca (Font Awesome, etc.) foi adicionada ao
# projeto só por causa deste ícone.
_BRAND_ICONS = {
    "instagram": (
        '<path d="M12 0C8.74 0 8.333.015 7.053.072 5.775.132 4.905.333 4.14.63c-.789.306-1.459.717-2.126 '
        '1.384S.935 3.35.63 4.14C.333 4.905.131 5.775.072 7.053.012 8.333 0 8.74 0 12s.015 3.667.072 '
        '4.947c.06 1.277.261 2.148.558 2.913.306.788.717 1.459 1.384 2.126.667.666 1.336 1.079 2.126 '
        '1.384.766.296 1.636.499 2.913.558C8.333 23.988 8.74 24 12 24s3.667-.015 4.947-.072c1.277-.06 '
        '2.148-.262 2.913-.558.788-.306 1.459-.718 2.126-1.384.666-.667 1.079-1.335 1.384-2.126.296-.765 '
        '.499-1.636.558-2.913.06-1.28.072-1.687.072-4.947s-.015-3.667-.072-4.947c-.06-1.277-.262-2.149-.558'
        '-2.913-.306-.789-.718-1.459-1.384-2.126C21.319 1.347 20.651.935 19.86.63c-.765-.297-1.636-.499'
        '-2.913-.558C15.667.012 15.26 0 12 0zm0 2.16c3.203 0 3.585.016 4.85.071 1.17.055 1.805.249 2.227'
        '.415.562.217.96.477 1.382.896.419.42.679.819.896 1.381.164.422.36 1.057.413 2.227.057 1.266.07 '
        '1.646.07 4.85s-.015 3.585-.074 4.85c-.061 1.17-.256 1.805-.421 2.227-.224.562-.479.96-.898 '
        '1.382-.419.419-.824.679-1.38.896-.42.164-1.065.36-2.235.413-1.274.057-1.649.07-4.859.07-3.211 '
        '0-3.586-.015-4.859-.074-1.171-.061-1.816-.256-2.236-.421-.569-.224-.96-.479-1.379-.898-.421-.419'
        '-.69-.824-.9-1.38-.165-.42-.359-1.065-.42-2.235-.045-1.26-.061-1.649-.061-4.844 0-3.196.016-3.586'
        '.061-4.861.061-1.17.255-1.814.42-2.234.21-.57.479-.96.9-1.381.419-.419.81-.689 1.379-.898.42-.166 '
        '1.051-.361 2.221-.421 1.275-.045 1.65-.06 4.859-.06l.045.03zm0 3.678c-3.405 0-6.162 2.76-6.162 '
        '6.162 0 3.405 2.76 6.162 6.162 6.162 3.405 0 6.162-2.76 6.162-6.162 0-3.405-2.76-6.162-6.162'
        '-6.162zM12 16c-2.21 0-4-1.79-4-4s1.79-4 4-4 4 1.79 4 4-1.79 4-4 4zm7.846-10.405c0 .795-.646 '
        '1.44-1.44 1.44-.795 0-1.44-.646-1.44-1.44 0-.794.646-1.439 1.44-1.439.793-.001 1.44.645 1.44 '
        '1.439z" />'
    ),
}

# Só 2 tamanhos, de propósito (regra do design system: nada de dezenas de
# variantes) — "normal" para ícone complementar em botão/link de texto
# corrido, "compact" para célula de tabela/toolbar densa. A área clicável
# de quem envolve o ícone (.icon-btn) é controlada à parte, via padding —
# nunca aumentando o SVG em si.
_SIZES = {
    "normal": "20",
    "compact": "16",
}


@register.simple_tag
def icon(name, size="normal", extra_class=""):
    inner = _ICONS.get(name)
    if inner is None:
        # Nome desconhecido: nunca derruba a página nem imprime HTML sem
        # escapar — só um comentário discreto pra facilitar debug em dev.
        return mark_safe(f"<!-- icon desconhecido: {escape(name)} -->")

    dimension = _SIZES.get(size, _SIZES["normal"])
    classes = "icon-svg"
    if extra_class:
        classes = f"{classes} {escape(extra_class)}"

    return mark_safe(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{dimension}" height="{dimension}" '
        f'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" '
        f'class="{classes}" aria-hidden="true" focusable="false">{inner}</svg>'
    )


@register.simple_tag
def brand_icon(name, size="normal", extra_class=""):
    """
    Mesma disciplina de `icon()` acima (fail-safe, sempre escapado), mas
    para o dicionário `_BRAND_ICONS` — logotipos de marca de terceiro
    (preenchidos, não contornados). Hoje só "instagram" existe; o nome
    desconhecido tem o mesmo comportamento silencioso de `icon()`.
    """

    inner = _BRAND_ICONS.get(name)
    if inner is None:
        return mark_safe(f"<!-- brand icon desconhecido: {escape(name)} -->")

    dimension = _SIZES.get(size, _SIZES["normal"])
    classes = "icon-svg"
    if extra_class:
        classes = f"{classes} {escape(extra_class)}"

    return mark_safe(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{dimension}" height="{dimension}" '
        f'viewBox="0 0 24 24" fill="currentColor" '
        f'class="{classes}" aria-hidden="true" focusable="false">{inner}</svg>'
    )
