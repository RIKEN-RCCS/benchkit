const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function fixture(loaded, href) {
    const assigned = [];
    const listeners = {};
    function item(name, panel) {
        const attrs = new Set(panel && name === loaded ? ["data-execution-loaded"] : []);
        return {
            dataset: panel ? {executionPanel: name} : {executionTab: name},
            handlers: {}, hidden: name !== loaded,
            hasAttribute: key => attrs.has(key),
            setAttribute: key => attrs.add(key), removeAttribute: key => attrs.delete(key),
            addEventListener(name, callback) { this.handlers[name] = callback; },
        };
    }
    const names = ["runs", "profiles", "triggers", "diagnostics"];
    const links = names.map(name => item(name, false));
    const panels = names.map(name => item(name, true));
    const root = {
        querySelectorAll: selector => selector.includes("execution-tab") ? links : panels,
        querySelector: () => null,
    };
    const url = new URL(href);
    const window = {
        location: {href, hash: url.hash, assign: value => assigned.push(String(value))},
        history: {pushState() { throw new Error("Unloaded tabs must navigate normally"); }},
        addEventListener: (name, callback) => { listeners[name] = callback; },
    };
    const document = {
        querySelector: () => root, getElementById: () => null,
        addEventListener: (_name, callback) => callback(),
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../static/js/execution_management.js"), "utf8"),
        {document, window, URL, fetch() { throw new Error("Hidden tab must not fetch receipts"); }});
    return {links, panels, window, listeners, assigned};
}

test("unloaded tab clicks keep native navigation and browser history", () => {
    const page = fixture("profiles", "https://example.invalid/console/admin/execution-profiles?tab=profiles");
    let prevented = false;
    page.links[0].handlers.click({button: 0, preventDefault() { prevented = true; }});
    assert.equal(prevented, false);
    assert.deepEqual(page.assigned, []);
});

for (const [anchor, destination] of [["execution-history", "runs"], ["profile-budget", "profiles"],
    ["profile-editor", "profiles"], ["trigger-editor", "triggers"]]) {
    test(`legacy #${anchor} loads its missing panel`, () => {
        const loaded = destination === "runs" ? "profiles" : "runs";
        const page = fixture(loaded, `https://example.invalid/console/admin/execution-profiles?history_page=2#${anchor}`);
        assert.equal(page.assigned.length, 1);
        const target = new URL(page.assigned[0]);
        assert.equal(target.searchParams.get("tab"), destination);
        assert.equal(target.searchParams.get("history_page"), "2");
        assert.equal(target.hash, "#" + anchor);
    });
}

test("back/forward restores an unloaded view through a GET", () => {
    const page = fixture("profiles", "https://example.invalid/console/admin/execution-profiles?tab=profiles");
    page.window.location.href = "https://example.invalid/console/admin/execution-profiles?tab=triggers&history_status=submitted";
    page.listeners.popstate();
    assert.equal(new URL(page.assigned[0]).searchParams.get("tab"), "triggers");
    assert.equal(new URL(page.assigned[0]).searchParams.get("history_status"), "submitted");
});
