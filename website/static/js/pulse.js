// static/js/pulse.js
class PulseApp {
  constructor() {
    console.log('🚀 PulseApp инициализирован');
    this.currentYear = null;
    this.selectedTypes = [];
    this.selectedClasses = [];
    this.map = null;
    this.ymaps = null;
    this.allData = null;

    this.init();
  }

  async init() {
    console.log('📌 Запуск init()');
    this.bindEvents();

    // Загружаем данные первыми
    await this.loadData();

    // Карта обновится внутри loadData
  }

  bindEvents() {
    console.log('🔗 Привязываем события');



    // Кнопки годов
    const yearButtons = document.querySelectorAll('.year-filter');
    yearButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        const selectedYear = e.target.dataset.year;
        console.log('📅 Выбран год:', selectedYear);

        // Обновляем активный класс
        yearButtons.forEach(b => {
          b.classList.remove('btn-warning');
          b.classList.add('btn-outline-secondary');
        });
        e.target.classList.remove('btn-outline-secondary');
        e.target.classList.add('btn-warning');

        // Устанавливаем год и загружаем данные
        this.currentYear = selectedYear;
        this.loadData();
      });
    });
    console.log('✅ События кнопок годов привязаны');

    // Кнопка "Применить"
    const applyBtn = document.getElementById('applyFilters');
    if (applyBtn) {
      applyBtn.addEventListener('click', () => {
        console.log('🖱️ Нажата кнопка Применить');
        // Преобразуем названия в коды
        const typeNameToCode = {
          'Кубок': 'cup',
          'Первенство': 'competition',
          'Чемпионат': 'championship'
        };
        this.selectedTypes = Array.from(document.querySelectorAll('.type-filter:checked'))
        .map(cb => typeNameToCode[cb.value] || cb.value);
        this.selectedClasses = Array.from(document.querySelectorAll('.class-filter:checked')).map(cb => cb.value);
        console.log('📊 Выбранные типы:', this.selectedTypes);
        console.log('📊 Выбранные классы:', this.selectedClasses);
        this.loadData(); // Вместо filterData используем loadData с параметрами
      });
      console.log('✅ События кнопки привязаны');
    }

    // Кнопка "Сбросить" (если есть)
    const resetBtn = document.getElementById('resetFilters');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        console.log('🔄 Сброс фильтров');

        // Сбрасываем чекбоксы
        document.querySelectorAll('.type-filter, .class-filter').forEach(cb => {
          cb.checked = false;
        });

        // Сбрасываем выбранные значения
        this.selectedTypes = [];
        this.selectedClasses = [];



        // Загружаем данные без фильтров
        this.loadData();
      });
      console.log('✅ События кнопки сброса привязаны');
    }

    // Загружаем фильтры из URL при загрузке страницы
    this.loadFiltersFromURL();
  }

  loadFiltersFromURL() {
    const urlParams = new URLSearchParams(window.location.search);

    // Год
    const yearParam = urlParams.get('year');
    if (yearParam) {
      this.currentYear = yearParam;

      // Подсвечиваем соответствующую кнопку
      document.querySelectorAll('.year-filter').forEach(btn => {
        if (btn.dataset.year === yearParam) {
          btn.classList.remove('btn-outline-secondary');
          btn.classList.add('btn-warning');
        } else {
          btn.classList.remove('btn-warning');
          btn.classList.add('btn-outline-secondary');
        }
      });
    }

    // Типы
    const typeParams = urlParams.getAll('type');
    if (typeParams.length > 0) {
      this.selectedTypes = typeParams;
      document.querySelectorAll('.type-filter').forEach(cb => {
        cb.checked = typeParams.includes(cb.value);
      });
    }

    // Классы
    const classParams = urlParams.getAll('class');
    if (classParams.length > 0) {
      this.selectedClasses = classParams;
      document.querySelectorAll('.class-filter').forEach(cb => {
        cb.checked = classParams.includes(cb.value);
      });
    }
    if (!this.currentYear) {
      const yearButtons = document.querySelectorAll('.year-filter');
      if (yearButtons.length > 0) {
        this.currentYear = yearButtons[0].dataset.year;

        // Подсвечиваем его
        yearButtons.forEach(btn => {
          if (btn.dataset.year === this.currentYear) {
            btn.classList.remove('btn-outline-secondary');
            btn.classList.add('btn-warning');
          }
        });
      }
    }
  }

  async loadYandexMaps() {
    console.log('🗺️ Ожидаем готовность Яндекс.Карт');
    return new Promise((resolve) => {
      if (typeof window.ymaps === 'undefined') {
        console.warn('⚠️ Скрипт Яндекс.Карт не найден в HTML');
        resolve();
        return;
      }

      window.ymaps.ready(() => {
        console.log('✅ Яндекс.Карты полностью готовы');
        this.ymaps = window.ymaps;
        resolve();
      });
    });
  }

  async loadData() {
    try {
      console.log('🔄 Начинаем загрузку данных...');
      this.showLoading();

      // Дожидаемся готовности API карт
      if (!this.ymaps) {
        await this.loadYandexMaps();
      }

      // Определяем год для загрузки
      let yearToLoad = this.currentYear;
      if (!yearToLoad) {
        const yearSlider = document.getElementById('yearSlider');
        if (yearSlider && yearSlider.max) {
          yearToLoad = yearSlider.max;
        }
      }

      // Собираем все параметры для API
      const params = new URLSearchParams();

      if (yearToLoad) params.append('year', yearToLoad);

      // Добавляем выбранные типы
      this.selectedTypes.forEach(type => params.append('type', type));

      // Добавляем выбранные классы
      this.selectedClasses.forEach(cls => params.append('class', cls));

      console.log('📡 Запрос к API:', `/api/v2/pulse/?${params.toString()}`);

      const response = await fetch(`/api/v2/pulse/?${params.toString()}`);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

      const data = await response.json();
      this.allData = data;

      // Обновляем интерфейс
      this.updateFilters();
      this.renderCards(this.allData.championships);
      this.updateChampionSpotlight(this.allData.championships);

      // Обновляем карту
      if (this.ymaps && this.allData.tracks) {
        this.updateMap(this.allData.tracks);
      }

      // Обновляем URL без перезагрузки страницы
      this.updateURL(params);

    } catch (error) {
      console.error('❌ Ошибка:', error);
      this.showError('Ошибка загрузки данных.');
    }
  }

  updateURL(params) {
    const newUrl = `${window.location.pathname}?${params.toString()}`;
    window.history.pushState({}, '', newUrl);
  }

  showLoading() {
    const container = document.getElementById('tournamentCards');
    if (container) {
      container.innerHTML = `
      <div class="col-12 text-center py-5">
      <div class="spinner-border text-warning" role="status" style="width: 3rem; height: 3rem;">
      <span class="visually-hidden">Загрузка...</span>
      </div>
      <p class="text-muted mt-3">Загружаем данные...</p>
      </div>
      `;
    }
  }

  showError(message) {
    const container = document.getElementById('tournamentCards');
    if (container) {
      container.innerHTML = `
      <div class="col-12">
      <div class="card bg-dark border-danger p-5 text-center">
      <i class="fas fa-exclamation-triangle text-danger mb-3" style="font-size: 3rem;"></i>
      <p class="text-danger m-0">${message}</p>
      <button class="btn btn-outline-warning mt-3 mx-auto" style="width: 200px;" onclick="location.reload()">
      Обновить страницу
      </button>
      </div>
      </div>
      `;
    }
  }

  updateFilters() {
    if (!this.allData || !this.allData.filters) return;

    console.log('🔄 Обновляем фильтры');

    const yearSlider = document.getElementById('yearSlider');
    const yearButtonsContainer = document.getElementById('yearButtons');



    // Обновляем кнопки годов (если список годов изменился)
    if (yearButtonsContainer && this.allData.filters.years) {
      // Здесь можно добавить логику обновления списка годов
      // если они могут меняться динамически
    }
  }

  // Метод filterData больше не нужен, так как фильтрация происходит на сервере
  // Удаляем его или оставляем для обратной совместимости

  renderCards(championships) {
    console.log('🎨 Отрисовываем карточки, количество:', championships.length);

    const container = document.getElementById('tournamentCards');
    if (!container) {
      console.error('❌ Контейнер tournamentCards не найден');
      return;
    }

    if (!championships || championships.length === 0) {
      container.innerHTML = `
      <div class="col-12">
      <div class="card bg-dark border-secondary p-5 text-center">
      <i class="fas fa-search text-muted mb-3" style="font-size: 3rem;"></i>
      <p class="text-muted m-0">Нет турниров за выбранный период</p>
      </div>
      </div>
      `;
      return;
    }

    let html = '';
    championships.forEach(champ => {
      // ФИЛЬТРАЦИЯ ПО КЛАССАМ — ДОБАВЛЕНО!
      let filteredChampions = champ.champions;
      if (this.selectedClasses.length > 0) {
        filteredChampions = champ.champions.filter(c =>
        this.selectedClasses.includes(c.class)
        );
      }

      // Если нет подходящих чемпионов — пропускаем карточку
      if (filteredChampions.length === 0) return;

      // Группируем чемпионов по классам
      const championsByClass = {};
      filteredChampions.forEach(c => {
        if (!championsByClass[c.class]) {
          championsByClass[c.class] = [];
        }
        championsByClass[c.class].push(c);
      });

      // Формируем HTML для чемпионов
      let championsHtml = '';
      Object.entries(championsByClass).forEach(([className, champions]) => {
        championsHtml += `
        <div class="mb-3 pb-2 border-bottom border-secondary">
        <div class="small fw-bold text-info text-uppercase mb-2">${className}</div>
        <div class="ms-2">
        `;

        champions.forEach(c => {
          const badgeClass = c.position === 1 ? 'warning' : (c.position === 2 ? 'secondary' : (c.position === 3 ? 'bronze' : 'dark'));
          championsHtml += `
          <div class="small mb-1 d-flex align-items-center">
          <span class="badge bg-${badgeClass} me-2" style="width: 24px;">${c.position}</span>
          <span class="text-light">${c.name}</span>
          <span class="text-muted ms-auto">${c.points} очков</span>
          </div>
          `;
        });

        championsHtml += `
        </div>
        </div>
        `;
      });

      // Уникальные трассы для этого чемпионата
      const uniqueTrackNames = [...new Set(champ.tracks.map(t => t.name))];

      html += `
      <div class="col-md-6 mb-4">
      <div class="card championship-card">
      <a href="${champ.url}" style="text-decoration: none; color: inherit;">
      ${champ.cover_image ?
        `<img src="${champ.cover_image}" class="card-img-top" alt="${champ.title}">` :
        `<div class="bg-secondary d-flex align-items-center justify-content-center" style="height: 200px;">
        <span class="text-muted text-uppercase small fw-bold">${champ.title}</span>
        </div>`
      }
      <div class="card-body">
      <h5 class="card-title text-uppercase">${champ.title}</h5>
       </a>
      <div class="mb-3">
      <span class="badge bg-primary me-2">${champ.years.join(' - ')}</span>
      <span class="badge bg-info">${champ.type || 'Тип не указан'}</span>
      </div>
      <div class="mb-3">
      ${championsHtml}
      </div>
      <div class="d-flex justify-content-between align-items-center mt-3 pt-2 border-top border-secondary">
      <small class="text-muted">
      <i class="fas fa-map-marker-alt me-1"></i>
      ${uniqueTrackNames.length} трасс
      </small>
      <a href="${champ.url}" class="btn btn-outline-warning btn-sm text-uppercase fw-bold">
      Подробнее
      </a>
      </div>
      </div>
      </div>
      </div>
      `;
    });

    container.innerHTML = html;
    console.log('✅ Карточки отрисованы');
  }

  updateChampionSpotlight(championships) {
    console.log('🌟 Обновляем блок чемпионов');

    const photoEl = document.getElementById('championPhoto');
    const nameEl = document.getElementById('championName');

    if (!photoEl || !nameEl) {
      console.error('❌ Элементы для чемпионов не найдены');
      return;
    }

    if (!championships || championships.length === 0) {
      nameEl.textContent = 'Нет данных за выбранный период';
      photoEl.innerHTML = '';
      return;
    }

    // Общий заголовок (год)
    nameEl.textContent = `Чемпионы и лидеры ${this.currentYear} года`;

    // Строим HTML с группировкой по чемпионатам
    let html = '<div class="champions-container text-center">';

    championships.forEach(champ => {
      const champions = champ.champions.filter(c => c.position === 1);
      if (champions.length === 0) return;

      let displayTitle = this.getChampionTitle(champ.title, champ.years);
      html += `<h3 class="champion-subtitle">${champ.title_prefix} ${displayTitle}</h3>`;
      html += '<div class="champion-photos justify-content-center">';

      champions.forEach(champion => {
        html += '<div class="champion-card">';
        html += `<a href="${champion.url}" target="_blank" style="text-decoration: none; display: block;">`;

        // Контейнер для фото с классом на нём
        html += '<div class="champion-photo-wrapper">';

        if (champion.photo) {
          html += `<img src="${champion.photo}" class="champion-photo-img" alt="${champion.name}">`;
        } else {
          html += `<div class="champion-photo-placeholder"><i class="fas fa-user"></i></div>`;
        }

        // Название класса на фото (внизу)
        html += `<div class="champion-class-on-photo">${champion.class}</div>`;
        html += '</div>'; // закрываем champion-photo-wrapper

        html += '</a>'; // закрываем ссылку

        // Имя пилота под фото
        html += `<div class="champion-name">${champion.name}</div>`;
        html += '</div>'; // закрываем champion-card
      });

      html += '</div>';
    });

    html += '</div>';

    photoEl.innerHTML = html;
  }
  getChampionTitle(title, years) {
    const cleanTitle = title.replace(/\d{4}/g, '').trim();
    const lowerTitle = cleanTitle.toLowerCase();
    let titleWithAdjective = cleanTitle;

    if (lowerTitle.includes('зимний')) {
      titleWithAdjective = cleanTitle.replace(/зимний/i, 'Зимнего');
    } else if (lowerTitle.includes('летний')) {
      titleWithAdjective = cleanTitle.replace(/летний/i, 'Летнего');
    } else if (lowerTitle.includes('весенний')) {
      titleWithAdjective = cleanTitle.replace(/весенний/i, 'Весеннего');
    } else if (lowerTitle.includes('осенний')) {
      titleWithAdjective = cleanTitle.replace(/осенний/i, 'Осеннего');
    }

    if (lowerTitle.includes('кубок')) {
      const newTitle = titleWithAdjective.replace(/кубок/i, 'кубка');
      return `${newTitle} ${years.join('-')}`;
    } else if (lowerTitle.includes('чемпионат')) {
      const newTitle = titleWithAdjective.replace(/чемпионат/i, 'чемпионата');
      return `${newTitle} ${years.join('-')}`;
    } else if (lowerTitle.includes('первенство')) {
      const newTitle = titleWithAdjective.replace(/первенство/i, 'первенства');
      return `${newTitle} ${years.join('-')}`;
    } else {
      return `${titleWithAdjective} ${years.join('-')}`;
    }
  }

  updateMap(tracks) {
    console.log('🗺️ Обновляем карту');

    const mapElement = document.getElementById('map');
    if (!mapElement) {
      console.warn('⚠️ Элемент карты не найден');
      return;
    }

    if (!window.ymaps) {
      console.warn('⚠️ Яндекс.Карты не загружены, показываем заглушку');
      mapElement.innerHTML = `
      <div class="d-flex align-items-center justify-content-center bg-dark text-white-50" style="height: 400px;">
      <div class="text-center">
      <i class="fas fa-map-marked-alt mb-3" style="font-size: 3rem;"></i>
      <p>Карта временно недоступна</p>
      <small class="text-muted">Попробуйте обновить страницу</small>
      </div>
      </div>
      `;
      return;
    }

    try {
      if (!this.map) {
        this.map = new window.ymaps.Map('map', {
          center: [55.76, 37.64],
          zoom: 5
        });
        console.log('✅ Карта создана');
      } else {
        this.map.geoObjects.removeAll();
      }

      // Убираем дубликаты трасс
      const uniqueTracks = [];
      const trackIds = new Set();

      tracks.forEach(track => {
        if (!trackIds.has(track.id)) {
          trackIds.add(track.id);
          uniqueTracks.push(track);
        }
      });

      if (uniqueTracks.length === 0) {
        this.map.setCenter([55.76, 37.64], 5);
        return;
      }

      // Добавляем маркеры
      uniqueTracks.forEach(track => {
        if (track.lat && track.lng) {
          const placemark = new window.ymaps.Placemark(
            [track.lat, track.lng],
            {
              hintContent: track.name,
              balloonContent: `
              <strong>${track.name}</strong><br>
              ${track.city || ''}<br>
              ${track.region || ''}
              `
            },
            {
              preset: 'islands#greenIcon'
            }
          );
          this.map.geoObjects.add(placemark);
        }
      });

      // Центрируем карту
      if (uniqueTracks.length > 1) {
        this.map.setBounds(this.map.geoObjects.getBounds());
      } else if (uniqueTracks.length === 1) {
        this.map.setCenter([uniqueTracks[0].lat, uniqueTracks[0].lng], 10);
      }

      console.log('✅ Карта обновлена');

    } catch (error) {
      console.error('❌ Ошибка при работе с картой:', error);
    }
  }
}

// Запускаем после загрузки DOM
document.addEventListener('DOMContentLoaded', () => {
  console.log('📄 DOM загружен, создаем PulseApp');
  window.pulseApp = new PulseApp();
});
