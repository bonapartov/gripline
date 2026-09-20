/*
 * Страница пилота (/drivers/<slug>/). Чисто статический файл — без Django-тегов
 * внутри (иначе он не был бы валидным JS для {% static %}). Данные читаются
 * из data-* атрибутов, проставленных шаблоном на элементах, и из уже
 * существующего JSON-блока истории (driverHistoryData).
 */
document.addEventListener('DOMContentLoaded', function () {
    // ---------- Вкладки — якорные ссылки на секции одной страницы (не
    // JS-переключаемые панели), скролл — нативный + html{scroll-behavior:smooth}
    // из driver_page.css. Здесь только подсветка активного пункта по скроллу
    // (scroll-spy) и клик по "Открыть в истории →" (нужен JS, чтобы заодно
    // выставить фильтр по классу перед переходом). ----------
    var tabs = document.querySelectorAll('.glv2-tab');
    var panels = document.querySelectorAll('.glv2-tab-panel');

    if (panels.length && typeof IntersectionObserver !== 'undefined') {
        var spy = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) { return; }
                var name = entry.target.getAttribute('data-tab-panel');
                tabs.forEach(function (t) { t.classList.toggle('active', t.getAttribute('data-tab') === name); });
            });
        }, { rootMargin: '-40% 0px -55% 0px' });
        panels.forEach(function (p) { spy.observe(p); });
    }

    // ---------- Тумблер «Карьера / Класс» — плитки-счётчики + радар ----------
    // Обе версии каждой плитки уже отрендерены сервером (data-scope="career"/
    // "class") — тумблер переключает их видимость через CSS-атрибут на общей
    // обёртке (охватывает и колонку с радаром, и колонку с плитками), без
    // JS-форматирования чисел (в т.ч. без проблемы с запятой в ru-локали,
    // см. комментарий у radar_class_js/radar_career_js в views.py). Радар —
    // отдельный случай (canvas не размножить через CSS-видимость, как div'ы
    // плиток), для него applyRadarMode() ниже перерисовывает Chart.js.
    var statTiles = document.getElementById('glv2StatTiles');
    document.querySelectorAll('.glv2-scope-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (btn.disabled || !statTiles) { return; }
            var mode = btn.getAttribute('data-scope-btn');
            statTiles.setAttribute('data-scope-mode', mode);
            document.querySelectorAll('.glv2-scope-btn').forEach(function (b) { b.classList.remove('active'); });
            btn.classList.add('active');
            applyRadarMode(mode);
        });
    });

    document.querySelectorAll('.glv2-open-history').forEach(function (el) {
        el.addEventListener('click', function () {
            var classId = el.getAttribute('data-class-id');
            if (classId) {
                var sel = document.getElementById('glv2FilterClass');
                if (sel) { sel.value = classId; applyFilters(); }
            }
            // href="#glv2-history" уже есть на элементе — переход браузер
            // делает сам, preventDefault не нужен.
        });
    });

    // ---------- Радар «Профиль результатов» (переключается тем же тумблером,
    // что и плитки-счётчики — см. обработчик выше) ----------
    var radarChart = null;
    var radarModes = null;
    var radarCurrent = null;

    function initRadarChart() {
        var canvas = document.getElementById('glv2RadarChart');
        if (!canvas || typeof Chart === 'undefined') { return; }

        // Пятая ось — "Рейтинг" в режиме "класс" (BT-балл, нет карьерного
        // эквивалента — нет кросс-классовой модели) и "Финишей" в режиме
        // "карьера" (тот же принцип "больше — лучше", что и у остальных
        // осей, в отличие от DNF). Форма радара всегда 5-точечная — меняются
        // только данные и подпись пятой оси.
        function readMode(prefix, fifthLabel) {
            return {
                labels: ['Старты', 'Победы', 'Подиумы', 'Поулы', fifthLabel],
                values: [
                    parseFloat(canvas.getAttribute('data-' + prefix + '-starts-pct')),
                    parseFloat(canvas.getAttribute('data-' + prefix + '-wins-pct')),
                    parseFloat(canvas.getAttribute('data-' + prefix + '-podiums-pct')),
                    parseFloat(canvas.getAttribute('data-' + prefix + '-poles-pct')),
                    parseFloat(canvas.getAttribute('data-' + prefix + '-rating-pct')),
                ],
                // Сырое значение рядом с процентом на каждой оси — без него
                // "Победы 100%" выглядит как баг, а не как "больше побед, чем
                // у всех остальных" (нашли на живом примере: 7 побед — максимум
                // среди пилотов класса).
                raw: [
                    canvas.getAttribute('data-' + prefix + '-starts-raw'),
                    canvas.getAttribute('data-' + prefix + '-wins-raw'),
                    canvas.getAttribute('data-' + prefix + '-podiums-raw'),
                    canvas.getAttribute('data-' + prefix + '-poles-raw'),
                    canvas.getAttribute('data-' + prefix + '-rating-raw'),
                ],
            };
        }
        radarModes = { class: readMode('class', 'Рейтинг'), career: readMode('career', 'Финишей') };
        radarCurrent = radarModes[canvas.getAttribute('data-default-scope') === 'career' ? 'career' : 'class'];

        radarChart = new Chart(canvas.getContext('2d'), {
            type: 'radar',
            data: {
                labels: radarCurrent.labels,
                datasets: [{
                    data: radarCurrent.values,
                    backgroundColor: 'rgba(255, 193, 7, 0.28)',
                    borderColor: '#ffc107',
                    borderWidth: 2,
                    pointBackgroundColor: '#ffc107',
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    // radarCurrent читается по ссылке на момент отрисовки/наведения,
                    // не копируется при создании графика — applyRadarMode() ниже
                    // переприсваивает эту же переменную при переключении тумблера.
                    tooltip: { callbacks: { label: function (ctx) { return radarCurrent.raw[ctx.dataIndex] + ' · ' + ctx.parsed.r + '%'; } } },
                },
                scales: {
                    r: {
                        min: 0, max: 100,
                        grid: { color: 'rgba(255,255,255,0.1)' },
                        angleLines: { color: 'rgba(255,255,255,0.1)' },
                        // Проценты показаны сразу под подписью оси, не по наведению —
                        // Chart.js поддерживает многострочный pointLabels через массив.
                        pointLabels: {
                            color: '#b0bec5',
                            font: { size: 11 },
                            callback: function (label, index) { return [label, radarCurrent.raw[index] + ' · ' + radarCurrent.values[index] + '%']; },
                        },
                        ticks: { display: false, stepSize: 25 },
                    }
                }
            }
        });
    }

    function applyRadarMode(mode) {
        if (!radarChart || !radarModes || !radarModes[mode]) { return; }
        radarCurrent = radarModes[mode];
        radarChart.data.labels = radarCurrent.labels;
        radarChart.data.datasets[0].data = radarCurrent.values;
        radarChart.update();
    }

    // ---------- Динамика рейтинга по классам ----------
    // Карточки классов объединены под одним выпадающим списком (см. обработчик
    // #glv2ClassRatingSelect ниже) — видна только одна, остальные display:none.
    // Графики создаются ЛЕНИВО, по одному, при первом показе карточки: Chart.js
    // не умеет посчитать размеры канваса, который в момент создания скрыт
    // (display:none даёт 0x0) — график на нём остался бы пустым/неправильно
    // отмасштабированным даже после того, как карточку потом покажут.
    var ratingCharts = {};
    function normPos(pos, total) { return total > 1 ? (total - pos) / (total - 1) * 100 : 50; }

    function initOneRatingChart(canvas) {
        if (typeof Chart === 'undefined' || !canvas) { return; }
        var classId = Number(canvas.getAttribute('data-class-id'));
        if (ratingCharts[classId]) { return; }
        var rows = historyData.filter(function (r) { return r.class_id === classId; }).slice().reverse();
        if (!rows.length) { return; }
        ratingCharts[classId] = new Chart(canvas.getContext('2d'), {
                type: 'line',
                data: {
                    labels: rows.map(function (r) { return r.date ? r.date.slice(0, 7).split('-').reverse().join('.') : ''; }),
                    datasets: [{
                        label: 'Результат',
                        data: rows.map(function (r) { return r.status ? 0 : normPos(r.position, r.group_size); }),
                        borderColor: '#0dcaf0',
                        backgroundColor: 'rgba(13, 202, 240, 0.1)',
                        tension: 0.3,
                        fill: true,
                        pointBackgroundColor: rows.map(function (r) {
                            return r.position === 1 ? '#ffc107' : r.position === 2 ? '#adb5bd' : r.position === 3 ? '#cd7f32' : '#0dcaf0';
                        }),
                        pointBorderColor: '#fff',
                        pointRadius: 5,
                        pointHoverRadius: 7,
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    // Точка на 100% (1-е место) рисуется ровно на границе области
                    // графика (chartArea) — Chart.js по умолчанию клипует отрисовку
                    // ИМЕННО по этой границе, а не по краю канваса, поэтому одного
                    // layout.padding.top было недостаточно: он резервирует пустое
                    // место на канвасе, но точка всё равно обрезалась clip-маской
                    // ровно по центру (проверено попиксельно через getImageData —
                    // выше центра точки прозрачные пиксели). clip:false отключает
                    // это клипование, padding.top оставлен — теперь именно он даёт
                    // точке место для отрисовки внутри канваса.
                    clip: false,
                    layout: { padding: { top: 28 } },
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: function (ctx) {
                            var r = rows[ctx.dataIndex];
                            return r.status ? [r.status_label, r.competition_name] : ['Место: ' + r.position, r.competition_name];
                        } } }
                    },
                    scales: {
                        // Голые проценты на оси ("40%", "60%"...) сами по себе не
                        // объясняют, что это нормализованное место в заезде — точное
                        // место уже показано в тултипе при наведении. Подписываем
                        // только края шкалы словами, промежуточные деления оставляем
                        // без текста (сетка видна, текста нет).
                        y: {
                            min: 0, max: 100, grid: { color: 'rgba(255,255,255,0.1)' },
                            ticks: {
                                color: '#adb5bd', stepSize: 25,
                                callback: function (v) {
                                    if (v === 0) { return 'Худший результат'; }
                                    if (v === 100) { return 'Лучший результат'; }
                                    return '';
                                },
                            },
                        },
                        x: { grid: { display: false }, ticks: { color: '#adb5bd', maxRotation: 45, minRotation: 45 } }
                    }
                }
            });
    }

    function initRatingCharts() {
        // На загрузке страницы график нужен только видимой по умолчанию
        // карточке (первая в DOM — самый свежий класс, см. сортировку
        // class_ratings в views.py). Остальные — по выбору в списке ниже.
        initOneRatingChart(document.querySelector('.glv2-rating-canvas'));
    }

    // Список выбора класса дублирован внутри КАЖДОЙ карточки (лежит в её же
    // строке заголовка, рядом с названием класса) — виден только у той
    // карточки, что сейчас показана, остальные скрыты вместе с card целиком.
    // Поэтому слушаем через делегирование на document, а не по одному id.
    document.addEventListener('change', function (e) {
        if (!e.target.classList || !e.target.classList.contains('glv2-class-rating-select')) { return; }
        var id = e.target.value;
        document.querySelectorAll('.glv2-rating-card[data-class-rating-id]').forEach(function (card) {
            card.style.display = card.getAttribute('data-class-rating-id') === id ? '' : 'none';
        });
        initOneRatingChart(document.querySelector('.glv2-rating-card[data-class-rating-id="' + id + '"] .glv2-rating-canvas'));
    });

    // ---------- История: данные ----------
    var historyDataEl = document.getElementById('driverHistoryData');
    var historyData = historyDataEl ? JSON.parse(historyDataEl.textContent) : [];
    var filtered = historyData.slice();
    var expanded = false;
    var COLLAPSED_SIZE = 8;

    function formatLap(ms) {
        if (!ms) { return null; }
        var minutes = Math.floor(ms / 60000);
        var seconds = (ms % 60000) / 1000;
        return minutes + ':' + seconds.toFixed(3).padStart(6, '0');
    }

    var SESSION_BADGE = {
        qual: '<span class="badge bg-primary text-white" style="font-size:10px;width:45px;" title="Квалификация">К</span>',
        pre_final: '<span class="badge bg-warning text-dark" style="font-size:10px;width:45px;" title="Предфинал">Пф</span>',
        final: '<span class="badge bg-success" style="font-size:10px;width:45px;" title="Финал">Ф</span>'
    };

    function positionBadge(row) {
        if (row.status) {
            return '<span class="badge bg-secondary" style="width:45px;background:#3a1a1a !important;color:#ff6b6b;" title="' + row.status_label + '">' + row.status_label + '</span>';
        }
        var cls = 'bg-secondary';
        if (row.position === 1) { cls = 'bg-warning text-dark'; }
        else if (row.position === 2) { cls = 'bg-light text-dark'; }
        else if (row.position === 3) { cls = 'bg-bronze'; }
        return '<span class="badge ' + cls + '" style="width:45px;">' + row.position + '</span>';
    }

    function sessionBadges(row) {
        var html = '';
        if (row.qual_position) { html += '<span class="badge bg-primary text-white" style="font-size:10px; width:45px;" title="Квалификация: #' + row.qual_position + '">К</span>'; }
        if (row.pre_final_position) { html += '<span class="badge bg-warning text-dark" style="font-size:10px; width:45px;" title="Предфинал: #' + row.pre_final_position + '">Пф</span>'; }
        if (row.position) { html += '<span class="badge bg-success" style="font-size:10px; width:45px;" title="Финал: #' + row.position + '">Ф</span>'; }
        return html;
    }

    function dynamicsCell(row) {
        if (row.status) { return '<span class="text-muted">—</span>'; }
        if (row.start_position != null && row.position != null) {
            var arrow = '<span class="text-secondary">—</span>';
            if (row.position_gain > 0) { arrow = '<span class="text-success fw-bold">▲' + row.position_gain + '</span>'; }
            else if (row.position_gain < 0) { arrow = '<span class="text-danger fw-bold">▼' + Math.abs(row.position_gain) + '</span>'; }
            return '<span class="text-muted font-monospace">' + row.start_position + '→' + row.position + '</span> ' + arrow +
                ' <span class="badge bg-success" style="font-size:10px; width:45px;" title="Финал">Ф</span>';
        }
        if (row.pre_final_start_pos != null && row.pre_final_position != null) {
            var gain = row.pre_final_start_pos - row.pre_final_position;
            var pfArrow = '<span class="text-secondary">—</span>';
            if (gain > 0) { pfArrow = '<span class="text-success fw-bold">▲' + gain + '</span>'; }
            else if (gain < 0) { pfArrow = '<span class="text-danger fw-bold">▼' + Math.abs(gain) + '</span>'; }
            return '<span class="text-muted font-monospace">' + row.pre_final_start_pos + '→' + row.pre_final_position + '</span> ' + pfArrow +
                ' <span class="badge bg-warning text-dark" style="font-size:10px; width:45px;" title="Предфинал">Пф</span>';
        }
        return '<span class="text-muted">—</span>';
    }

    function lapCell(row) {
        if (!row.best_lap_ms) { return '—'; }
        return '<div class="d-flex align-items-center justify-content-center gap-1">' +
            '<span class="font-monospace">' + formatLap(row.best_lap_ms) + '</span>' +
            '<span class="flex-shrink-0">' + (SESSION_BADGE[row.best_lap_session] || '') + '</span>' +
            '</div>';
    }

    function raceChipButton(row) {
        if (!row.has_lap_chart || !row.race_number) { return ''; }
        return '<button type="button" class="gl-lapchart-trigger-dynamic btn btn-sm btn-outline-info py-0 px-2" ' +
            'data-group-id="' + row.group_id + '" data-race-number="' + row.race_number + '" aria-label="Ход гонки">' +
            '<i class="fas fa-play"></i></button>';
    }

    function renderTable() {
        var body = document.getElementById('glv2HistoryBody');
        if (!body) { return; }
        var rows = expanded ? filtered : filtered.slice(0, COLLAPSED_SIZE);

        if (!rows.length) {
            body.innerHTML = '<tr><td colspan="10" class="text-center p-5 text-muted">Данные о заездах отсутствуют</td></tr>';
        } else {
            body.innerHTML = rows.map(function (row) {
                var dnfIcon = row.status ? '<i class="fas fa-triangle-exclamation text-danger me-1" style="font-size:0.87rem;" title="Не финишировал"></i>' : '';
                return '<tr>' +
                    '<td class="align-middle text-center">' + positionBadge(row) + '</td>' +
                    '<td class="align-middle text-muted small font-monospace">' + row.date_display + '</td>' +
                    '<td class="align-middle text-center fw-bold text-info">' + (row.race_number || '—') + '</td>' +
                    '<td class="align-middle"><a href="' + row.competition_url + '" class="text-white text-decoration-none d-flex align-items-center flex-wrap gap-1">' + dnfIcon +
                        '<span class="fw-bold text-nowrap">' + row.competition_name + '</span>' +
                        '<span class="mx-1 text-secondary opacity-50">|</span>' +
                        '<span class="small text-info text-uppercase text-nowrap">' + row.class_name + '</span>' +
                        sessionBadges(row) + '</a></td>' +
                    '<td class="align-middle text-muted small">' + (row.chassis_url ? '<a href="' + row.chassis_url + '" class="text-muted text-decoration-none">' + row.chassis_name + '</a>' : (row.chassis_name || '—')) + '</td>' +
                    '<td class="align-middle text-center">' + raceChipButton(row) + '</td>' +
                    '<td class="align-middle">' + (row.team_url ? '<a href="' + row.team_url + '" class="text-warning text-decoration-none">' + row.team_name + '</a>' : '<span class="text-muted fst-italic small">Личный зачёт</span>') + '</td>' +
                    '<td class="align-middle text-center small">' + dynamicsCell(row) + '</td>' +
                    '<td class="align-middle text-center text-muted small">' + lapCell(row) + '</td>' +
                    '<td class="align-middle text-end fw-bold text-warning">' + Math.round(row.points) + '</td>' +
                    '</tr>';
            }).join('');
        }

        document.getElementById('glv2HistoryCount').textContent = 'Найдено: ' + filtered.length;
        var moreBtn = document.getElementById('glv2HistoryMoreBtn');
        if (moreBtn) {
            var remaining = filtered.length - COLLAPSED_SIZE;
            var showBtn = !expanded && remaining > 0;
            // Снять фокус ДО скрытия: display:none на всё ещё сфокусированной
            // (только что нажатой) кнопке заставляет браузер сам решать, куда
            // переносить фокус — на практике это подбрасывало скролл к началу
            // страницы вместо того, чтобы остаться на месте разворота таблицы.
            if (!showBtn && document.activeElement === moreBtn) { moreBtn.blur(); }
            moreBtn.style.display = showBtn ? '' : 'none';
            moreBtn.hidden = !showBtn;
            if (showBtn) { moreBtn.textContent = 'Показать ещё (' + remaining + ')'; }
        }
    }

    function applyFilters() {
        var seasonEl = document.getElementById('glv2FilterSeason');
        var classEl = document.getElementById('glv2FilterClass');
        var season = seasonEl ? seasonEl.value : '';
        var classId = classEl ? classEl.value : '';
        filtered = historyData.filter(function (row) {
            if (season && String(row.season) !== season) { return false; }
            if (classId && String(row.class_id) !== classId) { return false; }
            return true;
        });
        expanded = false;
        renderTable();
    }

    var seasonFilter = document.getElementById('glv2FilterSeason');
    var classFilter = document.getElementById('glv2FilterClass');
    if (seasonFilter) { seasonFilter.addEventListener('change', applyFilters); }
    if (classFilter) { classFilter.addEventListener('change', applyFilters); }
    var moreBtnEl = document.getElementById('glv2HistoryMoreBtn');
    if (moreBtnEl) { moreBtnEl.addEventListener('click', function () { expanded = true; renderTable(); }); }

    function renderHistory() { applyFilters(); }

    // ---------- Share ----------
    var shareBtn = document.getElementById('glv2ShareBtn');
    if (shareBtn) {
        shareBtn.addEventListener('click', function () {
            var name = shareBtn.getAttribute('data-driver-name') || document.title;
            if (navigator.share) {
                navigator.share({ title: name, url: window.location.href }).catch(function () {});
            } else if (navigator.clipboard) {
                navigator.clipboard.writeText(window.location.href);
            }
        });
    }

    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
        if (typeof bootstrap !== 'undefined') { new bootstrap.Tooltip(el); }
    });

    // Все секции видимы сразу (не скрытые табы) — графики и таблица истории
    // инициализируются один раз на загрузке страницы, без привязки к вкладкам.
    initRadarChart();
    initRatingCharts();
    renderHistory();
});
