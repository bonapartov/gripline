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

    // ---------- Радар «Профиль результатов» (перцентили внутри класса) ----------
    function initRadarChart() {
        var canvas = document.getElementById('glv2RadarChart');
        if (!canvas || typeof Chart === 'undefined') { return; }
        var labels = ['Старты', 'Победы', 'Подиумы', 'Поулы', 'Рейтинг'];
        var values = [
            parseFloat(canvas.getAttribute('data-starts-pct')),
            parseFloat(canvas.getAttribute('data-wins-pct')),
            parseFloat(canvas.getAttribute('data-podiums-pct')),
            parseFloat(canvas.getAttribute('data-poles-pct')),
            parseFloat(canvas.getAttribute('data-rating-pct')),
        ];
        new Chart(canvas.getContext('2d'), {
            type: 'radar',
            data: {
                labels: labels,
                datasets: [{
                    data: values,
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
                    tooltip: { callbacks: { label: function (ctx) { return ctx.parsed.r + '%'; } } },
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
                            callback: function (label, index) { return [label, values[index] + '%']; },
                        },
                        ticks: { display: false, stepSize: 25 },
                    }
                }
            }
        });
    }

    // ---------- Динамика рейтинга по классам ----------
    function normPos(pos, total) { return total > 1 ? (total - pos) / (total - 1) * 100 : 50; }

    function initRatingCharts() {
        if (typeof Chart === 'undefined') { return; }
        document.querySelectorAll('.glv2-rating-canvas').forEach(function (canvas) {
            var classId = Number(canvas.getAttribute('data-class-id'));
            var rows = historyData.filter(function (r) { return r.class_id === classId; }).slice().reverse();
            if (!rows.length) { return; }
            new Chart(canvas.getContext('2d'), {
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
                    layout: { padding: { top: 16 } },
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: function (ctx) {
                            var r = rows[ctx.dataIndex];
                            return r.status ? [r.status_label, r.competition_name] : ['Место: ' + r.position, r.competition_name];
                        } } }
                    },
                    scales: {
                        y: { min: 0, max: 100, grid: { color: 'rgba(255,255,255,0.1)' }, ticks: { color: '#adb5bd', callback: function (v) { return v + '%'; } } },
                        x: { grid: { display: false }, ticks: { color: '#adb5bd', maxRotation: 45, minRotation: 45 } }
                    }
                }
            });
        });
    }

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
