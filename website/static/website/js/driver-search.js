window.GriplineDriverSearch = (function () {
    var DRIVERS_URL = '/drivers-api/';
    var cache = null;

    function loadDrivers() {
        if (!cache) {
            cache = fetch(DRIVERS_URL)
                .then(function (r) { return r.json(); })
                .then(function (data) { return data.items || []; })
                .catch(function () { cache = null; return []; });
        }
        return cache;
    }

    function filterDrivers(items, query) {
        var q = (query || '').toLowerCase().trim();
        if (!q) return items.slice(0, 8);
        return items.filter(function (d) {
            return (d.full_name || '').toLowerCase().indexOf(q) !== -1;
        }).slice(0, 8);
    }

    return { loadDrivers: loadDrivers, filterDrivers: filterDrivers };
})();
