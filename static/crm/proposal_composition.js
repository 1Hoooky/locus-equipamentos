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

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.querySelector("[data-proposal-item-add-form]");
    if (form) {
      initAvailabilityCheck(form);
      initItemTypeToggle(form);
    }
  });
})();
