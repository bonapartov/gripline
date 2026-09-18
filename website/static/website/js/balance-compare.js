/*
 * Пикер на странице сравнения сетапов (/balance/compare/, Блок 7 ТЗ §8.1).
 * Прогрессивное улучшение поверх обычной GET-формы (два <select> + кнопка
 * "Сравнить" уже работают без JS) — как только заполнены обе стороны,
 * форма отправляется сама, без ожидания клика по кнопке.
 */
(function () {
  "use strict";

  var selectA = document.getElementById("glCompareSelectA");
  var selectB = document.getElementById("glCompareSelectB");
  if (!selectA || !selectB) return; // не на странице сравнения / пустой picker

  function maybeSubmit() {
    if (selectA.value && selectB.value) selectA.form.submit();
  }

  selectA.addEventListener("change", maybeSubmit);
  selectB.addEventListener("change", maybeSubmit);
})();
