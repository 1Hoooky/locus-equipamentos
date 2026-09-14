# Fase 2 — Operação: proposta de arquitetura (fundação operacional)

Status: **proposta, aguardando aprovação — nada abaixo foi implementado.**
Data: 25/08/2026.

Escopo desta etapa: Clientes, consulta automática de CNPJ, endereço fiscal, endereço de entrega/operação, unidades/locais, vínculo de equipamentos, movimentações, e integração à timeline existente. Nada de manutenção completa, higienização completa, contratos, financeiro, CRM, dashboard final, calendário, alertas, IA ou redesign — isso continua fora desta entrega.

Ponto de partida importante: **`apps/clients` e `apps/operations` já existem como esqueleto de schema desde a Fase 1**, criados propositalmente para `Equipment.current_client`/`Equipment.current_location` terem para onde apontar sem exigir uma migration disruptiva depois. `Location` já tem `type` (`ESTOQUE`/`CLIENTE`/`MANUTENCAO`/`TRANSPORTE`/`OUTRO`) e uma FK opcional para `Client` — ou seja, o modelo `Client → Location` que esta proposta usa já estava previsto, não é uma ideia nova. Nenhum dos dois apps tem view/service real ainda (só `admin.py` básico), e nenhum dos dois foi usado em produção — os dois únicos campos com dado real hoje são as FKs vazias em `Equipment`.

---

## 1. Models propostos e campos

### 1.1 `apps.core.models.Address` (novo)

Um único model de endereço, reutilizado tanto pelo endereço fiscal do cliente quanto pelo endereço operacional de cada unidade — em vez de duplicar os mesmos 7 campos em duas tabelas diferentes. Fica em `core` (não em `clients` nem em `operations`) porque os dois apps vão depender dele e `operations` já depende de `clients` — colocar em `core`, que nenhum dos dois importa de volta, evita qualquer risco de import circular.

| Campo | Tipo | Obrigatório | Observação |
|---|---|---|---|
| `cep` | CharField(9) | não | Formato livre na entrada, normalizado (só dígitos) no backend |
| `logradouro` | CharField(255) | não | |
| `numero` | CharField(20) | não | Texto, não inteiro (existe "S/N", "123A") |
| `complemento` | CharField(100) | não | |
| `bairro` | CharField(100) | não | |
| `cidade` | CharField(100) | não | |
| `uf` | CharField(2) | não | |
| `reference_notes` | TextField | não | Só usado por endereços operacionais ("portão azul, fundos"); fica em branco para endereço fiscal — ver risco 15.1 |

Nenhum campo é obrigatório no model porque um cliente pode ser cadastrado sem endereço completo ainda (cadastro rápido, revisão depois) — a obrigatoriedade, se quisermos alguma, fica na camada de formulário/serviço, não no schema.

### 1.2 `apps.clients.models.Client` (evolução do model já existente)

Mantém `company_name`, `trade_name`, `phone`, `email`, `contact_name`, `notes`, `is_active`, `created_at`/`updated_at` exatamente como estão.

**Alterações:**

| Campo | Tipo | Mudança |
|---|---|---|
| `client_type` | CharField choices (`PJ`, `PF`), default `PJ` | **novo** — hoje o model não distingue; isso prepara para Pessoa Física sem precisar renomear `document`/`cnpj` depois |
| `document` | CharField(18), normalizado (só dígitos no banco) | **já existe**, mas passa a ter `unique=True` (nulls permitidos, únicos entre não-nulos) e validação de formato/checksum conforme `client_type` |
| `state_registration` | CharField(20), blank | **novo** — inscrição estadual |
| `registration_status` | CharField(60), blank | **novo** — situação cadastral, texto livre (não é um `choices` nosso: é vocabulário da Receita Federal/provider externo, ver seção 5) |
| `fiscal_address` | OneToOneField(`Address`, null=True, blank=True, on_delete=CASCADE) | **novo** |
| `address`, `city`, `state` | — | **removidos** (substituídos por `fiscal_address`) — ver risco 15.1 |

`company_name` continua sendo a razão social (é isso que já significa hoje); `trade_name` continua sendo o nome fantasia. Não crio campos novos para isso, só documento a semântica.

### 1.3 `apps.operations.models.Location` (evolução do model já existente)

Mantém `name`, `type`, `client` (FK opcional), `is_active`, timestamps.

**Alteração:** `address` deixa de ser `CharField` solto e passa a ser `OneToOneField(Address, null=True, blank=True, on_delete=CASCADE)`.

Isso é a "unidade/local operacional" da seção 5 do seu pedido: `Location(type=CLIENTE, client=<Cliente>)` é literalmente "Cliente X, Unidade Maringá". Nenhum model novo é necessário para "unidade" — já existe.

### 1.4 `apps.operations.models.Movement` (novo)

Evento estruturado e imutável, no mesmo espírito de `StatusHistory`/`ConditionHistory` (Fase 1) — nunca editado depois de criado, sempre gravado por um serviço único.

| Campo | Tipo | Obrigatório | Observação |
|---|---|---|---|
| `equipment` | FK `Equipment` | sim | `related_name="movements"` |
| `movement_type` | CharField choices | sim | `INSTALACAO`, `RETIRADA`, `TRANSFERENCIA`, `RETORNO_ESTOQUE`, `ENVIO_MANUTENCAO`, `RETORNO_MANUTENCAO`, `OUTRO` — `TextChoices` extensível para tipos futuros |
| `origin_location` | FK `Location`, null=True | não | de onde saiu (quando aplicável) |
| `destination_location` | FK `Location`, null=True | não | para onde foi (quando aplicável) |
| `client` | FK `Client`, null=True | não | denormalizado a partir de `destination_location.client` — existe para permitir `Movement.objects.filter(client=X)` sem join, e porque você listou "cliente" explicitamente como campo próprio do evento |
| `reason` | TextField | **a definir — ver 15.4** | motivo/observação |
| `created_by` | FK `User`, PROTECT | sim | |
| `created_at` | DateTimeField auto_now_add | sim | |

`Meta.ordering = ["-created_at"]`, nunca há `updated_at` (é um evento, não um registro editável) — mesmo padrão de `StatusHistory`.

### 1.5 Sem novos models genéricos de histórico

Não crio uma tabela "TimelineEvent" genérica. A seção 8 explica por quê.

---

## 2. Relacionamentos (resumo)

```
Client 1───1 Address (fiscal_address)
Client 1───N Location
Location 1───1 Address (endereço operacional)
Location N───1 Client (opcional — Location type=ESTOQUE/MANUTENCAO/TRANSPORTE não tem client)
Equipment N───1 Client (current_client — já existe)
Equipment N───1 Location (current_location — já existe)
Equipment 1───N Movement
Movement N───1 Location (origin, opcional)
Movement N───1 Location (destination, opcional)
Movement N───1 Client (opcional, denormalizado)
```

---

## 3. Serviços de domínio propostos

Mesmo padrão já usado em `apps.equipment.services` (Fase 1): dataclass de entrada + função única que é o ÚNICO caminho suportado para a operação, nunca `Model.objects.create()` direto em view/form.

- **`apps.clients.services.create_client(data: NewClientData) -> Client`** — normaliza documento, valida duplicidade, cria `fiscal_address` (se informado), e opcionalmente cria a unidade/`Location` inicial ("endereço de entrega" do cadastro simples) na mesma transação atômica. É o caminho usado tanto pelo cadastro individual quanto, futuramente, pela importação em lote (seção 10).
- **`apps.clients.services.update_client(...)`** — edição normal (não mexe em `document` depois de criado? — **decisão a confirmar**, ver 15.5).
- **`apps.clients.lookup.CompanyLookupService.lookup(cnpj) -> CompanyLookupResult`** — detalhada na seção 5.
- **`apps.operations.services.create_location(...)`** — cria uma unidade adicional para um cliente já existente.
- **`apps.operations.services.create_movement(data: NewMovementData) -> Movement`** — detalhada na seção 8/9: cria o `Movement`, atualiza `equipment.current_location`/`current_client`, e (conforme a tabela de transição aprovada) chama `apps.equipment.services.change_status()` já existente — nunca duplica a lógica de gravar `StatusHistory`.

Nenhum desses substitui ou duplica `create_equipment()`, `change_status()`, `change_condition()` etc. — são consumidores deles.

---

## 4. Arquitetura da consulta de CNPJ

```
apps/clients/lookup/
    __init__.py
    base.py        # CompanyLookupResult, CompanyLookupProvider (interface), exceptions
    brasilapi.py   # BrasilAPICompanyLookupProvider
    service.py     # CompanyLookupService — escolhe o provider e orquestra a chamada
```

`base.py` define:

- `CompanyLookupResult` — dataclass com os campos que QUALQUER provider pode preencher: `cnpj`, `company_name`, `trade_name`, `registration_status`, `phone`, `email`, e um `fiscal_address` (mesma forma de `Address`: cep/logradouro/número/complemento/bairro/cidade/uf). Todos os campos são opcionais — um provider pode não devolver tudo.
- `CompanyLookupProvider` — classe-base abstrata com um único método `lookup(cnpj: str) -> CompanyLookupResult`. Trocar de fornecedor no futuro = escrever uma nova classe que implementa esse método; nada mais muda.
- `CompanyLookupUnavailable` / `CompanyLookupNotFound` — as ÚNICAS exceções que escapam do módulo. View/form só conhecem essas duas, nunca `httpx.TimeoutException`, `httpx.ConnectError`, erro de parsing de JSON, etc. — tudo isso é capturado dentro do provider/service e reempacotado.

`CompanyLookupService.lookup(cnpj)`:
1. Normaliza e valida o CNPJ (reaproveita a MESMA função de normalização usada pelo `Client.document`, para não ter duas implementações de "o que é um CNPJ válido" divergindo com o tempo).
2. Resolve o provider configurado (`settings.COMPANY_LOOKUP_PROVIDER`, default `"brasilapi"`) a partir de um registro simples `{"brasilapi": BrasilAPICompanyLookupProvider}`.
3. Chama `provider.lookup(cnpj)` com timeout curto (proposta: 3s de conexão, 5s de leitura, sem retry automático).
4. Qualquer falha (timeout, erro de rede, HTTP não-2xx, 404, JSON malformado, corpo incompleto) vira `CompanyLookupUnavailable` (ou `CompanyLookupNotFound` especificamente para "CNPJ não encontrado") — nunca uma exceção não tratada.

**Views/forms não importam `httpx` nem sabem que existe BrasilAPI** — só chamam `CompanyLookupService.lookup(cnpj)` e tratam duas exceções conhecidas.

Dependência nova necessária: nenhuma biblioteca HTTP está instalada hoje (`requirements/base.txt` não tem `requests` nem `httpx`). Proponho `httpx` (timeout mais explícito que `requests`, e mantém a porta aberta para um provider assíncrono no futuro, sem reescrever nada agora).

**Segredos:** BrasilAPI (CNPJ) é pública e não exige chave hoje. Mesmo assim, a arquitetura já reserva o caminho certo: qualquer provider futuro que precise de credencial lê via `python-decouple` (`config("NOME_DA_VARIAVEL", default="")`), exatamente como `DJANGO_SECRET_KEY`/config de banco já fazem — nunca hardcoded, e documentado em `.env.example` só quando de fato existir.

---

## 5. Fluxo de fallback manual (o requisito mais importante desta seção)

Proposta de UI: o formulário de cadastro de cliente tem DOIS botões — **"Consultar CNPJ"** e **"Salvar"** — no mesmo POST, distinguidos por um campo oculto (`action=lookup` / `action=save`), sem depender de JavaScript (htmx já está carregado no projeto e pode ser usado depois como melhoria progressiva, mas não é pré-requisito).

```
Usuário digita CNPJ → clica "Consultar CNPJ"
  → view chama CompanyLookupService.lookup(cnpj)
  → sucesso: formulário é re-renderizado PRÉ-PREENCHIDO (não salvo), com aviso
    "Dados sugeridos pela consulta — revise antes de salvar."
  → CompanyLookupNotFound: mensagem "CNPJ não encontrado na base pública.
    Você pode continuar o cadastro manualmente." — formulário continua com o
    que o usuário já tinha digitado
  → CompanyLookupUnavailable (timeout/erro/indisponível):
    "Não foi possível consultar o CNPJ automaticamente. Você pode continuar
    o cadastro manualmente." — mesmo comportamento

Usuário revisa/edita os campos (preenchidos ou não) → clica "Salvar"
  → create_client() de sempre, sem nenhuma dependência da consulta ter
    funcionado ou não
```

A consulta **nunca** persiste nada — só popula o formulário em memória, na mesma requisição. Nenhum caminho leva a 500: as duas exceções do serviço são sempre capturadas na view.

---

## 6. Endereço fiscal × endereço de entrega × `Location` — como evito duplicação

Não existe um terceiro conceito "endereço de entrega" separado de `Location`. O que a seção 4 do seu pedido chama de "endereço de entrega" É a unidade/local operacional (seção 5) — só que, no cadastro simples, criada automaticamente como a primeira `Location` do cliente, em vez de exigir uma tela separada.

- **Endereço fiscal** pertence ao `Client` (`Client.fiscal_address`) — um só, é o endereço cadastral/fiscal da empresa.
- **Endereço operacional** pertence a cada `Location` (`Location.address`) — pode haver vários, um por unidade.

"Usar endereço fiscal como endereço de entrega" (marcado por padrão) é puramente uma conveniência de formulário: quando marcado, os campos do endereço da primeira `Location` vêm pré-preenchidos com os valores do endereço fiscal digitado/consultado. Ao salvar, `create_client()` cria **dois registros `Address` distintos** (um para `fiscal_address`, outro para `Location.address`), mesmo que os valores sejam idênticos no momento da criação — nunca a mesma linha, nunca uma FK compartilhada. Por isso, editar o endereço fiscal depois não altera silenciosamente o endereço operacional já usado em movimentações: são linhas diferentes desde o instante em que existem.

Se o usuário desmarcar a opção, os campos do endereço da unidade ficam editáveis e em branco (ou com o que ele já tiver digitado), sem vínculo nenhum com o fiscal.

---

## 7. Vínculo de equipamentos e fonte de verdade da localização atual

`Equipment.current_client` e `Equipment.current_location` **já existem** desde a Fase 1 e continuam sendo, sem nenhuma mudança de forma, a única fonte de verdade sobre "onde o equipamento está agora". Isso não é uma tabela nova — é justamente o par de campos que a Fase 1 reservou para isto.

Por que isso já impede o estado impossível que você descreveu ("disponível no estoque E instalado em cliente ao mesmo tempo"): são FKs simples, um equipamento só pode apontar para UM `current_location`/`current_client` por vez, por construção. O que falta não é uma nova fonte de verdade — é a disciplina de só atualizar esses dois campos através de `create_movement()` (nunca por edição direta, mesmo raciocínio já aplicado a `status`/`condition`/`patrimonio`), e dentro da MESMA transação atômica que grava o `Movement` e (quando aplicável) chama `change_status()`. Se a transação falhar no meio, nem o `Movement` nem a atualização de local ficam gravados parcialmente — mesma garantia de atomicidade já usada em `create_equipment_batch()`.

"Por onde já passou" é exatamente a tabela `Movement` (histórico completo, nunca sobrescrito) — "onde está agora" é `current_location`/`current_client` (o retrato do presente, atualizado a cada movimentação). Duas responsabilidades claramente separadas, sem redundância: uma é o log, a outra é o estado atual derivado do log mais recente.

---

## 8. Timeline única — como agregar sem duplicar dados

`get_equipment_history_timeline()` (Fase 1, `apps/equipment/services.py`) já foi desenhada para isto — a própria docstring da função, escrita durante a Fase 1, já previa: *"é esse formato comum — não o template — que permite plugar novos tipos de evento no futuro (Manutenção/Higienização/Movimentação, Fase 2): basta um novo bloco aqui que produza dicts no mesmo formato, sem tocar na página."*

A proposta é literalmente isso: adicionar mais um bloco à mesma função, iterando `equipment.movements.select_related(...)` e produzindo dicts no mesmo formato comum (`event_type`, `event_type_label`, `old_value_display`, `new_value_display`, `reason`, `changed_by`, `changed_at`) que `StatusHistory`/`ConditionHistory` já produzem. O merge e a ordenação cronológica (`sort` por `changed_at`) que já existem passam a incluir o terceiro tipo automaticamente — **o template (`detail_private.html`) não muda uma linha**, porque ele já itera sobre uma lista genérica de eventos, sem `if` por tipo.

Cada fonte de dado continua na sua própria tabela (`StatusHistory`, `ConditionHistory`, `Movement`) — não crio uma tabela "TimelineEvent" genérica que duplicaria tudo isso só para facilitar o frontend. A união acontece em memória, na hora de montar a página, não no banco.

Consequência que já aparece no seu próprio exemplo (seção 8 do seu pedido): quando uma movimentação implica mudança de status (ver seção 9), isso gera **duas linhas na timeline** — uma de `StatusHistory` ("Status: Disponível → Em operação") e uma de `Movement` ("Instalado na Modema Automóveis — Unidade Maringá") — exatamente como você mesmo mostrou no exemplo, não uma linha só. Confirmo esse comportamento como intencional, não como duplicação indevida.

---

## 9. Status × Movimentação — proposta de regras (não implementada)

Tabela proposta para `create_movement()` aplicar — **sujeita à sua aprovação antes de qualquer código**:

| Movimentação | Status atual exigido | Novo status | Efeito em local/cliente |
|---|---|---|---|
| Instalação em cliente | `DISPONIVEL` | `EM_OPERACAO` | `current_client`/`current_location` = destino |
| Retirada (volta para estoque) | `EM_OPERACAO` | `DISPONIVEL` | `current_client` = nulo, `current_location` = estoque |
| Transferência (cliente/unidade → outro) | `EM_OPERACAO` | *(sem mudança)* | `current_client`/`current_location` = novo destino |
| Retorno ao estoque | `EM_OPERACAO` ou `MANUTENCAO` | `DISPONIVEL` | `current_client` = nulo, `current_location` = estoque |
| Envio para manutenção | `DISPONIVEL` ou `EM_OPERACAO` | `MANUTENCAO` | `current_location` = local de manutenção, `current_client` = nulo |
| Retorno da manutenção | `MANUTENCAO` | `DISPONIVEL` | `current_location` = estoque |

Pontos em aberto que preciso da sua decisão antes de codificar:

1. **Retorno da manutenção direto para um cliente** (sem passar pelo estoque) — permito como uma movimentação só, ou exijo sempre duas (retorno + nova instalação), para manter o histórico explícito? Minha recomendação é exigir duas, para não "esconder" um passo no meio.
2. **`INATIVO`** (equipamento desativado/reemitido) fica fora dessa máquina de estados por enquanto — continua só acessível pelos fluxos já existentes (`supersede_equipment`), não por uma `Movement`. Confirma?
3. Uma tentativa de movimentação fora dessas pré-condições (ex.: "instalar" um equipamento que já está `EM_OPERACAO`) deve ser rejeitada com uma mensagem clara (`ValueError`, mesmo padrão de `change_status()`), nunca silenciosamente ignorada ou sobrescrita.

---

## 10. Estratégia futura de importação em lote (arquitetura, não implementação agora)

Mesmo padrão já validado duas vezes na Fase 1 (importação legada de equipamentos, cadastro de equipamentos em lote): o importador nunca cria `Client` diretamente — sempre chama `create_client()`, o mesmo serviço do cadastro individual, dentro do fluxo de upload → revisão → confirmação já estabelecido (`apps/equipment/views_import.py` é o modelo a replicar, adaptado para clientes).

Enriquecimento por CNPJ em lote **não** roda dentro da importação síncrona (uma planilha de algumas centenas de linhas chamando `CompanyLookupService` uma vez por linha, de forma síncrona, dentro de uma única requisição, estouraria qualquer timeout razoável e sobrecarregaria um provider gratuito sem SLA). Proposta para quando isso for priorizado: um comando de management (`manage.py enrich_clients_by_cnpj`) rodado manualmente, processando em lotes pequenos com espaçamento entre chamadas, atualizando clientes que já existem (criados com os dados literais da planilha) — nunca bloqueando o cadastro em si. Fica registrado como estratégia, não como pendência de código desta entrega.

---

## 11. Matriz de permissões proposta

Reaproveita os 4 perfis atuais. `CAN_REGISTER_OPERATIONS` **já existe** em `apps/accounts/permissions.py` desde a Fase 1, criada e comentada exatamente como *"manutenção/higienização/movimentação — Fase 2"* — proponho reutilizá-la para instalar/retirar/transferir, não criar uma constante nova.

| Ação | Perfis | Constante |
|---|---|---|
| Visualizar cliente | Todos os 4 | `CAN_VIEW_CLIENTS` (nova) |
| Cadastrar cliente | Admin, Administrativo | `CAN_MANAGE_CLIENTS` (nova) |
| Editar cliente | Admin, Administrativo | `CAN_MANAGE_CLIENTS` (mesma) |
| Cadastrar unidade | Admin, Administrativo | `CAN_MANAGE_LOCATIONS` (nova) |
| Editar unidade | Admin, Administrativo | `CAN_MANAGE_LOCATIONS` (mesma) |
| Instalar equipamento | Admin, Administrativo, Operacional | `CAN_REGISTER_OPERATIONS` (já existe) |
| Retirar equipamento | Admin, Administrativo, Operacional | `CAN_REGISTER_OPERATIONS` (já existe) |
| Transferir equipamento | Admin, Administrativo, Operacional | `CAN_REGISTER_OPERATIONS` (já existe) |
| Visualizar movimentações | Todos os 4 | `CAN_VIEW_MOVEMENTS` (nova) |

Mesma disciplina da Fase 1 (reforçada pela auditoria de 25/08): toda permissão aplicada via `RoleRequiredMixin`/`allowed_roles` no backend, nunca só escondendo botão — e, seguindo o mesmo padrão corrigido para `CAN_VIEW_ACQUISITION_VALUE`, qualquer dado sensível de cliente (se algum campo futuro exigir isso) seria protegido também na camada de consulta, não só no template.

---

## 12. Telas mínimas propostas

1. Lista de clientes (busca por razão social/nome fantasia/CNPJ, filtro por ativo/inativo)
2. Cadastro de cliente (dados + botão "Consultar CNPJ" + endereço fiscal + endereço de entrega/unidade inicial com o checkbox "usar fiscal")
3. Edição de cliente
4. Ficha do cliente (dados, endereço fiscal, lista de unidades, lista de equipamentos atualmente vinculados)
5. Cadastro de unidade adicional (`Location`)
6. Edição de unidade
7. Instalar equipamento (a partir da ficha do equipamento, mesmo padrão visual de "Alterar status")
8. Retirar equipamento
9. Transferir equipamento
10. *(Timeline: nenhuma tela nova — já existe e passa a incluir movimentações automaticamente, seção 8)*

---

## 13. Plano de migrations (sequência proposta)

1. `core`: criar `Address`.
2. `clients`: adicionar `client_type`, `state_registration`, `registration_status`, `fiscal_address`; tornar `document` único; **remover** `address`/`city`/`state` (seguro — ver risco 15.1, nenhum dado real existe hoje nesses campos).
3. `operations`: trocar `Location.address` de `CharField` para `OneToOneField(Address)`.
4. `operations`: criar `Movement`.
5. `accounts/permissions.py`: adicionar as 4 constantes novas (não gera migration — não é model).

Cada item acima é uma migration própria e focada, no mesmo estilo já usado na Fase 1 (uma mudança por migration, não uma migration gigante fazendo tudo).

---

## 14. Testes necessários (planejados, não escritos ainda)

- Normalização/validação de CNPJ (formatos variados, checksum inválido, duplicidade — inclusive contra cliente inativo).
- `CompanyLookupService`: sucesso, timeout, erro de conexão, CNPJ não encontrado (404), resposta incompleta/malformada, troca de provider (um provider falso registrado só no teste, provando que a view não muda).
- `create_client()`: com e sem dados de consulta, com e sem unidade inicial, endereço fiscal e de entrega como registros `Address` independentes (editar um não afeta o outro após a criação).
- Múltiplas unidades por cliente.
- `create_movement()`: cada tipo, atomicidade (rollback total em falha no meio, mesmo padrão do lote de equipamentos), a tabela de transição de status aprovada, rejeição de transição inválida, atualização correta de `current_location`/`current_client`.
- Timeline: `Movement` aparece intercalado corretamente com `StatusHistory`/`ConditionHistory` na ordem cronológica certa.
- Matriz de permissões completa, via HTTP, mesma rigor da auditoria de 25/08 (não só ausência visual).
- **Regressão crítica:** a ficha pública do QR (`detail_public.html`) continua sem expor cliente/local/movimentação nem por engano, agora que esses dados vão existir de verdade pela primeira vez em produção.

---

## 15. Riscos e decisões em aberto

1. **`Client.address`/`city`/`state` e `Location.address` (CharField) serão removidos/restruturados.** Confirmado seguro porque nenhum dos dois apps foi usado em produção na Fase 1 (só existiam como schema vazio) — mas é uma mudança estrutural de schema e quero seu sinal explícito antes de migrar.
2. **Nova dependência externa:** proponho `httpx` (nenhuma lib HTTP está instalada hoje). Precisa entrar em `requirements/base.txt`.
3. **BrasilAPI não tem SLA formal** (serviço comunitário/gratuito) — a arquitetura trata isso como esperado (timeout curto, sem retry, fallback manual sempre disponível), mas vale registrar que instabilidade do provider é esperada, não excepcional.
4. **`Movement.reason` obrigatório ou opcional?** Sua lista diz "quando aplicável", mas o padrão já estabelecido em `change_status()`/`change_condition()` é sempre obrigatório, para garantir auditoria. Recomendo manter obrigatório por consistência — preciso da sua confirmação.
5. **`Client.document` pode ser editado depois de criado?** Equipamento tem `patrimonio` imutável por design; cliente não tem um equivalente natural a "reemissão". Recomendo permitir edição (diferente de patrimônio, CNPJ pode ter sido digitado errado e a empresa é a mesma), mas com log de auditoria — o que me leva ao próximo ponto.
6. **`django-simple-history` em `Client`/`Location`?** Hoje só `EquipmentModel`/`Equipment` têm. Sem isso, uma edição de cadastro de cliente (ex.: correção de CNPJ, telefone) não fica registrada em lugar nenhum. Não é CRM (é rastreabilidade básica) — mas é uma decisão de escopo que prefiro te trazer em vez de decidir sozinho.
7. **Situação cadastral/inscrição estadual pela BrasilAPI:** a consulta pública de CNPJ (dados da Receita Federal) normalmente NÃO traz inscrição estadual (é dado de SEFAZ estadual, fora do escopo da Receita) — o campo continua existindo no cadastro, mas via BrasilAPI provavelmente só `registration_status` (situação cadastral) vem preenchido automaticamente; `state_registration` fica quase sempre manual. Sinalizando para não gerar expectativa errada.

---

## Resumo do que preciso de você

Aprovação (ou ajuste) em: modelo de dados das seções 1–2; arquitetura de consulta de CNPJ (seção 4/5); a tabela de transição status×movimentação da seção 9 (item mais sensível — bloqueia a implementação de `create_movement()`); e as 7 decisões abertas da seção 15 (especialmente 15.1, 15.4 e 15.6).

Nenhum código foi escrito para esta etapa. Aguardando sua aprovação antes de implementar.
