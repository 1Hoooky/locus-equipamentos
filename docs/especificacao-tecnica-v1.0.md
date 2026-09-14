# Especificação Técnica v1.0 — Sistema de Gestão de Equipamentos Locus Locações

**Status:** aprovada conceitualmente pela Locus para início do desenvolvimento. Nenhuma linha de código foi escrita ainda — este documento é a referência oficial para o começo da Fase 1.
**Data:** 20/08/2026
**Histórico:** v0.1 (escopo/arquitetura inicial, patrimônio sequencial global) → v0.2 (hospedagem HostGator e domínio confirmados) → v0.3 (patrimônio redesenhado como `LOC-{MODEL_CODE}-{SEQUENCE}`, sequência por modelo) → **v1.0 (consolidação final: telas, fluxos, critérios de aceite, backlog de Fase 2/3, decisões fechadas)**.

---

## 1. Entendimento do projeto

A Locus Locações aluga equipamentos de climatização e aquecimento (climatizadores e aquecedores, hoje; a arquitetura precisa suportar categorias futuras sem alteração estrutural). O controle atual é feito por planilha (`Estoque.Atualizado.xlsx`), examinada antes de escrever esta especificação:

- 305 equipamentos ativos catalogados: 172 climatizadores e 133 aquecedores.
- Catálogo de modelos mais granular do que "5 + 3" — reforça a exigência de categorias/modelos extensíveis, cadastrados via interface, nunca fixos no código-fonte.
- Esquema próprio de código por equipamento (ex.: `20261122201003`), frágil: mistura informação de negócio no identificador, sem página, histórico ou QR associado.
- Planilha espalhada em 7 abas parcialmente redundantes, sem fonte oficial única, com ~35–40 linhas sem subcategoria/descrição.
- Sem status operacional, condição, localização ou histórico — é uma foto do cadastro, não um controle vivo.

Este é exatamente o problema que o sistema resolve: sair de uma "foto estática" para um controle vivo, com identidade permanente e legível por modelo via QR Code.

## 2. Objetivos

- Dar a cada equipamento uma identidade digital única, permanente e nunca reaproveitada (patrimônio), legível por modelo/família a partir do próprio código.
- Permitir consulta e ação rápida via QR Code, otimizada para celular.
- Preservar histórico completo de tudo que acontece com o equipamento — nunca apenas o estado atual.
- Suportar múltiplos perfis de usuário com permissões reais, validadas no backend.
- Ser tecnicamente independente: hospedagem própria, domínio próprio, dados exportáveis, sem lock-in desnecessário.
- Crescer em fases (Patrimônio Digital → Operação → Gestão) sem exigir reconstrução do que já foi feito.

## 3. Escopo do MVP (Fase 1 — Patrimônio Digital)

- Autenticação de usuários e perfis de permissão (backend-enforced).
- Cadastro de categorias e modelos de equipamento, cada modelo com um `code` próprio (extensível, sem limite fixo de modelos).
- Cadastro de equipamento com geração automática e atômica de patrimônio no formato `LOC-{MODEL_CODE}-{SEQUENCE}`, com sequência independente por modelo.
- Campos de status operacional e condição física, independentes entre si.
- Busca e filtros combinados (patrimônio, modelo, categoria, serial, status, condição).
- Geração de QR Code por equipamento, apontando para URL permanente em `estoque.locuslocacoes.com.br`.
- Página individual do equipamento, com duas camadas de visualização (pública mínima / autenticada completa).
- Interface mobile-first para a página do equipamento; desktop-friendly para telas administrativas.
- Importação inicial da planilha atual (305 equipamentos).
- Exportação de dados (CSV/Excel) desde o primeiro momento.
- Infraestrutura de histórico/auditoria desde o primeiro dia (mesmo com a UI completa de linha do tempo só na Fase 2 — histórico não capturado no início não pode ser reconstruído depois).

## 4. O que NÃO entra no MVP

Clientes, movimentações, manutenção, higienização, dashboard, alertas automáticos, app nativo, integrações externas, multi-tenant, internacionalização. Tudo isso está detalhado e priorizado na seção 21 (Backlog futuro) — não é esquecido, só não faz parte da Fase 1.

## 5. Principais regras de negócio

**Patrimônio:**

- Formato `LOC-{MODEL_CODE}-{SEQUENCE}` (ex.: `LOC-AQCP-0001`), sem espaços.
- Numeração **não é global** — cada `EquipmentModel` tem sua própria sequência independente. `LOC-AQCP-0001` e `LOC-AQCT-0001` coexistem sem duplicidade, porque o patrimônio completo (com o código do modelo) é único.
- `SEQUENCE` começa com 4 dígitos (`0001`–`9999`); acima disso cresce sem zero-padding adicional (`LOC-AQCP-10000`) — a arquitetura não trava nesse limite.
- Gerado exclusivamente pelo backend, de forma atômica (seção 8), nunca calculado ou digitado no frontend.
- Nunca reutilizado, mesmo com o equipamento inativado.
- **Permanente após criado.** Corrigir o modelo de um equipamento depois do cadastro nunca regenera o patrimônio automaticamente — procedimento excepcional definido na seção 8.
- O sistema **nunca faz parsing** da string do patrimônio para descobrir o modelo. Fonte da verdade: relação `Equipment → EquipmentModel`.
- Códigos de modelo pertencem ao cadastro de `EquipmentModel` — nunca fixos no código-fonte.

**Demais regras:**

- Exclusão física de registros com histórico relevante é proibida; usa-se inativação (soft delete/`is_active`).
- Status (disponível, em operação, manutenção, inativo) e condição (bom, médio, ruim, inutilizável) são campos independentes, cada um com seu próprio histórico.
- QR Code nunca guarda dados do equipamento, só a URL permanente do patrimônio.
- Toda mudança relevante gera evento imutável e datado no histórico (append-only).
- Permissões validadas sempre no backend/API, nunca só escondendo botão no frontend.
- Página pública do QR nunca expõe cliente atual, valor de aquisição, dados de manutenção ou qualquer informação operacional interna. Categoria e modelo do equipamento **podem** aparecer publicamente (decisão final — seção 22), pois ajudam a identificar um equipamento encontrado/perdido sem revelar nada sensível.

## 6. Entidades necessárias

| Entidade | Papel |
|---|---|
| `User` | conta de acesso, com um `role` |
| `Role` / grupo de permissão | Administrador, Administrativo, Operacional/Técnico, Consulta |
| `Category` | categoria pai (ex.: Aquecedor, Climatizador), extensível |
| `EquipmentModel` | modelo dentro de uma categoria, com `code` próprio que compõe o patrimônio, extensível |
| `Equipment` | equipamento físico — `patrimonio` (imutável), `model_id` (FK), `model_sequence` (inteiro escopado por modelo) |
| `StatusHistory` | cada mudança de status |
| `ConditionHistory` | cada mudança de condição |
| `Client` | cliente (schema pronto na Fase 1, uso a partir da Fase 2) |
| `Location` | estoque/barracão, cliente, manutenção, transporte, outro |
| `Movement` | ida/volta entre localizações (Fase 2) |
| `Maintenance` | preventiva/corretiva (Fase 2) |
| `Cleaning` | higienização (Fase 2) |
| `Attachment` | foto/arquivo vinculável a equipamento, manutenção, higienização ou evento |
| `HistoricalEquipment` (e equivalentes) | snapshot automático via `django-simple-history` |

## 7. Relacionamento entre as entidades

```
Category 1───N EquipmentModel 1───N Equipment
Equipment N───1 Location (localização atual, nullable)
Equipment N───1 Client (cliente atual, nullable)
Equipment N───1 Equipment (superseded_by, nullable — reemissão excepcional, seção 8)
Equipment 1───N StatusHistory
Equipment 1───N ConditionHistory
Equipment 1───N Movement (fase 2) ── Movement N───1 Location (origem/destino)
Equipment 1───N Maintenance (fase 2)
Equipment 1───N Cleaning (fase 2)
Equipment 1───N Attachment
Maintenance 1───N Attachment
Cleaning 1───N Attachment
User 1───N Equipment (created_by)
User 1───N StatusHistory / Movement / Maintenance / Cleaning (responsável)
```

`model_sequence` é escopado por `EquipmentModel`, não por `Category`.

## 8. Proposta do banco de dados

Banco: **PostgreSQL**.

**`users`**: `id`, `name`, `email` (único), `password_hash` (Argon2/PBKDF2), `role` (enum ADMIN/ADMINISTRATIVO/OPERACIONAL/CONSULTA), `is_active`, `created_at`.

**`categories`**: `id`, `name` (único), `slug` (único), `is_active`.

**`equipment_models`**: `id`, `category_id` (FK), `name` (exibição), `code` (único, obrigatório, caixa alta, sem espaços, regex `^[A-Z0-9]{2,20}$`, imutável assim que existir um `Equipment` vinculado), `manufacturer` (opcional), `specs` (JSONB, opcional), `last_sequence` (integer, default 0 — contador interno para geração atômica), `is_active`, timestamps.

**`equipment`**: `id` (interno, nunca exposto), `patrimonio` (único, indexado, imutável), `model_id` (FK), `model_sequence` (integer), `category_id` (denormalizado), `serial_number`, `legacy_code` (rastreabilidade da planilha antiga), `supplier`, `acquisition_date`, `acquisition_value`, `status` (enum DISPONIVEL/EM_OPERACAO/MANUTENCAO/INATIVO), `condition` (enum BOM/MEDIO/RUIM/INUTILIZAVEL), `current_location_id` (FK, nullable), `current_client_id` (FK, nullable), `superseded_by_id` (FK → equipment, nullable), `last_maintenance_date`, `last_cleaning_date`, `next_maintenance_date`, `notes`, `is_active`, `created_by_id` (FK), timestamps.

**`status_history`** / **`condition_history`**: `id`, `equipment_id`, `old_value`, `new_value`, `changed_by_id`, `changed_at`, `reason`.

**`clients`** (Fase 1: schema; Fase 2: uso): `id`, `company_name`, `trade_name`, `document`, `phone`, `email`, `address`, `city`, `state`, `contact_name`, `notes`, `is_active`.

**`locations`**: `id`, `name`, `type` (enum ESTOQUE/CLIENTE/MANUTENCAO/TRANSPORTE/OUTRO), `client_id` (FK opcional), `address`, `is_active`.

**`movements`** (Fase 2): `id`, `equipment_id`, `from_location_id`, `to_location_id`, `moved_at`, `moved_by_id`, `reason`.

**`maintenances`** (Fase 2): `id`, `equipment_id`, `date`, `technician_id`, `type` (PREVENTIVA/CORRETIVA), `reason`, `diagnosis`, `service_performed`, `parts_replaced`, `notes`, `condition_before`, `condition_after`, `next_maintenance_date`.

**`cleanings`** (Fase 2): `id`, `equipment_id`, `date`, `responsible_id`, `procedure`, `condition_found`, `notes`, `result`, `next_cleaning_date`.

**`attachments`**: `id`, `equipment_id`/`maintenance_id`/`cleaning_id` (nullable), `file_path`, `caption`, `uploaded_by_id`, `uploaded_at`.

Todas as tabelas de cadastro principal ganham tabela histórica espelho via `django-simple-history` (seção 16).

### Constraints garantidas no banco

- `equipment.patrimonio` — **UNIQUE** (global).
- `(equipment.model_id, equipment.model_sequence)` — **UNIQUE**.
- `equipment_models.code` — **UNIQUE**, com CHECK espelhando a validação de formato.

### Geração atômica do patrimônio

1. Dentro de `transaction.atomic()`, `EquipmentModel.objects.select_for_update().get(pk=model_id)` — trava a linha daquele modelo especificamente; modelos diferentes não se bloqueiam entre si.
2. Incrementa `last_sequence` naquela linha; o novo valor vira `model_sequence`.
3. Monta `patrimonio = f"LOC-{model.code}-{model_sequence:04d}"` (sem padding extra acima de 9999) e cria o `Equipment` na mesma transação.
4. A constraint `(model_id, model_sequence)` UNIQUE é a segunda linha de defesa contra qualquer inconsistência que escape da lógica acima.

Proibido usar `MAX(model_sequence) + 1` sem lock. Teste automatizado obrigatório: N cadastros concorrentes do mesmo modelo devem gerar sequenciais únicos e sem lacunas.

### Imutabilidade e reclassificação de modelo (procedimento excepcional)

`patrimonio` e `model_sequence` nunca são editados por fluxo normal — nenhuma tela permite alterá-los diretamente. Se um equipamento foi cadastrado com modelo errado, dois caminhos, restritos a **Administrador**, com motivo obrigatório e evento auditado:

1. **Reclassificar modelo (padrão):** corrige `model_id`; `patrimonio` e `model_sequence` permanecem — a etiqueta física já impressa continua válida. A divergência entre prefixo e modelo atual fica visível na linha do tempo, nunca escondida.
2. **Reemitir patrimônio (exceção):** ação separada, com confirmação explícita ("vou reimprimir a etiqueta física"). Inativa o registro atual e cria um novo `Equipment` com patrimônio gerado do zero, ligado via `superseded_by_id` — histórico do equipamento antigo continua consultável.

`EquipmentModel.code` segue regra análoga: editável livremente enquanto o modelo não tiver equipamentos; trava na interface normal assim que existir o primeiro; correção excepcional depois disso exige procedimento administrativo à parte, auditado, e não reescreve patrimônios já emitidos (eles mantêm o prefixo antigo).

## 9. Arquitetura recomendada

**Monolito modular server-rendered**, não microserviços, não SPA separada da API.

Justificativa: time único, volume de dados pequeno-médio, valor concentrado em disciplina de dados e permissões — não em escala horizontal. Microserviços adicionariam complexidade operacional sem benefício, contra o princípio de simplicidade e manutenibilidade.

Módulos (apps Django): `accounts`, `catalog` (categorias/modelos), `equipment`, `clients`, `operations` (movimentação/manutenção/higienização), `attachments`, `qrcodes`, `dashboard`. A geração de patrimônio vive em `apps/equipment/services.py`, isolada da view, para facilitar testes de concorrência sem simular requisições HTTP inteiras.

API REST (Django REST Framework) exposta só onde há necessidade real: import/export e futura consulta programática. Não é a camada obrigatória entre frontend e backend — o frontend web usa o Django direto.

## 10. Stack tecnológica e serviços externos

| Camada | Recomendação | Alternativas | Por quê |
|---|---|---|---|
| Backend | Django 5 (Python) | Node/NestJS, Rails | Baterias inclusas (auth, ORM, migrations, admin); `django-simple-history` resolve histórico; `select_for_update()` cobre a geração atômica sem SQL cru |
| Frontend | Templates Django + HTMX + Alpine.js + Tailwind CSS | React/Next.js (SPA) | Um único codebase e deploy, sem duplicar autenticação/permissão em duas camadas |
| Banco de dados | PostgreSQL | MySQL | JSONB para specs flexíveis, sem lock-in, `SELECT FOR UPDATE` maduro |
| QR e etiquetas | `qrcode` (Python) + `Pillow`/`WeasyPrint` (PDF) | serviço externo de QR | Geração local, sem dependência de terceiro para algo central |
| Fila/agendamento (Fase 3) | `cron` do sistema inicialmente; Celery + Redis só se necessário | Celery desde já | Não adicionar infraestrutura antes de precisar |
| Fotos | disco do VPS via `django-storages`, com backup externo | S3 direto | Troca de backend sem mudar código de negócio, se o volume exigir |
| Hospedagem | **HostGator VPS NVMe 4** (2 vCPU / 4 GB RAM / 100 GB NVMe, root/SSH, Docker) + Docker Compose | Hetzner/DigitalOcean/Contabo | Já definida pela Locus — servidor no Brasil, Docker suportado |
| CI/CD | GitHub Actions | GitLab CI | Gratuito no volume usado, sem lock-in real |

**Serviços externos:**

| Serviço | Por que | Custo aprox. | Risco de lock-in | Saída |
|---|---|---|---|---|
| VPS HostGator NVMe 4 | Hospedar app, banco, arquivos | a partir de ~R$ 21,69/mês (plano de entrada); NVMe 4 fica acima — confirmar valor e renovação no site | Baixo (Linux + Docker) | Migrar `docker-compose.yml` para outro provedor |
| Domínio `locuslocacoes.com.br` | URL permanente dos QR Codes | já registrado | Nenhum | Transferir de registrador quando quiser |
| Backup externo (ex.: Backblaze B2) | Cópia off-site de banco e fotos | ~R$ 25–50/mês | Baixo (API S3-compatible) | Trocar provedor S3-compatible |
| E-mail transacional (Mailgun/Resend/SES) | Redefinição de senha, convites | Grátis até um volume baixo | Baixo | Trocar provedor SMTP/API |
| GitHub | Versionamento e CI/CD | Grátis no uso previsto | Baixo | Migrar/espelhar repositório |

## 11. Autenticação e permissões

Sessão Django (`HttpOnly` + `Secure`, CSRF nativo), senha Argon2, `django-axes` contra força bruta, redefinição por e-mail.

| Ação | Administrador | Administrativo | Operacional/Técnico | Consulta |
|---|---|---|---|---|
| Gerenciar usuários e permissões | Sim | Não | Não | Não |
| Cadastrar/editar categorias e modelos | Sim | Sim | Não | Não |
| Editar `code` de modelo com equipamentos / reemitir patrimônio | Sim | Não | Não | Não |
| Reclassificar modelo de equipamento existente | Sim | Não | Não | Não |
| Cadastrar/editar equipamento | Sim | Sim | Não | Não |
| Ver valor de aquisição / dados financeiros | Sim | Sim | Não | Não |
| Registrar manutenção/higienização/movimentação (Fase 2) | Sim | Sim | Sim | Não |
| Alterar condição/status | Sim | Sim | Sim | Não |
| Adicionar fotos | Sim | Sim | Sim | Não |
| Consultar equipamento e histórico | Sim | Sim | Sim | Sim |
| Exportar dados | Sim | Sim | Não | Não |
| Importar planilha legada | Sim | Não | Não | Não |

Matriz vira testes automatizados desde a Fase 1 — nunca só documentação.

## 12. Telas da Fase 1

| Tela | Acesso | Plataforma prioritária | Notas |
|---|---|---|---|
| Login | Público | Mobile + Desktop | E-mail/senha, link "esqueci minha senha" |
| Recuperação de senha | Público (com token) | Mobile + Desktop | Envio de link por e-mail transacional |
| Listagem/busca de equipamentos | Autenticado (todos os perfis) | Desktop, responsiva | Filtros combinados (patrimônio, modelo, categoria, serial, status, condição) + busca livre |
| Ficha do equipamento — pública | Não autenticado (via QR) | Mobile-first | Empresa, categoria, modelo, patrimônio, convite para login. Nada de cliente/manutenção/valor |
| Ficha do equipamento — autenticada | Autenticado | Mobile-first | Ficha completa + linha do tempo + ações rápidas conforme permissão |
| Cadastro/edição de equipamento | Administrador, Administrativo | Desktop | Modelo, serial, fornecedor, aquisição, valor, status, condição, notas, fotos. Patrimônio só aparece depois de salvar, nunca editável |
| Cadastro/edição de categoria | Administrador, Administrativo | Desktop | CRUD simples |
| Cadastro/edição de modelo | Administrador, Administrativo | Desktop | Inclui `code`; campo trava após o primeiro equipamento vinculado |
| Reclassificação de modelo (ação restrita) | Administrador | Desktop | Formulário com motivo obrigatório; preview do que muda e do que permanece (patrimônio) |
| Geração/download de QR e etiqueta | Administrador, Administrativo | Desktop | Individual e em lote (PDF) |
| Exportação de dados | Administrador, Administrativo | Desktop | CSV/Excel, respeita os filtros aplicados na listagem |
| Importação da planilha legada | Administrador | Desktop | Fluxo assistido com tela de revisão antes de confirmar (seção 13) |
| Gestão de usuários | Administrador | Desktop | Criar usuário, definir perfil, ativar/desativar |

## 13. Fluxos principais

**A. Cadastro de equipamento e geração de patrimônio**
1. Administrador/Administrativo abre "Novo equipamento" e seleciona um `EquipmentModel` já cadastrado.
2. Preenche serial, fornecedor, data/valor de aquisição, condição inicial (status inicia como `DISPONIVEL` por padrão).
3. Ao salvar, o backend executa a geração atômica (seção 8) e retorna o `patrimonio` definitivo.
4. A tela de confirmação já oferece o download do QR/etiqueta daquele patrimônio.

**B. Escaneamento do QR**
1. Alguém aponta a câmera para a etiqueta → abre `estoque.locuslocacoes.com.br/equipamentos/LOC-...`.
2. Se não autenticado: vê ficha pública (empresa, categoria, modelo, patrimônio) e um convite para login.
3. Se autenticado: vê ficha completa e as ações permitidas pelo seu perfil (na Fase 1, majoritariamente consulta; ações de manutenção/movimentação chegam na Fase 2).

**C. Reclassificação de modelo (exceção)**
1. Administrador identifica um equipamento cadastrado com modelo errado.
2. Abre a ação restrita "Reclassificar modelo", escolhe o modelo correto e escreve o motivo (obrigatório).
3. Sistema atualiza `model_id`, mantém `patrimonio`/`model_sequence`, registra evento auditado na linha do tempo.
4. Se a divergência for grande demais para conviver (ex.: categoria errada), o Administrador aciona separadamente "Reemitir patrimônio", com confirmação explícita de que a etiqueta física será trocada.

**D. Importação da planilha legada**
1. Administrador faz upload do arquivo (ou aponta para a planilha já mapeada).
2. Sistema tenta casar cada linha com um `EquipmentModel` existente (por código/descrição) e sinaliza linhas sem correspondência clara ou com dados incompletos (as ~35–40 linhas identificadas).
3. Tela de revisão lista essas pendências para curadoria manual antes da confirmação — nada entra "errado" silenciosamente.
4. Ao confirmar, cada linha vira um `Equipment` com `legacy_code` preenchido e `patrimonio` gerado pela mesma rotina atômica usada no cadastro manual.

**E. Login e controle de sessão**
1. Usuário entra com e-mail/senha; `django-axes` limita tentativas.
2. Sessão via cookie `HttpOnly`/`Secure`; toda rota sensível revalida o perfil no backend a cada requisição — nunca confia em estado do frontend.

## 14. Estratégia para QR Codes e etiquetas

URL permanente por patrimônio, ex.: `https://estoque.locuslocacoes.com.br/equipamentos/LOC-NI23BT-0041`. QR codifica só a URL, nunca dados do equipamento. Sistema fica em subdomínio (`estoque.locuslocacoes.com.br`) porque o domínio raiz já hospeda o site institucional da Locus — sem qualquer risco de conflito, é só um novo registro DNS.

Etiqueta física em PDF (`WeasyPrint`, com impressão em lote): nome/logo Locus Locações, nome de exibição do modelo, patrimônio completo em texto grande e legível **sem QR** (ex.: `LOC-NI23BT-0041`), e o QR Code.

## 15. Estratégia para fotos/arquivos

Validação de tipo/tamanho/dimensão no upload; nome de arquivo gerado pelo sistema (evita path traversal e colisão); remoção de metadados EXIF (evita vazar GPS de onde a foto foi tirada); thumbnail para listagens; armazenamento via `django-storages` (disco local + backup externo, migrável para S3-compatible sem mudar código); soft delete de anexos.

## 16. Estratégia de histórico/auditoria

1. **Snapshot automático de campo** via `django-simple-history` em `Equipment`, `Client`, `EquipmentModel` etc. — inclusive reclassificações de modelo e correções excepcionais de `code`.
2. **Eventos estruturados de domínio**: `StatusHistory`, `ConditionHistory`, `Movement`, `Maintenance`, `Cleaning`.

A ficha do equipamento junta as duas fontes numa linha do tempo única, ordenada por data. Nenhum evento é apagado fisicamente; correções entram como novo evento.

## 17. Estratégia de backup

`pg_dump` diário automático (retenção 30–90 dias); cópia de dumps e fotos para armazenamento externo (ex.: Backblaze B2 via `rclone`); backup adicional antes de cada migration/deploy; teste de restore documentado e periódico.

## 18. Riscos técnicos

- **Concorrência na geração do patrimônio por modelo** — mitigado por `select_for_update()` + constraint UNIQUE (seção 8).
- **Reclassificação usada como atalho para mascarar erro de cadastro** — mitigado por permissão restrita a Administrador + motivo obrigatório + auditoria visível.
- **Vazamento de dado interno na página pública do QR** — mitigado por teste automatizado específico do que aparece deslogado.
- **Crescimento de armazenamento de fotos sem plano** — mitigado por compressão no upload e política de retenção definida cedo.
- **Qualidade dos dados legados** (~35–40 linhas incompletas) — exige curadoria manual na importação (fluxo D, seção 13).
- **Permissão esquecida em rota nova** — mitigado por testes automatizados de permissão cobrindo os 4 perfis, desde a Fase 1.
- **Dependência de uma única pessoa para operar o servidor** — mitigado documentando o processo de deploy desde o início.

## 19. Estrutura sugerida de pastas/repositório

```
locus-equipamentos/
├── config/                    # settings (base/dev/prod), urls, wsgi/asgi
├── apps/
│   ├── accounts/               # usuários, perfis, autenticação
│   ├── catalog/                 # categorias, modelos (code, geração de patrimônio)
│   ├── equipment/                 # equipamento, patrimônio, status, condição
│   ├── clients/                     # clientes (Fase 2)
│   ├── operations/                   # movimentação, manutenção, higienização (Fase 2)
│   ├── attachments/                    # fotos/arquivos
│   ├── qrcodes/                          # geração de QR e etiquetas
│   ├── dashboard/                          # indicadores (Fase 3)
│   └── core/                                # utilitários compartilhados (soft delete, timestamps, mixins)
├── templates/                   # templates Django + partials HTMX
├── static/                        # Tailwind/Alpine/assets
├── tests/                           # testes por app, incluindo permissão e concorrência de patrimônio
├── docs/                              # este documento e futuras decisões de arquitetura (ADRs)
├── scripts/                             # import da planilha, seed de dados de demonstração e de códigos de modelo
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── .env.example                           # nunca credenciais reais no repositório
├── requirements/ (base.txt, dev.txt, prod.txt)
├── manage.py
└── README.md
```

## 20. Critérios de aceite da Fase 1

- Novo equipamento cadastrado recebe patrimônio no formato correto, com `model_sequence` coerente para aquele modelo.
- Cadastros concorrentes do mesmo modelo (testado automaticamente) nunca geram `model_sequence` duplicado.
- Editar o modelo de um equipamento existente nunca altera seu `patrimonio` — só a reclassificação explícita e auditada faz isso.
- `EquipmentModel.code` não pode ser editado pela interface normal assim que existir ao menos um equipamento vinculado.
- Página pública (`/equipamentos/LOC-...` sem login) nunca exibe cliente, valor de aquisição, manutenção ou qualquer dado interno — coberto por teste automatizado.
- Os 305 equipamentos da planilha atual são importados com `legacy_code` preservado, `model_id` correto e novo `patrimonio` gerado pela rotina atômica.
- Exportação CSV/Excel reproduz corretamente `patrimonio`, `model`, `status`, `condition` e `legacy_code` de todos os equipamentos ativos.
- Administrador cadastra um modelo novo (com `code` novo) e gera patrimônios para ele sem qualquer alteração de código-fonte ou deploy.
- As 12 telas da seção 12 estão implementadas e navegáveis nos perfis corretos, com a matriz de permissões da seção 11 coberta por testes automatizados.
- QR impresso de um equipamento de teste, escaneado no celular, abre a ficha pública correta em menos de 2 segundos numa conexão 4G comum.

## 21. Backlog futuro — Fase 2 e Fase 3

**Nada desta seção é implementado agora.** Ela existe para dar continuidade sem retrabalho: o schema e a arquitetura da Fase 1 (seções 8–9) já preveem essas tabelas e módulos.

**Fase 2 — Operação**

- Cadastro completo de clientes (`Client`) e vínculo com equipamentos.
- Movimentações (`Movement`): registrar troca de localização (estoque ↔ cliente ↔ manutenção ↔ transporte), sempre como novo registro, nunca sobrescrevendo `current_location_id` sem histórico.
- Fluxos de instalação e retirada de equipamento num cliente.
- Manutenção preventiva e corretiva (`Maintenance`): diagnóstico, serviço realizado, peças substituídas, condição antes/depois, fotos antes/depois.
- Higienização (`Cleaning`): procedimento, condição encontrada, resultado, próxima higienização prevista.
- Fotos vinculadas diretamente a eventos de manutenção/higienização/movimentação.
- Linha do tempo completa e navegável na ficha do equipamento, unindo todos os tipos de evento.
- Telas novas: cadastro de cliente, registrar movimentação, registrar manutenção, registrar higienização, histórico de localização por cliente.
- Permissões: Operacional/Técnico passa a de fato usar as ações de registrar manutenção/higienização/movimentação já previstas na matriz da seção 11.

**Fase 3 — Gestão**

- Dashboard: total de equipamentos, por status, por categoria/modelo, condição da frota, manutenções próximas, higienizações pendentes, movimentações recentes.
- Alertas de manutenção/higienização próximas (via `cron`, sem necessidade de Celery inicialmente).
- Relatórios e exportações avançadas (além do CSV/Excel simples da Fase 1).
- Interface própria de consulta ao histórico/auditoria (hoje só disponível via `django-simple-history` internamente).
- Refinamentos administrativos gerais conforme uso real do sistema mostrar necessidade.

## 22. Decisões finais confirmadas

- **Hospedagem:** HostGator VPS NVMe 4 (2 vCPU / 4 GB RAM / 100 GB NVMe), Docker Compose por cima.
- **Domínio e subdomínio:** `locuslocacoes.com.br` (já registrado). Sistema em `estoque.locuslocacoes.com.br` para não afetar o site institucional atual — nome de subdomínio adotado como padrão; troca é só um registro DNS, sem custo, caso a Locus prefira outro nome mais adiante.
- **Stack:** Django 5 + HTMX + Alpine.js + Tailwind + PostgreSQL, monolito modular, conforme seções 9–10.
- **Padrão de patrimônio:** `LOC-{MODEL_CODE}-{SEQUENCE}`, sequência independente por modelo (seções 5 e 8).
- **Página pública do QR:** mostra empresa, categoria e modelo do equipamento, além do patrimônio — nunca cliente, valor ou dados de manutenção.
- **Migração dos 305 equipamentos:** recebem novo patrimônio sequencial por modelo; código antigo preservado em `legacy_code`, sem influenciar a nova numeração.

**Códigos de modelo iniciais (seed de dados, não hardcoded):**

| Categoria | Código | Modelo |
|---|---|---|
| Aquecedor | `AQCP` | Aquecedor Pirâmide |
| Aquecedor | `AQCT` | Aquecedor Torre |
| Aquecedor | `AQCH` | Aquecedor Híbrido |
| Climatizador | `NI23TC` | NI23 Tanque Caixa |
| Climatizador | `NI23BT` | NI23 Big Tank |
| Climatizador | `NI23TS` | NI23 Tanque Suporte |
| Climatizador | `9PRO` | nome comercial pendente (seção 23) |
| Climatizador | `9PRO2` | versão 220V do 9PRO — nome comercial pendente (seção 23) |
| Climatizador | `6PRO` | nome comercial pendente (seção 23) |

## 23. Pendências operacionais (não bloqueiam o início da Fase 1)

Itens de dado/operação, não de arquitetura — o desenvolvimento pode começar em paralelo a essas definições:

1. Nomes comerciais completos de `9PRO`, `9PRO2` e `6PRO` (necessários antes de emitir a primeira etiqueta desses modelos, não antes de começar a programar).
2. Curadoria das ~35–40 linhas incompletas da planilha atual, antes ou durante a importação (fluxo D, seção 13).
3. Quantidade e perfis de usuários no lançamento (ajuda a dimensionar onboarding, não bloqueia o cadastro do primeiro Administrador).
4. Volume médio esperado de fotos por equipamento/evento (o armazenamento em disco do VPS atende o início; só relevante decidir migração para S3-compatible se o volume crescer).
5. Prazo desejado para a Fase 1 entrar em uso (ajuda a priorizar dentro do próprio MVP, se necessário).

---

Esta é a versão aprovada para o início do desenvolvimento. A partir daqui, o próximo passo é o detalhamento técnico da Fase 1: modelos de dados finais em Django, migrations e as primeiras telas — que só começa após um novo sinal explícito de início.
