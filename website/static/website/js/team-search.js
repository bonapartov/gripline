window.GriplineTeamSearch = (function () {
    var TEAMS_URL = '/api/v2/teams-api/';
    var cache = null;

    function loadTeams() {
        if (!cache) {
            cache = fetch(TEAMS_URL)
                .then(function (r) { return r.json(); })
                .then(function (data) { return data.items || []; })
                .catch(function () { cache = null; return []; });
        }
        return cache;
    }

    function filterTeams(items, query) {
        var q = (query || '').toLowerCase().trim();
        if (!q) return items.slice(0, 8);
        return items.filter(function (t) {
            return (t.name || '').toLowerCase().indexOf(q) !== -1;
        }).slice(0, 8);
    }

    return { loadTeams: loadTeams, filterTeams: filterTeams };
})();
