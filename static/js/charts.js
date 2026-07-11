/* charts.js — SVG chart rendering: line chart, heatmap, donut, model bars */

// === Stacked Area Chart ===
function renderLineChart(data) {
    if (!data || data.length === 0) return '<div class="trend-empty">暂无数据</div>';
    var width = 620, height = 220;
    var pad = { top: 18, right: 48, bottom: 35, left: 15 };
    var chartW = width - pad.left - pad.right;
    var chartH = height - pad.top - pad.bottom;
    var max = Math.max.apply(null, data.map(function(d) { return d.value; }).concat([1]));

    var xFor = function(i) { return pad.left + (data.length === 1 ? chartW / 2 : (i / (data.length - 1)) * chartW); };
    var yFor = function(val) { return pad.top + chartH - (val / max) * chartH; };
    var yForRate = function(rate) { return pad.top + chartH - (rate / 100) * chartH; };

    var points = data.map(function(d, i) {
        return {
            x: xFor(i), y: yFor(d.value), inputY: yFor(d.input || 0), rateY: yForRate(d.cacheRate || 0),
            label: d.label, value: d.value, input: d.input || 0, output: d.output || 0,
            cacheRead: d.cacheRead || 0, cacheRate: d.cacheRate || 0
        };
    });

    var gridLines = [0, 0.25, 0.5, 0.75, 1].map(function(r) {
        var y = pad.top + chartH - r * chartH;
        return '<line x1="' + pad.left + '" y1="' + y + '" x2="' + (width - pad.right) + '" y2="' + y + '" stroke="var(--border)" stroke-width="1" stroke-dasharray="4,4" opacity="0.3"/>';
    }).join('');

    var inputPath = points.map(function(p, i) { return (i === 0 ? 'M' : 'L') + ' ' + p.x + ',' + p.inputY; }).join(' ');
    var inputClose = ' L ' + points[points.length - 1].x + ',' + (pad.top + chartH) + ' L ' + points[0].x + ',' + (pad.top + chartH) + ' Z';
    var outputPath = points.map(function(p, i) { return (i === 0 ? 'M' : 'L') + ' ' + p.x + ',' + p.y; }).join(' ');
    var outputClose = ' L ' + points[points.length - 1].x + ',' + points[points.length - 1].inputY + ' L ' + points[0].x + ',' + points[0].inputY + ' Z';
    var linePath = points.map(function(p, i) { return (i === 0 ? 'M' : 'L') + ' ' + p.x + ',' + p.y; }).join(' ');
    var ratePath = points.map(function(p, i) { return (i === 0 ? 'M' : 'L') + ' ' + p.x + ',' + p.rateY; }).join(' ');
    var rateDots = points.map(function(p) { return p.cacheRate === 0 ? '' : '<circle cx="' + p.x + '" cy="' + p.rateY + '" r="2.5" fill="var(--success)" opacity="0.9"/>'; }).join('');
    var dots = points.map(function(p) { return '<circle cx="' + p.x + '" cy="' + p.y + '" r="3.5" fill="var(--accent)" stroke="var(--bg)" stroke-width="2"/>'; }).join('');

    var labelStep = Math.max(1, Math.ceil(data.length / 6));
    var labels = points.map(function(p, i) {
        if (i % labelStep !== 0 && i !== data.length - 1) return '';
        return '<text x="' + p.x + '" y="' + (height - 12) + '" text-anchor="middle" font-size="10" fill="var(--text-secondary)" font-family="var(--mono)">' + p.label + '</text>';
    }).join('');

    var rateLabels = [0, 25, 50, 75, 100].map(function(r) {
        var y = yForRate(r);
        return '<text x="' + (width - pad.right + 5) + '" y="' + (y + 3) + '" font-size="9" fill="var(--success)" font-family="var(--mono)">' + r + '%</text>';
    }).join('');

    var crosshair = '<line id="crosshair" x1="0" y1="' + pad.top + '" x2="0" y2="' + (pad.top + chartH) + '" stroke="var(--text-secondary)" stroke-width="1" stroke-dasharray="3,3" opacity="0" pointer-events="none"/>';
    var overlay = '<rect id="chartOverlay" x="0" y="0" width="' + width + '" height="' + height + '" fill="transparent" style="cursor:crosshair"/>';

    return '<svg id="trendSvg" viewBox="0 0 ' + width + ' ' + height + '" style="width:100%;height:240px" preserveAspectRatio="xMidYMid meet">' +
        '<defs>' +
            '<linearGradient id="inputGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--purple)" stop-opacity="0.3"/><stop offset="100%" stop-color="var(--purple)" stop-opacity="0.04"/></linearGradient>' +
            '<linearGradient id="outputGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--accent)" stop-opacity="0.35"/><stop offset="100%" stop-color="var(--accent)" stop-opacity="0.08"/></linearGradient>' +
        '</defs>' +
        gridLines +
        '<path d="' + inputPath + inputClose + '" fill="url(#inputGrad)"/>' +
        '<path d="' + outputPath + outputClose + '" fill="url(#outputGrad)"/>' +
        '<path d="' + linePath + '" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>' +
        '<path d="' + ratePath + '" fill="none" stroke="var(--success)" stroke-width="2" stroke-dasharray="6,4" stroke-linecap="round" stroke-linejoin="round"/>' +
        rateDots + dots + rateLabels + crosshair + labels + overlay +
    '</svg>';
}

// === Chart hover tooltip ===
function attachChartHover(data) {
    var svg = document.getElementById('trendSvg');
    var overlay = document.getElementById('chartOverlay');
    var crosshair = document.getElementById('crosshair');
    var tooltip = document.getElementById('chartTooltip');
    if (!svg || !overlay) return;

    var width = 620, height = 220;
    var pad = { top: 18, right: 48, bottom: 35, left: 15 };
    var chartW = width - pad.left - pad.right;
    var chartH = height - pad.top - pad.bottom;
    var xCoords = data.map(function(d, i) { return pad.left + (data.length === 1 ? chartW / 2 : (i / (data.length - 1)) * chartW); });

    overlay.addEventListener('mousemove', function(e) {
        var ctm = svg.getScreenCTM();
        if (!ctm) return;
        var pt = svg.createSVGPoint();
        pt.x = e.clientX; pt.y = e.clientY;
        var svgPt = pt.matrixTransform(ctm.inverse());
        var mouseX = svgPt.x;
        var crossX = Math.max(pad.left, Math.min(width - pad.right, mouseX));

        var minDist = Infinity, idx = 0;
        for (var i = 0; i < xCoords.length; i++) {
            var dist = Math.abs(xCoords[i] - mouseX);
            if (dist < minDist) { minDist = dist; idx = i; }
        }
        var p = data[idx];

        crosshair.setAttribute('x1', crossX);
        crosshair.setAttribute('x2', crossX);
        crosshair.setAttribute('opacity', '0.6');

        var containerRect = svg.parentElement.getBoundingClientRect();
        var tipPt = svg.createSVGPoint();
        tipPt.x = xCoords[idx]; tipPt.y = svgPt.y;
        var tipScreen = tipPt.matrixTransform(ctm);
        var pointScreenX = tipScreen.x - containerRect.left;
        var pointScreenY = tipScreen.y - containerRect.top;
        var tipW = 180;
        var tipX = pointScreenX + 14;
        if (tipX + tipW > containerRect.width) tipX = pointScreenX - tipW - 10;
        var tipY = Math.max(8, Math.min(pointScreenY - 20, containerRect.height - 100));
        tooltip.style.left = tipX + 'px';
        tooltip.style.top = tipY + 'px';
        tooltip.innerHTML =
            '<div class="tt-label">' + p.label + '</div>' +
            '<div class="tt-row"><span class="tt-swatch" style="background:var(--accent)"></span>输出 ' + p.output.toLocaleString('zh-CN') + '</div>' +
            '<div class="tt-row"><span class="tt-swatch" style="background:var(--purple)"></span>输入 ' + p.input.toLocaleString('zh-CN') + '</div>' +
            (p.cacheRate > 0 ? '<div class="tt-row"><span class="tt-swatch" style="background:var(--success)"></span>缓存命中 ' + p.cacheRate + '% (' + p.cacheRead.toLocaleString('zh-CN') + ')</div>' : '') +
            '<div class="tt-total">总计 ' + p.value.toLocaleString('zh-CN') + ' tokens</div>';
        tooltip.classList.add('show');
    });

    overlay.addEventListener('mouseleave', function() {
        crosshair.setAttribute('opacity', '0');
        tooltip.classList.remove('show');
    });
}

// === GitHub-style heatmap for yearly view ===
function renderHeatmap(data) {
    if (!data || data.length === 0) return '<div class="trend-empty">暂无数据</div>';
    var dataMap = {}, maxVal = 0, dates = [];
    data.forEach(function(d) { dataMap[d.key] = d; dates.push(d.key); if (d.value > maxVal) maxVal = d.value; });

    var cellSize = 11, cellGap = 3, cellStep = cellSize + cellGap;
    var leftPad = 24, topPad = 18;
    var firstDate = new Date(dates[0] + 'T00:00:00');
    var firstDow = firstDate.getDay();
    var numWeeks = Math.ceil((dates.length + firstDow) / 7);
    var width = leftPad + numWeeks * cellStep + 10;
    var height = topPad + 7 * cellStep + 28;

    function colorFor(val) {
        if (val === 0) return 'var(--surface-hover)';
        var r = maxVal > 0 ? val / maxVal : 0;
        if (r < 0.25) return 'rgba(88,166,255,0.2)';
        if (r < 0.5) return 'rgba(88,166,255,0.4)';
        if (r < 0.75) return 'rgba(88,166,255,0.65)';
        return 'rgba(88,166,255,0.95)';
    }

    var cells = '', monthLabels = '', lastMonth = -1;
    var dayNames = ['日', '一', '二', '三', '四', '五', '六'];
    var dayLabels = '';
    [1, 3, 5].forEach(function(d) { dayLabels += '<text x="0" y="' + (topPad + d * cellStep + 8) + '" class="heatmap-day-label">' + dayNames[d] + '</text>'; });
    var mNames = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'];

    dates.forEach(function(key, i) {
        var date = new Date(key + 'T00:00:00');
        var dow = date.getDay();
        var weekIdx = Math.floor((i + firstDow) / 7);
        var x = leftPad + weekIdx * cellStep;
        var y = topPad + dow * cellStep;
        var pt = dataMap[key];
        var val = pt ? pt.value : 0;
        var title = key + ' (' + date.toLocaleDateString('zh-CN', { weekday: 'short' }) + ') · ' + (pt && val > 0 ? formatTokens(val) + ' tokens' : '无用量');
        cells += '<rect class="heatmap-cell" x="' + x + '" y="' + y + '" width="' + cellSize + '" height="' + cellSize + '" rx="2" fill="' + colorFor(val) + '" data-date="' + key + '"><title>' + title + '</title></rect>';
        if (dow === 0 && date.getMonth() !== lastMonth) { lastMonth = date.getMonth(); monthLabels += '<text x="' + x + '" y="' + (topPad - 5) + '" class="heatmap-month-label">' + mNames[lastMonth] + '</text>'; }
    });

    var legend = '<g transform="translate(' + (width - 135) + ',' + (height - 14) + ')">' +
        '<text x="0" y="9" class="heatmap-day-label">少</text>' +
        '<rect x="16" y="0" width="10" height="10" rx="2" fill="var(--surface-hover)"/>' +
        '<rect x="29" y="0" width="10" height="10" rx="2" fill="rgba(88,166,255,0.2)"/>' +
        '<rect x="42" y="0" width="10" height="10" rx="2" fill="rgba(88,166,255,0.4)"/>' +
        '<rect x="55" y="0" width="10" height="10" rx="2" fill="rgba(88,166,255,0.65)"/>' +
        '<rect x="68" y="0" width="10" height="10" rx="2" fill="rgba(88,166,255,0.95)"/>' +
        '<text x="84" y="9" class="heatmap-day-label">多</text></g>';

    return '<div class="heatmap-wrap"><svg class="heatmap-svg" viewBox="0 0 ' + width + ' ' + height + '" style="width:100%;max-width:' + width + 'px;height:auto;display:block;margin:0 auto">' + monthLabels + dayLabels + cells + legend + '</svg></div>';
}

// === Heatmap hover tooltip ===
function attachHeatmapHover(data) {
    var svg = document.querySelector('#trendChart .heatmap-svg');
    var tooltip = document.getElementById('chartTooltip');
    if (!svg || !tooltip) return;
    var dataMap = {};
    data.forEach(function(d) { dataMap[d.key] = d; });

    svg.addEventListener('mousemove', function(e) {
        var cell = e.target;
        if (!cell.classList || !cell.classList.contains('heatmap-cell')) { tooltip.classList.remove('show'); return; }
        var date = cell.getAttribute('data-date');
        if (!date) return;
        var pt = dataMap[date];
        var card = svg.closest('.card');
        var cardRect = card.getBoundingClientRect();
        var tipX = e.clientX - cardRect.left + 14;
        var tipY = e.clientY - cardRect.top - 10;
        var tipW = 200;
        if (tipX + tipW > cardRect.width) tipX = e.clientX - cardRect.left - tipW - 10;
        tipY = Math.max(8, tipY);
        tooltip.style.left = tipX + 'px';
        tooltip.style.top = tipY + 'px';
        var d = new Date(date + 'T00:00:00');
        var dateLabel = date + ' ' + d.toLocaleDateString('zh-CN', { weekday: 'long' });
        if (pt && pt.value > 0) {
            tooltip.innerHTML =
                '<div class="tt-label">' + dateLabel + '</div>' +
                '<div class="tt-row"><span class="tt-swatch" style="background:var(--accent)"></span>输出 ' + pt.output.toLocaleString('zh-CN') + '</div>' +
                '<div class="tt-row"><span class="tt-swatch" style="background:var(--purple)"></span>输入 ' + pt.input.toLocaleString('zh-CN') + '</div>' +
                (pt.cacheRate > 0 ? '<div class="tt-row"><span class="tt-swatch" style="background:var(--success)"></span>缓存命中 ' + pt.cacheRate + '% (' + pt.cacheRead.toLocaleString('zh-CN') + ')</div>' : '') +
                '<div class="tt-total">总计 ' + formatTokens(pt.value) + ' tokens</div>';
        } else {
            tooltip.innerHTML = '<div class="tt-label">' + dateLabel + '</div><div class="tt-row" style="color:var(--text-tertiary)">无用量数据</div>';
        }
        tooltip.classList.add('show');
    });
    svg.addEventListener('mouseleave', function() { tooltip.classList.remove('show'); });
}

// === Memory Donut ===
function renderDonut(values, total) {
    if (total === 0) return '<div class="trend-empty">暂无数据</div>';
    var size = 180, cx = 90, cy = 90, r = 72;
    var circumference = 2 * Math.PI * r;
    var strokeWidth = 20;
    var colors = ['var(--accent)', 'var(--purple)', 'var(--success)', 'var(--warning)'];
    var cumulative = 0;
    var segments = values.map(function(v, i) {
        var fraction = v.value / total;
        var length = fraction * circumference;
        var offset = -cumulative * circumference;
        cumulative += fraction;
        return { label: v.label, value: v.value, color: colors[i], length: length, offset: offset, fraction: fraction };
    });
    var circles = segments.map(function(s) {
        if (s.length <= 0) return '';
        var pct = (s.fraction * 100).toFixed(1);
        return '<circle class="donut-segment" data-label="' + s.label + '" data-value="' + s.value + '" data-pct="' + pct + '" cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="' + s.color + '" stroke-width="' + strokeWidth + '" stroke-dasharray="' + s.length + ' ' + (circumference - s.length) + '" stroke-dashoffset="' + s.offset + '" transform="rotate(-90 ' + cx + ' ' + cy + ')" style="transition: stroke-dasharray 0.6s ease; cursor: pointer"/>';
    }).join('');
    var legend = segments.map(function(s) {
        var pct = (s.fraction * 100).toFixed(1);
        return '<div class="legend-item"><span class="legend-swatch" style="background:' + s.color + '"></span><div class="legend-text"><div class="legend-name">' + s.label + '</div><div class="legend-meta">' + s.value + ' · ' + pct + '%</div></div></div>';
    }).join('');
    return '<div class="donut-wrap"><div class="donut-container"><svg viewBox="0 0 ' + size + ' ' + size + '" style="width:' + size + 'px;height:' + size + 'px">' + circles + '</svg><div class="donut-center"><div class="donut-total">' + total + '</div><div class="donut-label">总条目</div></div></div><div class="memory-legend">' + legend + '</div></div>';
}

// === Model usage bars ===
function renderModelBars(models) {
    if (!models || models.length === 0) return '<div class="empty">暂无模型用量数据</div>';
    var maxTokens = models[0].total || 1;
    var colors = ['var(--accent)', 'var(--purple)', 'var(--success)', 'var(--warning)', 'var(--danger)'];
    return models.map(function(m, i) {
        var pct = Math.round(m.total / maxTokens * 100);
        var color = colors[i % colors.length];
        var shortName = m.model.replace('kimi-code/', '');
        return '<div class="model-bar-item">' +
            '<span class="model-bar-name" title="' + m.model + '">' + shortName + '</span>' +
            '<div class="model-bar-wrap"><div class="model-bar-fill" style="width:' + pct + '%;background:' + color + '"></div></div>' +
            '<span class="model-bar-count">' + formatTokens(m.total) + '</span>' +
        '</div>';
    }).join('');
}


// === Donut hover tooltip ===
function attachDonutHover(containerId, tooltipId) {
    containerId = containerId || 'memoryChart';
    tooltipId = tooltipId || 'memoryTooltip';
    var svg = document.querySelector('#' + containerId + ' .donut-container svg');
    var tooltip = document.getElementById(tooltipId);
    if (!svg || !tooltip) return;
    var segments = svg.querySelectorAll('.donut-segment');
    if (!segments.length) return;
    var card = svg.closest('.card');

    segments.forEach(function(seg) {
        seg.addEventListener('mouseenter', function(e) {
            var label = seg.getAttribute('data-label');
            var value = seg.getAttribute('data-value');
            var pct = seg.getAttribute('data-pct');
            var color = seg.getAttribute('stroke');
            tooltip.innerHTML =
                '<div class="tt-label">' + label + '</div>' +
                '<div class="tt-row"><span class="tt-swatch" style="background:' + color + '"></span>' + value + ' 条</div>' +
                '<div class="tt-row">占比 ' + pct + '%</div>';
            tooltip.classList.add('show');
        });
        seg.addEventListener('mousemove', function(e) {
            var cardRect = card.getBoundingClientRect();
            var tipW = 160;
            var tipX = e.clientX - cardRect.left + 12;
            if (tipX + tipW > cardRect.width) tipX = e.clientX - cardRect.left - tipW - 10;
            var tipY = e.clientY - cardRect.top - 30;
            if (tipY < 8) tipY = e.clientY - cardRect.top + 15;
            tooltip.style.left = tipX + 'px';
            tooltip.style.top = tipY + 'px';
        });
        seg.addEventListener('mouseleave', function() {
            tooltip.classList.remove('show');
        });
    });
}
