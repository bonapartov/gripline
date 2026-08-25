(function () {
    var TRIGGER_RE = /@([А-ЯЁа-яё\s-]{1,40})$/u;

    function escapeHtml(s) {
        return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function combinedResults(query) {
        return Promise.all([
            window.GriplineDriverSearch.loadDrivers(),
            window.GriplineTeamSearch.loadTeams(),
        ]).then(function (all) {
            var drivers = window.GriplineDriverSearch.filterDrivers(all[0], query).map(function (d) {
                return { type: 'driver', label: 'пилот', name: d.full_name, url: d.absolute_url };
            });
            var teams = window.GriplineTeamSearch.filterTeams(all[1], query).map(function (t) {
                return { type: 'team', label: 'команда', name: t.name, url: t.absolute_url };
            });
            return drivers.concat(teams).slice(0, 8);
        });
    }

    function attachMentionPopover(cm) {
        var popover = null;
        var latestQuery = null;

        function closePopover() {
            if (popover) { popover.remove(); popover = null; }
        }

        function insertResult(result, fromCh, toCh, line) {
            var link = '<a href="' + result.url + '" target="_blank" rel="noopener">' + escapeHtml(result.name) + '</a>';
            cm.replaceRange(link, { line: line, ch: fromCh }, { line: line, ch: toCh });
            closePopover();
        }

        function renderPopover(matchText, from, to, line) {
            closePopover();
            latestQuery = matchText;
            combinedResults(matchText).then(function (results) {
                // Запрос устарел — за время ожидания пользователь напечатал ещё
                // символы, и renderPopover уже вызвался заново с новым matchText.
                if (matchText !== latestQuery) return;
                if (!results.length) return;
                var coords = cm.cursorCoords(true, 'page');
                popover = document.createElement('div');
                popover.className = 'mention-source mention-source--markdown';
                popover.style.left = coords.left + 'px';
                popover.style.top = coords.bottom + 'px';

                var list = document.createElement('ul');
                list.className = 'mention-source__results';
                results.forEach(function (result) {
                    var li = document.createElement('li');
                    var item = document.createElement('button');
                    item.type = 'button';
                    item.className = 'mention-source__result';
                    var badge = document.createElement('span');
                    badge.className = 'mention-source__result-badge';
                    badge.textContent = result.label;
                    item.appendChild(badge);
                    item.appendChild(document.createTextNode(result.name));
                    item.addEventListener('mousedown', function (e) {
                        e.preventDefault(); // не терять фокус/выделение CodeMirror
                        insertResult(result, from, to, line);
                    });
                    li.appendChild(item);
                    list.appendChild(li);
                });
                popover.appendChild(list);
                document.body.appendChild(popover);
            });
        }

        cm.on('cursorActivity', function () {
            var cursor = cm.getCursor();
            var lineText = cm.getLine(cursor.line).slice(0, cursor.ch);
            var match = TRIGGER_RE.exec(lineText);
            if (match) {
                // from — начало всего совпадения (включая "@"), чтобы вставка
                // результата заменяла и триггер-символ, а не только имя после него.
                renderPopover(match[1], cursor.ch - match[0].length, cursor.ch, cursor.line);
            } else {
                closePopover();
            }
        });
        cm.on('blur', function () { setTimeout(closePopover, 150); });
    }

    var originalAttach = window.easymdeAttach;
    if (typeof originalAttach !== 'function') return;

    window.easymdeAttach = function (id, autoDownload) {
        originalAttach(id, autoDownload);
        var textarea = document.getElementById(id);
        var cm = textarea && textarea.codemirror;
        if (cm) attachMentionPopover(cm);
    };
})();
