# Auditoria — Landing pública do QR, navegação e nova Home

Auditoria pura, nada foi implementado. Todos os arquivos citados abaixo foram lidos diretamente do repositório nesta sessão (código, testes, settings, docs) — nenhuma suposição sobre o que "provavelmente existe". Onde um comportamento dependia de mecanismo interno do Django (o `next` do login), ele foi verificado empiricamente com um teste descartável, rodado e apagado antes de escrever este relatório — não é uma leitura de documentação, é o comportamento real deste projeto.

Ordem: como as três frentes se apoiam nos mesmos fatos (design system, permissões, autenticação), o relatório está organizado em 5 partes em vez de 39 seções soltas — mas cada item numerado que você pediu está identificável abaixo (a numeração do seu pedido aparece entre colchetes).

---

## PARTE A — Landing pública do QR

### [1] Diagnóstico da página pública atual

`templates/equipment/detail_public.html` (16 linhas, reproduzido por inteiro porque é curto):

```html
{% extends "base.html" %}
...
<div class="max-w-sm mx-auto card-pad text-center">
  <p class="page-subtitle mb-1">Equipamento Locus Locações</p>
  <h1 class="page-title mb-4">{{ equipment.patrimonio }}</h1>
  <p class="text-gray-700">{{ equipment.category.name }} · {{ equipment.model.name }}</p>
  <a href="{% url 'accounts:login' %}?next={{ request.path }}" class="btn-primary w-full mt-6">
    Entrar para ver mais detalhes
  </a>
</div>
```

Hoje ela é exatamente o que você descreveu não querer: uma ficha pública minimalista, sem imagem, sem identidade comercial forte, sem CTA de negócio — só identificação + "entrar". Ela estende `base.html` inteiro (herda o header ADMINISTRATIVO — logo "LOCUS Equipamentos" com link para login, sem menu porque `user.is_authenticated` é falso, mas ainda carrega toda a `@layer components` do sistema interno).

A view é `EquipmentDetailView` (`apps/equipment/views.py:421-490`), **uma view só para as duas rotas** — pública e privada —, roteada pela MESMA URL nomeada `equipment:detail` (`/equipamentos/<patrimonio>/`). Ela decide o template por `request.user.is_authenticated`:

```python
if not request.user.is_authenticated:
    return render(request, "equipment/detail_public.html", {"equipment": equipment})
# ... (autenticado: monta history_events, maintenance_summary etc. e renderiza detail_private.html)
```

Isso é uma base arquitetural ótima para o fluxo do item 10 (ver [19]-[22] abaixo) — o mesmo link do QR já serve as duas audiências sem nenhuma redireção especial.

**Achado técnico que importa para a Parte A inteira:** a query que busca `equipment` roda **sempre igual**, autenticado ou não —
```python
queryset = Equipment.objects.select_related("model", "category", "current_client", "current_location")
```
— só os três campos financeiros (`supplier`/`acquisition_date`/`acquisition_value`) são `.defer()`idos condicionalmente. Isso quer dizer que, hoje, o objeto `equipment` passado para `detail_public.html` **já chega com `current_client`/`current_location` carregados na memória**, mesmo que o template atual não os use. Não é um vazamento agora (Django só materializa o que o template acessa), mas é uma armadilha esperando alguém: um editor futuro de `detail_public.html` que escrever `{{ equipment.current_client }}` sem querer não erra a permissão — o dado já está ali, carregado. Ver risco de segurança [35] e a correção proposta em [12].

### [2] Dados anônimos expostos hoje

Literalmente só isto chega ao HTML renderizado para quem não está logado:

| Dado | Fonte | Sensível? |
|---|---|---|
| `equipment.patrimonio` | Equipment | Não — é o texto impresso no QR/etiqueta que a pessoa acabou de escanear |
| `equipment.category.name` | Category | Não — categoria genérica ("Aquecedor", "Climatizador") |
| `equipment.model.name` | EquipmentModel | Não — nome comercial do modelo |
| link para login com `?next=` | — | Não — não revela nada sobre o equipamento |

Nada mais é acessado pelo template hoje. `status`, `condition`, `current_client`, `current_location`, `notes`, dados financeiros: nenhum aparece — confirmado tanto pela leitura do template quanto pelos 3 arquivos de teste dedicados a provar isso (ver [32]).

### [3] Riscos de privacidade

1. **O real, hoje:** nenhum. A tela atual é deliberadamente mínima e os testes cobrem os vazamentos mais óbvios (cliente, unidade, movimentação, fornecedor, valor, observação interna).
2. **O latente (arquitetural), hoje:** `current_client`/`current_location` chegam carregados no objeto de contexto mesmo sem serem usados (ver achado em [1]) — nenhum teste prova que a QUERY não busca esses campos no caminho anônimo (só prova que o HTML renderizado não os contém). É a mesma categoria de proteção que a auditoria da Fase 1 já aplicou para os campos financeiros via `.defer()` — só que aqui ainda falta.
3. **O que a NOVA página precisa continuar garantindo:** tudo que a lista de "[12] conteúdo que não deve ser público" cobre, MAIS não reintroduzir nada disso ao adicionar as novas seções comerciais (imagem, specs, CTAs) — o risco concreto é alguém, ao "enriquecer" a página, puxar `equipment.current_location`/`equipment.notes` pensando que é só mais um campo de exibição.
4. **Novo risco introduzido pela mudança:** nenhum, se a estratégia de imagem for por MODELO (estático, versionado) como você já decidiu — não há upload, não há campo de usuário, não há superfície nova de dado privado.

### [4] Wireframe textual completo da nova landing QR

```
┌────────────────────────────────────────┐
│  LOCUS                             ☰    │  ← header público, fixo no topo
├────────────────────────────────────────┤
│                                          │
│   Você encontrou um equipamento Locus   │  ← contexto, 1 linha, tom acolhedor
│                                          │
│   ┌──────────────────────────────────┐  │
│   │                                  │  │
│   │                                  │  │
│   │      [IMAGEM DO EQUIPAMENTO]     │  │  ← hero, 220–400px de altura
│   │        (fundo claro/neutro,      │  │     conforme viewport, object-fit:
│   │         object-fit: contain)     │  │     contain, área reservada fixa
│   │                                  │  │
│   └──────────────────────────────────┘  │
│                                          │
│           Aquecedor Torre               │  ← model.name, tipografia forte
│           LOC-AQCT-0001                 │  ← patrimônio, pequeno, mono/cinza
│           Comfee                        │  ← model.manufacturer, SE preenchido
│                                          │
│   Soluções para ambientes mais          │  ← 1-2 linhas comerciais fixas da
│   confortáveis, com a qualidade Locus.  │     marca (não é specs do modelo —
│                                          │     ver [11])
│  ┌────────────────────────────────────┐ │
│  │      FAÇA SEU ORÇAMENTO       →    │ │  ← CTA primário, .btn-primary XL,
│  └────────────────────────────────────┘ │     full-width, ícone + texto
│                                          │
│  ┌────────────────────────────────────┐ │
│  │  💬  Fale com a Locus          →   │ │  ← lista de ações estilo link-page,
│  └────────────────────────────────────┘ │     mesmo padrão visual entre si,
│  ┌────────────────────────────────────┐ │     hierarquia só de ORDEM (não de
│  │  📷  Instagram                 →   │ │     tamanho/cor — só o 1º é dourado
│  └────────────────────────────────────┘ │     cheio, os demais são outline/
│  ┌────────────────────────────────────┐ │     neutros)
│  │  🌐  Conheça nosso site        →   │ │
│  └────────────────────────────────────┘ │
│  ┌────────────────────────────────────┐ │
│  │  🧊  Nossos equipamentos       →   │ │
│  └────────────────────────────────────┘ │
│                                          │
├────────────────────────────────────────┤
│         LOCUS · Locações                │  ← footer comercial simples
│    Escaneou por engano? Sem problema.   │
└────────────────────────────────────────┘
```

Diferenças deliberadas em relação à referência que você mandou: (a) o "você encontrou um equipamento Locus" fica ACIMA da imagem, não abaixo — dá contexto antes de mostrar o produto, reduzindo a chance de estranhamento de quem escaneou sem saber o que esperar; (b) os CTAs usam ícone à esquerda + seta à direita (padrão link-page real, tipo Linktree), não texto centralizado puro — reforça "isto é clicável e leva a algum lugar"; (c) o fabricante (`manufacturer`) só aparece SE o modelo tiver o campo preenchido (ver [11]) — não é um espaço reservado vazio.

### [5] Hierarquia visual proposta

1. Marca (topo, sempre visível, mínima)
2. Contexto de uma linha ("Você encontrou...")
3. **Imagem** — maior elemento visual da página, é o motivo comercial de ela existir
4. Nome do modelo — maior texto depois do CTA primário
5. Patrimônio — pequeno, secundário, só identificação
6. Descrição comercial curta (institucional, não do modelo)
7. **CTA primário** — único elemento com preenchimento dourado sólido (`.btn-primary`), tamanho maior que os outros botões
8. CTAs secundários — mesma largura entre si, estilo consistente (outline ou neutro claro), diferenciados só por ícone+texto, nunca por tamanho/cor individual (isso evita "hierarquia de CTA dentro dos CTAs secundários", que dilui o CTA primário)
9. Rodapé — menor elemento, presença de marca sem competir por atenção

### [6] Posição/tamanho da imagem do equipamento

- Container de altura fixa por breakpoint (reserva de espaço = zero CLS): **220px** até ~380px de largura de viewport, **280px** de ~380–600px, **360–400px** acima disso (tablet/desktop, já que a página pode ser aberta num navegador desktop também, ainda que mobile seja a prioridade).
- `object-fit: contain` (nunca `cover`) — é imagem de produto/catálogo, cortar a imagem destruiria a composição que a foto comercial já tem pronta.
- Fundo do container: um tom neutro claro (`bg-gray-50` ou branco), nunca preto/dourado — a imagem do produto já traz sua própria composição, o container só precisa não competir com ela.
- Sem borda/sombra pesada — o "grande = catálogo" vem do tamanho e do respiro ao redor, não de moldura.

### [7] Estratégia de PNG/WEBP

**WEBP como formato único**, sem fallback duplo em PNG via `<picture>`: suporte a WEBP em navegadores é hoje praticamente universal (todos os navegadores mobile relevantes desde ~2020), e manter dois arquivos por modelo é exatamente a complexidade desnecessária que a diretriz "sem duplicar" pede para evitar. PNG só entra como exceção pontual se uma imagem específica tiver transparência que alguma ferramenta de conversão degradar mal em WEBP — decisão caso a caso na hora de gerar o arquivo, não uma regra de par obrigatório no template.

Recomendação de captura/exportação: fonte em ~1000–1200px de largura, comprimida para WEBP qualidade ~75–80 (ponto de corte comum onde a perda visual é imperceptível em produto fotografado com fundo limpo). Meta de peso: **80–150KB por imagem** — a imagem é o LCP da página (ver [36]), então o peso dela pesa diretamente na métrica que mais importa aqui.

### [8] Estrutura de pasta static recomendada

O projeto está com `static/` **vazio** (só um `.gitkeep`) — não existe estrutura prévia para adaptar, é greenfield. Configuração já pronta em `config/settings/base.py`:
```python
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"      # alvo do collectstatic (deploy)
STATICFILES_DIRS = [BASE_DIR / "static"]    # fonte versionada no repo
```
Ou seja: qualquer arquivo colocado em `static/` já é servido corretamente por `{% load static %}{% static "..." %}` tanto em dev quanto (via `collectstatic` no deploy) no Render — nenhuma mudança de configuração necessária.

Estrutura proposta (equivalente à sua ideia, só reorganizada por convenção Django de "namespacing por app" — evita colisão de nome se `qrcodes`/outro app um dia também tiver estáticos):
```
static/
  images/
    equipment/
      9pro.webp
      9pro2.webp
      6pro.webp
      aqcp.webp
      aqct.webp
      aqch.webp
      _placeholder.webp        ← fallback genérico (ver [10])
    brand/
      logo-mark.svg            ← se um dia precisar do logo como arquivo
                                   (hoje o header é só texto "LOCUS")
  favicon.ico                  ← ver [18], hoje não existe nenhum
```
Nome de arquivo = `EquipmentModel.code` em minúsculas (`9PRO` → `9pro.webp`) — ver justificativa completa em [9].

### [9] Estratégia de mapping EquipmentModel → imagem

Auditado: `EquipmentModel` **não tem** e nunca teve campo de imagem (`models.py` lido por inteiro, só `category`/`name`/`code`/`manufacturer`/`specs`/`last_sequence`). Concordo com sua preferência — **não criar migration só para isto**.

`EquipmentModel.code` é a chave certa para o mapeamento, por três razões que já existem no próprio modelo, não inventadas para este propósito:
1. Já é **validado por regex** (`^[A-Z0-9]{2,20}$`, `CODE_VALIDATOR`) — maiúsculas/números apenas, sem espaço, sem acento. É literalmente já um "nome de arquivo seguro" por construção.
2. Já é **`unique=True`** — um `code` nunca aponta para dois modelos.
3. Já é **travado (imutável)** assim que o modelo tem equipamento vinculado (`EquipmentModel.clean()`) — o mapeamento nunca fica "orfão" por alguém renomear o código de um modelo em produção.

Mecanismo proposto — **mapping centralizado + função, zero `{% if %}` no template**:

```python
# apps/catalog/images.py (novo arquivo, só constantes + uma função)

MODEL_IMAGE_MAP = {
    "9PRO": "images/equipment/9pro.webp",
    "9PRO2": "images/equipment/9pro2.webp",
    "6PRO": "images/equipment/6pro.webp",
    "AQCP": "images/equipment/aqcp.webp",
    "AQCT": "images/equipment/aqct.webp",
    "AQCH": "images/equipment/aqch.webp",
}
PLACEHOLDER_IMAGE = "images/equipment/_placeholder.webp"

def get_model_image_path(model: "EquipmentModel") -> str:
    return MODEL_IMAGE_MAP.get(model.code, PLACEHOLDER_IMAGE)
```

E um template tag simples (mesmo padrão já aprovado para `{% icon %}` — `apps/core/templatetags/icons.py`) que devolve a URL já resolvida via `static()`:
```python
# apps/catalog/templatetags/model_images.py
@register.simple_tag
def model_image_url(model):
    return static(get_model_image_path(model))
```
Uso no template: `<img src="{% model_image_url equipment.model %}" ...>` — uma linha, nenhum `{% if model.code == "..." %}` em lugar nenhum. Adicionar um modelo novo = 1 linha no dicionário + 1 arquivo em `static/images/equipment/`, nenhum deploy de banco, nenhuma migration.

Alternativas descartadas (auditadas, com o motivo):
- **Campo de banco (`EquipmentModel.image_path` ou similar):** funcionaria, mas é exatamente a migration que você pediu para evitar se não houver necessidade real — e não há: o mapeamento muda tão raramente quanto o catálogo de modelos em si (evento administrativo raro, não operacional).
- **Convenção implícita de nome de arquivo = `code.lower() + ".webp"`, sem dicionário:** mais "mágico", quebra silenciosamente (imagem só "some", vira placeholder) se alguém salvar `9Pro.webp` ao invés de `9pro.webp` — o dicionário explícito é uma linha a mais de código, mas é auditável e falha de forma clara (chave ausente = placeholder, nunca um 404 de imagem).
- **`specs` (JSONField já existente) guardando o path da imagem:** tecnicamente evitaria o novo arquivo Python, mas espalha uma decisão de infraestrutura (caminho de arquivo estático) dentro de um campo pensado para dados comerciais livres (BTU, voltagem) — mistura duas responsabilidades sem necessidade.

### [10] Estratégia de fallback

A função `get_model_image_path()` acima **nunca retorna vazio/None** — todo modelo sem entrada no dicionário cai automaticamente no placeholder. Isso significa que o template NUNCA precisa de um `{% if %}` para "existe imagem?" — sempre há uma imagem válida para renderizar, então a tag `<img>` nunca aponta para um arquivo inexistente (nunca ícone quebrado do navegador).

O placeholder em si: uma composição simples com a identidade Locus (fundo claro + marca/silhueta genérica de equipamento em dourado/chumbo, sem tentar imitar produto real) — um único arquivo `_placeholder.webp`, reaproveitado por qualquer modelo sem foto cadastrada.

`alt` text: **nunca genérico demais nem vazio** — `alt="{{ equipment.model.name }}"` sempre (mesmo no caso do placeholder, o nome do modelo real continua correto e útil para leitor de tela/SEO de imagem; o que muda é só a imagem, não a informação textual que ela representa).

Dimensões: `width`/`height` (ou um wrapper com `aspect-ratio` fixo via CSS) sempre declarados no HTML — evita layout shift tanto para a imagem real quanto para o placeholder, que devem ter a MESMA proporção/dimensão de arquivo entre si por convenção (ex.: todas exportadas em 4:3 ou 1:1, a decidir na hora de gerar os assets).

**Lazy loading — análise pedida:** não, a imagem principal não deve ter `loading="lazy"`. Ela está no topo da página, sempre visível sem rolar (above the fold) — `lazy` é para imagens fora da viewport inicial; aplicado aqui, ele ativamente ATRASA o carregamento do próprio LCP, piorando a métrica que mais importa nesta página. Recomendado: `loading="eager"` (ou simplesmente omitir o atributo, que já é o padrão) `fetchpriority="high"` (atributo HTML padrão, sem JS, sinaliza ao navegador para priorizar esse download acima de outros recursos da página). Um `<link rel="preload" as="image" href="...">` no `<head>` é um ganho adicional válido (também HTML puro) — só precisa ser montado dinamicamente com a mesma função `model_image_url`, o que é natural já que o `<head>` do `base_public.html` também tem acesso a `equipment.model`.

### [11] Campos públicos do catálogo que podemos mostrar hoje

Auditados `Equipment`, `EquipmentModel`, `Category` por inteiro. Só isto existe e é seguro:

| Campo | Model | Populado hoje? | Mostrar na landing? |
|---|---|---|---|
| `patrimonio` | Equipment | Sempre (gerado automaticamente) | Sim — já é público (está no QR/etiqueta) |
| `model.name` | EquipmentModel | Sempre (obrigatório no cadastro) | Sim — nome comercial do produto |
| `category.name` | Category | Sempre | Opcional — já implícito no nome do modelo na maioria dos casos; pode virar um "olho" (tipo: Aquecedor) discreto perto do nome |
| `model.manufacturer` | EquipmentModel | **Às vezes** (`blank=True`, campo real e editável em `EquipmentModelForm`, mas não obrigatório) | Sim, **condicionalmente** — só renderizar o bloco se `model.manufacturer` não for vazio, nunca um rótulo "Fabricante: —" |
| `model.code` | EquipmentModel | Sempre | Não precisa — já está embutido no patrimônio (`LOC-{CODE}-{SEQUENCE}`), mostrar separado é redundante |
| `model.specs` (JSONField) | EquipmentModel | **Nunca, na prática** — não existe nenhum campo de formulário (`EquipmentModelForm.Meta.fields` não inclui `specs`), nenhuma tela de admin o edita além do Django admin cru, e uma busca no projeto inteiro não encontrou nenhum lugar que leia essa chave hoje | **Não** nesta rodada — ver abaixo |

**Sobre `specs`:** é um `JSONField(blank=True, default=dict, help_text="Campos livres por categoria (BTUs, voltagem, etc.)")` — o schema já está preparado exatamente para o tipo de informação comercial que você descreveu (capacidade, aplicação, alimentação, área recomendada), mas **está vazio para todo modelo hoje**, porque nenhuma tela permite preenchê-lo. Marco isso explicitamente como **possibilidade futura**: o hook de dados já existe (não precisaria de nova migration para viabilizar specs comerciais), só falta (a) decidir o schema de chaves (`{"capacidade_btu": ..., "voltagem": ...}` ou o que fizer sentido por categoria) e (b) adicionar `specs` ao `EquipmentModelForm` com os campos apropriados. Não fiz isso agora — é uma decisão de produto (quais chaves, quais categorias) que não me cabe inventar.

**Descrição comercial da linha "Soluções para ambientes mais confortáveis..." no wireframe:** não vem de nenhum campo do modelo — é texto institucional fixo da Locus (mesmo texto em toda página, independente do equipamento), a decidir com você. Não deve ser confundido com "specs do modelo".

### [12] Conteúdo que NÃO deve ser público (checklist de proteção a manter)

Tudo isto **já está protegido hoje** (nenhum aparece no HTML da rota anônima, confirmado por 3 suítes de teste dedicadas — [32]) e precisa **continuar assim** na página redesenhada:

`current_client`, `current_location` (nem a `Location`, nem seu `client`, nem endereço), `Movement` (origem/destino/tipo/motivo/quem fez), `Maintenance`/`Cleaning` (diagnóstico, serviço executado, responsável, datas), `status`/`condition` operacionais (ver nota abaixo), `notes` internas, `supplier`/`acquisition_date`/`acquisition_value`, qualquer `User`/responsável, `StatusHistory`/`ConditionHistory`, IDs internos crus (`equipment.pk`, `model.pk` — hoje só o `patrimonio` humano-legível é exposto na URL, e deve continuar assim).

**Nota sobre `status`/`condition`:** a página atual não mostra nenhum dos dois, e recomendo manter essa ausência na landing comercial — não são dados sensíveis no sentido de "segredo", mas são sinais OPERACIONAIS (ex.: "MANUTENÇÃO", "INUTILIZÁVEL") que não cabem numa página com objetivo comercial e que o teste `test_public_page_never_mentions_client_location_or_movement` já trava implicitamente (`assertNotIn("EM_OPERACAO", content)`) — qualquer decisão de reintroduzir isso precisaria vir de você explicitamente, e mudaria esse teste.

**Correção de defesa em profundidade recomendada (ver [1]/[35]):** o `select_related("current_client", "current_location")` da query de `EquipmentDetailView` deveria deixar de rodar incondicionalmente e só acontecer no ramo autenticado — o mesmo padrão de "a proteção não pode depender só do template esconder o dado" que a Fase 1 já aplicou ao valor de aquisição via `.defer()`, estendido aqui para as relações. Fica registrado como parte do trabalho de implementação futura, não fiz a mudança agora (é código, fora do escopo desta auditoria).

### [13] CTAs comerciais

Hierarquia (igual à sua proposta, mantida):
1. **FAÇA SEU ORÇAMENTO** — CTA primário, `.btn-primary` em tamanho maior (o único botão "cheio" dourado da página)
2. Fale com a Locus
3. Instagram
4. Conheça nosso site
5. Conheça nossos equipamentos

Sobre o item 5 — **atenção, ponto que precisa da sua decisão**: hoje não existe nenhuma página pública de catálogo/vitrine de equipamentos (a listagem `equipment:list` exige login). Esse CTA só tem para onde apontar se: (a) apontar para uma página do site institucional da Locus (fora deste sistema), ou (b) for descartado nesta rodada até existir uma vitrine pública própria. Não inventei URL nenhuma — ver [14].

### [14] Origem/configuração das URLs comerciais

Auditado: **nenhuma URL comercial existe hoje no projeto** — nenhuma menção a Instagram, WhatsApp, telefone, ou formulário de orçamento em nenhum `settings/*.py`, template ou variável de ambiente (`.env`). O único precedente de "URL externa configurável" é `SITE_BASE_URL` (`config/settings/base.py:27`, via `python-decouple`: `SITE_BASE_URL = config("SITE_BASE_URL", default="http://localhost:8000")`) — usado hoje só para montar a URL absoluta que vai dentro do QR Code.

Proposta (segue o MESMO padrão já validado no projeto, nenhum mecanismo novo):

```python
# config/settings/base.py — mesma família de SITE_BASE_URL
LOCUS_INSTAGRAM_URL = config("LOCUS_INSTAGRAM_URL", default="")
LOCUS_SITE_URL = config("LOCUS_SITE_URL", default="")
LOCUS_WHATSAPP_URL = config("LOCUS_WHATSAPP_URL", default="")   # ex.: https://wa.me/55...
LOCUS_ORCAMENTO_URL = config("LOCUS_ORCAMENTO_URL", default="")  # pode ser o mesmo WhatsApp com texto pré-preenchido, um formulário do site, ou um mailto:
```

E um **context processor** novo (mecanismo padrão do Django para "isto precisa estar disponível em todo template sem passar manualmente por toda view"), não uma variável solta:

```python
# apps/core/context_processors.py (novo arquivo)
def commercial_links(request):
    return {
        "commercial_links": {
            "instagram": settings.LOCUS_INSTAGRAM_URL,
            "site": settings.LOCUS_SITE_URL,
            "whatsapp": settings.LOCUS_WHATSAPP_URL,
            "orcamento": settings.LOCUS_ORCAMENTO_URL,
        }
    }
```
registrado em `TEMPLATES[0]["OPTIONS"]["context_processors"]`. Templates então usam `{{ commercial_links.instagram }}` — nenhuma URL hardcoded repetida, um único lugar (`.env`/settings) para atualizar quando o Instagram mudar de @ ou o WhatsApp trocar de número, sem tocar em nenhum template.

Cada link vazio (`""`, valor padrão) deve fazer o BOTÃO correspondente não renderizar (`{% if commercial_links.instagram %}`) — a página nunca mostra um CTA morto/quebrado por falta de configuração.

**Decisão que precisa de você:** os valores reais (Instagram, site, WhatsApp, orçamento) — não vou inventá-los. Ver [39].

### [15] Estratégia para Heroicons/logos de marca

Reaproveitar a infraestrutura já aprovada e vendorizada (`apps/core/templatetags/icons.py`, `{% icon "nome" %}`) para tudo que é conceito genérico:

| Link/ação | Ícone Heroicons | Já vendorizado? |
|---|---|---|
| Site | `globe-alt` | Não — precisa vendorizar (mesmo processo já usado nos 10 atuais) |
| Orçamento | `document-text` ou `clipboard-document-check` | Não |
| Fale com a Locus | `chat-bubble-left-right` (ou `phone` se o contato for ligação) | Não |
| Nossos equipamentos | `squares-2x2` ou `cube` | Não |
| Fechar/abrir menu público | `bars-3` / `x-mark` | `x-mark` já existe; `bars-3` ainda é um SVG cru dentro de `base.html` (não centralizado em `icons.py`) — bom momento para migrá-lo também |

**Instagram é o caso especial** que você já identificou: Heroicons é um conjunto de ícones de conceito, deliberadamente sem logos de marca. Três caminhos, com recomendação:

1. **Vendorizar o glifo oficial do Instagram** como um SVG isolado (mesmo mecanismo do `icons.py`, só mais uma entrada no dicionário) — o glifo mono-cor do Instagram é de domínio consolidado como ícone de identificação de rede social (o mesmo raciocínio usado por bibliotecas MIT-licenciadas dedicadas só a logos de marca, ex. "Simple Icons") e é um único `<path>`, sem custo de peso/dependência. **Esta é a recomendação** — reconhecimento de marca importa de verdade num CTA de conversão ("as pessoas reconhecem o ícone do Instagram mais rápido que a palavra").
2. Ícone genérico (`camera`/`photo` do Heroicons) + texto "Instagram" — zero-risco, mas mais fraco visualmente/reconhecimento.
3. Só texto, sem ícone nenhum — mais fraco ainda, quebraria a consistência visual da lista (todos os outros itens têm ícone).

Não instala nenhuma biblioteca (Font Awesome ou similar) em nenhum dos três caminhos — a diferença é só se vendorizamos **mais um** SVG isolado (opção 1) ou reaproveitamos o que já existe (opção 2/3). Ver decisão pendente em [39].

---

## PARTE B — Base pública, header, menu, fluxo de login

### [16] Proposta de `base_public.html`

Concordo fortemente com criar um arquivo separado — a base atual (`templates/base.html`) carrega cabeçalho administrativo, toggle de menu interno (`nav-toggle`/`main-nav`) e todo o contexto de "sistema logado" que não faz sentido (e passaria a informação errada) numa página comercial pública.

**Como compartilhar sem duplicar** (sua preocupação #11): extrair o bloco que HOJE está duplicável — o `<script>tailwind.config = {...}</script>` + o `<style type="text/tailwindcss">@layer components{...}</style>` inteiro — para um **partial incluído nos dois**:

```
templates/
  _design_tokens.html      ← <script>tailwind.config...</script> + <style>@layer components...</style>
                              (exatamente o conteúdo hoje entre as linhas 9–204 de base.html)
  base.html                 ← {% include "_design_tokens.html" %} + header/nav ADMINISTRATIVO
  base_public.html          ← {% include "_design_tokens.html" %} + header/nav PÚBLICO (novo)
```
Isso significa: um novo componente `.icon-btn-neutral`, por exemplo, continua definido em UM lugar só e fica disponível nas duas bases automaticamente — exatamente o "compartilhar tokens/componentes de forma limpa" que você pediu, sem duplicar CSS.

`base_public.html` adiciona, além disso, o que `base.html` não tem motivo para ter: metadata (ver [18]) e footer comercial — e **não inclui**: `<nav id="main-nav">` administrativa, o toggle `nav-toggle`/JS de menu interno, nenhum link para `equipment:list`/`clients:list`/etc.

### [17] Header público

```
[LOCUS]                              [☰]
```
Mobile-first, mínimo, igual ao que você propôs. Reaproveita a mesma marca-texto "LOCUS" já usada em `base.html` (`font-bold text-lg tracking-tight text-brand-gold`), sem o "Equipamentos" adicional (que é nome do SISTEMA interno, não da marca comercial) e sem link algum embutido na marca em si (na base atual, o logo é um link para `equipment:list`/login — na pública, não faz sentido linkar para lugar nenhum, ou no máximo para a própria home pública se um dia existir uma).

Botão `☰` abre o menu público (drawer/painel — ver [18]), reaproveitando o MESMO padrão de toggle vanilla JS já usado hoje (`nav-toggle` → `classList.toggle("hidden")`), só que apontando para o painel público em vez do `main-nav` administrativo.

### [18] Menu público

Itens, na ordem sugerida:
- Faça seu orçamento
- Fale com a Locus
- Instagram
- Conheça nosso site
- (Conheça nossos equipamentos — se [13] resolver para onde aponta)
- — divisor —
- **Entrar** (estilo secundário — `.link` ou `.btn-neutral`, nunca `.btn-primary`; visualmente menor/mais discreto que os itens comerciais acima, exatamente como você pediu: "o cliente comum não pode sentir que entrou num sistema administrativo")

Sobre SEO/social básico (seu item 18 original) — no mesmo arquivo `base_public.html`, blocos que o Django já suporta nativamente via `{% block %}`, sem nenhuma dependência nova:
```html
<title>{% block title %}{{ equipment.model.name }} — Locus Locações{% endblock %}</title>
<meta name="description" content="{% block description %}...{% endblock %}">
<meta property="og:title" content="...">
<meta property="og:description" content="...">
<meta property="og:image" content="{{ request.scheme }}://{{ request.get_host }}{% model_image_url equipment.model %}">
<link rel="icon" href="{% static 'favicon.ico' %}">
```
**Favicon: auditado, não existe nenhum no projeto hoje** (`find` por `favicon*` não encontrou nada) — mesmo `base.html` atual não declara um `<link rel="icon">`. Criar um é um item pequeno e independente, útil para as duas bases (interna e pública), mas exige um arquivo de imagem real (não vou gerar um agora, é uma decisão de marca). Sem analytics/tracking, como pedido.

### [19] Fluxo "Entrar" (funcionário não autenticado)

O botão "Entrar" do menu público aponta para exatamente o mesmo destino que já existe hoje na tela pública atual: `{% url 'accounts:login' %}?next={{ request.path }}`. Nada novo a inventar aqui — é o link que já está em produção.

### [20] Comportamento depois do login — **verificado empiricamente, já funciona hoje**

Escrevi e rodei (depois apaguei) um teste isolado simulando exatamente o fluxo do item 10 do seu pedido: GET em `/contas/login/?next=/equipamentos/LOC-AQX1-0001/`, depois POST de usuário/senha para a MESMA URL (reproduzindo o que o navegador faz quando `<form method="post">` não declara `action` — ele envia para a URL atual, querystring incluída). Resultado real:
```
POST status: 302
POST redirect Location: /equipamentos/LOC-AQX1-0001/
```
**O fluxo completo já funciona, sem nenhuma mudança de código.** Dois fatos do Django se combinam para isso, nenhum deles novo:
1. `templates/accounts/login.html` tem `<form method="post">` **sem `action`** — o navegador sempre envia o POST para a URL atual da página, preservando `?next=...` na querystring.
2. `LoginView` (usada sem customização em `apps/accounts/urls.py`, só com `template_name`) já procura `next` tanto em `request.POST` quanto em `request.GET` (`RedirectURLMixin.get_redirect_url()`, código-fonte do Django) — não precisa de um campo hidden para funcionar.

Como a URL do QR e a URL da ficha privada são **a mesma** (`equipment:detail`), o próprio `EquipmentDetailView` já resolve o "retorna direto para a ficha, sem passar por Home nem buscar de novo" — não porque foi construído para isso agora, mas porque a arquitetura de view única (pública/privada pela mesma rota) já era assim desde a Fase 1.

**O que falta, então, não é lógica — é reforço e prova:**
- Adicionar `<input type="hidden" name="next" value="{{ request.GET.next }}">` dentro do `<form>` de `login.html`, como defesa em profundidade: hoje funciona porque o form não tem `action`; se algum dia alguém adicionar um `action="{% url 'accounts:login' %}"` (mudança plausível, inofensiva à primeira vista), o `next` para de ser preservado silenciosamente, sem erro nenhum aparente. O hidden field torna o comportamento explícito e resistente a essa classe de regressão futura.
- Um teste automatizado dedicado (`apps/accounts/tests/test_login_next_redirect.py` ou similar) travando este comportamento — hoje **não existe nenhum teste cobrindo o parâmetro `next`** em lugar nenhum do projeto (busquei especificamente, nada encontrado). Ver [33].

### [21] Segurança do `next`

Nenhum código de validação de redirecionamento precisa ser escrito — `LoginView` já usa `django.utils.http.url_has_allowed_host_and_scheme()` internamente (via `RedirectURLMixin`) antes de redirecionar, restringindo o destino a: caminhos relativos dentro do próprio site, ou hosts explicitamente listados em `ALLOWED_HOSTS`/`get_success_url_allowed_hosts()`. Isso é o mecanismo seguro padrão do Django, e o projeto **não o sobrescreve em lugar nenhum** (confirmei: nenhum `success_url`, nenhum `form_class`, nenhum `get_redirect_url` customizado em `apps/accounts`).

O valor de `next` sempre é gerado pelo próprio servidor (`{{ request.path }}` dentro do template, nunca digitado/colável por um usuário) — não há, hoje, nenhum ponto de entrada onde um atacante controle o valor de `next` além da querystring, que já passa pela validação acima de qualquer forma. **Instrução para a implementação futura, explícita:** não escrever nenhum redirect manual (`HttpResponseRedirect(request.GET["next"])` cru) em lugar nenhum — sempre passar pelo mecanismo padrão do `LoginView`, que é exatamente o que já está em uso.

### [22] Comportamento do funcionário já autenticado

Achado importante, que simplifica bastante este ponto: **um usuário autenticado nunca vê `detail_public.html`** — `EquipmentDetailView` (linha 454 de `views.py`) só renderiza a versão pública quando `not request.user.is_authenticated`. Qualquer usuário logado, de qualquer perfil (ADMIN/ADMINISTRATIVO/OPERACIONAL/CONSULTA), que acesse a URL do QR **sempre** cai direto na ficha privada completa — não existe hoje, nesta view específica, nenhum bloqueio por permissão além de "estar logado" (`EquipmentDetailView` não usa `RoleRequiredMixin`/`allowed_roles`; os 4 perfis têm acesso de leitura à ficha, confirmado pelos testes de `AcquisitionValueVisibilityByRoleTest`, que só restringem o BLOCO de valor de aquisição dentro da ficha, não a ficha em si).

Consequência prática: o cenário "autenticado mas sem permissão para ver a ficha" **não existe** para esta tela específica hoje — então não há necessidade de nenhuma lógica nova de "esconder link confuso" para ela. O botão "Entrar"/"Abrir ficha interna" do header público, mencionado no seu pedido, só teria alguma ambiguidade a resolver se um usuário autenticado pudesse, de alguma forma, VER a página pública (o que não acontece — ele nunca chega nela, é redirecionado pela própria view antes). Registro isto como uma simplificação real da implementação futura, não como um ponto ainda em aberto.

---

## PARTE C — Navegação interna

### [23] Diagnóstico do menu mobile interno atual

Markup exato, `templates/base.html:216-245`:
```html
<button type="button" id="nav-toggle" aria-expanded="false" aria-controls="main-nav"
        class="sm:hidden text-white p-1.5 rounded-md hover:bg-white/10 ...">
  <svg ...>hambúrguer cru, não passa por {% icon %}</svg>
</button>
<nav id="main-nav" class="hidden sm:flex sm:items-center gap-x-4 gap-y-2 text-sm flex-wrap w-full sm:w-auto">
  <a>Equipamentos</a> <a>Manutenções</a> <a>Higienizações</a> <a>Clientes</a> <a>Unidades</a>
  {% if administrativo+ %}<a>Categorias</a> <a>Modelos</a>{% endif %}
  {% if admin %}<a>Importar planilha</a> <a>Usuários</a>{% endif %}
  <span>{{ user }} · {{ role }}</span>
  <form><button>Sair</button></form>
</nav>
```
E o JS inteiro (`base.html:262-278`): um `addEventListener("click", ...)` que faz `nav.classList.toggle("hidden")`.

**O bug estrutural exato:** a classe do `<nav>` é `hidden sm:flex ...` — a versão `flex` (com `gap-x-4 gap-y-2 flex-wrap`, que é o que dá espaçamento e quebra de linha organizada) **só se aplica a partir do breakpoint `sm:` (≥640px)**. No mobile, quando o JS remove `hidden`, o `<nav>` volta ao `display: block` padrão do navegador — os filhos (`<a>`, `<span>`, `<form>`) são todos inline/inline-block por natureza e ficam se acumulando em fluxo de texto normal, sem o `gap`/`flex-wrap` que só existe em telas maiores. Resultado: 7-9 links + o texto do usuário + o botão "Sair" tudo colado em fluxo de texto corrido, sem hierarquia visual, sem área de toque reservada, provavelmente quebrando de forma feia dependendo do tamanho de cada texto — exatamente o "visualmente quebrado" que você descreveu, com causa raiz identificada.

Outros problemas, catalogados:
- **9-11 alvos interativos** (7 links base + até 2 condicionais + "Sair") num único bloco plano, sem nenhum agrupamento.
- **"Sair" é texto sublinhado dentro de um `<form>` inline**, não um botão com área de toque — menor alvo de toque de todo o menu, justo numa ação sensível (log out).
- **Nenhum estado ativo** — a página em que você está não é destacada no menu (sem `aria-current="page"`, sem classe de destaque).
- **Nenhum ícone** — puro texto, inconsistente com o resto do sistema depois da fase de iconografia.
- **Nenhum foco de teclado dedicado** — o menu herda só o outline padrão do navegador nos links, sem tratamento.
- **Sem Escape para fechar, sem clique-fora para fechar** — só o próprio botão hambúrguer alterna.
- **Toggle único e genérico** (`document.getElementById`), sem nenhuma lógica de fechar ao navegar (clicar num link não fecha o menu explicitamente — o navegador troca de página então é irrelevante na prática, mas o estado do `aria-expanded` também não é resetado nesse meio-tempo).

### [24] Nova proposta de menu mobile interno

Um **drawer lateral** (painel deslizando da direita, cobrindo até ~85% da largura da tela, com fundo escurecido atrás) — não um painel que empurra o conteúdo, e não apenas "a navbar empilhada" que você pediu para evitar. Motivo da escolha entre as opções que você listou: um drawer separa claramente "eu estou navegando" de "eu estou olhando a página", dá espaço vertical suficiente para AGRUPAR por módulo (que uma navbar simplesmente empilhada não dá, viraria uma lista longa sem hierarquia igual ao problema atual, só que mais alta), e é o padrão mais reconhecível em sistemas administrativos mobile — sem precisar de nenhuma biblioteca nova (é HTML+CSS+um punhado de vanilla JS, mesmo espírito do toggle atual, só mais completo).

Estrutura agrupada (cruzando os módulos que você propôs com as URLs e permissões REAIS que auditei — nenhuma suposição):

| Grupo | Item | URL | Quem vê hoje |
|---|---|---|---|
| Operação | Equipamentos | `equipment:list` | Todo autenticado |
| Equipamentos | Novo equipamento | `equipment:create` | `CAN_MANAGE_EQUIPMENT` (Admin/Administrativo) |
| Equipamentos | Adicionar em lote | `equipment:batch_create` | idem |
| Equipamentos | Importar planilha | `equipment:import_upload` | `CAN_IMPORT_LEGACY_SPREADSHEET` (só Admin) |
| Manutenção | Manutenções | `maintenance:maintenance_list` | `CAN_VIEW_MAINTENANCE` (4 perfis — hoje mostrado sem `{% if %}` porque coincide com "todo autenticado") |
| Manutenção | Higienizações | `maintenance:cleaning_list` | idem |
| Cadastros | Clientes | `clients:list` | `CAN_VIEW_CLIENTS` (4 perfis) |
| Cadastros | Unidades | `operations:location_list` | idem |
| Cadastros | Categorias | `catalog:category_list` | `CAN_MANAGE_CATALOG` (Admin/Administrativo) |
| Cadastros | Modelos | `catalog:model_list` | idem |
| Administração | Usuários | `accounts:user_list` | `CAN_MANAGE_USERS` (só Admin) |
| Administração | Diagnóstico de unidades duplicadas | `operations:duplicate_locations_report` | `CAN_VIEW_DIAGNOSTICS` (só Admin) — **hoje sem NENHUM link de menu**, só acessível digitando a URL |

(**"Movimentações" fica de fora da tabela de propósito** — não existe hoje nenhuma tela de listagem de `Movement`, só a criação por equipamento (`operations:movement_create`); não posso adicionar um link de menu para uma tela que não existe. Fica registrado como uma tela nova a avaliar, fora do escopo desta auditoria.)

Cada grupo continua exatamente com os MESMOS `{% if %}` de permissão já usados em `base.html` hoje — só reorganizados visualmente, nenhuma regra nova. Um grupo inteiro (ex.: "Administração") só aparece se pelo menos um item dele for visível para o usuário.

Requisitos, mapeados no que já existe:
- **44px de toque**: reaproveitar a MESMA convenção de `.icon-btn` (`min-w-[44px] min-h-[44px]`) aplicada à altura de cada linha do drawer, não só a ícones.
- **Heroicons**: precisa vendorizar mais alguns (nenhum dos 10 atuais cobre "casa"/"usuários"/"pasta"/"engrenagem") — `home`, `users`, `archive-box` (ou `folder`), `cog-6-tooth`, além de migrar o hambúrguer cru para `bars-3` dentro de `icons.py`.
- **Estado ativo**: `aria-current="page"` no item cuja URL bate com `request.path`, com destaque visual (fundo dourado claro/borda esquerda dourada) — testável (`assertContains` no atributo).
- **Identidade Locus**: mesmo fundo `bg-brand-black`/tons de marca do header atual.
- **Botão fechar claro**: um `X` (`x-mark`, já vendorizado) no topo do drawer, além do backdrop clicável.
- **Foco de teclado + Escape**: vanilla JS (sem framework) — ao abrir, mover foco para o primeiro item do drawer; `keydown` de `Escape` fecha e devolve foco ao botão hambúrguer; um "focus trap" simples (ciclar Tab dentro do drawer enquanto aberto) é o único JS genuinamente novo desta frente, ainda pequeno (~20-30 linhas, mesmo estilo do toggle já existente).
- **Permissões**: inalteradas, ver tabela acima.

### [25] Proposta de navegação desktop por módulos

Hoje a `<nav>` desktop já funciona (o bug é só mobile), mas tem 7-9 links soltos, sem agrupamento — o mesmo problema de poluição, só que sem estar visualmente quebrado. Três caminhos, sem escolher um por você ainda (peço decisão em [39] porque cada um tem trade-off diferente de esforço/JS novo):

**Opção A — Manter tudo plano, só separar visualmente por divisores** (menor esforço, zero JS novo): agrupar os mesmos módulos da tabela acima lado a lado com um separador (`|` ou espaçamento maior) entre grupos, sem dropdown. Reduz poluição por AGRUPAMENTO VISUAL, não por ocultação — nada fica escondido atrás de clique extra, o que combina com "não esconder ações frequentes demais".

**Opção B — 2-3 dropdowns para os módulos menos frequentes** (ex.: "Cadastros ▾" agrupando Unidades/Categorias/Modelos, "Administração ▾" agrupando Usuários/Diagnóstico/Importar), mantendo Equipamentos/Manutenções/Clientes sempre visíveis e soltos (são os de uso diário). Reduz a contagem de itens no nível superior de ~9 para ~5-6, mas introduz o único JS novo desta frente (toggle de dropdown ao clique ou hover) — pequeno, vanilla, mesmo padrão do restante do projeto.

**Opção C — Reaproveitar o MESMO drawer do mobile também no desktop**, abrindo como painel lateral fixo/colapsável em vez de navbar horizontal — mais consistente entre os dois tamanhos de tela, mas é a mudança mais estrutural das três (a navbar desktop deixaria de ser uma barra horizontal).

Recomendo a **Opção B** como equilíbrio — reduz poluição de fato (a métrica que você pediu) sem introduzir uma reestruturação grande, mas as três são tecnicamente viáveis com os componentes que já existem (`.link`, cores/foco do design system).

---

## PARTE D — Nova Home interna

### [26] Proposta da nova Home

Hoje **não existe Home nenhuma** — confirmei em `config/urls.py`: não há rota `""` (raiz) registrada em lugar nenhum do projeto, e `LOGIN_REDIRECT_URL = "equipment:list"` (`config/settings/base.py:198`) faz a listagem de equipamentos funcionar como "home" de fato. Isto significa que criar uma Home de verdade é a mudança mais estrutural das três frentes: precisa de uma URL raiz nova, uma view nova, um template novo, e mudar `LOGIN_REDIRECT_URL` — nenhum desses pontos tem teste hoje que dependa do valor atual (busquei especificamente por testes que verificam para onde o login redireciona — nenhum encontrado), então a mudança é segura nesse sentido.

Estrutura conceitual (cards + listas, não gráfico por padrão — ver [27]):
```
linha 1 (cards de status):  [Disponíveis] [Em operação] [Manutenção] [Manutenções abertas]
linha 2 (ações rápidas):    [+ Novo equipamento] [+ Abrir manutenção] [+ Nova movimentação] ...
                             (cada atalho só aparece se o usuário tiver a permissão correspondente)
linha 3 (duas colunas):      [Movimentações recentes]     [Manutenções abertas (lista)]
                             [Higienizações recentes]     [Equipamentos que exigem atenção]
```
Isto é referência de layout, não prescrição pixel-a-pixel — o objetivo é: visão geral rápida (cards), atalho pras ações mais comuns, e 3-4 listas curtas do que está "quente" agora (não histórico completo, isso já existe nas telas de listagem).

### [27] Indicadores disponíveis hoje (auditados um a um)

| # | Indicador | Pergunta que responde | Model/query | Permissão | Custo |
|---|---|---|---|---|---|
| 1 | Equipamentos por status (Disponível/Em operação/Manutenção/Inativo) | "Como está a frota agora?" | `Equipment.objects.filter(is_active=True).values("status").annotate(total=Count("id"))` — **1 query**, agrega os 4 status de uma vez | Todo autenticado | Baixo — usa o índice existente em `status` |
| 2 | Equipamentos por condição (Bom/Médio/Ruim/Inutilizável) | "Quantos equipamentos precisam de atenção física?" | `Equipment.objects.filter(is_active=True).values("condition").annotate(total=Count("id"))` — **1 query** | Todo autenticado | Baixo — índice existente em `condition` |
| 3 | Manutenções abertas (contagem) | "Quantas fichas técnicas estão pendentes agora?" | `Maintenance.objects.filter(status="ABERTA", is_active=True).count()` — **1 query** | `CAN_VIEW_MAINTENANCE` (4 perfis) | Muito baixo — já é o mesmo par de campos do índice único parcial existente (`uniq_maintenance_aberta_ativa_por_equipamento`) |
| 4 | Manutenções abertas (lista curta, ex. 5 mais antigas) | "Quais manutenções precisam de atenção primeiro?" | `Maintenance.objects.filter(status="ABERTA", is_active=True).select_related("equipment").order_by("created_at")[:5]` — **1 query** | idem | Baixo |
| 5 | Movimentações recentes (lista curta) | "O que andou se movendo recentemente?" | `Movement.objects.select_related("equipment").order_by("-created_at")[:5]` — **1 query** (os nomes de origem/destino já são campos `*_name` denormalizados no próprio `Movement`, não precisam de mais `select_related`) | `CAN_VIEW_MOVEMENTS` (4 perfis) | Baixo |
| 6 | Higienizações recentes (lista curta) | "O que foi higienizado recentemente?" | `Cleaning.objects.select_related("equipment").order_by("-performed_at")[:5]` — **1 query** | `CAN_VIEW_MAINTENANCE` | Baixo |
| 7 | Equipamentos que exigem atenção (condição Ruim/Inutilizável) | "O que precisa de decisão/reparo?" | `Equipment.objects.filter(is_active=True, condition__in=["RUIM","INUTILIZAVEL"]).select_related("model")[:5]` — **1 query** | Todo autenticado | Baixo — índice existente em `condition` |
| 8 | Total de clientes / unidades ativas (opcional, menor prioridade) | "Base de clientes/unidades em números" | `Client.objects.count()`, `Location.objects.filter(is_active=True).count()` — **2 queries** | `CAN_VIEW_CLIENTS` | Baixo |

Todo indicador usa **agregação ou slice limitado (`[:5]`)**, nenhum `.count()` dentro de loop, nenhum N+1 (os `select_related` cobrem exatamente os campos que a lista precisa exibir). É a mesma disciplina que a auditoria de N+1 já aplicou em `equipment/list.html`/`maintenance_list.html` — reaproveitada aqui, não inventada.

### [28] Orçamento de queries

Somando os indicadores 1-7 (o conjunto "linha 1 + linha 3" do wireframe conceitual): **6 queries independentes, todas agregações ou listas curtas com `select_related`**, nenhuma dependente do tamanho da tabela crescer (todas usam `LIMIT`/`COUNT`, não trazem registros ilimitados). Adicionando o indicador 8 (opcional): **8 queries**. Nenhuma delas é um `.count()` disparado dentro de um loop Python — é exatamente o padrão que evitaria o timeout que vocês já sofreram contra o Postgres remoto. Uma Home com esse orçamento é comparável, em custo, a uma página de listagem filtrada — não a uma tela de relatório pesado.

### [29] Indicadores futuros (não disponíveis hoje, não inventados agora)

- **Movimentações por período/tipo (ex.: "instalações este mês")** — dá para calcular hoje (`Movement.created_at` existe), mas exigiria decidir uma janela de tempo/agrupamento específica — fica como ideia, não indicador pronto.
- **Manutenções por técnico responsável** — o campo `responsible` existe, mas vira métrica de desempenho individual, que é uma decisão de produto/gestão de pessoas, não uma auditoria técnica que eu deva propor sozinho.
- **Tempo médio de manutenção aberta até fechamento** — calculável (`closed_at - created_at`), mas é uma métrica derivada que merece sua própria validação de fórmula antes de virar card na Home.
- **Qualquer coisa dependente de `EquipmentModel.specs`** — indisponível até o campo ser populado de verdade (ver [11]).

---

## PARTE E — Fechamento

### [30] Componentes novos necessários (design system)

- `.public-cta` (ou nome equivalente) — botão de largura cheia, ícone à esquerda + texto + seta à direita, para a lista de CTAs comerciais da landing (o CTA primário reaproveita `.btn-primary`, só em tamanho maior).
- `.hero-image-frame` — container de altura fixa por breakpoint para a imagem do equipamento (ver [6]).
- `.public-header`, `.public-drawer` (ou nomes equivalentes) — cabeçalho e painel de menu da página pública.
- `.nav-drawer`, `.nav-group`, `.nav-item` (ou equivalente) — o novo menu mobile interno ([24]).
- `.stat-tile` (ou reaproveitar `.card-pad` com uma variante) — os 4 cards de indicador no topo da Home.
- Nenhuma dessas classes foi criada agora — ficam como proposta de nomes para a fase de implementação, seguindo o mesmo padrão de nomenclatura já aprovado (`.icon-btn-*`, `.badge-*`).

### [31] Arquivos que seriam alterados (implementação futura — nada tocado agora)

**Novos:** `templates/base_public.html`, `templates/_design_tokens.html`, `templates/equipment/detail_public.html` (reescrito), `templates/core/home.html`, `apps/core/context_processors.py`, `apps/core/views.py` (`HomeView`) ou `apps/core/urls.py`, `apps/catalog/images.py`, `apps/catalog/templatetags/model_images.py`, `static/images/equipment/*.webp` (assets reais, fornecidos por você), `static/favicon.ico`.

**Editados:** `apps/equipment/views.py` (`EquipmentDetailView` — contexto público + ajuste do `select_related`, ver [12]), `templates/accounts/login.html` (hidden `next`), `templates/base.html` (novo menu mobile + navegação por módulos), `apps/core/templatetags/icons.py` (novos ícones), `config/settings/base.py` (`LOGIN_REDIRECT_URL`, `LOCUS_*`, `context_processors`), `config/urls.py` (rota raiz).

**Fora do escopo, confirmado novamente:** `qrcodes/label.html` não entra em nenhuma dessas mudanças.

### [32] Testes existentes afetados

- `apps/equipment/tests/test_public_detail_view.py` — as duas asserções `assertIn(self.equipment.patrimonio, content)` / `assertIn("Aquecedor", content)` continuam válidas; precisarão de novas asserções para os elementos novos (imagem, CTA) sem enfraquecer as de ausência de dado sensível (`assertNotIn(...)`, que devem TODAS continuar passando sem alteração).
- `apps/equipment/tests/test_public_detail_no_operational_leak.py` — mesma lógica, nenhuma asserção precisa enfraquecer.
- `AcquisitionValueVisibilityByRoleTest` (dentro de `test_public_detail_view.py`) — `test_public_page_never_loads_acquisition_fields` continua válido tal como está.
- Nenhum teste de `apps/accounts` cobre `next` hoje — não há nada para "quebrar" ali, só para completar (ver [33]).
- Nenhum teste depende do valor de `LOGIN_REDIRECT_URL` — confirmado por busca dedicada.
- Nenhum teste cobre `base.html`/menu mobile hoje (é só markup, nunca foi testado por HTTP de forma estrutural) — logo, o redesenho do menu não quebra suíte nenhuma, mas também não tinha rede de segurança prévia (reforça a necessidade dos testes novos abaixo).

### [33] Novos testes necessários (implementação futura)

- Fluxo `next` completo: GET com `?next=`, POST, `assertRedirects` para a URL do equipamento — trava o comportamento verificado empiricamente em [20].
- Landing pública nova: presença de imagem (`<img>` com `alt` correto), presença dos CTAs configurados, AUSÊNCIA dos CTAs cujo `commercial_links` esteja vazio, e repetição de todas as asserções de ausência de dado sensível já existentes.
- `get_model_image_path()`/template tag: modelo com entrada no dicionário → path esperado; modelo sem entrada → placeholder; nunca lança exceção.
- Home: contagem de queries com `CaptureQueriesContext` (mesmo padrão já usado no projeto) provando que o número não cresce com mais registros — mesma disciplina do teste de N+1 já existente em `maintenance_list`.
- Menu mobile: presença/ausência de cada grupo por perfil (reaproveitando o padrão de teste de permissão já usado em `test_operations_views.py`), presença de `aria-current` na página ativa.

### [34] Riscos de regressão

Baixo-médio, maior que a fase de iconografia porque esta envolve URL raiz nova e mudança de `LOGIN_REDIRECT_URL` (nenhum teste depende disso hoje, mas é uma mudança de comportamento observável para todo usuário, não só cosmética). A reestruturação do menu mobile/desktop tem risco médio SE algum `{% if %}` de permissão for reescrito incorretamente ao mover os links de lugar — a mitigação é a mesma já usada nas duas fases anteriores: reaproveitar as condições exatas já existentes, nunca reescrever a lógica "de cabeça".

### [35] Riscos de segurança

O único ponto de atenção real é o já descrito em [1]/[12]: o `select_related` que carrega `current_client`/`current_location` incondicionalmente na query de `EquipmentDetailView`. Não é uma vulnerabilidade hoje (nada vaza), mas é uma armadilha para uma mudança futura descuidada no template público — a correção (restringir o `select_related` ao ramo autenticado) deveria acompanhar a reescrita de `detail_public.html`. Fora isso: nenhum mecanismo de redirecionamento novo é necessário (ver [21]), nenhum upload/armazenamento externo é introduzido (imagens são estáticas versionadas, exatamente como você pediu).

### [36] Riscos de performance

A landing pública pode receber tráfego anônimo maior que o resto do sistema — os pontos que mais pesam:
- **A imagem do equipamento é o LCP da página** (maior elemento visível logo no carregamento) — por isso a recomendação de WEBP leve (80-150KB), dimensões reservadas (`width`/`height` fixos, sem CLS) e `fetchpriority="high"` sem `lazy` em [10].
- **Zero dependência JS nova** nesta frente além do que já existe (htmx não é usado na página pública, Tailwind CDN é o único script externo, igual hoje).
- **Cache de estáticos**: `STATIC_ROOT`/`collectstatic` já é o mecanismo de produção — arquivos WEBP versionados no repo se beneficiam do cache-busting/headers que o Render já aplica a estáticos coletados, nenhuma configuração nova necessária.
- **Contagem de queries da página pública**: hoje é 1 (`get_object_or_404` com `select_related`) — a versão nova não deveria crescer além de 1-2 (ex.: se precisar buscar algo do modelo separadamente, o que não deveria ser necessário já que `model` já vem via `select_related`).

### [37] Estratégia de responsividade

- **Landing pública — prioridade mobile**, testar 320/360/390/430px (larguras reais de aparelho, não só os 3 breakpoints usados nas fases anteriores) além de tablet/desktop — reflete o uso real (abrir a câmera e escanear é um gesto mobile por definição). Nenhum elemento deveria depender de hover (é tela de toque).
- **Home interna — desktop prioritário, funcional em mobile**: os cards de indicador empilham em coluna única abaixo de um certo breakpoint (mesmo padrão `flex-wrap`/`grid` já usado em `equipment/list.html`), sem exigir scroll horizontal.
- **Menu — precisa parecer desenhado para mobile**, não a barra desktop comprimida (é literalmente o diagnóstico do problema atual em [23]) — o drawer proposto em [24] resolve isso por construção (é um componente mobile-first desde o desenho, não uma adaptação da navbar).

### [38] Ordem recomendada de implementação

Seguindo a prioridade que você declarou (QR + menu mobile primeiro):
1. Infraestrutura compartilhada: `_design_tokens.html` (extração sem duplicar), novos ícones em `icons.py`, `apps/catalog/images.py` + template tag, `apps/core/context_processors.py` + settings `LOCUS_*`.
2. `base_public.html` + header público + menu público + `detail_public.html` reescrito (a landing em si) — maior prioridade visual, conforme pedido.
3. Ajuste de `EquipmentDetailView` (contexto público + `select_related` restrito) + hidden `next` em `login.html` + teste do fluxo completo.
4. Menu mobile interno novo (`base.html`) — segunda prioridade visual declarada.
5. Navegação desktop por módulos (depende da opção A/B/C escolhida em [39]).
6. Nova Home (`HomeView`, URL raiz, `LOGIN_REDIRECT_URL`) — a mudança mais estrutural, por último, depois que o restante já estiver estável.
7. Suíte completa + `check` + `makemigrations --check --dry-run` + verificação visual, mesmo padrão das duas fases anteriores.

### [39] Decisões que precisam da sua aprovação

1. **Valores reais dos links comerciais** ([14]) — Instagram, site, WhatsApp/telefone, destino do "Faça seu orçamento". Sem eles, os botões correspondentes simplesmente não renderizam.
2. **Para onde aponta "Conheça nossos equipamentos"** ([13]) — site institucional externo, ou descartar o CTA nesta rodada por não existir vitrine pública própria ainda.
3. **Ícone do Instagram** ([15]) — vendorizar o glifo oficial da marca (recomendado) vs. ícone genérico + texto vs. só texto.
4. **Texto institucional fixo da landing** ([11]) — a frase tipo "Soluções para ambientes mais confortáveis..." não vem de nenhum campo do banco, precisa ser escrita/aprovada por vocês (pode ser única para todo o site ou variar por categoria — decisão de conteúdo, não técnica).
5. **Navegação desktop por módulos** ([25]) — opção A (só separadores visuais), B (dropdowns nos módulos secundários, recomendado) ou C (mesmo drawer do mobile também no desktop).
6. **Nomes/arquivos das imagens por modelo e o placeholder** ([9]/[10]) — preciso que vocês forneçam os arquivos WEBP reais (ou aprovem que eu gere um placeholder de marca simples enquanto isso).
7. **`specs` comercial no `EquipmentModel`** ([11]/[29]) — fica de fora nesta rodada (recomendado, por falta de dado real hoje) ou vocês querem que eu já desenhe o schema de chaves como trabalho futuro próximo.
8. **Escopo da Home nesta rodada** — os 8 indicadores auditados em [27] são o teto do que dá para calcular com confiabilidade hoje; confirmar se algum deve ficar de fora da primeira versão (ex.: manter só 1-2, 3, 5, 7 e deixar o resto para depois).

---

Nenhum arquivo de código foi criado ou alterado nesta auditoria — só este relatório. Aguardando sua aprovação (geral ou item a item) antes de tocar em qualquer template, view, settings ou criar os arquivos novos listados em [31].
