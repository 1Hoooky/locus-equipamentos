# Relatório — Rodada corretiva de UX/UI e markup (pós-homologação no Render)

Correções sobre a implementação de `ENTREGA_UX_HOME_NAVEGACAO_QR.md`, sem nenhuma feature de domínio nova. Nenhum model, migration, service, `SubmissionGuard` ou regra de permissão foi alterado — só templates, CSS/JS de front-end e o dicionário de ícones.

---

## 1. Causa exata do vazamento de código

O lexer de templates do Django (`django/template/base.py`) usa:

```
tag_re = re.compile(r"({%.*?%}|{{.*?}}|{#.*?#})")
```

Esse regex é compilado **sem** a flag `re.DOTALL`, então `.` nunca casa quebra de linha. Um comentário `{# ... #}` só é reconhecido como tag quando abre e fecha **na mesma linha**. Um bloco `{# #}` escrito ocupando várias linhas nunca "casa" com o regex — o `{#` de abertura e tudo o que vem depois (inclusive o `#}` que deveria fechá-lo) viram um único `TextNode` literal, impresso do jeito que está na tela. Foi exatamente isso que apareceu no topo da tela de Equipamentos e da landing pública em produção. A correção correta para comentário multi-linha é a tag de bloco `{% comment %}...{% endcomment %}`, que o parser de block tags do Django processa corretamente através de quebras de linha.

## 2. Todas as ocorrências encontradas

Varredura em **toda** a árvore `templates/**/*.html` (não só nos arquivos tocados na etapa anterior), procurando qualquer `{#` sem `#}` de fechamento na mesma linha. Resultado: **exatamente duas ocorrências no projeto inteiro**:

- `templates/base.html` — linhas 103–120 (comentário explicativo do drawer do menu mobile).
- `templates/base_public.html` — linhas 38–43 (comentário explicativo do header público).

Nenhuma outra ocorrência foi encontrada em `_design_tokens.html`, `equipment/detail_public.html`, `dashboard/home.html`, `accounts/login.html` ou em qualquer outro template do projeto — a varredura full-tree confirma que o bug está circunscrito a esses dois pontos.

A landing pública apresentava o mesmo sintoma por uma causa **independente** (investigada, não presumida): toda página pública estende `base_public.html`, e o comentário quebrado ali fica logo antes do `<header>`, então vazava em **toda** página pública, incluindo a própria landing.

## 3. Arquivos corrigidos

- `templates/base.html` — comentário convertido para `{% comment %}...{% endcomment %}`; reescrito também para a sidebar desktop (ver seção 4).
- `templates/base_public.html` — comentário convertido para `{% comment %}...{% endcomment %}`. **Nenhuma outra mudança de arquitetura** — landing pública não foi redesenhada.

Um regression bug adicional foi encontrado e corrigido durante a própria reescrita de `base.html`, antes da entrega: a primeira versão da sidebar colocava `<header>`/`<main>`/`<footer>` inteiros dentro do bloco `{% if user.is_authenticated %}`, o que quebrava a tela de login (nada era renderizado para usuário anônimo). Corrigido restaurando a coluna principal (header/main/footer) fora do `if` — só a sidebar e o drawer (que não fazem sentido para quem não está logado) continuam condicionados à autenticação. Pego pela suíte de testes antes da entrega (`test_login_next_redirect.py`).

## 4. Validação de estrutura HTML

Escrito um validador próprio (`apps/core/tests/html_validation.py`), baseado em `html.parser.HTMLParser` da biblioteca padrão — deliberadamente **não** usa BeautifulSoup/lxml/html5lib (não estavam instalados, e mais importante: esses parsers *reparam* HTML quebrado silenciosamente, escondendo exatamente o tipo de bug que se queria detectar). O validador empilha tags abertas e denuncia: fechamento sem abertura correspondente, fechamento fora de ordem, e tags nunca fechadas até o fim do documento.

Executado sobre HTML renderizado de verdade (via `Client` de teste, não os arquivos-fonte) para: listagem de Equipamentos (4 perfis + superusuário), Home, ficha privada de equipamento, tela de login, e a landing pública (com/sem imagem comercial real, com/sem links comerciais configurados). **Nenhum problema estrutural encontrado** em nenhum caso — ver `apps/core/tests/test_html_structure_validation.py`.

## 5. Arquitetura final da sidebar desktop

Sidebar fixa à esquerda (`<aside id="app-sidebar">`, `>= 640px`), identidade Locus (fundo `brand-black`, dourado para marca/ativo), 3 grupos — mesma taxonomia do drawer mobile (ver seção 6):

- **Topo**: marca "LOCUS Equipamentos" (link para a Home) + subtítulo discreto "Sistema de Equipamentos" + botão de colapsar/expandir.
- **Operação**: Home, Equipamentos, Manutenções, Higienizações (sem gate — todo autenticado vê).
- **Cadastros**: Clientes, Unidades (sem gate) + Categorias, Modelos (gate: `is_administrativo_ou_superior` ou `is_superuser` — mesma condição de antes).
- **Administração** (grupo inteiro só aparece com `is_admin` ou `is_superuser`): Importar planilha, Usuários, Diagnóstico de unidades.

Cada item: ícone Heroicon + texto, área clicável de 44px de altura mínima, hover (`bg-white/10`), estado ativo com **fundo dourado sólido** (`bg-brand-gold text-brand-black`, nunca só cor de texto) + `aria-current="page"`, calculado por `request.resolver_match.view_name` (mesma técnica já usada no drawer). Nenhuma regra de permissão nova — todas as condições (`is_administrativo_ou_superior`, `is_admin`, `is_superuser`) são as mesmas já usadas na navegação anterior e nas views.

A antiga barra horizontal + dropdowns "Cadastros"/"Administração" foi **removida** do template (nenhum elemento `#main-nav`/`[data-dropdown]` é mais renderizado); o CSS `.nav-dropdown-*` ficou órfão no `_design_tokens.html` (inofensivo, sem elemento usando).

## 6. Comportamento colapsado/expandido

Botão de toggle no topo da sidebar (ícone seta esquerda/direita, alterna). 100% client-side (`classList.toggle("is-collapsed")`), vanilla JS, sem framework novo:

- **Expandida** (240px / `w-60`): ícone + texto, títulos de grupo, subtítulo, marca completa.
- **Recolhida** (72px / `4.5rem`): só ícone, centralizado; texto/títulos/subtítulo somem via CSS (`display: none`), marca vira só "L". A área de conteúdo principal recupera o espaço automaticamente (é um filho `flex-1` do mesmo container flex — encolher a sidebar já libera a largura, sem JS adicional no lado do conteúdo).
- Todo link da sidebar sai do servidor já com **`title=` e `aria-label=`** (nome completo do item) — independente do estado, então o nome acessível/tooltip funciona tanto expandido quanto recolhido.
- Preferência de colapso persistida em `localStorage` (chave `locus:sidebarCollapsed`), leitura/escrita protegidas por `try/catch` — se `localStorage` não estiver disponível (navegação privada, política do navegador), o colapso continua funcionando dentro da sessão, só não persiste entre recarregamentos.

## 7. Comportamento mobile

Drawer mantido (mecânica preservada — não foi redesenhado do zero): hambúrguer abre, X fecha, clique no backdrop fecha, Escape fecha, foco vai para o botão de fechar ao abrir e volta ao hambúrguer ao fechar, scroll interno, toque mínimo de 44px, ícone + texto, fecha sozinho se a janela crescer para desktop. **Única mudança estrutural**: taxonomia realinhada de 5 grupos (Operação/Equipamentos/Manutenção/Cadastros/Administração) para os **mesmos 3 grupos da sidebar desktop** (Operação/Cadastros/Administração), com os mesmos itens e as mesmas condições de permissão.

Decisão explícita tomada nesta realinhagem (documentada em `test_mobile_menu_drawer.py`): os atalhos de criação rápida "Novo equipamento"/"Adicionar em lote" — que existiam no antigo grupo "Equipamentos" — não pertencem a nenhum dos 3 grupos aprovados no briefing (seção 3 do pedido de correção não os lista). Saíram do drawer; continuam alcançáveis pelo botão dourado já existente na própria tela de listagem de Equipamentos (que não foi redesenhada). "Importar planilha" migrou do antigo grupo "Equipamentos" para "Administração" — mesma permissão (`is_admin`/`is_superuser`) de antes, só reorganizado visualmente.

O header interno (fora da sidebar/drawer) foi simplificado: sem repetir navegação completa. Contém, no mobile, o botão de abrir o drawer + marca; no desktop, só usuário/perfil + "Sair" (a marca já vive no topo da sidebar, então some do header a partir de `sm:` para não duplicar).

## 8. Novos Heroicons adicionados

Vendorizados em `apps/core/templatetags/icons.py` (mesma licença/origem dos existentes — Heroicons outline 24×24, MIT), usando exclusivamente o mecanismo `{% icon %}` já existente — nenhuma biblioteca nova:

| Ícone | Uso | Observação |
|---|---|---|
| `sparkles` | Higienizações | Antes usava `tag`, semanticamente melhor agora |
| `building-office` | Unidades | Antes usava `archive-box` (que passou a ser de Equipamentos) |
| `arrow-up-tray` | Importar planilha | Corrige inconsistência: a etapa anterior usava `arrow-down-tray` (ícone de *download*) para uma ação de *upload* |
| `user-group` | Usuários | Distinto de `users` (Clientes), evita o mesmo ícone para dois conceitos diferentes |
| `magnifying-glass` | Diagnóstico de unidades | Antes usava `cog-6-tooth` (ícone de "configurações", não de "diagnóstico/busca") |

`Equipamentos` passou a usar `archive-box` (era `cube`); `Modelos` ficou com `cube`.

## 9. Testes adicionados/alterados

- **Novos**: `apps/core/tests/test_no_leaked_template_comments.py` (7 testes — trava os dois textos exatos que vazaram + checagem genérica de qualquer `{#` sem `#}` em qualquer página renderizada), `apps/core/tests/html_validation.py` (validador, sem testes próprios), `apps/core/tests/test_html_structure_validation.py` (9 testes — estrutura bem formada em todas as páginas alteradas, por perfil), `apps/core/tests/test_desktop_sidebar.py` (14 testes — substitui `test_desktop_nav_dropdowns.py`, cobre acessibilidade, taxonomia compartilhada, colapso/expansão, matriz de permissão de 4 perfis + superusuário).
- **Removido**: `apps/core/tests/test_desktop_nav_dropdowns.py` (testava a navegação por dropdowns, que não existe mais).
- **Atualizado**: `apps/core/tests/test_mobile_menu_drawer.py` (taxonomia de 3 grupos, remoção documentada dos atalhos de criação), `apps/operations/tests/test_duplicate_locations_report.py` (contagem de `<button>` no chrome global: 6 → 5 — um único toggle de sidebar no lugar dos dois toggles de dropdown da etapa anterior; contagem de `<form>` continua 2, sem alteração; nenhuma asserção de privacidade/conteúdo foi enfraquecida).
- Nenhum teste de privacidade pré-existente foi alterado ou enfraquecido (os 3 testes de vazamento de dado sensível na landing pública, o `assertNumQueries(1)` da rota pública, e toda a suíte de `test_public_detail_view.py`/`test_public_detail_no_operational_leak.py` continuam intactos e passando).

## 10. Total final da suíte

```
Ran 577 tests in 208.571s
OK
```

## 11. `manage.py check`

```
System check identified no issues (0 silenced).
```

## 12. `makemigrations --check --dry-run`

```
No changes detected
```

---

## Checklist manual de homologação no Render

**Vazamento de código (prioridade máxima):**
- [ ] Abrir a listagem de Equipamentos — nenhum texto de comentário aparece no topo da página
- [ ] Abrir a landing pública de qualquer equipamento (QR) — nenhum texto de comentário aparece

**Sidebar desktop:**
- [ ] Expandida por padrão na primeira visita; ícone + texto de cada item legível
- [ ] Botão de colapsar reduz para só ícones; texto de grupo/marca somem; conteúdo principal ganha o espaço liberado
- [ ] Recarregar a página mantém o estado colapsado/expandido escolhido (via `localStorage`)
- [ ] Passar o mouse sobre um ícone recolhido mostra o tooltip (nome do item)
- [ ] Item da tela atual aparece com fundo dourado (estado ativo) tanto expandido quanto recolhido
- [ ] Perfil Consulta/Operacional não vê "Categorias"/"Modelos"/grupo "Administração"; Administrativo vê Categorias/Modelos mas não Administração; Admin/superusuário vê tudo

**Drawer mobile:**
- [ ] Abertura/fechamento (hambúrguer, X, clique fora, Escape)
- [ ] Scroll interno com muitos itens (perfil Admin)
- [ ] Toque de 44px em dispositivo real
- [ ] Grupos exibidos são só Operação/Cadastros/Administração (não mais 5 grupos)
- [ ] "Novo equipamento"/"Adicionar em lote" não aparecem no drawer, mas o botão dourado na tela de Equipamentos continua funcionando

**Header interno:**
- [ ] Desktop: sem barra horizontal duplicada, só usuário/perfil + Sair
- [ ] Mobile: botão de abrir o drawer visível e funcional

**Landing pública / fluxo QR:**
- [ ] Fallback de imagem (`_placeholder.webp`) continua aparecendo para modelo sem foto real
- [ ] CTAs continuam condicionados às URLs configuradas (nenhum `href="#"` quebrado)
- [ ] QR → "Entrar" → login → volta para a ficha PRIVADA do mesmo equipamento

**Telas internas não tocadas:**
- [ ] Listagem de Equipamentos continua com o mesmo visual de conteúdo (título, botão dourado, filtros, tabela, badges) — só o chrome ao redor mudou

---

*Nenhuma feature nova além destas correções de UX/UI/markup. `qrcodes/label.html` não foi tocado. Nenhum model/migration/service/`SubmissionGuard`/regra de permissão foi alterado.*
