# Armazenamento de arquivos (estáticos e mídia)

Criado em 14/09/2026, junto da implementação de Produtos e Serviços/Proposta Comercial — é a primeira vez que o projeto grava arquivo de usuário/sistema em disco através de um `FileField` real (`apps.attachments.models.Attachment.file`, usado hoje para os PDFs de Proposta Comercial/Contrato gerados por `apps.crm`). Antes disso só existiam **estáticos** (imagens de modelo em `static/images/equipment/`, servidas via `{% static %}`) — nada de mídia gerada em runtime. Este documento cobre os dois, porque a distinção entre eles é exatamente o que costuma confundir quem mexe nisso pela primeira vez.

## Estáticos vs. mídia — a distinção que importa

- **Estáticos** (`STATIC_URL`/`STATIC_ROOT`/`STATICFILES_DIRS`) — arquivos que fazem parte do próprio código-fonte (CSS, JS, as fotos de modelo de equipamento em `static/images/equipment/`). Versionados no git, coletados uma vez no deploy (`collectstatic`), nunca escritos em runtime pela aplicação.
- **Mídia** (`MEDIA_URL`/`MEDIA_ROOT`) — arquivos gerados/enviados **em runtime**, pela própria aplicação. Nunca versionados no git. Hoje o único gerador é `apps.attachments` (via `apps.crm.services.issue_proposal()`/`generate_contract()`, que geram um PDF e chamam `create_attachment()`).

## Configuração (`config/settings/base.py`)

```python
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"       # destino de collectstatic
STATICFILES_DIRS = [BASE_DIR / "static"]     # fonte, versionada no git

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"              # NUNCA versionado no git
```

Em teste (`config/settings/test.py`), `MEDIA_ROOT` é sobrescrito para um diretório temporário novo a cada execução (`tempfile.mkdtemp(...)`) — ver `docs/testing.md` ("Isolamento de MEDIA_ROOT nos testes") para o motivo (evitar colisão de nome de arquivo entre execuções).

## Quem serve o quê, em cada caminho de deploy

| | Estáticos (`/static/`) | Mídia (`/media/`) |
|---|---|---|
| **VPS (Oracle + Docker Compose + Nginx)** | Nginx local, `alias /app/staticfiles/` (`docker/nginx.conf`) | Nginx local, `alias /app/media/` (`docker/nginx.conf`) |
| **Render + Neon (alternativo)** | WhiteNoise (`whitenoise.storage.CompressedStaticFilesStorage`), direto do processo Gunicorn — sem Nginx dedicado no Free tier | Sem storage externo configurado — ver "Pendência conhecida" abaixo |

**Ponto crítico de segurança**: em ambos os caminhos, o que serve `/media/` (Nginx local ou o processo Django/WhiteNoise) **não aplica nenhuma checagem de permissão do Django** — é `alias`/servidor de arquivo estático puro. Isso é seguro para fotos de modelo de equipamento (públicas por natureza — aparecem na landing pública do QR), mas **nunca seria seguro para os PDFs de Proposta/Contrato**, que contêm dados comerciais sensíveis (endereço, documento do cliente, valores negociados). Por isso `apps.attachments` **não expõe um link `/media/` direto em nenhuma tela** — todo download passa por `apps.crm.views.AttachmentDownloadView`, uma view Django normal (autenticada, com `permission_required`, e que valida que o `Attachment` pertence à `Opportunity` da URL antes de servir o arquivo via `FileResponse`). O arquivo fica fisicamente em `MEDIA_ROOT`/servível por `/media/` como qualquer outro, mas **nenhuma tela do sistema constrói ou expõe essa URL direta** — a única forma suportada de chegar no arquivo é pela view autenticada.

Se um dia `apps.attachments` ganhar um segundo consumidor com conteúdo verdadeiramente público (ex.: fotos de equipamento reaproveitando o mesmo model), a distinção acima precisa ser revisitada por conteúdo — não é uma regra automática do model, é uma decisão de cada view consumidora.

## Onde os arquivos de mídia ficam, na prática

`Attachment.file` usa `upload_to` dinâmico: `attachments/<app_label>/<model>/<object_id>/<filename>` — por exemplo, `attachments/crm/opportunity/42/PROP-000017.pdf`. Namespaced por dono sem `apps.attachments` precisar conhecer nada sobre o consumidor (`GenericForeignKey`, ver `docs/apps/attachments.md`).

## Pendência conhecida — mídia no caminho Render+Neon

O caminho de deploy Render (`config/settings/render.py`) configura `STORAGES["staticfiles"]` para WhiteNoise, mas **não define nenhum backend de storage para mídia** — o Free tier da Render tem filesystem efêmero (qualquer arquivo gravado em `MEDIA_ROOT` local é perdido no próximo deploy/restart do container). Isso não é um bug introduzido por esta implementação: o caminho Render já era descrito como "alternativo, para validação" antes de existir qualquer gerador real de mídia (`docs/deployment.md`). Agora que `apps.attachments` grava PDFs de verdade, essa lacuna passa a ser relevante pela primeira vez — mas **implementar um backend de storage externo (S3-compatível ou similar) está fora do escopo desta rodada** (a especificação de Produtos e Serviços não pediu isso, e a regra de execução era não inventar infraestrutura nova não solicitada). Registrado aqui para quando o caminho Render for usado para algo além de validação pontual: nesse momento, `MEDIA_ROOT` local deixa de ser suficiente e um `STORAGES["default"]` externo (ex.: `django-storages` + um bucket) precisa entrar. O caminho VPS (produção principal) não tem esse problema — `MEDIA_ROOT` é um volume persistente do host, fora do container.

## O que este documento não cobre

Não documenta o conteúdo/model de `Attachment` (ver `docs/apps/attachments.md`) nem o fluxo de geração de PDF (ver `docs/apps/crm.md`, seção Services — `apps.crm.pdf`). É só a camada de infraestrutura de arquivo (onde fica, quem serve, o que é seguro expor direto).
