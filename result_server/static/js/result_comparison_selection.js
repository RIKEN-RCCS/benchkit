(function (root) {
    'use strict';

    function validFilename(value) {
        return typeof value === 'string' && value.length <= 512 && value.endsWith('.json') &&
            !/[/\\,\x00-\x1f]/.test(value);
    }

    function createSelection(storage, key, scope, report) {
        var files = new Set();
        function save() {
            try {
                if (!storage) throw new Error('Storage unavailable');
                storage.setItem(key, JSON.stringify({scope: scope, files: Array.from(files)}));
            } catch (_) {
                report('Selection is available on this page only; browser storage is unavailable.');
            }
        }
        function reload() {
            try {
                if (!storage) throw new Error('Storage unavailable');
                var raw = storage.getItem(key);
                if (!raw) { files.clear(); return; }
                if (raw.length > 262144) throw new Error('Invalid selection');
                var data = JSON.parse(raw);
                if (!data || data.scope !== scope) {
                    files.clear();
                    save();
                    return;
                }
                if (!Array.isArray(data.files) || !data.files.every(validFilename)) {
                    throw new Error('Invalid selection');
                }
                files = new Set(data.files);
            } catch (_) {
                report('Saved comparison selection could not be restored.');
            }
        }
        reload();
        return {
            values: function () { return Array.from(files); },
            has: function (file) { return files.has(file); },
            set: function (file, checked) {
                if (!validFilename(file)) return;
                if (checked) files.add(file);
                else files.delete(file);
                save();
            },
            clear: function () { files.clear(); save(); },
            reload: reload
        };
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {createSelection: createSelection, validFilename: validFilename};
    }
    if (!root.document) return;
    var panel = root.document.getElementById('resultComparison');
    if (!panel) return;
    var compareUrl = panel.getAttribute('data-compare-url');
    var scope = panel.getAttribute('data-scope');
    var status = root.document.getElementById('comparisonStorageStatus');
    function report(message) {
        status.hidden = false;
        status.textContent = message;
    }
    var storage;
    try { storage = root.sessionStorage; } catch (_) { storage = null; }
    var selection = createSelection(storage, 'benchkit:result-comparison:' + compareUrl, scope, report);
    var compare = root.document.getElementById('compareBtn');
    var clear = root.document.getElementById('clearComparison');
    var list = root.document.getElementById('comparisonFiles');
    var checkboxes = root.document.querySelectorAll('.compare-checkbox');

    function render() {
        var files = selection.values();
        compare.disabled = files.length < 2;
        clear.disabled = files.length === 0;
        root.document.getElementById('compareHint').textContent = files.length + ' selected';
        root.document.getElementById('comparisonCount').textContent = files.length;
        list.replaceChildren();
        files.forEach(function (file) {
            var row = root.document.createElement('li');
            var label = root.document.createElement('a');
            label.className = 'comparison-filename';
            label.textContent = file;
            label.href = compareUrl.replace(/\/compare$/, '/detail/') + encodeURIComponent(file);
            var remove = root.document.createElement('button');
            remove.type = 'button';
            remove.className = 'tiny-button';
            remove.textContent = '\u00d7';
            remove.title = 'Remove ' + file;
            remove.setAttribute('aria-label', 'Remove ' + file);
            remove.addEventListener('click', function () {
                selection.set(file, false);
                render();
            });
            row.append(label, remove);
            list.append(row);
        });
        checkboxes.forEach(function (box) { box.checked = selection.has(box.value); });
    }

    checkboxes.forEach(function (box) {
        box.addEventListener('change', function () {
            selection.set(box.value, box.checked);
            render();
        });
    });
    root.selectAllVisible = function () {
        root.document.querySelectorAll('#resultsTable tbody tr').forEach(function (row) {
            var box = row.querySelector('.compare-checkbox');
            if (box && !row.hidden && row.style.display !== 'none') selection.set(box.value, true);
        });
        render();
    };
    root.deselectVisible = function () {
        checkboxes.forEach(function (box) { selection.set(box.value, false); });
        render();
    };
    clear.addEventListener('click', function () { selection.clear(); render(); });
    compare.addEventListener('click', function () {
        var files = selection.values();
        if (files.length >= 2) root.location.href = compareUrl + '?files=' + encodeURIComponent(files.join(','));
    });
    root.addEventListener('pageshow', function () { selection.reload(); render(); });
    render();
})(typeof window === 'undefined' ? globalThis : window);
