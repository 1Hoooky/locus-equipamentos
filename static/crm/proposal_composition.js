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
   * Tabela de Preços V1 (16/09/2026, seção 23): ao escolher um
   * Produto/Modelo OU um Serviço no form de adicionar/editar item,
   * consulta `SuggestedPriceView` (só leitura, GET, AJAX — mesmo padrão
   * de `initAvailabilityCheck` acima) e PREENCHE "Valor unitário". Um
   * "toque" real do usuário no campo (evento `input`, nunca disparado
   * por atribuição via JS) marca `data-user-edited`, e a partir daí a
   * sugestão nunca mais sobrescreve o campo automaticamente — só
   * atualiza o texto informativo ao lado (seção 24: "não travar
   * unit_price... o vendedor pode negociar valor diferente").
   *
   * RODADA 2.1 (14/10/2026, "Automatizar o preenchimento do preço da
   * tabela"): deixou de preencher só quando o campo está vazio — agora
   * SEMPRE atualiza `unit_price` enquanto não houver `data-user-edited`
   * (seção 3: "se o usuário alterar Produto/Modelo, Plano ou datas, e
   * ainda não tiver editado manualmente, atualizar automaticamente com
   * o novo valor"). No form de EDIÇÃO de um item já salvo, isso também
   * cobre a seção 12 ("trocar o equipamento/plano/data durante a edição
   * PODE buscar nova referência de tabela") sem nenhum código extra: o
   * valor pré-preenchido com o preço ATUAL do item nunca é tocado até o
   * usuário mudar algo que dispare uma nova consulta (nenhum `check()`
   * roda sozinho ao abrir o modal — só em `change`, ver listeners mais
   * abaixo), e só então passa a refletir a nova sugestão — exatamente
   * como já acontecia na composição de um item novo.
   */
  function initSuggestedPrice(form) {
    var modelField = form.querySelector('[name="equipment_model"]');
    var serviceField = form.querySelector('[name="service"]');
    var typeSelect = form.querySelector("[data-item-type-select]");
    var unitPriceField = form.querySelector('[name="unit_price"]');
    var hintEl = form.querySelector("[data-suggested-price-hint]");
    if (!unitPriceField || !hintEl || (!modelField && !serviceField)) {
      return;
    }

    // RODADA 2 (13/10/2026): "Condições comerciais" (plano + período) e
    // "Adicionar produto/serviço" são dois `<form>` DISTINTOS na MESMA
    // página (ver `templates/crm/_proposal_composition.html`) — por
    // isso a busca é pelo `document`, nunca só dentro de `form`. Podem
    // não existir (ex.: Oportunidade sem `conditions_form` ainda) —
    // tratado como "sem plano/datas", nunca um erro.
    var commercialPlanField = document.querySelector('[name="commercial_plan"]');
    var startDateField = document.querySelector('[name="contracted_start_date"]');
    var endDateField = document.querySelector('[name="contracted_end_date"]');

    unitPriceField.addEventListener("input", function () {
      unitPriceField.setAttribute("data-user-edited", "1");
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
        hintEl.hidden = true;
        return;
      }

      fetch(suggestedPriceUrl + "?" + params, { headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(function (response) {
          return response.json();
        })
        .then(function (data) {
          if (!data.ok) {
            hintEl.hidden = true;
            return;
          }
          if (!data.found) {
            hintEl.hidden = false;
            hintEl.textContent = data.reason || "Sem valor sugerido na Tabela de Preços — informe manualmente.";
            return;
          }
          var formatted = "R$ " + Number(data.unit_price).toFixed(2).replace(".", ",");
          hintEl.hidden = false;
          if (data.commercial_plan && data.commercial_term) {
            // Locação com matriz: mostra plano + prazo aplicado, nunca
            // só o valor cru — a origem do preço precisa ficar visível
            // (seção "exibir discretamente a origem do preço").
            hintEl.textContent =
              "Preço sugerido: " + formatted + " — " + data.commercial_plan + " · prazo aplicado: " + data.commercial_term;
            if (data.billing_mode_display) {
              hintEl.textContent += " (" + data.billing_mode_display + ")";
            }
          } else {
            hintEl.textContent = "Preço sugerido (" + data.business_type_display + "): " + formatted;
          }
          if (!unitPriceField.getAttribute("data-user-edited")) {
            unitPriceField.value = data.unit_price;
          }
        })
        .catch(function () {
          hintEl.hidden = true;
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
    // RODADA 2: mudar plano/período reconsulta automaticamente SE já
    // houver um Produto/Modelo escolhido (`check()` já sai sem
    // nenhum efeito quando não há — seção "alteração de plano ou
    // período"). Nunca altera um `ProposalItem` já salvo — isto só
    // afeta o campo ainda em composição, antes do POST.
    [commercialPlanField, startDateField, endDateField].forEach(function (field) {
      if (field) {
        field.addEventListener("change", check);
      }
    });
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
  // padrão dos modais "Remover item" já existentes). As três funções já
  // escopam toda busca a `form.querySelector(...)` (nunca ao
  // `document`), então rodar as três em cada form, inclusive vários
  // forms de edição na mesma página, é seguro sem nenhuma mudança nelas.
  document.addEventListener("DOMContentLoaded", function () {
    var forms = document.querySelectorAll("[data-proposal-item-add-form], [data-proposal-item-edit-form]");
    forms.forEach(function (form) {
      initAvailabilityCheck(form);
      initItemTypeToggle(form);
      initSuggestedPrice(form);
    });
  });
})();
