(function () {
    var React = window.React;
    var DraftJS = window.DraftJS;
    var Modifier = DraftJS.Modifier;
    var EditorState = DraftJS.EditorState;
    var h = React.createElement;

    function getBlockRect(editorState) {
        // См. pilot-mention.js: window.getSelection() к моменту монтирования
        // source-компонента уже сброшен, берём стабильный DOM-узел текущего
        // блока по его ключу.
        var blockKey = editorState.getSelection().getStartKey();
        var blockEl = document.querySelector('[data-offset-key^="' + blockKey + '-"]');
        if (!blockEl) return null;
        var rect = blockEl.getBoundingClientRect();
        if (!rect || (rect.width === 0 && rect.height === 0)) return null;
        return rect;
    }

    var TeamMentionSource = (function () {
        function TeamMentionSource(props) {
            React.Component.call(this, props);
            this.state = { query: '', results: [] };
            this.handleChange = this.handleChange.bind(this);
            this.handleKeyDown = this.handleKeyDown.bind(this);
        }
        TeamMentionSource.prototype = Object.create(React.Component.prototype);
        TeamMentionSource.prototype.constructor = TeamMentionSource;

        TeamMentionSource.prototype.componentDidMount = function () {
            // См. pilot-mention.js: source-компонент рендерится в потоке
            // документа внутри .Draftail-Editor, без ручного позиционирования
            // проваливается в конец редактора. Ставим fixed-координаты по
            // текущему выделению курсора.
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

        TeamMentionSource.prototype.runSearch = function (query) {
            var self = this;
            window.GriplineTeamSearch.loadTeams().then(function (items) {
                self.setState({ results: window.GriplineTeamSearch.filterTeams(items, query) });
            });
        };

        TeamMentionSource.prototype.handleChange = function (e) {
            var query = e.target.value;
            this.setState({ query: query });
            this.runSearch(query);
        };

        TeamMentionSource.prototype.handleKeyDown = function (e) {
            if (e.key === 'Escape') this.props.onClose();
        };

        TeamMentionSource.prototype.insertTeam = function (team) {
            var editorState = this.props.editorState;
            var DraftUtils = window.draftail && window.draftail.DraftUtils;
            var state = (DraftUtils && DraftUtils.removeCommandPalettePrompt)
                ? DraftUtils.removeCommandPalettePrompt(editorState)
                : editorState;
            var content = state.getCurrentContent();
            var contentWithEntity = content.createEntity('TEAM_MENTION', 'MUTABLE', {
                id: team.id,
                name: team.name,
            });
            var entityKey = contentWithEntity.getLastCreatedEntityKey();
            var selection = state.getSelection();
            // См. pilot-mention.js: если текст уже выделен (кнопка в тулбаре
            // над выделением), оставляем его как есть и просто делаем ссылкой
            // — не подменяем на каноничное название команды из базы.
            var changeType, newContent;
            if (selection.isCollapsed()) {
                changeType = 'insert-characters';
                newContent = Modifier.insertText(
                    contentWithEntity, selection, team.name, undefined, entityKey
                );
            } else {
                changeType = 'apply-entity';
                newContent = Modifier.applyEntity(contentWithEntity, selection, entityKey);
            }
            this.props.onComplete(EditorState.push(state, newContent, changeType));
        };

        TeamMentionSource.prototype.render = function () {
            var self = this;
            return h('div', { className: 'mention-source', ref: function (el) { self.wrapperEl = el; } },
                h('input', {
                    ref: function (el) { self.inputEl = el; },
                    type: 'text',
                    className: 'mention-source__input',
                    placeholder: 'Название команды…',
                    value: this.state.query,
                    onChange: this.handleChange,
                    onKeyDown: this.handleKeyDown,
                }),
                h('ul', { className: 'mention-source__results' },
                    this.state.results.map(function (team) {
                        return h('li', { key: team.id },
                            h('button', {
                                type: 'button',
                                onClick: function () { self.insertTeam(team); },
                            }, team.name)
                        );
                    })
                )
            );
        };

        return TeamMentionSource;
    })();

    function TeamMentionDecorator(props) {
        var data = props.contentState.getEntity(props.entityKey).getData();
        return h('a', { className: 'mention-decorator', title: data.name || '' }, props.children);
    }

    window.draftail.registerPlugin(
        { type: 'TEAM_MENTION', source: TeamMentionSource, decorator: TeamMentionDecorator },
        'entityTypes'
    );
})();
