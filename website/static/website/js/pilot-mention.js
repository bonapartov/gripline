(function () {
    var React = window.React;
    var DraftJS = window.DraftJS;
    var Modifier = DraftJS.Modifier;
    var EditorState = DraftJS.EditorState;
    var h = React.createElement;

    function getBlockRect(editorState) {
        // window.getSelection() к моменту монтирования source-компонента уже
        // сброшен (Draft.js успевает перерендерить DOM между закрытием
        // командной палитры и открытием source, см. componentDidMount ниже)
        // — anchorNode оказывается на случайном DIV с нулевым rect. Вместо
        // этого берём стабильный DOM-узел текущего блока по его ключу.
        var blockKey = editorState.getSelection().getStartKey();
        var blockEl = document.querySelector('[data-offset-key^="' + blockKey + '-"]');
        if (!blockEl) return null;
        var rect = blockEl.getBoundingClientRect();
        if (!rect || (rect.width === 0 && rect.height === 0)) return null;
        return rect;
    }

    var PilotMentionSource = (function () {
        function PilotMentionSource(props) {
            React.Component.call(this, props);
            this.state = { query: '', results: [] };
            this.handleChange = this.handleChange.bind(this);
            this.handleKeyDown = this.handleKeyDown.bind(this);
        }
        PilotMentionSource.prototype = Object.create(React.Component.prototype);
        PilotMentionSource.prototype.constructor = PilotMentionSource;

        PilotMentionSource.prototype.componentDidMount = function () {
            // Wagtail рендерит source-компонент обычным дочерним элементом
            // внутри .Draftail-Editor (в потоке документа, не как floating
            // tooltip), в отличие от встроенных источников (Ссылка и т.д.),
            // у которых своя модалка. Без ручного позиционирования блок
            // проваливается в конец редактора. Ставим fixed-координаты по
            // текущему выделению курсора — тот же приём, что в
            // mention-markdown.js для markdown-блока.
            var rect = getBlockRect(this.props.editorState);
            if (rect && this.wrapperEl) {
                this.wrapperEl.style.position = 'fixed';
                this.wrapperEl.style.top = (rect.bottom + 4) + 'px';
                this.wrapperEl.style.left = rect.left + 'px';
                this.wrapperEl.style.zIndex = '10000';
                this.wrapperEl.style.boxShadow = '0 4px 16px rgba(0, 0, 0, 0.4)';
            }
            this.runSearch('');
            if (this.inputEl) this.inputEl.focus({ preventScroll: true });
        };

        PilotMentionSource.prototype.runSearch = function (query) {
            var self = this;
            window.GriplineDriverSearch.loadDrivers().then(function (items) {
                self.setState({ results: window.GriplineDriverSearch.filterDrivers(items, query) });
            });
        };

        PilotMentionSource.prototype.handleChange = function (e) {
            var query = e.target.value;
            this.setState({ query: query });
            this.runSearch(query);
        };

        PilotMentionSource.prototype.handleKeyDown = function (e) {
            if (e.key === 'Escape') this.props.onClose();
        };

        PilotMentionSource.prototype.insertDriver = function (driver) {
            var editorState = this.props.editorState;
            var DraftUtils = window.draftail && window.draftail.DraftUtils;
            var state = (DraftUtils && DraftUtils.removeCommandPalettePrompt)
                ? DraftUtils.removeCommandPalettePrompt(editorState)
                : editorState;
            var content = state.getCurrentContent();
            var contentWithEntity = content.createEntity('PILOT_MENTION', 'MUTABLE', {
                id: driver.id,
                fullName: driver.full_name,
            });
            var entityKey = contentWithEntity.getLastCreatedEntityKey();
            var selection = state.getSelection();
            // Modifier.insertText требует схлопнутое выделение (просто курсор) и
            // бросает invariant-исключение на диапазоне — а сюда можно попасть и
            // с выделенным текстом (кнопка в плавающем тулбаре над выделением, а
            // не только через «/»-команду с курсором). replaceText работает в
            // обоих случаях: на схлопнутом диапазоне ведёт себя как insertText,
            // на непустом — корректно заменяет выделенный текст.
            var newContent = Modifier.replaceText(
                contentWithEntity, selection, driver.full_name, undefined, entityKey
            );
            this.props.onComplete(EditorState.push(state, newContent, 'insert-characters'));
        };

        PilotMentionSource.prototype.render = function () {
            var self = this;
            return h('div', { className: 'mention-source', ref: function (el) { self.wrapperEl = el; } },
                h('input', {
                    ref: function (el) { self.inputEl = el; },
                    type: 'text',
                    className: 'mention-source__input',
                    placeholder: 'Фамилия пилота…',
                    value: this.state.query,
                    onChange: this.handleChange,
                    onKeyDown: this.handleKeyDown,
                }),
                h('ul', { className: 'mention-source__results' },
                    this.state.results.map(function (driver) {
                        return h('li', { key: driver.id },
                            h('button', {
                                type: 'button',
                                onClick: function () { self.insertDriver(driver); },
                            }, driver.full_name + (driver.city ? ' — ' + driver.city : ''))
                        );
                    })
                )
            );
        };

        return PilotMentionSource;
    })();

    function PilotMentionDecorator(props) {
        var data = props.contentState.getEntity(props.entityKey).getData();
        return h('a', { className: 'mention-decorator', title: data.fullName || '' }, props.children);
    }

    window.draftail.registerPlugin(
        { type: 'PILOT_MENTION', source: PilotMentionSource, decorator: PilotMentionDecorator },
        'entityTypes'
    );
})();
