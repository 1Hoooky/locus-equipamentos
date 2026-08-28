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
