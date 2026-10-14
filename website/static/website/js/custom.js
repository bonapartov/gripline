/* Общие улучшения форм сайта (подключён в templates/coderedcms/pages/base.html). */
(function () {
    'use strict';
    var DATE_TYPES = ['date', 'datetime-local', 'time', 'month', 'week'];

    // Календарь открывается кликом в любом месте поля, а не только по иконке
    // (иконку скрывает custom.css). Нативный календарь браузера: на телефоне — системный.
    document.addEventListener('click', function (e) {
        var el = e.target;
        if (el.tagName !== 'INPUT' || DATE_TYPES.indexOf(el.type) === -1) return;
        if (el.readOnly || el.disabled || typeof el.showPicker !== 'function') return;
        try { el.showPicker(); } catch (err) { /* не во всех браузерах без жеста пользователя */ }
    });

    // Формы с data-validate: при отправке подсвечиваем ВСЕ незаполненные обязательные поля
    // (браузер сам показывает только первое), обводка снимается, как только поле исправлено.
    function fieldOf(el) { return el.type === 'radio' ? null : el; }
    function markInvalid(form) {
        var first = null;
        Array.prototype.forEach.call(form.elements, function (el) {
            if (!el.willValidate || el.disabled) return;
            var bad = !el.checkValidity();
            var target = fieldOf(el);
            if (target) target.classList.toggle('is-invalid', bad);
            if (bad && !first) first = el;
        });
        return first;
    }
    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form.hasAttribute || !form.hasAttribute('data-validate')) return;
        var first = markInvalid(form);
        if (first) {
            e.preventDefault();
            first.scrollIntoView({ behavior: 'smooth', block: 'center' });
            setTimeout(function () { first.focus({ preventScroll: true }); }, 300);
        }
    }, true);
    function clearIfValid(e) {
        var el = e.target;
        if (el.classList && el.classList.contains('is-invalid') && el.checkValidity()) {
            el.classList.remove('is-invalid');
        }
    }
    document.addEventListener('input', clearIfValid);
    document.addEventListener('change', clearIfValid);
})();
