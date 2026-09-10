/*
 * Модалка «Войти или зарегистрироваться» по клику на заблокированную
 * вкладку «Мои сетапы» (/balance/, app_base.html — общая для всех страниц
 * /balance/). Ведёт на уже существующую страницу выбора роли/входа
 * (choose_role), не на прямой Яндекс-OAuth в обход нее.
 */
(function () {
  "use strict";

  var trigger = document.getElementById("glBalanceSetupsLockedTab");
  var modal = document.getElementById("glBalanceAuthModal");
  if (!trigger || !modal) return;

  var closeBtn = document.getElementById("glBalanceAuthModalClose");
  var backdrop = document.getElementById("glBalanceAuthModalBackdrop");

  function open() {
    modal.hidden = false;
  }

  function close() {
    modal.hidden = true;
  }

  trigger.addEventListener("click", open);
  if (closeBtn) closeBtn.addEventListener("click", close);
  if (backdrop) backdrop.addEventListener("click", close);
  document.addEventListener("keydown", function (evt) {
    if (evt.key === "Escape") close();
  });
})();
