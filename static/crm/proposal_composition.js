/*
 * Produtos e Serviços — Composição comercial (14/09/2026).
 *
 * Escopo desta camada JS, deliberadamente pequeno (especificação, seção
 * 14: "Não recarregar a página inteira desnecessariamente SE a
 * arquitetura atual permitir interação dinâmica segura"):
 *
 * - Adicionar/editar/remover produto continuam POST normal (form HTML
 *   comum, POST → Redirect → GET) — o backend já é a única autoridade de
 *   cálculo (seção 80); duplicar essa lógica em JS só para evitar um
 *   reload seria risco sem necessidade real nesta etapa.
 * - A ÚNICA coisa dinâmica aqui é a "Consulta de disponibilidade"
 *   (seção 11): ao escolher um Produto/Modelo e uma Quantidade no form de
 *   adicionar item, consulta `AvailabilityCheckView` (só leitura, GET,
 *   AJAX) e mostra "X solicitados / Y disponíveis" ao lado do botão —
 *   nunca cria reserva/movimento/seleção de patrimônio (seção 12/77).
 */
(function () {
  "use strict";

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(null, args);
      }, wait);
    };
  }

  function initAvailabilityCheck(form) {
    var modelField = form.querySelector('[name="equipment_model"]');
    var quantityField = form.querySelector('[name="quantity"]');
    var resultEl = form.querySelector("[data-availability-result]");
    if (!modelField || !quantityField || !resultEl) {
      return;
    }

    var opportunityMatch = window.location.pathname.match(/\/oportunidades\/(\d+)\//);
    if (!opportunityMatch) {
      return;
    }
    var checkUrl = "/crm/oportunidades/" + opportunityMatch[1] + "/produtos-servicos/disponibilidade/";

    var check = debounce(function () {
      var modelId = modelField.value;
      var quantity = quantityField.value || "1";
      if (!modelId) {
        resultEl.hidden = true;
        return;
      }
      var url = checkUrl + "?equipment_model=" + encodeURIComponent(modelId) + "&quantity=" + encodeURIComponent(quantity);
      fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(function (response) {
          return response.json();
        })
        .then(function (data) {
          if (!data.ok) {
            resultEl.hidden = true;
            return;
          }
          resultEl.hidden = false;
          if (data.missing > 0) {
            resultEl.textContent = data.requested + " solicitados — " + data.available + " disponíveis — " + data.missing + " em falta.";
            resultEl.classList.add("text-red-600");
          } else {
            resultEl.textContent = data.requested + " solicitados — " + data.available + " disponíveis.";
            resultEl.classList.remove("text-red-600");
          }
        })
        .catch(function () {
          resultEl.hidden = true;
        });
    }, 250);

    modelField.addEventListener("change", check);
    quantityField.addEventListener("input", check);
  }

  /*
   * Tabela de Preços V1 (16/09/2026, seção 23) + RODADA 2 (13/10/2026) +
   * RODADA 2.1 (14/10/2026): ao escolher um Produto/Modelo OU um Serviço
   * (e, no form de adicionar, também ao mudar Plano/datas), consulta
   * `SuggestedPriceView` (só leitura, GET, AJAX) e preenche "Valor
   * unitário" — nunca trava o campo, o vendedor pode sempre digitar um
   * valor diferente por cima (seção 24).
   *
   * P0-04 / UX-001 (29/10/2026) — CORREÇÃO: a RODADA 2.1 passou a
   * sobrescrever `unit_price` incondicionalmente sempre que
   * `data-user-edited` estivesse ausente — o que incluía o valor
   * INICIAL renderizado pelo servidor para um item JÁ SALVO (nunca
   * passa por um evento `input` real) e, por causa de
   * `commercialPlanField`/`startDateField`/`endDateField` serem
   * buscados por `document` (não por `form`) e `initSuggestedPrice` ser
   * chamada uma vez por form (1 "adicionar" + 1 por modal de edição já
   * existente), uma única mudança de plano/data disparava N+1 consultas
   * e sobrescrevia em segundo plano o `unit_price` de TODOS os itens —
   * mesmo com o modal de edição deles fechado. Ver relatório de
   * investigação P0-04/UX-001 para a reprodução completa.
   *
   * Semântica corrigida (nunca mais um único booleano decide):
   *   - campo vazio                                → preenche direto.
   *   - valor atual == último valor que O PRÓPRIO
   *     script aplicou (`data-auto-price`)          → atualiza direto
   *                                                    (preserva o
   *                                                    ganho da RODADA
   *                                                    2.1: reconsulta
   *                                                    automática
   *                                                    enquanto nada
   *                                                    manual existir).
   *   - valor atual == sugestão de agora, mas sem
   *     `data-auto-price` (coincidência — ex.: valor
   *     inicial do servidor já bate com a sugestão)  → não pede
   *                                                    confirmação, mas
   *                                                    também NÃO passa
   *                                                    a ser
   *                                                    "automaticamente
   *                                                    gerenciado" só
   *                                                    por essa
   *                                                    coincidência (não
   *                                                    seta
   *                                                    `data-auto-price`
   *                                                    — uma sugestão
   *                                                    FUTURA diferente
   *                                                    ainda pede
   *                                                    confirmação).
   *   - qualquer outro valor (manual, ou inicial do
   *     servidor diferente da sugestão)              → preserva e
   *                                                    OFERECE o novo
   *                                                    preço (botão
   *                                                    dentro do próprio
   *                                                    `data-suggested-price-hint`,
   *                                                    sem modal novo);
   *                                                    só aplica se o
   *                                                    usuário clicar.
   *
   * `data-user-edited` continua sendo setado (compatibilidade com
   * qualquer outro código/teste que ainda o leia), mas DEIXOU de ser a
   * autoridade que decide se o campo pode ser sobrescrito.
   *
   * Correção do "N+1 listeners": o form de "Adicionar produto/serviço"
   * (único na página) continua reconsultando automaticamente ao mudar
   * Plano/datas. Cada modal de EDIÇÃO de item deixou de registrar um
   * listener próprio em Plano/datas — em vez disso, reconsulta só
   * quando aquele modal específico é efetivamente aberto, reaproveitando
   * o próprio botão `[data-open-modal]` que já abre o modal
   * (`opportunity_detail.js`) — nenhum sistema de modal novo ou
   * paralelo, só um listener adicional no mesmo botão — e quando o
   * Produto/Modelo/Serviço/Tipo DAQUELE próprio item muda (como já
   * acontecia).
   */
  function parseMoneyToCents(value) {
    if (value === null || value === undefined) {
      return null;
    }
    var text = String(value).trim();
    if (text === "") {
      return null;
    }
    // O backend (`str(Decimal)`) e o `<input type="number">` sempre
    // usam "." como separador decimal, nunca separador de milhar neste
    // campo — a normalização de "," é só uma proteção extra (P0-04,
    // seção "Comparação de valores"), nunca compara float diretamente.
    var asNumber = Number(text.replace(",", "."));
    if (!isFinite(asNumber)) {
      return null;
    }
    return Math.round(asNumber * 100);
  }

  function moneyEquals(a, b) {
    var centsA = parseMoneyToCents(a);
    var centsB = parseMoneyToCents(b);
    return centsA !== null && centsB !== null && centsA === centsB;
  }

  function initSuggestedPrice(form) {
    var modelField = form.querySelector('[name="equipment_model"]');
    var serviceField = form.querySelector('[name="service"]');
    var typeSelect = form.querySelector("[data-item-type-select]");
    var unitPriceField = form.querySelector('[name="unit_price"]');
    var hintEl = form.querySelector("[data-suggested-price-hint]");
    if (!unitPriceField || !hintEl || (!modelField && !serviceField)) {
      return;
    }

    // P0-04/UX-001: um modal de edição de item (`data-proposal-item-edit-form`)
    // sempre está dentro de um `.kanban-modal-backdrop`; o form de
    // "Adicionar produto/serviço" nunca está. Usamos isso só para saber
    // SE registramos o listener global de plano/data (só o form de
    // adicionar) ou o listener de abertura do modal (só os de edição) —
    // ver os dois ramos no final da função.
    var modalBackdrop = form.closest(".kanban-modal-backdrop");

    // RODADA 2 (13/10/2026): só existe UM form de "Condições comerciais"
    // na página (ver `templates/crm/_proposal_composition.html`) — a
    // busca é pelo `document`, nunca só dentro de `form`. Podem não
    // existir (ex.: Oportunidade sem `conditions_form` ainda) — tratado
    // como "sem plano/datas", nunca um erro.
    var commercialPlanField = document.querySelector('[name="commercial_plan"]');
    var startDateField = document.querySelector('[name="contracted_start_date"]');
    var endDateField = document.querySelector('[name="contracted_end_date"]');

    var requestSeq = 0;
    var pendingButton = null;

    function clearPendingSuggestion() {
      if (pendingButton && pendingButton.parentNode) {
        pendingButton.parentNode.removeChild(pendingButton);
      }
      pendingButton = null;
    }

    function offerSuggestedPrice(amountStr, message) {
      clearPendingSuggestion();
      hintEl.hidden = false;
      hintEl.textContent = message + " ";
      var button = document.createElement("button");
      button.type = "button";
      button.className = "btn-ghost btn-sm";
      button.textContent = "Aplicar preço sugerido";
      button.addEventListener("click", function () {
        unitPriceField.value = amountStr;
        unitPriceField.setAttribute("data-auto-price", amountStr);
        unitPriceField.removeAttribute("data-user-edited");
        hintEl.textContent = message;
        clearPendingSuggestion();
      });
      hintEl.appendChild(button);
      pendingButton = button;
    }

    function applyAutomatically(amountStr, message) {
      clearPendingSuggestion();
      unitPriceField.value = amountStr;
      unitPriceField.setAttribute("data-auto-price", amountStr);
      hintEl.hidden = false;
      hintEl.textContent = message;
    }

    unitPriceField.addEventListener("input", function () {
      unitPriceField.setAttribute("data-user-edited", "1");
      // P0-04/UX-001: uma oferta pendente ("Aplicar preço sugerido") se
      // refere ao valor que estava no campo quando ela foi exibida — se
      // o usuário digitou algo novo nesse meio tempo, a oferta não é
      // mais válida (garante só uma ação pendente por form, nunca uma
      // desatualizada).
      clearPendingSuggestion();
    });

    var opportunityMatch = window.location.pathname.match(/\/oportunidades\/(\d+)\//);
    if (!opportunityMatch) {
      return;
    }
    var suggestedPriceUrl = "/crm/oportunidades/" + opportunityMatch[1] + "/produtos-servicos/preco-sugerido/";

    var check = debounce(function () {
      var itemType = typeSelect ? typeSelect.value : "EQUIPAMENTO";
      var params = "";
      if (itemType === "SERVICO" && serviceField && serviceField.value) {
        params = "service=" + encodeURIComponent(serviceField.value);
      } else if (modelField && modelField.value) {
        params = "equipment_model=" + encodeURIComponent(modelField.value);
        // A matriz (plano+prazo) só existe para EQUIPAMENTO — o backend
        // é quem decide se vai usá-la ou não (nunca o JS: seção
        // "JavaScript não decide prazo/termo/rate"); aqui só repassamos
        // o que já está preenchido na tela, sem interpretar nada.
        if (commercialPlanField && commercialPlanField.value) {
          params += "&commercial_plan=" + encodeURIComponent(commercialPlanField.value);
        }
        if (startDateField && startDateField.value) {
          params += "&contracted_start_date=" + encodeURIComponent(startDateField.value);
        }
        if (endDateField && endDateField.value) {
          params += "&contracted_end_date=" + encodeURIComponent(endDateField.value);
        }
      } else {
        clearPendingSuggestion();
        hintEl.hidden = true;
        return;
      }

      // P0-04/UX-001: protege contra resposta HTTP antiga chegando
      // depois de uma consulta mais nova (ex.: usuário troca de modelo
      // A → B → C rapidamente) — um contador de requisição simples é
      // suficiente aqui, não precisamos cancelar a requisição em voo,
      // só ignorar uma resposta que não é mais a mais recente.
      var thisRequestId = ++requestSeq;

      fetch(suggestedPriceUrl + "?" + params, { headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(function (response) {
          return response.json();
        })
        .then(function (data) {
          if (thisRequestId !== requestSeq) {
            return;
          }
          if (!data.ok) {
            clearPendingSuggestion();
            hintEl.hidden = true;
            return;
          }
          if (!data.found) {
            clearPendingSuggestion();
            hintEl.hidden = false;
            hintEl.textContent = data.reason || "Sem valor sugerido na Tabela de Preços — informe manualmente.";
            return;
          }

          var amountStr = data.unit_price;
          var formatted = "R$ " + Number(amountStr).toFixed(2).replace(".", ",");
          var baseMessage;
          if (data.commercial_plan && data.commercial_term) {
            // Locação com matriz: mostra plano + prazo aplicado, nunca
            // só o valor cru — a origem do preço precisa ficar visível
            // (seção "exibir discretamente a origem do preço").
            baseMessage = "Preço sugerido: " + formatted + " — " + data.commercial_plan + " · prazo aplicado: " + data.commercial_term;
            if (data.billing_mode_display) {
              baseMessage += " (" + data.billing_mode_display + ")";
            }
          } else {
            baseMessage = "Preço sugerido (" + data.business_type_display + "): " + formatted;
          }

          // P0-04/UX-001 — decisão (ver semântica no comentário do topo
          // da função): nunca mais um único `data-user-edited` decide.
          var lastAuto = unitPriceField.hasAttribute("data-auto-price")
            ? unitPriceField.getAttribute("data-auto-price")
            : null;
          var currentValue = unitPriceField.value;

          if (currentValue === "" || (lastAuto !== null && moneyEquals(currentValue, lastAuto))) {
            applyAutomatically(amountStr, baseMessage);
            return;
          }

          if (lastAuto === null && moneyEquals(currentValue, amountStr)) {
            clearPendingSuggestion();
            hintEl.hidden = false;
            hintEl.textContent = baseMessage;
            return;
          }

          offerSuggestedPrice(amountStr, "Novo preço sugerido disponível — " + baseMessage);
        })
        .catch(function () {
          if (thisRequestId === requestSeq) {
            clearPendingSuggestion();
            hintEl.hidden = true;
          }
        });
    }, 250);

    if (modelField) {
      modelField.addEventListener("change", check);
    }
    if (serviceField) {
      serviceField.addEventListener("change", check);
    }
    if (typeSelect) {
      typeSelect.addEventListener("change", check);
    }

    if (!modalBackdrop) {
      // RODADA 2: mudar plano/período reconsulta automaticamente SE já
      // houver um Produto/Modelo escolhido (`check()` já sai sem
      // nenhum efeito quando não há). Nunca altera um `ProposalItem` já
      // salvo — isto só afeta o campo ainda em composição, antes do
      // POST. Só o form de "Adicionar produto/serviço" (único na
      // página) registra este listener global — ver P0-04/UX-001 no
      // comentário do topo da função sobre por que os modais de edição
      // NÃO podem fazer o mesmo.
      [commercialPlanField, startDateField, endDateField].forEach(function (field) {
        if (field) {
          field.addEventListener("change", check);
        }
      });
    } else if (modalBackdrop.id) {
      // P0-04/UX-001: form de edição de um item já existente — em vez
      // de reconsultar em segundo plano a cada mudança global de
      // plano/data, reconsulta só quando ESTE modal é aberto.
      // Reaproveita o próprio botão `[data-open-modal]` que já abre o
      // modal (ver `static/crm/opportunity_detail.js`); não substitui
      // nem duplica a lógica de abrir/fechar — só adiciona um segundo
      // listener, independente, no mesmo botão.
      var trigger = document.querySelector('[data-open-modal="' + modalBackdrop.id + '"]');
      if (trigger) {
        trigger.addEventListener("click", check);
      }
    }
  }

  /*
   * RODADA 4 (15/09/2026, seções 18-25): alterna qual grupo de campo
   * ("Produto/Modelo" vs. "Serviço") fica visível no form de adicionar
   * item, conforme o Tipo escolhido. Os dois campos continuam presentes
   * no HTML: sem JS (navegador antigo, JS desabilitado) ambos ficam
   * visíveis e habilitados e o form ainda funciona normalmente, pois o
   * `clean()` do backend é a autoridade real (seção 18). Quando o JS
   * roda, além de esconder o grupo não selecionado, desabilitamos seu
   * `<select>` para não enviar no POST um valor obsoleto do campo que o
   * usuário não está usando.
   */
  function initItemTypeToggle(form) {
    var typeSelect = form.querySelector("[data-item-type-select]");
    var groups = form.querySelectorAll("[data-item-type-group]");
    if (!typeSelect || !groups.length) {
      return;
    }

    function applyVisibility() {
      var selected = typeSelect.value;
      groups.forEach(function (group) {
        var matches = group.getAttribute("data-item-type-group") === selected;
        group.hidden = !matches;
        var field = group.querySelector("[data-item-type-field]");
        if (field) {
          field.disabled = !matches;
        }
      });
    }

    typeSelect.addEventListener("change", applyVisibility);
    applyVisibility();
  }

  // RODADA 2.1 (14/10/2026, "Edição de produto/serviço já inserido"):
  // além do form de "Adicionar produto/serviço" (`data-proposal-item-add-form`),
  // cada item já salvo agora tem seu PRÓPRIO `<form>` de edição dentro
  // de um modal (`data-proposal-item-edit-form`, um por item — mesmo
  // padrão dos modais "Remover item" já existentes). `initAvailabilityCheck`
  // e `initItemTypeToggle` escopam toda busca a `form.querySelector(...)`
  // (nunca ao `document`), então rodar as duas em cada form, inclusive
  // vários forms de edição na mesma página, é seguro sem nenhuma
  // mudança nelas. `initSuggestedPrice` É diferente (P0-04/UX-001): ela
  // mesma detecta, por form, se é o form de adicionar ou um modal de
  // edição, e decide internamente a quais eventos reagir — ver o
  // comentário no topo dessa função.
  document.addEventListener("DOMContentLoaded", function () {
    var forms = document.querySelectorAll("[data-proposal-item-add-form], [data-proposal-item-edit-form]");
    forms.forEach(function (form) {
      initAvailabilityCheck(form);
      initItemTypeToggle(form);
      initSuggestedPrice(form);
    });
  });
})();
