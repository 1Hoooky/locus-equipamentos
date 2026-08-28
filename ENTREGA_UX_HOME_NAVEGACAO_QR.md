# Entrega — UX/UI: Landing pública do QR, navegação e Home operacional

Implementação das 6 etapas aprovadas em `AUDITORIA_UX_HOME_NAVEGACAO_QR.md`, na ordem obrigatória definida no briefing de aprovação (28/08/2026): infraestrutura compartilhada → landing pública → privacidade/login → menu mobile → navegação desktop → Home operacional → homologação.

---

## 1. Resumo executivo

As três frentes pedidas foram implementadas: a página pública do QR virou uma mini landing comercial da Locus (imagem grande do modelo, CTAs configuráveis, identidade de marca); o menu interno ganhou um drawer mobile acessível e uma navegação desktop por dropdowns (Opção B); e uma Home operacional nova (`apps.dashboard`) passou a existir com 4 cards de status e 3 listas operacionais, sem nenhum gráfico. Nenhum model, migration, service de domínio, `SubmissionGuard` ou regra de permissão existente foi alterado — só views/templates/settings/URLs e dois módulos novos puramente de leitura (`apps.catalog.images`, `apps.dashboard`). A suíte completa está em 553/553 testes passando, `manage.py check` limpo e `makemigrations --check --dry-run` sem alterações pendentes.

## 2. Arquivos criados

- `templates/_design_tokens.html` — tokens/componentes Tailwind extraídos de `base.html`, compartilhados com `base_public.html`.
- `templates/base_public.html` — base da experiência pública (header minimalista, drawer de menu, SEO/Open Graph básico, footer discreto).
- `templates/dashboard/home.html` — Home operacional.
- `apps/catalog/images.py` — mapeamento `EquipmentModel.code` → imagem estática + fallback.
- `apps/catalog/templatetags/__init__.py`, `apps/catalog/templatetags/model_images.py` — template tags `model_image_url`/`model_has_commercial_image`.
- `apps/core/context_processors.py` — `commercial_links` (URLs comerciais configuráveis).
- `apps/dashboard/services.py`, `apps/dashboard/urls.py` — consultas e rota da Home.
- `static/images/equipment/_placeholder.webp` — placeholder de desenvolvimento (não é arte final).
- Testes novos: `apps/accounts/tests/test_login_next_redirect.py`, `apps/catalog/tests/test_model_images.py`, `apps/equipment/tests/test_public_landing.py`, `apps/core/tests/test_mobile_menu_drawer.py`, `apps/core/tests/test_desktop_nav_dropdowns.py`, `apps/dashboard/tests/test_home_view.py`.

## 3. Arquivos alterados

- `templates/base.html` — inclui `_design_tokens.html`; header com drawer mobile + navegação desktop por dropdowns; logo aponta para a Home quando autenticado.
- `templates/equipment/detail_public.html` — reescrito como landing comercial (estende `base_public.html`).
- `templates/accounts/login.html` — campo hidden `next` explícito.
- `apps/equipment/views.py` — `EquipmentDetailView` separada em `_get_public_equipment`/`_render_private` (defesa em profundidade).
- `apps/core/templatetags/icons.py` — novos ícones Heroicons + `brand_icon` (Instagram vendorizado).
- `apps/dashboard/views.py` — `DashboardHomeView`.
- `config/settings/base.py` — `LOCUS_*_URL`, context processor registrado, `LOGIN_REDIRECT_URL = "dashboard:home"`.
- `config/urls.py` — rota raiz `""` → `apps.dashboard.urls`.
- `.env.example` — documentação das novas variáveis de link comercial.
- `apps/operations/tests/test_duplicate_locations_report.py` — contagens de `<form>`/`<button>` atualizadas (consequência esperada do novo chrome global; nenhuma asserção de privacidade/conteúdo foi enfraquecida).
- `apps/dashboard/tests.py` removido → substituído por pacote `apps/dashboard/tests/`.

## 4. Decisões técnicas tomadas

- Imagem por modelo: dicionário Python (`MODEL_IMAGE_MAP`) chaveado por `EquipmentModel.code`, sem migration — exatamente a estratégia aprovada.
- Links comerciais: `settings.LOCUS_*_URL` (default `""`) + context processor, nenhum hardcoded em template.
- Privacidade: a rota pública usa `.only()` num queryset **próprio** (`_get_public_equipment`), não mais o mesmo `select_related` da rota privada com defer parcial — cliente/localização/financeiro/notas nunca saem do banco para o visitante anônimo.
- `next` no login: comportamento que já existia (mecanismo padrão do Django) reforçado com um campo hidden explícito — nenhuma validação própria contra open redirect foi escrita.
- Menu mobile: drawer lateral vanilla JS, permissões 100% reaproveitadas de `base.html`/views.
- Navegação desktop: Opção B (dropdowns só para Cadastros/Administração, ações frequentes continuam diretas).
- Home: `apps.dashboard` (app já existia vazio, só recebeu view/urls/services/template).

## 5. Landing pública — resultado final

`GET /equipamentos/<patrimonio>/` sem login renderiza `equipment/detail_public.html` sobre `base_public.html`: header `LOCUS + ☰`, "Você encontrou um equipamento Locus", imagem grande (proporção 4:3 reservada, `object-fit: contain`, sem lazy loading, `fetchpriority="high"`), categoria/modelo/patrimônio/fabricante (só se preenchido), texto comercial fixo aprovado, e os 5 CTAs (orçamento/WhatsApp/Instagram/site/equipamentos) — cada um só aparece se a URL correspondente estiver configurada.

## 6. Menu mobile interno — resultado final

Drawer lateral (`#mobile-menu-drawer`) com backdrop, agrupado em Operação/Equipamentos/Manutenção/Cadastros/Administração, 44px de toque mínimo, Heroicons, `aria-expanded`/`aria-controls`/`aria-current="page"`, Escape e clique no backdrop fecham, foco vai para o botão fechar ao abrir e volta ao hambúrguer ao fechar. Fecha sozinho se a janela crescer para desktop.

## 7. Navegação desktop — resultado final

Barra com Home/Equipamentos/Manutenções/Higienizações/Clientes/Unidades sempre visíveis, mais os dropdowns "Cadastros" (Categorias/Modelos) e "Administração" (Importar planilha/Usuários/Diagnóstico de unidades) — cada um só aparece com a mesma permissão que já protegia esses links antes. Dropdowns com teclado, Escape, clique fora, `aria-haspopup`/`aria-expanded`.

## 8. Home operacional — resultado final

`GET /` (autenticado) → 4 cards (Disponíveis/Em operação/Em manutenção/Manutenções abertas, cada um linkando para a listagem já filtrada) + 3 listas (movimentações recentes, manutenções abertas, equipamentos que exigem atenção). Sem gráfico, sem higienizações recentes, sem totais de clientes/unidades — exatamente o escopo aprovado.

## 9. Estratégia de imagens

`EquipmentModel.code` → arquivo em `static/images/equipment/`, resolvido por `apps.catalog.templatetags.model_images.model_image_url`, que **confirma a existência real do arquivo** (`django.contrib.staticfiles.finders.find`, cacheado em processo) antes de apontar para ele.

## 10. Estratégia de fallback

Qualquer modelo sem entrada no mapa, ou com entrada apontando para um arquivo ainda não enviado, cai em `_placeholder.webp` (gerado nesta etapa, neutro, claramente um placeholder de desenvolvimento — não arte final). A página nunca depende da imagem existir para renderizar nome/patrimônio/CTAs.

## 11. Segurança / privacidade

`EquipmentDetailView._get_public_equipment` usa `Equipment.objects.select_related("model","category").only(...)` com uma lista fixa de 5 campos — cliente, localização, financeiro, notas, lote e histórico técnico nunca são consultados no banco para o visitante anônimo (não é só o template escondendo). Os 3 testes de vazamento pré-existentes continuam passando sem alteração, mais 1 teste novo de contagem de queries (`assertNumQueries(1)`) trava esse comportamento.

## 12. Fluxo de login

Confirmado meses atrás (auditoria) que QR → login → mesma ficha privada já funcionava via mecanismo padrão do Django; nesta etapa foi adicionado um campo hidden `next` explícito (defesa em profundidade) e 7 testes novos, incluindo 2 de proteção contra open redirect (host externo e `//host` relativo) — ambos usando só a validação nativa do Django.

## 13. Query budget final

Landing pública: 1 query (equipamento + JOIN model/category). Home: 5 queries fixas (1 agregação de status + 1 contagem de manutenções abertas + 3 slices `[:5]` com `select_related`) — comprovado por teste que compara a contagem de queries com 3 registros vs. 15 registros semeados (mesmo número nos dois casos).

## 14. Testes adicionados

52 métodos de teste novos, distribuídos em 6 arquivos novos (ver seção 2), cobrindo: login/`next`/open-redirect (7), mapeamento de imagem (7), landing pública — conteúdo, imagem, CTAs, ausência de dado sensível, query budget (15), menu mobile — acessibilidade + matriz de permissão dos 4 perfis + superusuário (9), dropdowns desktop — mesma matriz (6), e Home — conteúdo, cards, listas, ausência de gráfico/métricas fora de escopo, query budget (8).

## 15. Resultado da suíte completa

```
553 testes — OK (0 falhas, 0 erros)
```

## 16. `manage.py check`

```
System check identified no issues (0 silenced).
```

## 17. `makemigrations --check --dry-run`

```
No changes detected
```

## 18. Riscos / pendências conhecidas

- As imagens comerciais reais (`9pro.webp`, `aqcp.webp`, etc.) ainda não existem — a landing está funcionalmente pronta, mas mostrará o placeholder até a Locus enviar os arquivos finais (só copiar os WEBPs para `static/images/equipment/`, sem mudança de código).
- Nenhuma das 5 URLs comerciais (`LOCUS_*_URL`) está configurada neste ambiente — a landing renderiza sem nenhum CTA até o `.env` de produção ser preenchido (comportamento seguro, mas precisa ser lembrado no deploy).
- Favicon real ainda não existe (decisão aprovada: não foi improvisado).
- `EquipmentModel.specs` continua fora de uso, como aprovado.
- Validação visual em navegador real (Chrome/Playwright) não foi possível nesta sandbox — ver checklist manual abaixo.

## 19. Checklist manual de homologação (Render)

**Landing QR:**
- [ ] Testar em 320px, 360px, 390px, 430px, tablet e desktop
- [ ] Imagem grande carrega sem layout shift perceptível
- [ ] Placeholder aparece corretamente para modelo sem foto real
- [ ] Cada CTA configurado abre a URL certa; nenhum aparece se vazio
- [ ] Menu (☰) abre/fecha, "Entrar" leva ao login
- [ ] Login a partir do QR retorna à ficha PRIVADA do mesmo equipamento

**Menu interno (mobile):**
- [ ] Abertura/fechamento do drawer, backdrop, Escape
- [ ] Scroll dentro do drawer com muitos itens (perfil Admin)
- [ ] Toque de 44px em dispositivo real
- [ ] Itens corretos por perfil (Admin/Administrativo/Operacional/Consulta)

**Navegação desktop:**
- [ ] Dropdowns abrem/fecham por clique, teclado e Escape
- [ ] Permissões corretas por perfil
- [ ] Estado ativo/hover visualmente claro

**Home:**
- [ ] Números dos 4 cards batem com a base real
- [ ] Links dos cards levam à listagem já filtrada
- [ ] As 3 listas mostram dados reais e atualizados
- [ ] Comportamento em mobile (cards empilham, listas legíveis)

---

*Nenhuma alteração de domínio (models/migrations/services/SubmissionGuard/permissões) foi feita nesta etapa. `qrcodes/label.html` não foi tocado.*
