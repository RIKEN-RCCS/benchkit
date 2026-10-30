const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = path.join(__dirname, '../static/js/result_comparison_selection.js');
const {createSelection, validFilename} = require(script);
const records = new Map();
const storage = {getItem: key => records.get(key) || null, setItem: (key, value) => records.set(key, value)};
let notices = [];
const report = text => notices.push(text);
let selected = createSelection(storage, 'instance-a', 'user-a', report);
selected.set('first.json', true);
selected.set('first.json', true);
assert.deepEqual(selected.values(), ['first.json']);
selected = createSelection(storage, 'instance-a', 'user-a', report);
selected.set('second.json', true);
assert.deepEqual(selected.values(), ['first.json', 'second.json']);
selected.set('first.json', false);
assert.deepEqual(selected.values(), ['second.json']);
assert.deepEqual(createSelection(storage, 'instance-b', 'user-a', report).values(), []);
assert.deepEqual(createSelection(storage, 'instance-a', 'user-b', report).values(), []);
assert.deepEqual(createSelection(storage, 'instance-a', 'user-a', report).values(), []);
selected.set('second.json', true);
selected.clear();
assert.deepEqual(createSelection(storage, 'instance-a', 'user-a', report).values(), []);
for (const file of ['../x.json', 'x,y.json', 'a\\x.json', 'x\n.json', 'x.txt', null]) {
    assert.equal(validFilename(file), false);
}
records.set('broken', '{bad');
assert.deepEqual(createSelection(storage, 'broken', 'a', report).values(), []);
records.set('broken', JSON.stringify({scope: 'a', files: ['../a.json']}));
assert.deepEqual(createSelection(storage, 'broken', 'a', report).values(), []);
assert.ok(notices.length);
const denied = {getItem() {throw Error('denied');}, setItem() {throw Error('denied');}};
selected = createSelection(denied, 'x', 'a', report);
selected.set('first.json', true);
assert.deepEqual(selected.values(), ['first.json']);

class Element {
    constructor(attrs = {}) {
        this.attrs = attrs;
        this.children = [];
        this.listeners = {};
        this.style = {};
        this.hidden = false;
    }
    getAttribute(key) {return this.attrs[key];}
    setAttribute(key, value) {this.attrs[key] = value;}
    addEventListener(name, fn) {this.listeners[name] = fn;}
    append(...items) {this.children.push(...items);}
    replaceChildren(...items) {this.children = items;}
    fire(name) {this.listeners[name]();}
    set innerHTML(_) {throw Error('Unsafe HTML insertion');}
}
function page(files, scope = 'scope', compareUrl = '/instance-a/results/compare') {
    const ids = {};
    for (const id of ['resultComparison', 'comparisonStorageStatus', 'compareBtn', 'clearComparison',
        'comparisonFiles', 'compareHint', 'comparisonCount']) ids[id] = new Element();
    ids.resultComparison.attrs = {'data-compare-url': compareUrl, 'data-scope': scope};
    const boxes = files.map(file => Object.assign(new Element(), {value: file, checked: false}));
    const rows = boxes.map(box => Object.assign(new Element(), {querySelector: () => box}));
    const win = {
        sessionStorage: storage, location: {href: ''}, listeners: {},
        addEventListener(name, fn) {this.listeners[name] = fn;},
        document: {
            getElementById: id => ids[id], createElement: () => new Element(),
            querySelectorAll: query => query === '.compare-checkbox' ? boxes : rows
        }
    };
    vm.runInNewContext(fs.readFileSync(script, 'utf8'), {window: win});
    return {ids, boxes, rows, win};
}
records.clear();
let first = page(['first.json']);
first.boxes[0].checked = true;
first.boxes[0].fire('change');
assert.equal(first.ids.compareBtn.disabled, true);
let second = page(['second.json']);
assert.equal(second.ids.comparisonCount.textContent, 1);
second.boxes[0].checked = true;
second.boxes[0].fire('change');
assert.equal(second.ids.compareBtn.disabled, false);
second.ids.compareBtn.fire('click');
assert.equal(second.win.location.href, '/instance-a/results/compare?files=first.json%2Csecond.json');
second.win.deselectVisible();
assert.equal(second.ids.comparisonCount.textContent, 1);
assert.equal(second.boxes[0].checked, false);
let initial = page([]);
assert.equal(initial.ids.comparisonCount.textContent, 1);
initial.ids.comparisonFiles.children[0].children[1].fire('click');
assert.equal(initial.ids.comparisonCount.textContent, 0);
first.win.listeners.pageshow();
assert.equal(first.boxes[0].checked, false);
first.win.selectAllVisible();
assert.equal(first.boxes[0].checked, true);
let revisited = page(['first.json', 'second.json']);
assert.equal(revisited.boxes[0].checked, true);
revisited.rows[1].hidden = true;
revisited.win.selectAllVisible();
assert.equal(revisited.boxes[1].checked, false);
revisited.ids.clearComparison.fire('click');
assert.equal(revisited.ids.comparisonCount.textContent, 0);
first.win.selectAllVisible();
assert.equal(page([], 'other-user').ids.comparisonCount.textContent, 0);
assert.equal(page([], 'scope', '/instance-b/results/compare').ids.comparisonCount.textContent, 0);
console.log('Comparison selection state and cross-page DOM tests: PASS');
