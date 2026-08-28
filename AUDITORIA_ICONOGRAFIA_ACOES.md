# Auditoria de iconografia e apresentação de ações — pré-requisito para a próxima etapa

**Data:** 28/08/2026
**Natureza:** só auditoria. Nenhum template, form, view, model, migration, service, permissão, URL, ID/name de campo, lógica HTMX ou comportamento de POST foi alterado nesta etapa. `qrcodes/label.html` não foi tocado nem inventariado em detalhe (fora de escopo, como determinado).

---

## 1. Inventário das ações existentes

Levantamento direto no HTML de todas as 47 telas ativas (exceto `qrcodes/label.html`). Agrupado por tipo de ação — cada ação lista as telas onde aparece, para evitar repetir ~90 ocorrências quase idênticas.

**Navegação para trás:** "&larr; Voltar" (`detail_private`, `client_detail`, `location_detail`, `movement_form`, e os 7 templates de Manutenção/Higienização), "Voltar e corrigir" (`batch_confirm`), "Voltar sem cancelar" (confirmações de cancelamento), "Cancelar e enviar outro arquivo" (`import_review`), "&larr; Ver categorias" / "Ver modelos de equipamento &rarr;" (navegação cruzada Catálogo).

**Ação primária de tela (sempre botão textual, `.btn-primary`):** "Novo equipamento", "Novo cliente", "Nova unidade", "Nova categoria", "Novo modelo", "Novo usuário", "Cadastrar"/"Salvar alterações" (`equipment_form`), "Confirmar" (`change_status`/`change_condition`), "Reclassificar", "Continuar" (`batch_create`), "Confirmar e criar N equipamentos" (`batch_confirm`), "Enviar e analisar" (`import_upload`), "Confirmar importação" (`import_review`), "Abrir manutenção", "Concluir manutenção", "Registrar higienização", "Entrar" (login), "Salvar cliente"/"Consultar CNPJ", "Salvar" (demais forms), "Registrar" (`movement_form`), "Filtrar" (4 listagens).

**Ação sensível (mantém peso visual/vermelho, nunca vira ícone sozinho):** "Reemitir patrimônio" (link em `detail_private`, botão em `supersede`), "Cancelar manutenção" / "Cancelar registro" (Higienização) — já com fluxo de confirmação dedicado.

**Ação destrutiva com confirmação própria:** "Confirmar cancelamento" (`maintenance_cancel_confirm`, `cleaning_cancel_confirm`) — POST-only, exige motivo/checkbox.

**Ação contextual de registro (dentro da ficha do equipamento, ação operacional do dia a dia):** "Registrar movimentação", "Alterar status", "Alterar condição", "Abrir manutenção", "Registrar higienização", "Editar dados", "Reclassificar modelo" — todas em `detail_private.html`, lado a lado.

**Ação de utilidade (QR/impressão/exportação):** "QR" / "Etiqueta" (colunas de `equipment/list.html`), "Ver QR Code" / "Baixar QR Code (PNG)" / "Baixar etiqueta (PDF)" (`detail_private.html`), "Exportar CSV" / "Exportar Excel" / "Exportar QR Codes" / "Exportar Etiquetas" (cabeçalho de `equipment/list.html`), "Ver equipamentos criados" / "Exportar etiquetas deste lote" / "Exportar QR Codes deste lote" (`batch_result.html`), "Adicionar equipamentos em lote".

**Navegação de listagem → detalhe ("Ver"):** `client_list.html`, `location_list.html`, e os links de patrimônio/nome em praticamente toda tabela (`equipment/list.html`, `maintenance/*_list.html`) — o próprio identificador (patrimônio, nome) já é o link, sem palavra "Ver" ao lado.

**Ação de edição:** "Editar" (`user_list`, `category_list`, `model_list`), "Editar dados" / "Editar endereço fiscal" / "Editar endereço" / "Editar unidade" (`client_detail`, `location_detail`).

**Paginação:** "Anterior" / "Próxima" (com `&larr;`/`&rarr;` já como prefixo/sufixo em `client_list.html`, sem seta nas demais 3 listagens).

**Formulário — ação secundária de saída (nunca destrutiva, é só "descartar e voltar"):** "Cancelar" — presente em praticamente todo formulário (16 telas), sempre como `.btn-neutral`.

**Link para registro relacionado ("Ver"/"ver ficha"):** dentro da seção "Manutenção e higienização" de `detail_private.html` (2 ocorrências) e no banner de manutenção em aberto.

## 2. Inconsistências encontradas

- **"Ver" tem dois papéis diferentes hoje**: às vezes é o próprio identificador clicável (patrimônio, nome da unidade), às vezes é uma palavra separada ("Ver" em `client_list.html`/`location_list.html`, "Ver" nos itens da seção de manutenção/higienização). Substituir só uma dessas formas por ícone sem tratar a outra criaria uma segunda inconsistência.
- **Paginação sem padrão único de seta**: `client_list.html` já usa `&larr;`/`&rarr;` (entidade HTML, não ícone); as outras 3 listagens (`equipment`, `maintenance`, `cleaning`) usam só o texto "Anterior"/"Próxima" sem seta nenhuma.
- **"Voltar" tem 3 variações de texto** ("Voltar", "Voltar e corrigir", "Voltar sem cancelar", "Cancelar e enviar outro arquivo") para o mesmo gesto de navegação-para-trás — um ícone de seta consistente ajudaria a reconhecer o padrão rapidamente, mas o texto que o acompanha precisa continuar variando (o motivo de cada "voltar" é diferente e relevante).
- **Densidade real de ações por linha de tabela**: hoje só duas tabelas têm mais de uma ação por linha — `equipment/list.html` (QR · Etiqueta) e nenhuma outra lista tem coluna de ações múltiplas (as demais têm só "Editar" ou "Ver", uma ação cada). A "sobrecarga visual" citada no pedido está concentrada em **duas fichas de detalhe** (`equipment/detail_private.html` com 8 ações + 3 de utilidade, e em menor grau `client_detail.html` com 3+2 ações), não nas tabelas em si — as tabelas do sistema já são enxutas.
- **Nenhum SVG/ícone existe hoje no projeto** além de 1 ícone de hambúrguer (menu mobile, em `base.html`) e o próprio QR Code gerado (`qrcodes/label.html`, fora de escopo) — ou seja, esta é a primeira introdução real de iconografia ao sistema, não uma padronização de algo já parcialmente feito.

## 3. Proposta de estratégia de iconografia

Aplicando a regra que você definiu (recorrente + universal → ícone; importante/específico/ambíguo → texto ou ícone+texto; ação primária → texto), a inventário acima aponta para:

- **Podem virar só ícone (com `aria-label`)**: Voltar (seta ← — mas em telas onde o texto ao lado já explica o destino, como "Voltar e corrigir"/"Voltar sem cancelar", o texto permanece, só ganha um ícone de seta ao lado, não substitui), QR (ícone de QR code), Etiqueta (ícone de tag), Ver/detalhe quando já existe um identificador textual ao lado (ex.: a coluna "Ver" de `client_list.html`/`location_list.html`, onde o nome já está na linha), paginação Anterior/Próxima (seta, mantendo "Anterior"/"Próxima" como texto por enquanto — ver seção 11 sobre mobile).
- **Devem continuar com texto, ou ganhar ícone+texto (nunca só ícone)**: "Editar dados", "Editar endereço fiscal", "Editar endereço", "Editar unidade" (múltiplas ações de "editar" diferentes na mesma tela do cliente — só um lápis sem contexto ficaria ambíguo entre elas); "Reclassificar modelo"; "Reemitir patrimônio" (ação sensível, cor + texto + ícone); "Registrar movimentação"/"Alterar status"/"Alterar condição"/"Abrir manutenção"/"Registrar higienização" (ações contextuais específicas do domínio, não universalmente reconhecíveis por ícone sozinho); "Cancelar manutenção"/"Cancelar registro"/"Confirmar cancelamento" (ações que já têm fluxo de confirmação — o texto explícito é parte da segurança da interação, não só estética).
- **Continuam 100% texto (ação primária ou ambígua demais para ícone)**: toda a lista da seção "ação primária de tela" acima, "Cancelar" genérico de formulário (ganha ícone de X pequeno como reforço, mas o texto "Cancelar" permanece — sozinho um X poderia ser lido como "fechar/excluir").
- **Onde uma toolbar compacta ajuda de fato**: só a coluna QR/Etiqueta de `equipment/list.html` hoje (2 ações lado a lado) — mas o maior ganho está em reorganizar as ações de `detail_private.html` em grupos visuais (ver seção 8), não em "esconder" nada atrás de ícone.
- **Onde ícone isolado pioraria a leitura**: qualquer uma das 6 ações contextuais de `detail_private.html` (Registrar movimentação, Alterar status/condição, Abrir manutenção, Registrar higienização, Reclassificar) — são específicas do domínio de locação de equipamentos, sem ícone universalmente reconhecível equivalente, e a ficha do equipamento é justamente onde o operador precisa ter certeza absoluta do que está clicando.

## 4. Biblioteca/abordagem técnica recomendada

**Contexto técnico confirmado por auditoria direta**: não existe `package.json` nem qualquer pipeline de build front-end no projeto — `base.html` carrega Tailwind e htmx puramente via `<script src="https://cdn...">`, sem npm/webpack/vite. Nenhuma biblioteca de ícone está presente hoje (0 ocorrências de Font Awesome, Bootstrap Icons, Material Icons, ou qualquer sprite).

**Recomendação: SVG inline vendorizado, servido via template tag Django — sem nova dependência JS, sem chamada de rede nova.**

Concretamente: criar `apps/core/templatetags/icons.py` com uma tag (`{% icon "eye" %}` ou `{% icon "eye" size="sm" %}`) que recebe o nome do ícone e devolve o `<svg>...</svg>` correspondente já com as classes Tailwind de tamanho/cor aplicadas — os `path`/`d` de cada ícone ficam vendorizados como strings Python (ou arquivos `.svg` lidos uma vez), copiados do conjunto **Heroicons** (MIT, mantido pela própria equipe do Tailwind CSS — por isso os tamanhos já "conversam" com as convenções Tailwind que o projeto já usa: `outline`/`solid` 24×24 para botões, e o subconjunto **`mini`** 20×20 e **`micro`** 16×16 já desenhados especificamente para UI compacta — exatamente o caso de "ícone compacto para tabela" pedido na Fase 3).

Por que essa abordagem e não as alternativas:

- **CDN de ícones (ex. `<script src="...iconify...">` ou Font Awesome via CDN)**: rejeitado — é exatamente o tipo de dependência externa nova que a instrução pede para evitar, adiciona uma chamada de rede a mais por página (mesmo risco de bloqueio que já vimos com o CDN do Tailwind neste ambiente de sandbox), e a maioria dessas libs carrega o conjunto INTEIRO de milhares de ícones por JS, quando o sistema precisa de ~15-20.
- **Pacote npm (Heroicons/Lucide via npm + build step)**: rejeitado nesta etapa — exigiria introduzir um pipeline de build (webpack/vite/esbuild) que hoje não existe no projeto, uma mudança de arquitetura desproporcional só para servir ícones, e um novo passo de deploy no Render.
- **Dezenas de SVGs colados diretamente em cada template**: rejeitado — é textualmente o problema que a instrução pede para evitar ("dezenas de SVGs diferentes copiados sem padrão"); sem um ponto central, o mesmo ícone "editar" acabaria com pequenas divergências entre telas ao longo do tempo.
- **Sprite único (`<svg style="display:none"><symbol id="icon-eye">...</symbol></svg>` definido uma vez em `base.html`, referenciado via `<use href="#icon-eye">` em cada tela)**: **alternativa tecnicamente válida e mais econômica em bytes por página** (cada uso vira `<svg class="..."><use href="#icon-eye"/></svg>`, ~40 bytes, contra ~150–300 bytes de um `<svg>` inline completo). Funciona bem porque a referência é sempre para o MESMO documento (não hotlink de arquivo externo, que tem restrições reais de cache/CORS em alguns navegadores). Estou citando como alternativa porque, para um sistema administrativo interno de baixo tráfego como este, a diferença de peso de página é irrelevante, e a tag Django é mais simples de manter, testar e de adicionar `aria-label`/`title` dinamicamente por uso — mas é uma escolha legítima se você preferir menos HTML repetido.
- **Emoji ou caracteres Unicode**: já excluído explicitamente pela sua instrução — e tecnicamente problemático mesmo sem essa restrição (renderização inconsistente entre sistema operacional/fonte, sem controle de peso de traço/tamanho, sem `aria-hidden` limpo).

**Decisão que precisa da sua aprovação:** confirmar Heroicons (ou, se preferir, Lucide — mesma viabilidade técnica, ISC license, também sem npm necessário para vendorizar os SVGs manualmente) como conjunto de referência, e template tag Django (opção A) vs. sprite `<symbol>`/`<use>` (opção B) como mecanismo de entrega. Meu recomendo é **A** (template tag) pela simplicidade e pela facilidade de acessibilidade por uso.

## 5. Componentes reutilizáveis propostos para o design system

A adicionar em `base.html`, no mesmo `@layer components` onde já vivem `.btn-*`/`.badge-*`:

- **`.icon-btn`** (base) — botão/link quadrado, ícone centralizado, `min-width`/`min-height` de 40px (ver seção 9, área de toque), `rounded-lg`, foco visível com o mesmo anel dourado já usado em `.btn`.
- **`.icon-btn-neutral`** — para ações de utilidade/navegação (QR, etiqueta, editar em tabela) — cinza, hover sutil. É o mais usado.
- **`.icon-btn-primary`** — reservado para os poucos casos em que uma ação primária secundária de tela (não a ação principal) se beneficia de destaque dourado com ícone — uso esperado raro.
- **`.icon-btn-danger`** — para ações sensíveis quando acompanhadas de ícone + texto (nunca só ícone) — mesma paleta vermelha de `.btn-danger`.
- **`.icon-inline`** — não é um botão, é só o ícone dimensionado para viver DENTRO de um `.link`/`.btn-*` já existente, ao lado do texto (ex.: seta de voltar antes do texto "Voltar").
- **`.action-group`** — container flex compacto (`gap-1`, sem bordas entre itens) para agrupar 2–3 `.icon-btn` lado a lado numa célula de tabela ou numa ficha, evitando repetir `flex gap-*` em cada template.

Tamanhos (evitando variantes demais, como pedido):

- **Ícone normal** (dentro de botão textual ou como `.icon-btn` isolado em ficha/ação de destaque): 20×20 (Heroicons `mini`).
- **Ícone compacto de tabela** (`.icon-btn` dentro de célula): 16×16 (Heroicons `micro`), com a área clicável do `.icon-btn` ainda em 32–36px mínimo — o ícone é pequeno, o alvo de toque não.
- Não proponho uma terceira variante de tamanho — dois tamanhos cobrem todos os casos do inventário.

## 6. Tabela de ações — tela, categoria, tratamento proposto

| Tela(s) | Ação atual | Categoria | Tratamento proposto | Ícone sugerido | Texto permanece? |
|---|---|---|---|---|---|
| Praticamente todas (detalhe/formulário) | "Voltar" / "&larr; Voltar" | Navegação | Ícone + texto | seta-esquerda (`arrow-left`) | Sim |
| `batch_confirm`, `import_review`, confirmações de cancelamento | "Voltar e corrigir" / "Cancelar e enviar outro arquivo" / "Voltar sem cancelar" | Navegação | Ícone + texto (texto varia por contexto) | seta-esquerda | Sim |
| Todo formulário (16 telas) | "Cancelar" | Navegação/saída de formulário | Ícone + texto | X (`x-mark`) | Sim |
| `client_list.html`, `location_list.html` | "Ver" (coluna de tabela) | Navegação (linha já nomeada) | Só ícone, com `aria-label="Ver detalhes de {{ objeto }}"` | olho (`eye`) | Não (some, ícone assume) |
| `detail_private.html` (seção de manutenção/higienização) | "Ver" / "ver ficha" | Navegação contextual | Ícone + texto curto ("Ver ficha") | olho | Sim |
| `equipment/list.html` (coluna QR) | "QR" | Utilidade | Só ícone, `aria-label="Ver QR Code de {{ patrimônio }}"` | QR code (`qr-code`) | Não |
| `equipment/list.html` (coluna Etiqueta) | "Etiqueta" | Utilidade | Só ícone, `aria-label="Baixar etiqueta de {{ patrimônio }}"` | tag (`tag`) | Não |
| `detail_private.html` | "Ver QR Code" | Utilidade | Ícone + texto (ação isolada, fora de tabela — espaço não é problema aqui) | QR code | Sim |
| `detail_private.html` | "Baixar QR Code (PNG)" / "Baixar etiqueta (PDF)" | Utilidade | Ícone + texto | download / tag | Sim |
| `equipment/list.html` (cabeçalho) | "Exportar CSV" / "Exportar Excel" / "Exportar QR Codes" / "Exportar Etiquetas" | Utilidade | Ícone + texto (4 ações parecidas, ícone ajuda a escanear, texto ainda necessário para diferenciar formato) | download | Sim |
| `user_list`, `category_list`, `model_list` | "Editar" (tabela, 1 ação por linha) | Edição | Só ícone, `aria-label="Editar {{ objeto }}"` | lápis (`pencil`) | Não |
| `client_detail.html` | "Editar dados" / "Editar endereço fiscal" | Edição (ambíguo entre si) | Ícone + texto | lápis | Sim |
| `location_detail.html` | "Editar unidade" / "Editar endereço" | Edição (ambíguo entre si) | Ícone + texto | lápis | Sim |
| `client_detail.html` (por unidade) | "Editar endereço" | Edição | Ícone + texto (repetido por linha, mas dentro de uma lista curta, não tabela densa) | lápis | Sim |
| `detail_private.html` | "Registrar movimentação" | Contextual de registro | Botão textual, ícone opcional complementar | seta-troca (`arrows-right-left`) opcional | Sim, sempre |
| `detail_private.html` | "Alterar status" / "Alterar condição" | Contextual de registro | Botão textual, sem ícone (ambíguo — "status" e "condição" não têm símbolo universal) | — | Sim, sempre |
| `detail_private.html` | "Abrir manutenção" / "Registrar higienização" | Contextual de registro | Botão textual (ação primária desses fluxos) | chave-inglesa (`wrench`) / gota (`sparkles`) opcional | Sim, sempre |
| `detail_private.html`, `equipment_form.html` | "Reclassificar modelo" | Contextual, pouco frequente | Botão/link textual, sem ícone | — | Sim, sempre |
| `detail_private.html`, `supersede.html` | "Reemitir patrimônio" | Ação sensível | Ícone + texto + cor vermelha mantida | troca (`arrow-path`) | Sim, sempre |
| `maintenance_detail.html` | "Concluir manutenção" | Contextual de registro (ação primária da tela) | Botão textual | check (`check`) opcional | Sim |
| `maintenance_detail.html`, `cleaning_detail.html` | "Cancelar manutenção" / "Cancelar registro" | Ação sensível | Ícone + texto (leva à tela de confirmação) | X | Sim |
| `*_cancel_confirm.html` | "Confirmar cancelamento" | Ação destrutiva (final, após confirmação) | Ícone + texto, cor de perigo | X ou alerta (`exclamation-triangle`) | Sim, sempre |
| `equipment/list.html`, `maintenance/*_list.html` | "Anterior" / "Próxima" | Paginação | Ícone + texto no desktop; ícone só (com `aria-label`) em telas muito estreitas se necessário (ver seção 11) | seta-esquerda / seta-direita | Sim (desktop) |
| Todas as listagens com filtro | "Filtrar" | Utilidade/ação de formulário | Permanece texto — "Filtrar" já é curto e é o único botão daquela cor na tela, ícone acrescentaria pouco | filtro (`funnel`) opcional, baixa prioridade | Sim, sempre |
| Toda tela com ação primária ("Novo X", "Salvar", "Confirmar", "Continuar", "Abrir manutenção" como botão, etc.) | — | Ação primária | Permanece 100% botão textual `.btn-primary`, sem substituir por ícone (pode ganhar um ícone complementar pequeno em casos pontuais, nunca substituindo o texto) | variável, baixa prioridade | Sim, sempre |

## 7. Proposta específica para `equipment/list.html`

- Cabeçalho: "Novo equipamento" continua botão textual dourado (ação primária). As 5 ações secundárias ("Adicionar em lote", "Exportar CSV", "Exportar Excel", "Exportar QR Codes", "Exportar Etiquetas") ganham ícone pequeno + texto — hoje são 5 links de texto dourado em fila, o ícone ajuda a escanear rapidamente qual é qual sem precisar ler as 5 palavras.
- Filtros: sem mudança — "Filtrar" continua texto (seção 6).
- Tabela: coluna "QR" e coluna "Etiqueta" (hoje 2 palavras + separador "·") viram um `.action-group` com 2 `.icon-btn-neutral` (ícone QR + ícone tag), cada um com `aria-label` específico incluindo o patrimônio da linha — reduz a coluna de ~20 caracteres de texto para 2 ícones de 16×16, ganho real de densidade numa tabela que pode ter dezenas de linhas visíveis.
- O link do próprio patrimônio (`{{ equipment.patrimonio }}`) continua exatamente como está — é a navegação primária da linha, já funciona bem como texto/link, não deveria virar ícone.
- Paginação: "Anterior"/"Próxima" ganham seta ao lado do texto no desktop.

## 8. Proposta específica para `equipment/detail_private.html`

Esta é a tela mais carregada do sistema — 6 ações contextuais + 2 administrativas + 1 sensível na mesma barra, mais 3 ações de utilidade (QR/etiqueta) logo abaixo. Análise honesta antes de propor qualquer mudança estrutural:

- **Não recomendo dropdown ou menu de 3 pontos.** Justificativa: as 6 ações contextuais (Registrar movimentação, Alterar status, Alterar condição, Abrir manutenção, Registrar higienização, Editar dados) são exatamente as ações que um operador usa no dia a dia — escondê-las atrás de um menu obrigaria um clique extra para tarefas de alta frequência, o oposto do "leitura rápida, ações primárias óbvias" que a padronização visual anterior já estabeleceu como prioridade. Um menu faria sentido para ações RARAS (ex.: Reclassificar modelo, Reemitir patrimônio), mas mesmo essas já são poucas o bastante para não justificar a complexidade de um menu (que traria sua própria carga de acessibilidade — foco de teclado, `Escape` para fechar, clique fora, etc. — não trivial "de graça").
- **Proposta real: separar visualmente em 2 grupos, sem esconder nada.** Grupo 1 ("ações operacionais do dia a dia" — Registrar movimentação, Alterar status, Alterar condição, Abrir manutenção, Registrar higienização): continuam como estão, texto simples, talvez com ícone complementar pequeno cada uma. Grupo 2 ("ações administrativas/pouco frequentes" — Editar dados, Reclassificar modelo, Reemitir patrimônio): visualmente separado (ex.: um `border-l` ou um segundo card mais discreto), mantendo texto e a cor de alerta do "Reemitir patrimônio". Essa separação já existe parcialmente no código (Editar/Reclassificar/Reemitir já são condicionados a `is_administrativo_ou_superior`/`is_admin`), então a separação visual reforça uma distinção que a permissão já estabelece — não é uma reorganização arbitrária.
- Seção QR/etiqueta (3 links): viram `.action-group` com ícone + texto curto cada (QR Code / Baixar PNG / Baixar PDF) — aqui, diferente da tabela, sobra espaço horizontal, então o texto continua, só ganha o ícone como reforço visual de reconhecimento rápido.
- Badges de Status/Condição (já implementados na etapa anterior) permanecem como estão — não fazem parte desta auditoria de ícones de ação.

## 9. Tratamento de ações sensíveis/destrutivas

- Nenhuma ação sensível ou destrutiva deste sistema pode ser representada só por ícone — todas mantêm texto explícito, seguindo sua regra 4 (nunca depender só de cor) e regra 5 (nunca só ícone sem identificação clara) já embutidas na sua instrução.
- "Reemitir patrimônio": ícone + texto + `text-red-600` mantido (como já está desde a padronização anterior) — o ícone reforça reconhecimento, não substitui a explicação.
- "Cancelar manutenção" / "Cancelar registro" (Higienização): ícone (X) + texto, leva para a tela de confirmação já existente (`*_cancel_confirm.html`) — nenhuma mudança no fluxo de 2 passos já implementado.
- "Confirmar cancelamento" (a ação final, dentro da tela de confirmação, POST real): ícone de alerta ou X + texto + `.btn-danger`, exatamente como já está hoje — nenhuma mudança funcional, só a adição do ícone ao botão que já existe.
- Em nenhum caso o ícone muda a exigência de confirmação/motivo já implementada pelo `SubmissionGuard`/formulário — a auditoria não encontrou nenhum lugar onde adicionar um ícone reduziria a segurança de uma ação destrutiva.

## 10. Estratégia de acessibilidade

- **Todo `.icon-btn` sem texto visível recebe `aria-label` descritivo e específico** (nunca genérico como "ação" — sempre "Ver detalhes de {{ patrimônio }}", "Baixar etiqueta de {{ patrimônio }}" etc., interpolando o identificador da linha quando fizer sentido, para diferenciar múltiplas linhas de tabela entre si para quem usa leitor de tela).
- **`title` como complemento, não substituto**: `title="{{ mesmo texto do aria-label }}"` no mesmo elemento cobre o tooltip nativo do navegador no hover, sem precisar de nenhum JS/framework de tooltip — atende ao pedido de "mecanismo simples equivalente" sem introduzir peso novo. Suficiente para este projeto: são ações bem conhecidas (editar, ver, baixar), não conceitos que precisem de uma explicação longa que só um tooltip rico resolveria.
- **Foco de teclado**: `.icon-btn` herda o mesmo `focus-visible:ring-2 focus-visible:ring-brand-gold` já definido em `.btn` — nenhum componente novo de foco, reaproveita o que já existe.
- **Navegação por teclado**: como todo `.icon-btn` continua sendo um `<a>`/`<button>` real (nunca uma `<div onclick>`), tab/Enter já funcionam nativamente — nenhum JS adicional necessário para isso.
- **Área de toque**: `.icon-btn` definido com no mínimo 32×32px de área clicável (ícone de 16×16 centralizado dentro, com padding) — abaixo da recomendação usual de 44×44 para toque primário, mas adequado para uma ferramenta de uso majoritariamente desktop/mouse com ações secundárias em tabela; nas telas onde a ação é mais provável de ser tocada no celular (ex.: os botões de ação de `detail_private.html`), o tamanho sobe para o padrão de botão normal (`.btn`/`.icon-btn` em tamanho "normal" 20×20 com padding maior), não o compacto de tabela.
- **Cor nunca é o único sinal**: já é uma prática existente no design system (badges sempre têm texto dentro, nunca só uma bolinha colorida) — a iconografia segue a mesma regra: um ícone vermelho de "Reemitir patrimônio" sempre vem com a palavra ao lado, nunca só a cor/forma.

## 11. Estratégia desktop/mobile

- **Desktop**: onde há espaço horizontal sobrando (fichas de detalhe, cabeçalhos de lista), ícone + texto é o padrão — o ícone só têm ganho real de densidade dentro de células de tabela estreitas (QR/Etiqueta) ou onde o texto já é redundante com o conteúdo da linha (coluna "Ver").
- **Mobile**: nenhuma ação vira ícone-sozinho SÓ por estar em tela estreita se ela não era ícone-sozinho no desktop — ex.: "Editar dados"/"Editar endereço fiscal" continuam com texto em mobile também, porque a ambiguidade entre elas não desaparece em tela pequena. A área de toque dos `.icon-btn` que já são ícone-sozinho (Ver, QR, Etiqueta, Editar-de-tabela) precisa ser confirmada ≥32px também em mobile — nenhuma tabela vira layout de cards nesta etapa (fora de escopo, como já determinado na padronização anterior), então essas colunas de ícone continuam dentro da mesma `.table-wrap` com `overflow-x-auto` já existente.
- **Paginação em mobile**: "Anterior"/"Próxima" — proponho manter o texto mesmo em mobile (não reduzir a só seta), porque são apenas 2 ocorrências por página e a perda de clareza não compensa o pequeno ganho de espaço; é uma decisão de baixo risco que também fica para sua aprovação caso prefira o contrário.

## 12. Arquivos que seriam alterados numa implementação futura

- **Novo**: `apps/core/templatetags/icons.py` (a tag `{% icon %}` e o dicionário de SVGs vendorizados).
- `templates/base.html` — adicionar `{% load icons %}` no topo e as novas classes `.icon-btn*`/`.action-group` ao `@layer components`; o botão de menu mobile (`#nav-toggle`, hoje com um SVG solto) passaria a usar a mesma tag, por consistência.
- Templates com ações a converter: `equipment/list.html`, `equipment/detail_private.html`, `clients/client_list.html`, `clients/client_detail.html`, `operations/location_list.html`, `operations/location_detail.html`, `catalog/category_list.html`, `catalog/model_list.html`, `accounts/user_list.html`, os 10 templates de `maintenance/`, `equipment/batch_result.html`, `equipment/import_summary.html`, e os botões "Cancelar"/"Voltar" nos 16 formulários simples já migrados na etapa anterior — na prática, a maioria dos 37 templates já padronizados visualmente ganha pelo menos um ícone.
- Nenhuma alteração prevista em `apps/*/views.py`, `apps/*/forms.py` (além, se necessário, de nenhuma — a tag de ícone é só de template), `apps/*/models.py`, `apps/*/services.py`, `apps/*/urls.py`, `apps/*/migrations/`.

## 13. Riscos de regressão

- **Baixo, mas real, para leitores de tela e testes que verificam texto visível**: qualquer teste que hoje faça `assertContains(response, "Editar")` ou `assertContains(response, "QR")` como STRING VISÍVEL pararia de encontrar esse texto nas ações que viram ícone-sozinho (ver seção 14) — precisa de verificação linha a linha antes de implementar, trocando essas asserções por checagem do `aria-label` ou do `href`, quando for o caso.
- **Baixo para comportamento**: como nenhum `href`, `name`, `id` ou atributo `hx-*` muda — só o conteúdo visual interno do link/botão —, o risco sobre HTMX/SubmissionGuard/permissões é praticamente nulo.
- **Baixo, mas requer atenção manual**: o mesmo teste `test_page_exposes_no_destructive_action` (`apps/operations/tests/test_duplicate_locations_report.py`) que já se mostrou sensível a mudanças estruturais globais duas vezes nesta jornada (contagem de `<button>`) pode voltar a precisar de ajuste SE a tag `{% icon %}` renderizar `<svg>` dentro de um `<button>` em algum lugar que hoje não tem — precisa ser conferido especificamente nessa página quando a implementação acontecer (ela é somente-leitura, não deveria ganhar `.icon-btn` nenhum, mas herda qualquer coisa nova em `base.html`).
- **Nenhum risco identificado** para regras de domínio, permissões, ou dados — coerente com o fato de que só o markup interno de elementos de navegação/ação muda.

## 14. Testes que poderiam ser afetados

Varredura da suíte por asserções de texto visível ligadas às ações candidatas a virar ícone-sozinho:

- Testes que verificam `assertContains(response, "Editar")` nas listagens de Usuários/Categorias/Modelos, se existirem, precisariam trocar para checar o `href` do link de edição ou o `aria-label`, em vez do texto "Editar" — a checar linha a linha no momento da implementação (não levantei essa varredura profunda agora porque isso já seria começar a implementar, não auditar; a varredura completa faz parte da próxima etapa).
- Testes de `client_list.html`/`location_list.html` que possam checar a palavra "Ver" no HTML da tabela.
- Testes de `equipment/list.html` que possam checar as palavras "QR"/"Etiqueta" como texto visível na tabela (distinto dos testes que checam a URL `qrcodes:qr_png`/`qrcodes:label_pdf`, que continuam válidos sem mudança).
- Nenhum teste de contagem de `<a>`/`<button>` foi encontrado além do já citado `test_page_exposes_no_destructive_action` — ele conta só `<button>` e `<form>`, não `<a>`, então não deve ser afetado a menos que algum link vire `<button>` no processo (não é a proposta).
- **Nenhum teste de comportamento (status HTTP, permissão, criação/edição de registro, redirecionamento) deveria ser afetado** — a mesma conclusão da auditoria anterior se repete aqui: a suíte testa comportamento, não markup, então o risco está concentrado nos poucos testes que asseram texto visível especificamente.

## 15. Ordem recomendada de implementação (para quando você aprovar)

1. Criar a infraestrutura (`apps/core/templatetags/icons.py`, vendorizar os ~15-18 ícones Heroicons necessários, adicionar `.icon-btn*`/`.action-group` a `base.html`) e testar isoladamente antes de tocar em qualquer tela existente.
2. Aplicar primeiro em `equipment/list.html` (tela de referência já usada na etapa anterior) — validar visualmente e ajustar a API da tag se necessário antes de replicar.
3. `equipment/detail_private.html` — a tela mais complexa, com a separação em 2 grupos proposta na seção 8.
4. Listagens simples (`client_list`, `location_list`, `user_list`, `category_list`, `model_list`) — mecânico, baixo risco, mesmo padrão em todas.
5. Fichas de detalhe restantes (`client_detail`, `location_detail`).
6. Telas de Manutenção/Higienização (10 templates) — já usam `.link`/`.btn-neutral` de forma consistente, troca mecânica.
7. Formulários (botões "Cancelar"/"Voltar", ícone complementar) — última prioridade, menor ganho de legibilidade por serem ações já claras.
8. Rodar a suíte completa, ajustar os testes de texto identificados na seção 14, `check`/`makemigrations --check`, relatório final.

## 16. Decisões que precisam da sua aprovação antes de eu implementar

1. **Conjunto de ícones**: Heroicons (recomendado) ou Lucide — ambos vendorizáveis sem npm, ambos com licença permissiva.
2. **Mecanismo de entrega**: template tag Django com SVG inline por uso (recomendado, mais simples) ou sprite `<symbol>`/`<use>` central em `base.html` (mais econômico em bytes, levemente mais indireto).
3. **Ícones aprovados vs. reconsiderar**: confirmar especificamente os 4 ícone-sozinho da tabela da seção 6 (Ver em listagem, QR, Etiqueta, Editar-de-tabela) — são os únicos casos onde o texto desapareceria completamente; todos os demais mantêm texto por padrão.
4. **Proposta de `detail_private.html`** (seção 8): aprovar a separação visual em 2 grupos (operacional vs. administrativo/sensível) sem menu dropdown — ou indicar se prefere manter tudo num único grupo, só com ícones adicionados.
5. **Paginação em mobile** (seção 11): manter texto completo "Anterior"/"Próxima" mesmo em mobile, ou reduzir a só seta com `aria-label` em telas muito estreitas.
6. **Ícone complementar em botões de ação primária** (ex.: "Abrir manutenção" com um ícone de chave-inglesa ao lado): aprovar caso a caso durante a implementação, ou já definir que NENHUM botão primário ganha ícone nesta rodada (mais conservador, mais rápido de implementar, ainda plenamente alinhado à sua regra 3).

---

Aguardando sua aprovação — geral ou item a item — antes de criar `apps/core/templatetags/icons.py` ou alterar qualquer template.
