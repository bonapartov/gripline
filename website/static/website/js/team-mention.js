(function () {
    var React = window.React;
    var DraftJS = window.DraftJS;
    var Modifier = DraftJS.Modifier;
    var EditorState = DraftJS.EditorState;
    var h = React.createElement;

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
            this.runSearch('');
            if (this.inputEl) this.inputEl.focus();
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
            var newContent = Modifier.insertText(
                contentWithEntity, selection, team.name, undefined, entityKey
            );
            this.props.onComplete(EditorState.push(state, newContent, 'insert-characters'));
        };

        TeamMentionSource.prototype.render = function () {
            var self = this;
            return h('div', { className: 'mention-source' },
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
