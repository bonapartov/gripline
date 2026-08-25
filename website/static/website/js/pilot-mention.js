(function () {
    var React = window.React;
    var DraftJS = window.DraftJS;
    var Modifier = DraftJS.Modifier;
    var EditorState = DraftJS.EditorState;
    var h = React.createElement;

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
            this.runSearch('');
            if (this.inputEl) this.inputEl.focus();
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
            var newContent = Modifier.insertText(
                contentWithEntity, selection, driver.full_name, undefined, entityKey
            );
            this.props.onComplete(EditorState.push(state, newContent, 'insert-characters'));
        };

        PilotMentionSource.prototype.render = function () {
            var self = this;
            return h('div', { className: 'mention-source' },
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
