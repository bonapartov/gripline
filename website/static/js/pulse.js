// static/js/pulse.js

class PulseApp {
    constructor() {
        this.year = null;
        this.activeTypes = new Set();
        this.activeClasses = new Set();
        this.activeTrack = null;
        this.data = null;
        this.ymaps = null;
        this.map = null;

        this.CLASS_ORDER = [
            'Rotax Max Micro', 'Rotax Max Mini', 'Rotax Max Junior',
            'Rotax Max Senior', 'Rotax Max DD2', 'Rotax Max DD2 Masters',
        ];

        this.init();
    }

    async init() {
        const activePill = document.querySelector('.pl-year-pill.active');
        this.year = activePill ? parseInt(activePill.dataset.year) : null;

        document.querySelectorAll('.pl-year-pill').forEach(pill => {
            pill.addEventListener('click', async (e) => {
                const btn = e.currentTarget;
                if (btn.classList.contains('active')) return;
                document.querySelectorAll('.pl-year-pill').forEach(p => p.classList.remove('active'));
                btn.classList.add('active');
                this.year = parseInt(btn.dataset.year);
                document.getElementById('pl-year-display').textContent = this.year;
                this.activeTypes.clear();
                this.activeClasses.clear();
                this.activeTrack = null;
                await this.loadData();
            });
        });

        await this.loadYandexMaps();
        await this.loadData();
    }

    async loadYandexMaps() {
        return new Promise(resolve => {
            if (typeof window.ymaps === 'undefined') { resolve(); return; }
            window.ymaps.ready(() => { this.ymaps = window.ymaps; resolve(); });
        });
    }

    async loadData() {
        this.showLoading();
        const params = new URLSearchParams();
        if (this.year) params.set('year', this.year);

        try {
            const resp = await fetch('/api/v2/pulse/?' + params);
            if (!resp.ok) throw new Error(resp.status);
            this.data = await resp.json();
            this.renderAll();
        } catch (e) {
            this.showError();
        }
    }

    // ── Helpers ──────────────────────────────────────────────────────────

    typeStyle(typeName) {
        if (/чемпионат/i.test(typeName))  return { bg: '#198754', text: '#fff',    dot: '#198754' };
        if (/кубок/i.test(typeName))      return { bg: '#ffc107', text: '#1a1a25', dot: '#ffc107' };
        if (/первенство/i.test(typeName)) return { bg: '#0d6efd', text: '#fff',    dot: '#0d6efd' };
        return                                    { bg: '#2a2a35', text: '#fff',    dot: '#0dcaf0' };
    }

    stagesCount(n) {
        if (n % 10 === 1 && n % 100 !== 11) return `${n} этап`;
        if ([2,3,4].includes(n % 10) && ![12,13,14].includes(n % 100)) return `${n} этапа`;
        return `${n} этапов`;
    }

    // ── Производные данные ────────────────────────────────────────────────

    filteredStages() {
        let stages = this.data.stages || [];
        if (this.activeTypes.size > 0) {
            stages = stages.filter(s => this.activeTypes.has(s.type_name));
        }
        if (this.activeClasses.size > 0) {
            stages = stages.filter(s =>
                s.winners.some(w => this.activeClasses.has(w.class_name))
            );
        }
        if (this.activeTrack !== null) {
            stages = stages.filter(s => s.track && s.track.id === this.activeTrack);
        }
        return stages;
    }

    filteredChampions() {
        const classOrder = ['micro', 'mini', 'junior', 'senior', 'dd2', 'dd2 masters'];
        const classRank = c => {
            const name = c.class.toLowerCase();
            if (name.includes('dd2 masters')) return classOrder.indexOf('dd2 masters');
            const i = classOrder.findIndex(k => name.includes(k));
            return i === -1 ? 99 : i;
        };
        const result = [];
        for (const ch of this.data.championships || []) {
            if (!ch.is_current || ch.is_completed) continue;
            if (this.activeTypes.size > 0 && !this.activeTypes.has(ch.type)) continue;
            for (const c of ch.champions || []) {
                if (c.position !== 1) continue;
                if (this.activeClasses.size > 0 && !this.activeClasses.has(c.class)) continue;
                result.push(c);
            }
        }
        return result.sort((a, b) => classRank(a) - classRank(b));
    }

    // Топ-шасси считается по type+class фильтрам (не по трассе)
    computeChassis() {
        let stages = this.data.stages || [];
        if (this.activeTypes.size > 0) {
            stages = stages.filter(s => this.activeTypes.has(s.type_name));
        }

        const wins = {};
        const classMap = {};

        for (const stage of stages) {
            for (const cls of stage.winners) {
                if (this.activeClasses.size > 0 && !this.activeClasses.has(cls.class_name)) continue;
                const winner = cls.places.find(p => p.position === 1);
                if (winner && winner.chassis) {
                    wins[winner.chassis] = (wins[winner.chassis] || 0) + 1;
                    if (!classMap[winner.chassis]) classMap[winner.chassis] = new Set();
                    classMap[winner.chassis].add(cls.class_name);
                }
            }
        }

        return Object.entries(wins)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 3)
            .map(([name, count], i) => ({
                rank: i + 1,
                name,
                wins: count,
                classes: [...(classMap[name] || [])],
            }));
    }

    // ── Главный рендер ────────────────────────────────────────────────────

    renderAll() {
        const stages   = this.filteredStages();
        const champions = this.filteredChampions();
        const chassis  = this.computeChassis();

        this.renderFilters();
        this.renderLeaders(champions);
        this.renderTimeline(stages);
        this.renderChassis(chassis);
        this.renderTrackList(stages);

        // Карта — только трассы из отфильтрованных этапов
        const trackIds = new Set(stages.filter(s => s.track).map(s => s.track.id));
        const mapTracks = (this.data.tracks || []).filter(t => trackIds.has(t.id));
        this.updateMap(mapTracks);
    }

    // ── Фильтры ───────────────────────────────────────────────────────────

    renderFilters() {
        this._renderChips(
            'pl-type-chips', 'pl-type-reset',
            this.data.filters?.types || [],
            this.activeTypes,
            typeName => {
                if (this.activeTypes.has(typeName)) this.activeTypes.delete(typeName);
                else this.activeTypes.add(typeName);
                this.activeTrack = null;
                this.renderAll();
            },
            () => { this.activeTypes.clear(); this.activeTrack = null; this.renderAll(); }
        );

        // Классы — из данных этапов
        const allClasses = [...new Set(
            (this.data.stages || []).flatMap(s => s.winners.map(w => w.class_name))
        )].sort((a, b) => {
            const ia = this.CLASS_ORDER.indexOf(a), ib = this.CLASS_ORDER.indexOf(b);
            return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
        });

        this._renderChips(
            'pl-class-chips', 'pl-class-reset',
            allClasses,
            this.activeClasses,
            className => {
                if (this.activeClasses.has(className)) this.activeClasses.delete(className);
                else this.activeClasses.add(className);
                this.activeTrack = null;
                this.renderAll();
            },
            () => { this.activeClasses.clear(); this.activeTrack = null; this.renderAll(); }
        );
    }

    _renderChips(chipsId, resetId, items, activeSet, onToggle, onReset) {
        const wrap = document.getElementById(chipsId);
        const resetBtn = document.getElementById(resetId);
        if (!wrap) return;

        wrap.innerHTML = items.map(item => {
            const active = activeSet.has(item);
            return `<button class="pl-chip${active ? ' pl-chip--active' : ''}" data-val="${this._esc(item)}">${item}</button>`;
        }).join('');

        wrap.querySelectorAll('.pl-chip').forEach(chip => {
            chip.addEventListener('click', () => onToggle(chip.dataset.val));
        });

        if (resetBtn) {
            resetBtn.style.display = activeSet.size > 0 ? '' : 'none';
            resetBtn.onclick = onReset;
        }
    }

    // ── Лидеры ────────────────────────────────────────────────────────────

    renderLeaders(champions) {
        const el = document.getElementById('pl-leaders-strip');
        if (!el) return;

        if (!champions.length) {
            el.innerHTML = `<div class="pl-empty"><i class="fas fa-crown"></i><p>Нет данных о лидерах за выбранный период</p></div>`;
            return;
        }

        el.innerHTML = champions.map((c, i) => {
            const ring = (i === 0 && this.activeClasses.size === 0) ? '#ffc107' : '#2a2a35';
            const photoHtml = c.photo
                ? `<img src="${this._esc(c.photo)}" alt="${this._esc(c.name)}">`
                : `<div class="pl-leader-placeholder"><i class="fas fa-user"></i></div>`;
            const meta = (c.race_number ? `#${c.race_number} · ` : '') + `${c.points} очк.`;
            return `
            <div class="pl-leader-card">
                <div class="pl-leader-photo-wrap" style="border-color:${ring}">
                    ${photoHtml}
                    <div class="pl-leader-class-badge">${this._esc(c.class)}</div>
                </div>
                <div class="pl-leader-name"><a href="${this._esc(c.url)}">${this._esc(c.name)}</a></div>
                <div class="pl-leader-meta">${meta}</div>
            </div>`;
        }).join('');
    }

    // ── Таймлайн ──────────────────────────────────────────────────────────

    renderTimeline(stages) {
        const el = document.getElementById('pl-timeline');
        const counter = document.getElementById('pl-stage-count');
        if (!el) return;

        if (counter) counter.textContent = this.stagesCount(stages.length);

        if (!stages.length) {
            el.innerHTML = `<div class="pl-empty"><i class="fas fa-calendar-times"></i><p>Нет этапов под выбранные фильтры</p></div>`;
            return;
        }

        const stageGroups = this.data.stage_groups || [];

        // Группируем отфильтрованные этапы по championship_id
        const byChamp = {};
        for (const s of stages) {
            const cid = s.championship_id;
            if (!byChamp[cid]) byChamp[cid] = [];
            byChamp[cid].push(s);
        }

        // Предстоящие = без победителей; сортируем по дате (ближайшие первыми)
        const allUpcoming = stages
            .filter(s => s.winners.length === 0)
            .sort((a, b) => (a.date_iso || '').localeCompare(b.date_iso || ''));

        // Один ближайший — показываем явно; остальные — в аккордеон
        const nextUpcoming = allUpcoming.length > 0 ? allUpcoming[0] : null;
        const accordionStages = allUpcoming.slice(1).reverse();

        let html = '';

        // Аккордеон «Предстоящие» — только если выбранный год не меньше текущего
        const isCurrentYear = !this.year || this.year >= new Date().getFullYear();

        if (accordionStages.length > 0 && isCurrentYear) {
            // Группируем по championship_id, сохраняя порядок stageGroups
            const accByChamp = {};
            for (const s of accordionStages) {
                if (!accByChamp[s.championship_id]) accByChamp[s.championship_id] = [];
                accByChamp[s.championship_id].push(s);
            }
            let accBodyHtml = '';
            let accFirstGroup = true;
            for (const group of stageGroups) {
                const gs = accByChamp[group.id];
                if (!gs || !gs.length) continue;
                if (!accFirstGroup) {
                    accBodyHtml += `<div style="height:4px;margin:24px 0;background:repeating-linear-gradient(90deg,#3a3a45 0 10px,transparent 10px 18px);border-radius:2px"></div>`;
                }
                accFirstGroup = false;
                if (group.date_last_full) {
                    accBodyHtml += `
                    <div class="pl-finish">
                        <div class="pl-finish-flag"></div>
                        <span class="pl-finish-label">Финиш · ${this._esc(group.date_last_full)} · ${this._esc(group.title)}</span>
                    </div>`;
                }
                accBodyHtml += gs.map(s => this._renderStation(s)).join('');
                if (group.date_first) {
                    accBodyHtml += `
                    <div class="pl-start">
                        <div class="pl-start-flag"></div>
                        <span class="pl-start-label">Старт · ${this._esc(group.date_first)} · ${this._esc(group.title)}</span>
                    </div>`;
                }
            }
            html += `
            <details class="pl-upcoming-accordion">
                <summary class="pl-upcoming-summary">
                    <i class="fas fa-calendar-alt"></i>
                    Предстоящие
                    <span class="pl-upcoming-count">${this.stagesCount(accordionStages.length)}</span>
                    <i class="fas fa-chevron-down pl-upcoming-chevron"></i>
                </summary>
                <div class="pl-upcoming-body">
                    ${accBodyHtml}
                </div>
            </details>`;
        }

        // Рендер по группам: ближайший предстоящий + завершённые
        let firstGroup = true;

        for (const group of stageGroups) {
            const groupStages = byChamp[group.id] || [];
            const groupCompleted = groupStages.filter(s => s.winners.length > 0);
            const isNextUpcomingHere = nextUpcoming && groupStages.includes(nextUpcoming);

            if (!groupCompleted.length && !isNextUpcomingHere) continue;

            const style = this.typeStyle(group.type_name);

            if (!firstGroup) {
                html += `<div style="height:4px;margin:24px 0;background:repeating-linear-gradient(90deg,#3a3a45 0 10px,transparent 10px 18px);border-radius:2px"></div>`;
            }
            firstGroup = false;

            if (group.is_completed && group.date_last_full) {
                html += `
                <div class="pl-finish">
                    <div class="pl-finish-flag"></div>
                    <span class="pl-finish-label">Финиш · ${this._esc(group.date_last_full)} · ${this._esc(group.title)}</span>
                </div>`;
                html += this._renderChampionsMini(group.id);
            }

            if (isNextUpcomingHere) {
                html += this._renderStation(nextUpcoming);
            }

            html += groupCompleted.map(s => this._renderStation(s)).join('');

            if (group.date_first) {
                html += `
                <div class="pl-start">
                    <div class="pl-start-flag"></div>
                    <span class="pl-start-label">Старт · ${this._esc(group.date_first)} · ${this._esc(group.title)}</span>
                </div>`;
            }
        }

        el.innerHTML = html;
    }

    _renderChampionsMini(champId) {
        const classOrder = ['micro', 'mini', 'junior', 'senior', 'dd2', 'dd2 masters'];
        const classRank = name => {
            const n = name.toLowerCase();
            if (n.includes('dd2 masters')) return classOrder.indexOf('dd2 masters');
            const i = classOrder.findIndex(k => n.includes(k));
            return i === -1 ? 99 : i;
        };
        const champ = (this.data.championships || []).find(c => c.id === champId);
        if (!champ) return '';
        const winners = (champ.champions || [])
            .filter(c => c.position === 1)
            .sort((a, b) => classRank(a.class) - classRank(b.class));
        if (!winners.length) return '';
        const items = winners.map(c => {
            const photoInner = c.photo
                ? `<img src="${this._esc(c.photo)}" alt="">`
                : `<div class="pl-leader-placeholder"><i class="fas fa-user"></i></div>`;
            return `
            <div class="pl-leader-card">
                <div class="pl-leader-photo-wrap">
                    ${photoInner}
                    <div class="pl-leader-class-badge">${this._esc(c.class)}</div>
                </div>
                <div class="pl-leader-name"><a href="${this._esc(c.url)}">${this._esc(c.name)}</a></div>
            </div>`;
        }).join('');
        return `<div class="pl-champs-block">
            <div class="pl-champs-title">Чемпионы сезона · ${this._esc(champ.title)}</div>
            <div class="pl-champs-row">${items}</div>
        </div>`;
    }

    _renderStation(stage) {
        const style = this.typeStyle(stage.type_name);

        const visibleWinners = this.activeClasses.size > 0
            ? stage.winners.filter(w => this.activeClasses.has(w.class_name))
            : stage.winners;

        const winnersHtml = visibleWinners.length
            ? `<div class="pl-winners-row">${visibleWinners.map(w => `
                <div class="pl-winners-col">
                    ${w.event_url
                        ? `<a href="${this._esc(w.event_url)}" class="pl-class-badge pl-class-badge--link">${this._esc(w.class_name)}</a>`
                        : `<span class="pl-class-badge">${this._esc(w.class_name)}</span>`}
                    ${w.places.map(p => `
                    <div class="pl-place-row">
                        <span class="pl-pos-badge pl-pos-${p.position}">${p.position}</span>
                        ${p.driver_url
                            ? `<a href="${this._esc(p.driver_url)}" class="pl-place-name${p.position === 1 ? ' pl-place-name--1' : ''} pl-place-name--link">${this._esc(p.name)}</a>`
                            : `<span class="pl-place-name${p.position === 1 ? ' pl-place-name--1' : ''}">${this._esc(p.name)}</span>`}
                        ${p.race_number ? `<span class="pl-place-num">#${this._esc(p.race_number)}</span>` : '<span></span>'}
                    </div>`).join('')}
                </div>`).join('')}
            </div>` : '';

        const coverHtml = stage.cover_image
            ? `<img src="${this._esc(stage.cover_image)}" class="pl-station-cover" alt="">`
            : `<div class="pl-station-cover pl-station-cover--placeholder"><i class="fas fa-flag-checkered"></i></div>`;

        const dateLine = stage.date_start + (stage.date_end ? ` — ${stage.date_end}` : '');
        const trackLine = stage.track
            ? `<span><i class="fas fa-map-marker-alt"></i> ${this._esc(stage.track.name)}${stage.track.city ? ', ' + stage.track.city : ''}</span>`
            : '';

        return `
        <div class="pl-station">
            <div class="pl-station-dot" style="background:${style.dot};box-shadow:0 0 0 2px ${style.dot}"></div>
            <div class="pl-stationcard">
                ${coverHtml}
                <div class="pl-station-body">
                    <div class="pl-station-meta">
                        <span><i class="fas fa-calendar-day"></i> ${dateLine}</span>
                        ${trackLine}
                    </div>
                    <div class="pl-station-title">
                        <a href="${this._esc(stage.championship_url || stage.url)}" class="pl-station-name">${this._esc(stage.title)}</a>
                        <span class="pl-type-badge" style="background:${style.bg};color:${style.text}">${this._esc(stage.type_name)}</span>
                        <span class="pl-champ-divider-title">${this._esc(stage.championship_title)}</span>
                    </div>
                    ${winnersHtml}
                </div>
                ${stage.winners.length > 0 ? `<a href="${this._esc(stage.championship_url || stage.url)}" class="pl-station-link">Результаты →</a>` : ''}
            </div>
        </div>`;
    }

    // ── Шасси ─────────────────────────────────────────────────────────────

    renderChassis(chassis) {
        const section = document.getElementById('pl-chassis-section');
        const el = document.getElementById('pl-chassis');
        if (!section || !el) return;

        if (!chassis.length) { section.style.display = 'none'; return; }
        section.style.display = '';

        const rankStyle = {
            1: { bg: '#ffc107', text: '#212529' },
            2: { bg: '#f8f9fa', text: '#212529' },
            3: { bg: '#cd7f32', text: '#fff' },
        };

        el.innerHTML = chassis.map(c => {
            const rs = rankStyle[c.rank] || { bg: '#2a2a35', text: '#fff' };
            return `
            <div class="pl-chassis-card">
                <div class="pl-chassis-rank" style="background:${rs.bg};color:${rs.text}">${c.rank}</div>
                <div class="pl-chassis-info">
                    <div class="pl-chassis-name">${this._esc(c.name)}</div>
                    <div class="pl-chassis-classes">${c.classes.join(', ')}</div>
                </div>
                <div class="pl-chassis-wins-col">
                    <div class="pl-chassis-wins">${c.wins}</div>
                    <div class="pl-chassis-wins-label">ПОБЕД</div>
                </div>
            </div>`;
        }).join('');
    }

    // ── Список трасс ──────────────────────────────────────────────────────

    renderTrackList(stages) {
        const el = document.getElementById('pl-track-list');
        const resetBtn = document.getElementById('pl-track-reset');
        const activeLabel = document.getElementById('pl-track-active-label');
        if (!el) return;

        // Счётчик этапов по трассам в текущей выборке
        const trackCounts = {};
        const trackInfo = {};
        for (const s of stages) {
            if (!s.track) continue;
            const id = s.track.id;
            trackCounts[id] = (trackCounts[id] || 0) + 1;
            if (!trackInfo[id]) trackInfo[id] = s.track;
        }

        if (resetBtn) {
            resetBtn.style.display = this.activeTrack !== null ? '' : 'none';
            resetBtn.onclick = () => { this.activeTrack = null; this.renderAll(); };
        }
        if (activeLabel) {
            activeLabel.style.display = this.activeTrack !== null ? '' : 'none';
        }

        const entries = Object.entries(trackInfo);
        if (!entries.length) {
            el.innerHTML = `<p style="color:#6c757d;font-size:13px;margin:0">Нет трасс</p>`;
            return;
        }

        el.innerHTML = entries.map(([id, t]) => {
            const numId = parseInt(id);
            const active = this.activeTrack === numId;
            return `
            <div class="pl-track-row${active ? ' pl-track-row--active' : ''}" data-track-id="${id}">
                <i class="fas fa-map-marker-alt" style="color:#ffc107;flex-shrink:0"></i>
                <span class="pl-track-name">${this._esc(t.name)}</span>
                <span class="pl-track-count">×${trackCounts[id]}</span>
                <span class="pl-track-city">${this._esc(t.city || '')}</span>
            </div>`;
        }).join('');

        el.querySelectorAll('.pl-track-row').forEach(row => {
            row.addEventListener('click', () => {
                const id = parseInt(row.dataset.trackId);
                this.activeTrack = this.activeTrack === id ? null : id;
                this.renderAll();
            });
        });
    }

    // ── Карта ─────────────────────────────────────────────────────────────

    updateMap(tracks) {
        const mapEl = document.getElementById('map');
        if (!mapEl || !this.ymaps) return;

        if (!this.map) {
            this.map = new this.ymaps.Map('map', { center: [55.76, 37.64], zoom: 5 });
        } else {
            this.map.geoObjects.removeAll();
        }

        for (const t of tracks) {
            if (!t.lat || !t.lng) continue;
            this.map.geoObjects.add(new this.ymaps.Placemark(
                [t.lat, t.lng],
                {
                    hintContent: t.name,
                    balloonContent: `<strong>${t.name}</strong>${t.city ? '<br>' + t.city : ''}`,
                },
                { preset: 'islands#greenIcon' }
            ));
        }

        if (tracks.length > 1) {
            const bounds = this.map.geoObjects.getBounds();
            if (bounds) this.map.setBounds(bounds, { checkZoomRange: true });
        } else if (tracks.length === 1 && tracks[0].lat) {
            this.map.setCenter([tracks[0].lat, tracks[0].lng], 10);
        } else {
            this.map.setCenter([55.76, 37.64], 5);
        }
    }

    // ── Состояния загрузки / ошибки ───────────────────────────────────────

    showLoading() {
        const spinner = `<div class="pl-empty"><div class="spinner-border text-warning" role="status" style="width:3rem;height:3rem"></div><p style="margin-top:12px">Загружаем данные…</p></div>`;
        ['pl-leaders-strip', 'pl-timeline'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = spinner;
        });
    }

    showError() {
        const html = `
        <div class="pl-empty">
            <i class="fas fa-exclamation-triangle" style="color:#dc3545"></i>
            <p style="color:#dc3545">Ошибка загрузки данных</p>
            <button class="btn btn-outline-warning btn-sm mt-2" onclick="location.reload()">Обновить страницу</button>
        </div>`;
        ['pl-leaders-strip', 'pl-timeline'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = html;
        });
    }

    // ── Утилиты ───────────────────────────────────────────────────────────

    _esc(str) {
        return String(str ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.pulseApp = new PulseApp();
});
