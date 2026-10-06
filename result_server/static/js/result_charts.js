/* Result plots drawn with browser SVG APIs. No external chart runtime. */
(function () {
    'use strict';
    const ns = 'http://www.w3.org/2000/svg';
    const palette = ['#2474ad', '#b43f58', '#168276', '#a46c0b', '#7757a8', '#526570'];

    function element(tag, attributes, text) {
        const node = document.createElementNS(ns, tag);
        Object.entries(attributes || {}).forEach(([key, value]) => node.setAttribute(key, value));
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function number(value) {
        if (typeof value !== 'number' && typeof value !== 'string') return NaN;
        if (typeof value === 'string' && !value.trim()) return NaN;
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : NaN;
    }

    function format(value) {
        return Number(value.toPrecision(4)).toString();
    }

    function vectorSeries(vector, prefix) {
        if (!vector || !vector.table) return [];
        const {columns, rows} = vector.table;
        return columns.slice(1).map((column, index) => ({
            label: prefix + column,
            points: rows.map(row => ({x: number(row[0]), y: number(row[index + 1])}))
        }));
    }

    function draw(container, series, options) {
        const legend = document.createElement('div');
        legend.className = 'result-chart-legend';
        const yLabel = document.createElement('div');
        yLabel.className = 'result-chart-axis';
        yLabel.textContent = options.yLabel;
        const svg = element('svg', {height: 300, role: 'group', 'aria-label': options.title});
        svg.classList.add('result-chart-plot');
        const xLabel = document.createElement('div');
        xLabel.className = 'result-chart-axis result-chart-x';
        xLabel.textContent = options.xLabel;
        const tooltip = document.createElement('div');
        tooltip.className = 'result-chart-value';
        tooltip.setAttribute('role', 'status');
        container.replaceChildren(legend, yLabel, svg, xLabel, tooltip);
        const visible = series.map(() => true);

        function render() {
            tooltip.textContent = '';
            const width = Math.max(240, container.clientWidth);
            const left = 70, right = width - 24, top = 16, bottom = 256;
            svg.setAttribute('viewBox', `0 0 ${width} 300`);
            svg.replaceChildren(element('title', {}, options.title));
            const usable = p => Number.isFinite(p.x) && Number.isFinite(p.y) && (!options.logX || p.x > 0);
            let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
            series.forEach((item, index) => {
                if (!visible[index]) return;
                item.points.forEach(p => {
                    if (!usable(p)) return;
                    const x = options.logX ? Math.log10(p.x) : p.x;
                    xMin = Math.min(xMin, x); xMax = Math.max(xMax, x);
                    yMin = Math.min(yMin, p.y); yMax = Math.max(yMax, p.y);
                });
            });
            if (!Number.isFinite(xMin)) {
                svg.append(element('text', {x: width / 2, y: 150, 'text-anchor': 'middle'}, 'No plottable data'));
                return;
            }
            if (options.labels) { xMin = 0; xMax = Math.max(1, options.labels.length - 1); }
            else if (xMin === xMax) { xMin -= 0.5; xMax += 0.5; }
            const padding = yMin === yMax ? Math.abs(yMin) * 0.1 || 1 : (yMax - yMin) * 0.08;
            yMin -= padding; yMax += padding;
            const xPosition = x => left + (x - xMin) / (xMax - xMin) * (right - left);
            const yPosition = y => bottom - (y - yMin) / (yMax - yMin) * (bottom - top);
            for (let i = 0; i <= 4; i++) {
                const value = yMin + (yMax - yMin) * i / 4;
                const y = yPosition(value);
                svg.append(element('line', {x1: left, x2: right, y1: y, y2: y, stroke: '#dce4e7'}));
                svg.append(element('text', {x: left - 8, y: y + 4, 'text-anchor': 'end'}, format(value)));
            }
            svg.append(element('path', {d: `M${left},${top} V${bottom} H${right}`, fill: 'none', stroke: '#75858e'}));
            const tickCount = Math.max(2, Math.min(6, Math.floor((right - left) / 100) + 1));
            const ticks = new Set();
            for (let i = 0; i < tickCount; i++) {
                let value = xMin + (xMax - xMin) * i / (tickCount - 1);
                if (options.labels) value = Math.min(options.labels.length - 1, Math.round(value));
                if (ticks.has(value)) continue;
                ticks.add(value);
                const fullLabel = options.labels ? String(options.labels[value]) : format(options.logX ? 10 ** value : value);
                const label = options.labels && fullLabel.length > 12 ? fullLabel.slice(0, 10) + '...' : fullLabel;
                const tick = element('text', {
                    x: xPosition(value), y: bottom + 22,
                    'text-anchor': i === 0 ? 'start' : i === tickCount - 1 ? 'end' : 'middle'
                }, label);
                tick.append(element('title', {}, fullLabel));
                svg.append(tick);
            }
            series.forEach((item, index) => {
                if (!visible[index]) return;
                const color = palette[index % palette.length];
                let path = '', connected = false;
                const points = [];
                item.points.forEach(p => {
                    if (!usable(p)) { connected = false; return; }
                    const x = xPosition(options.logX ? Math.log10(p.x) : p.x), y = yPosition(p.y);
                    path += `${connected ? 'L' : 'M'}${x},${y} `;
                    connected = true;
                    points.push({p, x, y});
                });
                svg.append(element('path', {d: path, fill: 'none', stroke: color, 'stroke-width': 2}));
                points.forEach(({p, x, y}) => {
                    const xValue = options.labels ? options.labels[p.x] : p.x;
                    const description = `${item.label}: ${xValue} / ${p.y}`;
                    const point = element('circle', {cx: x, cy: y, r: 4, fill: color, tabindex: 0, 'aria-label': description});
                    point.append(element('title', {}, description));
                    ['pointerenter', 'focus', 'click'].forEach(event => point.addEventListener(event, () => { tooltip.textContent = description; }));
                    ['pointerleave', 'blur'].forEach(event => point.addEventListener(event, () => { tooltip.textContent = ''; }));
                    svg.append(point);
                });
            });
        }

        series.forEach((item, index) => {
            const label = document.createElement('label');
            const toggle = document.createElement('input');
            toggle.type = 'checkbox';
            toggle.checked = true;
            toggle.addEventListener('change', () => { visible[index] = toggle.checked; render(); });
            const swatch = document.createElement('span');
            swatch.className = 'result-chart-swatch';
            swatch.style.backgroundColor = palette[index % palette.length];
            const text = document.createElement('span');
            text.textContent = item.label;
            label.append(toggle, swatch, text);
            legend.append(label);
        });
        render();
        let previousWidth = container.clientWidth;
        if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => {
            if (container.clientWidth !== previousWidth) {
                previousWidth = container.clientWidth;
                render();
            }
        }).observe(container);
        else window.addEventListener('resize', render);
    }

    function read(id, attribute) {
        return JSON.parse(document.getElementById(id).getAttribute(attribute));
    }

    function initialize() {
        try {
            const detail = document.getElementById('vectorChart');
            if (detail) {
                const vector = read('vectorData', 'data-vector');
                const axis = vector.x_axis || {};
                const label = (axis.name || 'X Axis') + (axis.unit ? ` (${axis.unit})` : '');
                draw(detail, vectorSeries(vector, ''), {logX: true, xLabel: label, yLabel: 'Value', title: 'Vector metrics (logarithmic X axis)'});
            }
            const timeline = document.getElementById('fomTimelineChart');
            if (timeline) {
                const results = read('resultsJsonData', 'data-results');
                const config = read('compareConfigData', 'data-config');
                const overlay = document.getElementById('compareVectorChart');
                if (overlay) draw(overlay, results.flatMap(r => vectorSeries((r.data.metrics || {}).vector, r.timestamp + ' - ')), {
                    logX: true, xLabel: config.vector_axis_label || 'X Axis', yLabel: 'Value', title: 'Vector comparison (logarithmic X axis)'
                });
                const label = 'FOM' + (config.fom_unit ? ` (${config.fom_unit})` : '');
                draw(timeline, [{label, points: results.map((r, index) => ({x: index, y: number(r.data.FOM)}))}], {
                    labels: results.map(r => r.timestamp), xLabel: 'Timestamp', yLabel: label, title: 'FOM timeline'
                });
            }
        } catch (error) {
            document.getElementById('chartFallback').hidden = false;
        }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
    else initialize();
}());
