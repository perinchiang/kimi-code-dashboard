/* app.js — Main application logic for Kimi Code Dashboard */

// === State ===
var trendData = null;
var currentTrendUnit = 'daily';
var pageLoadTime = Date.now();
var statusData = {};
var startupServiceState = { supported: false, loaded: false, dashboard: { enabled: false, mode: 'off' }, kimi: { enabled: false } };

// === Settings ===
var SETTINGS_KEY = 'kimi_dashboard_settings_v1';
var SETTINGS_DEFAULTS = {
    show_trends: true,
    show_minicards: true,
    show_kimi_usage: true,
    show_memory: true,
    show_tool_model_usage: true,
    show_tasks: true,
    show_kimi_web_btn: true,
    show_status_bar: true,
    follow_system_theme: true,  // 跟随系统主题开关
    manual_theme: 'dark',       // 手动模式下选中的主题: light / dark
    kw_bind: '0.0.0.0',          // Kimi Web 绑定地址
    kw_port: 5494,               // Kimi Web 端口
    kw_bypass_auth: true,        // 关闭密码认证 (true=无需密码)
    kw_allowed_hosts: '',         // 允许的域名 (逗号分隔)
    kw_public_url: '',           // 自定义访问URL (留空自动生成)
    default_permission_mode: 'manual', // Kimi Code 默认权限模式 (manual/auto/yolo)
    enable_pwa_icons: false,     // 是否启用 PWA 图标（添加到手机主屏幕）
    __startup_dashboard_mode: 'off', // Dashboard 开机启动模式 (normal/elevated/off)
};
// 分组定义：icon 用 SVG path data (24x24 viewBox)
var SETTINGS_GROUPS = [
    {
        title: 'Kimi Web 服务',
        desc: '启动配置',
        icon: '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>',
        items: [
            { key: 'kw_bind', label: '绑定地址', desc: '切换会自动重启服务', type: 'segment', row: true, options: [
                { v: '127.0.0.1', t: '仅本机访问' },
                { v: '0.0.0.0',   t: '外网可访问' }
            ]},
            { key: 'kw_port', label: '端口', desc: '默认 5494', type: 'number', row: true },
            { key: 'kw_bypass_auth', label: '关闭密码认证', desc: '无需密码直接访问', row: true },
            { key: 'kw_public_url', label: '自定义访问 URL', desc: '域名会自动加入信任列表', type: 'text', row: true, wide: true },
            { key: 'default_permission_mode', label: '默认权限模式', desc: 'Kimi Code 新建会话时的默认审批模式；修改后需重启 Kimi Web', type: 'segment', row: true, options: [
                { v: 'manual', t: '逐条确认' },
                { v: 'auto', t: '自动模式' },
                { v: 'yolo', t: 'YOLO 模式' },
            ]},
        ]
    },
    {
        title: '开机启动',
        desc: '登录时自动启动服务',
        icon: '<path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z"/><path d="M12 6v6l4 2"/>',
        items: [
            { key: '__startup_dashboard_mode', label: 'Dashboard 开机启动', desc: '选择 Dashboard 的启动方式', type: 'segment', row: true, options: [
                { v: 'normal', t: '开机自启' },
                { v: 'elevated', t: '管理员启动' },
                { v: 'off', t: '关闭' }
            ]},
            { key: '__startup_kimi', label: 'Kimi Code 开机自启', desc: '登录后自动启动 Kimi Web 服务', type: 'startup_toggle', row: true },
        ]
    },
    {
        title: '主题',
        desc: '外观偏好',
        icon: '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>',
        items: [
            { key: 'follow_system_theme', label: '跟随系统主题', desc: '开启后随系统切换日间/夜间；关闭后用顶部按钮手动切换', row: true },
        ]
    },
    {
        title: 'PWA',
        desc: '手机主屏幕图标',
        icon: '<rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/>',
        items: [
            { key: 'enable_pwa_icons', label: '启用 PWA 图标', desc: '开启后注入 favicon、apple-touch-icon 和 manifest，方便添加到手机桌面', row: true },
        ]
    },
    {
        title: '界面显示',
        desc: '控制首页各模块的显示',
        icon: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
        items: [
            { key: 'show_trends', label: 'Token 用量趋势', desc: '首页顶部的用量趋势图表', row: true },
            { key: 'show_minicards', label: '快捷入口卡片', desc: 'Skills / MCP / 定时任务 / 第三方模型', row: true },
            { key: 'show_kimi_usage', label: 'Kimi Usage', desc: '登录状态、版本检查、额度信息', row: true },
            { key: 'show_memory', label: 'Memory Status', desc: 'TencentDB 记忆统计与 Gateway 健康', row: true },
            { key: 'show_tool_model_usage', label: '工具调用 & 模型用量', desc: '工具/Skill/模型调用排行榜', row: true },
            { key: 'show_tasks', label: '定时任务看板', desc: '快捷入口中的定时任务卡片', row: true },
            { key: 'show_kimi_web_btn', label: '启动 Kimi Web 按钮', desc: '右上角启动 Kimi Web 的按钮', row: true },
            { key: 'show_status_bar', label: '顶部状态栏', desc: 'Skills / MCP / Gateway 等状态 pill', row: true },
        ]
    }
];

function loadSettings() {
    try {
        var raw = localStorage.getItem(SETTINGS_KEY);
        var saved = raw ? JSON.parse(raw) : {};
        return Object.assign({}, SETTINGS_DEFAULTS, saved);
    } catch (e) {
        return Object.assign({}, SETTINGS_DEFAULTS);
    }
}

function saveSettings(settings) {
    try {
        localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch (e) { /* ignore */ }
}

function normalizePublicUrl(url) {
    url = String(url || '').trim();
    if (!url) return '';
    if (!/^https?:\/\//i.test(url)) url = 'https://' + url;
    return url;
}

function showToast(message, duration) {
    duration = duration || 5000;
    var existing = document.getElementById('kimiToast');
    if (existing) existing.remove();
    var el = document.createElement('div');
    el.id = 'kimiToast';
    el.style.cssText = 'position:fixed;bottom:20px;right:20px;max-width:420px;background:var(--card-bg);color:var(--text);border:1px solid var(--border);border-radius:10px;padding:14px 18px;box-shadow:0 6px 20px rgba(0,0,0,0.35);z-index:10000;font-size:14px;line-height:1.55;transition:opacity .3s;cursor:default;';
    el.innerHTML = message;
    document.body.appendChild(el);
    setTimeout(function() {
        el.style.opacity = '0';
        setTimeout(function() { el.remove(); }, 300);
    }, duration);
}

var settings = loadSettings();

function applySettings() {
    var s = settings;
    function setDisplay(id, show) {
        var el = document.getElementById(id);
        if (el) el.style.display = show ? '' : 'none';
    }
    setDisplay('section-trends', s.show_trends);
    setDisplay('section-minicards', s.show_minicards);
    setDisplay('section-kimi', s.show_kimi_usage);
    setDisplay('section-memory', s.show_memory);
    setDisplay('section-tool-model', s.show_tool_model_usage);
    setDisplay('tasksMiniCard', s.show_tasks);
    var kimiWebBtn = document.getElementById('kimiWebBtn');
    if (kimiWebBtn) kimiWebBtn.style.display = s.show_kimi_web_btn ? '' : 'none';
    var statusBar = document.getElementById('statusBar');
    if (statusBar) statusBar.style.display = s.show_status_bar ? '' : 'none';
    applyTheme();
    applyPwaIcons();
}

function applyPwaIcons() {
    var enabled = settings.enable_pwa_icons;
    var head = document.head;
    var ids = ['pwa-favicon', 'pwa-apple-touch-icon', 'pwa-manifest', 'pwa-apple-capable', 'pwa-apple-status'];

    if (!enabled) {
        ids.forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.remove();
        });
        return;
    }

    function ensureLink(id, rel, href) {
        var el = document.getElementById(id);
        if (!el) {
            el = document.createElement('link');
            el.id = id;
            el.rel = rel;
            head.appendChild(el);
        }
        el.href = href;
    }
    function ensureMeta(id, name, content) {
        var el = document.getElementById(id);
        if (!el) {
            el = document.createElement('meta');
            el.id = id;
            el.name = name;
            head.appendChild(el);
        }
        el.content = content;
    }

    ensureLink('pwa-favicon', 'icon', '/static/pwa/favicon.ico');
    ensureLink('pwa-apple-touch-icon', 'apple-touch-icon', '/static/pwa/apple-touch-icon.png');
    ensureLink('pwa-manifest', 'manifest', '/static/pwa/manifest.json');
    ensureMeta('pwa-apple-capable', 'apple-mobile-web-app-capable', 'yes');
    ensureMeta('pwa-apple-status', 'apple-mobile-web-app-status-bar-style', 'black-translucent');
}

function setSetting(key, value) {
    settings[key] = value;
    saveSettings(settings);
    applySettings();
    if (key === 'kw_bind' || key === 'default_permission_mode') renderSettings();
    if (key === '__startup_dashboard_mode') {
        setDashboardStartupMode(value);
        return;
    }
    if (key === 'default_permission_mode') {
        postJSON('/api/update-config', { default_permission_mode: value })
            .then(function(data) {
                if (data.success) {
                    showToast('已保存到 config.toml，重启 Kimi Web 后生效', 4000);
                } else {
                    showToast('保存失败: ' + (data.error || '未知错误'), 5000);
                }
            })
            .catch(function(e) {
                showToast('保存失败: ' + e.message, 5000);
            });
    }
}

function resetSettings() {
    settings = Object.assign({}, SETTINGS_DEFAULTS);
    saveSettings(settings);
    renderSettings();
    applySettings();
}

// === Theme ===
// 返回当前实际生效的主题
function getEffectiveTheme() {
    if (settings.follow_system_theme) {
        return (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) ? 'light' : 'dark';
    }
    return settings.manual_theme || 'dark';
}

// 应用主题到 <html data-theme=...>，并切换顶部图标显示
function applyTheme() {
    var effective = getEffectiveTheme();
    document.documentElement.setAttribute('data-theme', effective);
    // 同步 meta theme-color
    var meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) { meta = document.createElement('meta'); meta.name = 'theme-color'; document.head.appendChild(meta); }
    meta.content = effective === 'light' ? '#ffffff' : '#0d1117';
    // 顶部按钮始终可见：显示当前生效主题的反色图标（暗→显太阳提示可切亮，亮→显月亮提示可切暗）
    var iconSun  = document.getElementById('themeIconSun');
    var iconMoon = document.getElementById('themeIconMoon');
    if (iconSun)  iconSun.style.display  = (effective === 'dark')  ? '' : 'none';
    if (iconMoon) iconMoon.style.display = (effective === 'light') ? '' : 'none';
}

// 顶部按钮点击：切换 dark <-> light
// 若当前处于跟随系统模式，先关闭它，恢复手动模式
function cycleThemeMode() {
    var target = (getEffectiveTheme() === 'dark') ? 'light' : 'dark';
    if (settings.follow_system_theme) {
        settings.follow_system_theme = false;
        saveSettings(settings);
        renderSettings();
    }
    setSetting('manual_theme', target);
}

// 系统主题变化时，若处于跟随系统模式则实时跟随
if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', function () {
        if (settings.follow_system_theme) applyTheme();
    });
}

// 页面加载时立即应用一次
applyTheme();
applyPwaIcons();

// === Skill / MCP descriptions ===
var SKILL_DESC = {
    'datacom-coach': 'HCIE-Datacom 实验教练，按 P0-P4 阶段苏格拉底式引导，不给直接答案',
    'datacom-lab-coach': 'HCIE-Datacom 实验规划与实战教练，覆盖规划→配置→验收→笔记全闭环',
    'design-taste-frontend': '反模板化前端技能，专做不像 AI 生成的落地页和作品集',
    'memory-status': '查询 TencentDB 长期记忆 L0-L3 四级状态并表格展示',
    'agent-browser': '浏览器自动化：截图、表单填写、网页交互、动态渲染抓取',
    'agent-browser-core': '浏览器自动化核心技能，基于 agent-browser CLI',
    'github-skill-publisher': '将本地 Skill 发布到 GitHub 仓库',
    'web-access': '联网操作总入口：搜索、网页抓取、登录后操作',
    'obsidian': 'Obsidian 笔记库操作与 obsidian-cli 自动化',
    'self-improvement': '记录纠错与学习，实现 Agent 持续自我改进',
    'model-switcher': '切换 WorkBuddy 会话模型，直接更新 SQLite 数据库',
    'network-scanner': '扫描网络发现设备，获取 MAC 地址、厂商、主机名',
    'workbuddy-checkin': 'WorkBuddy 每日签到、查询签到状态、设置自动签到',
    'plan-and-choose': '多方案对比选择，展示 2-3 个选项等待用户决策',
    'ima-skills': 'IMA 知识库与笔记管理：上传文件、搜索知识库、编辑笔记',
    'obsidian-douban-cover-sync': '同步 Obsidian 豆瓣封面图到 Cloudflare R2',
};

var MCP_DESC = {
    'memory': '本地向量记忆服务，Kimi Code 会话级上下文存储',
    'tencentdb-memory': 'TencentDB 长期记忆桥接，L0-L3 四级持久化记忆',
    'page-agent': '页面代理 MCP，浏览器页面交互与自动化',
    'playwright': 'Playwright 浏览器自动化：截图/点击/填表/抓取',
    'github': 'GitHub MCP：操作仓库/PR/Issue/代码搜索',
    'brave-search': 'Brave 搜索引擎：网页/图片/新闻搜索',
    'filesystem': '文件系统 MCP，读写本地文件',
    'fetch': 'HTTP 请求 MCP，抓取网页/API 数据',
    'sequential-thinking': '顺序思维 MCP，多步推理与规划',
};

function getSkillDesc(skill) {
    if (SKILL_DESC[skill.id]) return SKILL_DESC[skill.id];
    var d = skill.description || '';
    if (!d || d.trim() === '>' || d.trim() === '') return '暂无简介';
    return d;
}
function getMcpDesc(name) { return MCP_DESC[name] || ''; }

// === Helpers ===
function formatDate(iso) {
    if (!iso) return '未知';
    var d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString('zh-CN');
}
function formatTokens(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    return n.toString();
}
function formatRemaining(resetTime) {
    if (!resetTime) return '';
    var target;
    if (typeof resetTime === 'number') {
        target = resetTime > 1e12 ? new Date(resetTime) : new Date(resetTime * 1000);
    } else {
        target = new Date(resetTime);
    }
    if (isNaN(target)) return '';
    var diff = target - Date.now();
    if (diff <= 0) return '即将刷新';
    var minutes = Math.floor(diff / 60000);
    var hours = Math.floor(minutes / 60);
    var days = Math.floor(hours / 24);
    if (days > 0) return days + 'd' + (hours % 24) + 'h';
    if (hours > 0) return hours + 'h' + (minutes % 60) + 'm';
    return minutes + 'm';
}
async function fetchJSON(url, options) {
    var res = await fetch(url, options);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return res.json();
}
function postJSON(url, body) {
    var opts = { method: 'POST' };
    if (body !== undefined) {
        opts.headers = { 'Content-Type': 'application/json' };
        opts.body = JSON.stringify(body);
    }
    return fetchJSON(url, opts);
}
function setError(id, msg) {
    document.getElementById(id).innerHTML = '<div class="error">' + msg + '</div>';
}

// === Launch Kimi Web ===
async function checkKimiWebStatus() {
    try {
        var cfg = { port: parseInt(settings.kw_port, 10) || 5494 };
        var data = await postJSON('/api/kimi-web-status', cfg);
        statusData.kimiWeb = data;
        var btn = document.getElementById('kimiWebBtn');
        var text = document.getElementById('kimiWebBtnText');
        if (data.running) { btn.classList.add('running'); text.textContent = 'Kimi Web 运行中'; }
        else { btn.classList.remove('running'); text.textContent = '启动 Kimi Web'; }
    } catch (e) { /* ignore */ }
}

async function launchKimiWeb() {
    var btn = document.getElementById('kimiWebBtn');
    var text = document.getElementById('kimiWebBtnText');
    var publicUrl = normalizePublicUrl(settings.kw_public_url);

    // 如果没填自定义 URL，提示用户
    if (!publicUrl) {
        if (!confirm('未配置自定义访问 URL，将使用本地地址 http://127.0.0.1:' + (settings.kw_port || 5494) + '\n\n是否继续？\n（点击「取消」去设置页填写自定义 URL）')) {
            window.location.hash = '#/settings';
            return;
        }
    }
    btn.disabled = true;
    text.textContent = '启动中...';
    var wasRunning = btn.classList.contains('running');
    if (wasRunning) text.textContent = '重启中...';
    try {
        var cfg = {
            bind: settings.kw_bind || '0.0.0.0',
            port: parseInt(settings.kw_port, 10) || 5494,
            bypass_auth: settings.kw_bypass_auth !== false,
            public_url: publicUrl
        };
        console.log('[launchKimiWeb] sending cfg:', JSON.stringify(cfg));
        var data = await postJSON('/api/launch-kimi-web', cfg);
        console.log('[launchKimiWeb] response:', JSON.stringify(data));
        if (data.status === 'launched' || data.status === 'already_running') {
            btn.classList.add('running');
            text.textContent = '已启动 \u2713';
            setTimeout(function() { text.textContent = 'Kimi Web 运行中'; btn.disabled = false; }, 1500);

            var url = data.url || '';
            if (url && !/^https?:\/\//i.test(url)) url = 'https://' + url;

            // 同步尝试打开，避免 about:blank 在 macOS/Safari 上无法导航的问题
            var popup = null;
            try { popup = window.open(url, '_blank'); } catch (e) { /* ignore */ }
            if (!popup || popup.closed || typeof popup.closed === 'undefined') {
                showToast('浏览器拦截了新窗口，请<a href="' + escapeHtml(url) + '" target="_blank" style="color:var(--accent);text-decoration:underline;font-weight:600;">点击这里</a>打开 Kimi Web', 8000);
            }
        } else {
            text.textContent = '启动失败';
            setTimeout(function() { text.textContent = '启动 Kimi Web'; btn.disabled = false; }, 2000);
            alert('启动失败: ' + (data.error || data.status || '未知错误'));
        }
    } catch (e) {
        text.textContent = '启动失败';
        setTimeout(function() { text.textContent = '启动 Kimi Web'; btn.disabled = false; }, 2000);
        alert('启动失败: ' + e.message);
    }
}

// === Clock + Uptime ===
function updateClock() {
    var now = new Date();
    document.getElementById('clock').textContent = now.toLocaleTimeString('zh-CN', { hour12: false });
}
setInterval(updateClock, 1000);
updateClock();

// === Status Bar ===
function renderStatusBar() {
    var bar = document.getElementById('statusBar');
    var pills = [];
    if (statusData.kimi) {
        var cls = statusData.kimi.loggedIn ? 'ok' : 'warn';
        pills.push('<div class="status-pill ' + cls + '"><span class="dot"></span>Kimi v' + statusData.kimi.version + ' &middot; ' + statusData.kimi.sessionCount + ' sessions</div>');
    }
    if (statusData.mcp) {
        var cls2 = statusData.mcp.available === statusData.mcp.total ? 'ok' : (statusData.mcp.available > 0 ? 'warn' : 'err');
        pills.push('<div class="status-pill ' + cls2 + '"><span class="dot"></span>MCP ' + statusData.mcp.available + '/' + statusData.mcp.total + '</div>');
    }
    if (statusData.memory) {
        var cls3 = statusData.memory.gatewayReachable ? 'ok' : 'err';
        var label = statusData.memory.gatewayReachable ? 'Gateway 可达' : 'Gateway 不可达';
        pills.push('<div class="status-pill ' + cls3 + '"><span class="dot"></span>' + label + '</div>');
    }
    if (statusData.skills) {
        pills.push('<div class="status-pill ok"><span class="dot"></span>' + statusData.skills.total + ' Skills &middot; ' + statusData.skills.localCount + ' 本地</div>');
    }
    if (statusData.modelConfig) {
        var mc = statusData.modelConfig;
        pills.push('<div class="status-pill ok"><span class="dot"></span>' + (mc.providers || []).length + ' Providers &middot; ' + (mc.models || []).length + ' Models</div>');
    }
    if (statusData.trends && statusData.trends.total) {
        pills.push('<div class="status-pill ok"><span class="dot"></span>累计 ' + formatTokens(statusData.trends.total.value) + ' tokens</div>');
    }
    bar.innerHTML = pills.join('');
}

// === Skills ===
async function loadSkills() {
    try {
        var data = await fetchJSON('/api/skills');
        statusData.skills = data;
        document.getElementById('skillsMiniMetric').textContent = data.enabledCount + '/' + data.total;
        document.getElementById('skillsMiniLabel').textContent = '启用 / 总计';
        var pills = [];
        if (data.disabledCount) pills.push('<span class="task-mini-pill disabled"><span class="dot"></span>已禁用 ' + data.disabledCount + '</span>');
        document.getElementById('skillsMiniStatus').innerHTML = pills.join('') || '';
    } catch (e) {
        document.getElementById('skillsMiniMetric').textContent = '!';
        document.getElementById('skillsMiniLabel').textContent = '加载失败';
    }
}

// === MCP ===
async function loadMCP() {
    try {
        var data = await fetchJSON('/api/mcp');
        statusData.mcp = data;
        document.getElementById('mcpMiniMetric').textContent = data.available + '/' + data.total;
        document.getElementById('mcpMiniLabel').textContent = '可用 / 总数';
        var pills = [];
        if (data.disabled) pills.push('<span class="task-mini-pill disabled"><span class="dot"></span>已禁用 ' + data.disabled + '</span>');
        document.getElementById('mcpMiniStatus').innerHTML = pills.join('') || '';
    } catch (e) {
        document.getElementById('mcpMiniMetric').textContent = '!';
        document.getElementById('mcpMiniLabel').textContent = '加载失败';
    }
}

// === SPA routing ===
function handleRoute() {
    var hash = location.hash || '#/';
    document.getElementById('view-home').style.display = (hash === '#/') ? '' : 'none';
    document.getElementById('view-skills').style.display = (hash === '#/skills') ? '' : 'none';
    document.getElementById('view-mcp').style.display = (hash === '#/mcp') ? '' : 'none';
    document.getElementById('view-models').style.display = (hash === '#/models') ? '' : 'none';
    document.getElementById('view-tasks').style.display = (hash === '#/tasks') ? '' : 'none';
    document.getElementById('view-settings').style.display = (hash === '#/settings') ? '' : 'none';
    window.scrollTo(0, 0);
    if (hash === '#/skills') renderSkillsDetail();
    else if (hash === '#/mcp') renderMcpDetail();
    else if (hash === '#/models') renderModelConfigDetail();
    else if (hash === '#/tasks') renderTasksDetail();
    else if (hash === '#/settings') renderSettings();
}

function renderSkillsDetail() {
    var data = statusData.skills;
    var list = document.getElementById('skillsDetailList');
    var stats = document.getElementById('skillsDetailStats');
    if (!data) { list.innerHTML = '<div class="empty">数据加载中...</div>'; return; }
    stats.innerHTML = '<span>共 <strong>' + data.total + '</strong> 个</span><span>已启用 <strong>' + data.enabledCount + '</strong></span>' + (data.disabledCount ? '<span>已禁用 <strong>' + data.disabledCount + '</strong></span>' : '') + '<span>本地可用 <strong>' + data.localCount + '</strong></span>';
    renderSkillsDetailList(data.skills);
}

function renderSkillCard(s) {
    var enabledChecked = s.enabled ? ' checked' : '';
    var badgeCls = s.enabled ? (s.local ? 'badge-local' : 'badge-remote') : 'badge-disabled';
    var badgeText = s.enabled ? (s.local ? '本地' : '仅 lock') : '已禁用';
    var desc = getSkillDesc(s);
    var actions = '<div class="skill-card-actions">' +
        '<label class="toggle-switch" title="启用/禁用"><input type="checkbox" onchange="toggleSkillEnabled(\'' + s.id + '\', this.checked)"' + enabledChecked + '><span class="toggle-slider"></span></label>' +
        '<button class="btn-task" onclick="openSkillEdit(\'' + s.id + '\')">编辑</button>' +
        '<button class="btn-task btn-danger" onclick="deleteSkill(\'' + s.id + '\')">卸载</button>' +
    '</div>';
    return '<div class="skill-card ' + (s.enabled ? '' : 'disabled') + '" data-skill-id="' + s.id + '"><div class="skill-card-header"><span class="skill-card-name">' + s.name + '</span><span class="badge ' + badgeCls + '">' + badgeText + '</span></div><div class="skill-card-desc">' + desc + '</div><div class="skill-card-meta"><span class="label">ID:</span> ' + s.id + '</div><div class="skill-card-meta"><span class="label">来源:</span> ' + (s.source || '未知') + '</div>' + (s.installedAt ? '<div class="skill-card-meta"><span class="label">安装时间:</span> ' + s.installedAt.slice(0, 10) + '</div>' : '') + actions + '</div>';
}

function renderSkillsDetailList(skills) {
    var list = document.getElementById('skillsDetailList');
    list.className = 'skill-grid';
    if (!skills || !skills.length) { list.innerHTML = '<div class="empty">暂无 Skills</div>'; return; }
    list.innerHTML = skills.map(renderSkillCard).join('');
}

function filterSkillsDetail(q) {
    var skills = statusData.skills ? statusData.skills.skills : [];
    var ql = (q || '').toLowerCase().trim();
    var filtered = ql ? skills.filter(function(s) {
        return (s.name || '').toLowerCase().indexOf(ql) !== -1 || (s.description || '').toLowerCase().indexOf(ql) !== -1 || (s.id || '').toLowerCase().indexOf(ql) !== -1;
    }) : skills;
    if (!filtered.length) { document.getElementById('skillsDetailList').innerHTML = '<div class="empty">未找到匹配的 Skill</div>'; return; }
    renderSkillsDetailList(filtered);
}

function renderMcpDetail() {
    var data = statusData.mcp;
    var list = document.getElementById('mcpDetailList');
    var stats = document.getElementById('mcpDetailStats');
    if (!data) { list.innerHTML = '<div class="empty">数据加载中...</div>'; return; }
    stats.innerHTML = '<span>共 <strong>' + data.total + '</strong> 个</span><span>已启用 <strong>' + data.enabled + '</strong></span>' + (data.disabled ? '<span>已禁用 <strong>' + data.disabled + '</strong></span>' : '') + '<span>可用 <strong>' + data.available + '</strong></span>';
    list.className = 'mcp-grid';
    if (!data.servers.length) { list.innerHTML = '<div class="empty">未配置 MCP</div>'; return; }
    list.innerHTML = data.servers.map(renderMcpCard).join('');
}

function _mcpTypeInfo(s) {
    var cmd = (s.command || '').toLowerCase();
    var args = s.args || [];
    var type = 'other', label = 'Other', cls = 'badge-remote';
    var display = '';

    if (cmd.endsWith('python.exe') || cmd.endsWith('python') || cmd.includes('python')) {
        type = 'python';
        label = 'Python';
        cls = 'badge-local';
        var script = args.find(function(a) { return a.toLowerCase().endsWith('.py'); }) || args[args.length - 1] || s.command;
        display = script.split('/').pop().split('\\').pop();
    } else if (cmd === 'npx' || cmd.endsWith('npx') || cmd.endsWith('npx.cmd')) {
        type = 'npx';
        label = 'NPX';
        cls = 'mcp-type-npx';
        var pkg = args.filter(function(a) { return a !== '-y'; }).pop() || '';
        display = pkg;
    } else if (cmd.endsWith('node.exe') || cmd.endsWith('node')) {
        type = 'node';
        label = 'Node';
        cls = 'mcp-type-node';
        var script = args.find(function(a) { return a.toLowerCase().endsWith('.js'); }) || args[args.length - 1] || s.command;
        display = script.split('/').pop().split('\\').pop();
    } else if (cmd.endsWith('.cmd') || cmd.endsWith('.bat')) {
        type = 'cmd';
        label = 'CMD';
        cls = 'mcp-type-cmd';
        display = s.command.split('/').pop().split('\\').pop();
    } else {
        display = s.command.split('/').pop().split('\\').pop();
    }
    return { type: type, label: label, cls: cls, display: display || s.command };
}

function _mcpCompactCommand(s) {
    var info = _mcpTypeInfo(s);
    return info.label + ': ' + info.display;
}

function _mcpDetailHtml(s) {
    var info = _mcpTypeInfo(s);
    var desc = s.description || getMcpDesc(s.name) || s.detail || '';
    var lines = [];
    if (desc) lines.push('<div class="mcp-detail-row"><span class="label">描述:</span> ' + desc + '</div>');
    lines.push('<div class="mcp-detail-row"><span class="label">类型:</span> <span class="badge ' + info.cls + '">' + info.label + '</span></div>');
    lines.push('<div class="mcp-detail-row"><span class="label">状态:</span> <span class="status ' + s.status + '"><span class="status-dot"></span>' + s.status + '</span></div>');
    lines.push('<div class="mcp-detail-row"><span class="label">命令:</span> <code>' + escapeHtml(s.command) + '</code></div>');
    if (s.args && s.args.length) {
        lines.push('<div class="mcp-detail-row"><span class="label">参数:</span></div>');
        lines.push('<ul class="mcp-detail-list">' + s.args.map(function(a) { return '<li><code>' + escapeHtml(a) + '</code></li>'; }).join('') + '</ul>');
    }
    if (s.cwd) lines.push('<div class="mcp-detail-row"><span class="label">cwd:</span> <code>' + escapeHtml(s.cwd) + '</code></div>');
    if (s.env && Object.keys(s.env).length) {
        lines.push('<div class="mcp-detail-row"><span class="label">环境变量:</span></div>');
        lines.push('<ul class="mcp-detail-list">' + Object.keys(s.env).map(function(k) { return '<li>' + escapeHtml(k) + '=<span class="mcp-secret">***</span></li>'; }).join('') + '</ul>');
    }
    return lines.join('');
}

var _currentMcpDetailId = null;

function openMcpDetail(mcpId) {
    var data = statusData.mcp;
    if (!data) return;
    var s = data.servers.find(function(x) { return x.name === mcpId; });
    if (!s) return;
    _currentMcpDetailId = mcpId;
    document.getElementById('mcp-detail-name').textContent = s.name;
    document.getElementById('mcp-detail-content').innerHTML = _mcpDetailHtml(s);
    document.getElementById('mcpDetailModal').style.display = '';
    document.body.style.overflow = 'hidden';
}

function closeMcpDetail() {
    document.getElementById('mcpDetailModal').style.display = 'none';
    document.body.style.overflow = '';
    _currentMcpDetailId = null;
}

function renderMcpCard(s) {
    var enabledChecked = s.enabled ? ' checked' : '';
    var statusCls = s.status;
    var desc = s.description || getMcpDesc(s.name) || s.detail || '';
    return '<div class="mcp-card ' + (s.enabled ? '' : 'disabled') + '" data-mcp-id="' + s.name + '" onclick="if(event.target===this)openMcpDetail(\'' + s.name + '\')">' +
        '<div class="mcp-card-header"><span class="mcp-card-name">' + s.name + '</span><span class="status ' + statusCls + '"><span class="status-dot"></span>' + s.status + '</span></div>' +
        (desc ? '<div class="mcp-card-desc">' + desc + '</div>' : '') +
        '<div class="mcp-card-actions">' +
            '<label class="toggle-switch" title="启用/禁用" onclick="event.stopPropagation()"><input type="checkbox" onchange="toggleMcpEnabled(\'' + s.name + '\', this.checked)"' + enabledChecked + '><span class="toggle-slider"></span></label>' +
            '<button class="btn-task" onclick="event.stopPropagation();openMcpDetail(\'' + s.name + '\')">详情</button>' +
            '<button class="btn-task" onclick="event.stopPropagation();openMcpEdit(\'' + s.name + '\')">编辑</button>' +
            '<button class="btn-task btn-danger" onclick="event.stopPropagation();deleteMcp(\'' + s.name + '\')">删除</button>' +
        '</div>' +
    '</div>';
}

// === Memory ===
var MEMORY_MCP_REPO = 'https://github.com/perinchiang/kimi-code-memory-mcp';

function renderMemoryEmptyMessage(offline) {
    var link = '<a href="' + MEMORY_MCP_REPO + '" target="_blank" style="color:var(--accent);text-decoration:underline;font-weight:600;">kimi-code-memory-mcp</a>';
    if (offline) {
        return 'Memory Gateway 未连接（127.0.0.1:8420）。<br>如需长期向量记忆，可搭配 ' + link + ' 使用；不需要可在<a href="#/settings" style="color:var(--accent);text-decoration:underline;">设置</a>中关闭 Memory Status 卡片。';
    }
    return 'Gateway 在线，但目前没有任何记忆数据。<br>系统会在多轮对话后自动提取 L0–L3 记忆；如果长时间未生成，请检查向量模型和 LLM API 配置是否正常。不需要可在<a href="#/settings" style="color:var(--accent);text-decoration:underline;">设置</a>中关闭。';
}

async function loadMemory() {
    try {
        var data = await fetchJSON('/api/memory');
        statusData.memory = data;
        if (!data.gatewayReachable) {
            document.getElementById('memorySummary').innerHTML = '<div class="memory-empty">' + renderMemoryEmptyMessage(true) + '</div>';
            document.getElementById('memoryChart').innerHTML = '';
            return;
        }
        var values = [
            { label: 'L0 原始对话', value: data.l0 },
            { label: 'L1 原子记忆', value: data.l1 },
            { label: 'L2 场景/指令', value: data.l2 },
            { label: 'L3 人格画像', value: data.l3 },
        ];
        var total = data.l0 + data.l1 + data.l2 + data.l3;
        if (total === 0) {
            document.getElementById('memorySummary').innerHTML = '<div class="memory-empty">' + renderMemoryEmptyMessage(false) + '</div>';
            document.getElementById('memoryChart').innerHTML = '';
            return;
        }
        var gwStatus = data.gatewayReachable ? 'Gateway 在线' : 'Gateway 离线';
        var layerStatus = (data.l0 >= 0 && data.l1 >= 0 && data.l2 >= 0 && data.l3 >= 0) ? '四级记忆正常' : '部分记忆层异常';
        document.getElementById('memorySummary').innerHTML = '<div class="memory-subtitle">共 ' + total + ' 条记忆</div><div class="memory-breakdown">' + gwStatus + ' · ' + layerStatus + '</div>';
        document.getElementById('memoryChart').innerHTML = renderDonut(values, total);
        attachDonutHover();
    } catch (e) { setError('memorySummary', '加载失败: ' + e.message); }
}

// === Kimi Usage + Quota ===
async function loadKimi() {
    try {
        var results = await Promise.all([
            fetchJSON('/api/kimi'),
            fetchJSON('/api/kimi-quota').catch(function() { return { configured: false, error: '查询失败' }; }),
        ]);
        var data = results[0], quota = results[1];
        statusData.kimi = data;

        var deviceLabel = data.deviceLabel || '本地';
        var dashboardVer = (window.dashboardVersion || '1.0.0');
        document.getElementById('kimiSummary').innerHTML =
            '<div class="metric">' + data.sessionCount + '</div>' +
            '<div class="metric-label">本地会话数量 &middot; ' + escapeHtml(deviceLabel) + '</div>' +
            '<div class="kimi-meta-row">' +
                '<span>Dashboard v' + escapeHtml(dashboardVer) + '</span>' +
                '<span class="sep">·</span>' +
                '<span>' + (data.loggedIn ? '已登录' : '未登录') + '</span>' +
                '<span class="sep">·</span>' +
                '<a class="console-link-inline" href="' + data.consoleUrl + '" target="_blank" rel="noopener">Console</a>' +
                '<span id="kimiUpdateBtnSlot" style="margin-left:0.4rem"></span>' +
            '</div>';

        var quotaHtml = '';
        if (!quota.configured) {
            quotaHtml = '<div class="hint"><strong>额度查询</strong><br>在 <code>~/.kimi-code/dashboard/.env</code> 写入 <code>KIMI_API_KEY=your-api-key</code> 后刷新，即可显示 5 小时窗口与 7 天窗口额度。<br>API Key 可在 <a class="console-link" href="' + data.consoleUrl + '" target="_blank" rel="noopener">Kimi Code Console</a> 创建。</div>';
        } else if (quota.error) {
            quotaHtml = '<div class="error">额度查询失败: ' + quota.error + '</div>';
        } else {
            var infoIconSvg = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
            var renderTierConsole = function(tier, title, tip) {
                if (!tier) return '';
                var pct = tier.limit > 0 ? Math.round((tier.used / tier.limit) * 100) : 0;
                var resetText = formatRemaining(tier.resetTime) || '-';
                var usedText = tier.used !== null ? formatTokens(tier.used) : '-';
                var limitText = tier.limit !== null ? formatTokens(tier.limit) : '-';
                return '<div class="quota-console-card" title="' + escapeHtml(tip) + '">' +
                    '<div class="quota-console-header">' + escapeHtml(title) + infoIconSvg + '</div>' +
                    '<div class="quota-console-body">' +
                        '<span class="quota-console-pct">' + pct + '%</span>' +
                        '<span class="quota-console-reset">' + escapeHtml(resetText) + ' 后重置</span>' +
                    '</div>' +
                    '<div class="quota-console-bar"><div class="quota-console-fill" style="width:' + pct + '%"></div></div>' +
                    '<div class="quota-console-meta"><span>已用 ' + usedText + '</span><span>上限 ' + limitText + '</span></div>' +
                '</div>';
            };
            quotaHtml = '<div class="quota-console-grid">' +
                renderTierConsole(quota.weekly, '本周用量', '最近 7 天累计用量') +
                renderTierConsole(quota.fiveHour, '频限明细', '最近 5 小时滑动窗口') +
            '</div>';
        }
        document.getElementById('kimiUsageInfo').innerHTML = quotaHtml;
    } catch (e) { setError('kimiSummary', '加载失败: ' + e.message); }
    renderVersionCheck();
}

// === Kimi Version Check & One-click Update ===
var updatePollTimer = null;

function setUpdateSlot(html) {
    var slot = document.getElementById('kimiUpdateBtnSlot');
    if (slot) slot.innerHTML = html;
}

async function checkKimiUpdate() {
    var box = document.getElementById('kimiVersionCheck');
    setUpdateSlot('<span class="vc-spinner" style="vertical-align:middle"></span><span style="font-size:0.72rem;color:var(--text-secondary);margin-left:0.3rem">检查中…</span>');
    if (box) box.innerHTML = '';
    try { var r = await fetchJSON('/api/kimi-update'); renderVersionCheck(r); }
    catch (e) {
        setUpdateSlot('<button class="vc-btn vc-btn-sm" onclick="checkKimiUpdate()">检查更新</button>');
        if (box) box.innerHTML = '<div class="vc-row vc-error">版本检查失败: ' + e.message + '</div>';
    }
}

function renderVersionCheck(r) {
    var box = document.getElementById('kimiVersionCheck');
    if (!box) return;
    if (r && r.error) {
        setUpdateSlot('<button class="vc-btn vc-btn-sm" onclick="checkKimiUpdate()">重试</button>');
        box.innerHTML = '<div class="vc-row"><span class="vc-error">最新版查询失败: ' + (r.message || r.error) + '</span></div>';
        return;
    }
    if (r && r.updateAvailable) {
        var notes = (r.releaseNotes || '').replace(/"/g, '&quot;').replace(/\n/g, ' ');
        setUpdateSlot('<button class="vc-btn vc-btn-sm" onclick="runKimiUpdate()">\u2b07 更新 Kimi Code</button>');
        var html = '<div class="vc-row"><span class="vc-tag">当前 <strong>' + r.current + '</strong></span><span class="vc-tag vc-tag-warn">\u2192 最新 <strong>' + r.latest + '</strong></span>';
        if (notes) html += '<a class="vc-link" href="' + r.releaseUrl + '" target="_blank" rel="noopener" title="' + notes + '">更新内容</a>';
        else if (r.releaseUrl) html += '<a class="vc-link" href="' + r.releaseUrl + '" target="_blank" rel="noopener">Release</a>';
        html += '</div>';
        box.innerHTML = html;
        return;
    }
    if (r && r.current) {
        setUpdateSlot('<span class="vc-tag vc-tag-ok" style="font-size:0.72rem;padding:0.12rem 0.45rem;cursor:pointer" onclick="checkKimiUpdate()" title="点击重新检查">\u2713 已是最新</span>');
        box.innerHTML = '';
        return;
    }
    // 默认/初始状态：手动检查按钮放在 Console 右侧 slot 里
    setUpdateSlot('<button class="vc-btn vc-btn-sm" onclick="checkKimiUpdate()">检查更新</button>');
    box.innerHTML = '';
}

async function runKimiUpdate() {
    var box = document.getElementById('kimiVersionCheck');
    if (!box) return;
    box.innerHTML = '<div class="vc-row"><span class="vc-spinner"></span><span style="font-size:0.78rem;color:var(--text-secondary)">正在下载并更新…</span></div><pre class="vc-log" id="vcLog"></pre>';
    if (updatePollTimer) { clearTimeout(updatePollTimer); updatePollTimer = null; }
    try {
        // POST instead of GET (security fix)
        var r = await postJSON('/api/kimi-update/run');
        if (r.status === 'error') {
            box.innerHTML = '<div class="vc-row vc-error">启动更新失败: ' + r.error + '</div><button class="vc-btn vc-btn-sm" onclick="checkKimiUpdate()">返回</button>';
            return;
        }
        pollUpdateStatus();
    } catch (e) { box.innerHTML = '<div class="vc-row vc-error">启动更新失败: ' + e.message + '</div>'; }
}

function pollUpdateStatus() {
    if (updatePollTimer) clearTimeout(updatePollTimer);
    fetchJSON('/api/kimi-update/status').then(function(s) {
        var log = document.getElementById('vcLog');
        if (log && s.log) { log.textContent = s.log.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, ''); log.scrollTop = log.scrollHeight; }
        if (s.running) { updatePollTimer = setTimeout(pollUpdateStatus, 1200); }
        else {
            var box = document.getElementById('kimiVersionCheck');
            if (!box) return;
            if (s.status === 'success') {
                box.innerHTML = '<div class="vc-row"><span class="vc-ok">\u2713 更新完成！</span></div><div class="vc-meta" style="margin-top:0.4rem">请刷新页面以加载新版本。</div><button class="vc-btn" style="margin-top:0.4rem" onclick="location.reload()">刷新页面</button>';
            } else {
                box.innerHTML = '<div class="vc-row vc-error">\u2717 更新未成功 (exit ' + s.exitCode + ')</div><pre class="vc-log">' + (s.log || '').replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '') + '</pre><button class="vc-btn vc-btn-sm" style="margin-top:0.4rem" onclick="checkKimiUpdate()">返回</button>';
            }
        }
    }).catch(function() { updatePollTimer = setTimeout(pollUpdateStatus, 2500); });
}

// === Trend rendering ===
function renderTrend(unit) {
    currentTrendUnit = unit;
    if (!trendData) return;
    var data = trendData[unit];
    document.getElementById('chartTooltip').classList.remove('show');
    var chartEl = document.getElementById('trendChart');
    if (unit === 'yearly') { chartEl.innerHTML = renderHeatmap(data); attachHeatmapHover(data); }
    else { chartEl.innerHTML = renderLineChart(data); attachChartHover(data); }
    var total = data.reduce(function(a, b) { return a + b.value; }, 0);
    document.getElementById('trendTotal').textContent = formatTokens(total);
    document.querySelectorAll('.trend-tab').forEach(function(btn) { btn.classList.toggle('active', btn.dataset.unit === unit); });
    // Update legend bar
    var legendEl = document.getElementById('trendLegend');
    if (legendEl && unit !== 'yearly') {
        legendEl.style.display = 'flex';
        legendEl.innerHTML =
            '<div class="trend-legend-item"><span class="trend-legend-swatch" style="background:var(--accent)"></span>输出</div>' +
            '<div class="trend-legend-item"><span class="trend-legend-swatch" style="background:var(--purple)"></span>输入</div>' +
            '<div class="trend-legend-item"><span class="trend-legend-swatch" style="background:var(--success)"></span>缓存命中</div>';
    } else if (legendEl) {
        legendEl.style.display = 'none';
    }
}

async function loadTrends() {
    document.getElementById('trendTotal').textContent = '-';
    document.getElementById('trendGrandTotal').textContent = '-';
    try {
        trendData = await fetchJSON('/api/kimi-trends');
        statusData.trends = trendData;
        renderTrend(currentTrendUnit);
        if (trendData.total) {
            document.getElementById('trendGrandTotal').textContent = formatTokens(trendData.total.value);
            var evalEl = document.getElementById('trendGrandTotalEval');
            var ev = trendData.total.cacheEvaluation;
            if (evalEl && ev && ev.level !== 'none') {
                evalEl.textContent = ev.label;
                evalEl.className = 'cache-eval-badge cache-eval-' + ev.level;
                evalEl.title = '缓存命中率 ' + (trendData.total.cacheRate || 0) + '%';
            } else if (evalEl) {
                evalEl.textContent = '';
                evalEl.className = 'cache-eval-badge';
            }
        }
    } catch (e) {
        setError('trendChart', '加载失败: ' + e.message);
        document.getElementById('trendTotal').textContent = '-';
        document.getElementById('trendGrandTotal').textContent = '-';
        var evalElErr = document.getElementById('trendGrandTotalEval');
        if (evalElErr) { evalElErr.textContent = ''; evalElErr.className = 'cache-eval-badge'; }
    }
}

// === Tool Usage ===
var toolSortState = { tool: false, skill: false, model: false }; // false=desc, true=asc

async function loadToolUsage() {
    try {
        var data = await fetchJSON('/api/tool-usage');
        statusData.toolUsage = data;
        document.getElementById('toolCallTotal').textContent = data.totalToolCalls;
        document.getElementById('skillCallTotal').textContent = data.totalSkillCalls;
        renderToolLeaderboard();
        renderSkillLeaderboard();
    } catch (e) { document.getElementById('toolUsageList').innerHTML = '<div class="error">加载失败: ' + e.message + '</div>'; }
}



var LB_MAX_ITEMS = 10;

function renderLeaderboardList(elemId, items, maxVal, totalCount, barClass, getDesc, formatCount) {
    var el = document.getElementById(elemId);
    if (!el) return;
    if (!items || items.length === 0) {
        el.innerHTML = '<div class="empty">暂无数据</div>';
        return;
    }
    var shown = items.slice(0, LB_MAX_ITEMS);
    var remaining = items.length - shown.length;
    var html = shown.map(function(item, i) {
        var pct = Math.round(item.count / maxVal * 100);
        var sharePct = (item.count / totalCount * 100).toFixed(1);
        var name = item.name || item.model;
        var desc = getDesc ? getDesc(item) : '';
        var top1 = i === 0 ? ' top1' : '';
        var countText = formatCount ? formatCount(item.count) : item.count;
        var nameAttr = desc || name;
        if (item.model) name = name.replace('kimi-code/', '');
        return '<div class="leaderboard-item' + top1 + '"><span class="leaderboard-rank">' + (i+1) + '</span><span class="leaderboard-name" title="' + nameAttr + '">' + name + '</span><div class="leaderboard-bar-wrap"><div class="leaderboard-bar ' + barClass + '" style="width:' + pct + '%">' + (pct > 15 ? '<span class="leaderboard-bar-pct">' + sharePct + '%</span>' : '') + '</div></div><span class="leaderboard-count">' + countText + '</span></div>';
    }).join('');
    if (remaining > 0) {
        html += '<div class="lb-more">还有 ' + remaining + ' 个未显示</div>';
    }
    el.innerHTML = html;
}

function renderToolLeaderboard() {
    var data = statusData.toolUsage;
    if (!data || !data.tools) return;
    var sorted = data.tools.slice().sort(function(a, b) {
        return toolSortState.tool ? a.count - b.count : b.count - a.count;
    });
    var maxTool = data.tools.length > 0 ? data.tools[0].count : 1;
    renderLeaderboardList('toolUsageList', sorted, maxTool, data.totalToolCalls || 1, 'tool');
}

function renderSkillLeaderboard() {
    var data = statusData.toolUsage;
    if (!data || !data.skills) return;
    if (data.skills.length === 0) {
        document.getElementById('skillUsageList').innerHTML = '<div class="empty">暂无 Skill 调用记录</div>';
        return;
    }
    var sorted = data.skills.slice().sort(function(a, b) {
        return toolSortState.skill ? a.count - b.count : b.count - a.count;
    });
    var maxSkill = data.skills[0].count;
    var descFn = function(s) { return SKILL_DESC[s.name] || ''; };
    renderLeaderboardList('skillUsageList', sorted, maxSkill, data.totalSkillCalls || 1, 'skill', descFn);
}

function toggleSort(type) {
    toolSortState[type] = !toolSortState[type];
    var btnId = type === 'tool' ? 'sortToolBtn' : type === 'skill' ? 'sortSkillBtn' : 'sortModelBtn';
    var btn = document.getElementById(btnId);
    if (btn) {
        if (toolSortState[type]) btn.classList.add('asc');
        else btn.classList.remove('asc');
    }
    if (type === 'tool') renderToolLeaderboard();
    else if (type === 'skill') renderSkillLeaderboard();
    else if (type === 'model') renderModelLeaderboard();
}

// === Model Usage (new feature) ===
async function loadModelUsage() {
    try {
        var data = await fetchJSON('/api/model-usage');
        statusData.modelUsage = data;
        renderModelLeaderboard();
    } catch (e) {
        var el2 = document.getElementById('modelUsageList');
        if (el2) el2.innerHTML = '<div class="error">加载失败: ' + e.message + '</div>';
    }
}

function renderModelLeaderboard() {
    var data = statusData.modelUsage;
    if (!data) return;
    var totalEl = document.getElementById('modelTotalCalls');
    var chartEl = document.getElementById('modelChart');
    if (!chartEl) return;
    totalEl.textContent = formatTokens(data.totalCalls || 0);
    if (!data.models || data.models.length === 0) {
        chartEl.innerHTML = '<div class="empty">暂无模型用量数据</div>';
        return;
    }
    var total = data.models.reduce(function(s, m) { return s + m.total; }, 0);
    var sorted = data.models.slice().sort(function(a, b) {
        return toolSortState.model ? a.total - b.total : b.total - a.total;
    });
    var maxTokens = data.models[0].total || 1;
    var colors = ['var(--accent)', 'var(--purple)', 'var(--success)', 'var(--warning)', 'var(--danger)'];
    var items = sorted.map(function(m) {
        return { name: m.model, count: m.total, _color: colors[sorted.indexOf(m) % colors.length] };
    });
    // Custom render for model (uses formatTokens + custom bar color)
    var shown = items.slice(0, LB_MAX_ITEMS);
    var remaining = items.length - shown.length;
    chartEl.innerHTML = shown.map(function(item, i) {
        var pct = Math.round(item.count / maxTokens * 100);
        var sharePct = (item.count / total * 100).toFixed(1);
        var shortName = item.name.replace('kimi-code/', '');
        var top1 = i === 0 ? ' top1' : '';
        return '<div class="leaderboard-item' + top1 + '"><span class="leaderboard-rank">' + (i+1) + '</span><span class="model-bar-name" title="' + item.name + '">' + shortName + '</span><div class="leaderboard-bar-wrap"><div class="leaderboard-bar" style="width:' + pct + '%;background:' + item._color + '">' + (pct > 15 ? '<span class="leaderboard-bar-pct">' + sharePct + '%</span>' : '') + '</div></div><span class="model-bar-count">' + formatTokens(item.count) + '</span></div>';
    }).join('');
    if (remaining > 0) {
        chartEl.innerHTML += '<div class="lb-more">还有 ' + remaining + ' 个未显示</div>';
    }
    var tooltip = document.getElementById('modelTooltip');
    if (tooltip) tooltip.classList.remove('show');
}

// === Model Config (third-party providers / models) ===
var MODEL_CONFIG_TYPES = [
    { value: 'auto', label: '自动识别（推荐）' },
    { value: 'openai', label: 'OpenAI 兼容' },
    { value: 'anthropic', label: 'Anthropic Claude' },
    { value: 'kimi', label: 'Kimi / Moonshot' },
    { value: 'google-genai', label: 'Google Gemini' },
    { value: 'openai_responses', label: 'OpenAI Responses API' },
    { value: 'vertexai', label: 'Google Vertex AI' },
];
var MODEL_CONFIG_TYPE_LABEL = {
    'auto': '自动识别',
    'openai': 'OpenAI 兼容',
    'anthropic': 'Anthropic Claude',
    'kimi': 'Kimi / Moonshot',
    'google-genai': 'Google Gemini',
    'openai_responses': 'OpenAI Responses API',
    'vertexai': 'Google Vertex AI',
};
var MODEL_CONFIG_CAPS = ['thinking', 'always_thinking', 'image_in', 'video_in', 'tool_use'];
var PROVIDER_PRESETS = [
    { name: 'MiniMax Token 计划', id: 'minimax', base_url: 'https://api.minimaxi.com/v1' },
    { name: 'DeepSeek API', id: 'deepseek', base_url: 'https://api.deepseek.com/v1' },
    { name: 'OpenCode GO', id: 'opencode', base_url: 'https://opencode.ai/zen/go/v1' },
    { name: '腾讯混元 Token 计划', id: 'tencent-hunyuan', base_url: 'https://api.hunyuan.cloud.tencent.com/v1' },
    { name: '阿里云百炼', id: 'bailian', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
];
var MODEL_CONTEXT_OPTIONS = [
    { value: 8192, label: '8K' },
    { value: 32768, label: '32K' },
    { value: 128000, label: '128K' },
    { value: 200000, label: '200K' },
    { value: 256000, label: '256K' },
    { value: 512000, label: '512K' },
    { value: 1000000, label: '1M' },
];
var MODEL_MAX_TOKENS_OPTIONS = [
    { value: 4096, label: '4K' },
    { value: 8192, label: '8K' },
    { value: 16384, label: '16K' },
    { value: 32768, label: '32K' },
    { value: 64000, label: '64K' },
    { value: 128000, label: '128K' },
];
var MASKED_KEY = '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022';

function escapeHtml(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function loadModelConfig() {
    try {
        var data = await fetchJSON('/api/model-config');
        statusData.modelConfig = data;
        var pCount = (data.providers || []).length;
        var mCount = (data.models || []).length;
        document.getElementById('modelConfigMetric').textContent = pCount + '/' + mCount;
        document.getElementById('modelConfigLabel').textContent = 'Providers / Models';
        if (location.hash === '#/models') renderModelConfigDetail();
    } catch (e) {
        document.getElementById('modelConfigMetric').textContent = '!';
        document.getElementById('modelConfigLabel').textContent = '加载失败';
    }
}

function renderModelConfigDetail() {
    var data = statusData.modelConfig;
    if (!data) { document.getElementById('providersList').innerHTML = '<div class="empty">加载中...</div>'; return; }

    // Default model selector
    var sel = document.getElementById('defaultModelSelect');
    sel.innerHTML = '<option value="">-- 选择默认模型 --</option>' +
        (data.models || []).map(function(m) {
            return '<option value="' + escapeHtml(m.id) + '"' + (m.id === data.default_model ? ' selected' : '') + '>' + escapeHtml(m.id) + '</option>';
        }).join('');

    // Providers list
    var providersHtml = (data.providers || []).map(function(p) {
        return '<div class="config-item" id="provider-row-' + escapeHtml(p.id) + '">' +
            '<div class="config-item-title"><span>' + escapeHtml(p.id) + '</span><span class="badge badge-local">' + escapeHtml(MODEL_CONFIG_TYPE_LABEL[p.type] || p.type) + '</span></div>' +
            '<div class="config-item-meta">' + escapeHtml(p.base_url) + '</div>' +
            '<div class="config-item-actions">' +
                '<button class="btn-task" onclick="detectModels(\'' + escapeHtml(p.id).replace(/'/g, "\\'") + '\')">探测模型</button>' +
                '<button class="btn-task" onclick="editProvider(\'' + escapeHtml(p.id).replace(/'/g, "\\'") + '\')">编辑</button>' +
                '<button class="btn-task" onclick="deleteProvider(\'' + escapeHtml(p.id).replace(/'/g, "\\'") + '\')">删除</button>' +
            '</div>' +
        '</div>';
    }).join('');
    if (!providersHtml) providersHtml = '<div class="empty">暂无 Provider，点击右上角添加</div>';
    document.getElementById('providersList').innerHTML = providersHtml;

    // Provider filter for models
    var filterSel = document.getElementById('modelProviderFilter');
    var currentFilter = filterSel ? filterSel.value : '';
    var filterOptions = '<option value="">全部 provider</option>' +
        (data.providers || []).map(function(p) {
            return '<option value="' + escapeHtml(p.id) + '"' + (p.id === currentFilter ? ' selected' : '') + '>' + escapeHtml(p.id) + '</option>';
        }).join('');
    if (filterSel) filterSel.innerHTML = filterOptions;

    // Models list
    var filterValue = filterSel ? filterSel.value : '';
    var filteredModels = (data.models || []).filter(function(m) {
        return !filterValue || m.provider === filterValue;
    });
    var modelsHtml = filteredModels.map(function(m) {
        var isDefault = m.id === data.default_model;
        var meta = 'provider=' + escapeHtml(m.provider) + ' &middot; model=' + escapeHtml(m.model) +
            ' &middot; ctx=' + (m.max_context_size || 0).toLocaleString();
        if (m.max_tokens) meta += ' &middot; max_tokens=' + m.max_tokens.toLocaleString();
        return '<div class="config-item" id="model-row-' + escapeHtml(m.id) + '">' +
            '<div class="config-item-title"><span>' + escapeHtml(m.id) + '</span>' + (isDefault ? '<span class="badge badge-local">默认</span>' : '') + '</div>' +
            '<div class="config-item-meta">' + meta + '</div>' +
            '<div class="config-item-caps">' + (m.capabilities || []).map(function(c) { return '<span class="cap-badge">' + escapeHtml(c) + '</span>'; }).join('') + '</div>' +
            '<div class="config-item-actions">' +
                '<button class="btn-task" onclick="editModel(\'' + escapeHtml(m.id).replace(/'/g, "\\'") + '\')">编辑</button>' +
                '<button class="btn-task" onclick="deleteModel(\'' + escapeHtml(m.id).replace(/'/g, "\\'") + '\')">删除</button>' +
            '</div>' +
        '</div>';
    }).join('');
    if (!modelsHtml) {
        modelsHtml = '<div class="empty">' + (filterValue ? '该 provider 下暂无 Model' : '暂无 Model，点击右上角添加') + '</div>';
    }
    document.getElementById('modelsList').innerHTML = modelsHtml;
}

function providerFormHtml(p) {
    p = p || {};
    var typeOptions = MODEL_CONFIG_TYPES.map(function(t) {
        return '<option value="' + t.value + '"' + (p.type === t.value ? ' selected' : '') + '>' + escapeHtml(t.label) + '</option>';
    }).join('');
    var presetHtml = '';
    if (!p.id) {
        var presetOptions = '<option value="">-- 选择预设提供商（可选）--</option>' +
            PROVIDER_PRESETS.map(function(pr) {
                return '<option value="' + escapeHtml(pr.id) + '">' + escapeHtml(pr.name) + '</option>';
            }).join('');
        presetHtml = '<label>预设提供商</label><select id="provider-preset" onchange="applyProviderPreset(this.value)">' + presetOptions + '</select>';
    }
    return '<div class="config-form">' +
        presetHtml +
        '<label>ID</label><input type="text" id="provider-id" value="' + escapeHtml(p.id) + '"' + (p.id ? ' disabled' : '') + ' placeholder="例如 openai">' +
        '<label>类型</label><select id="provider-type">' + typeOptions + '</select>' +
        '<label>Base URL</label><input type="text" id="provider-base_url" value="' + escapeHtml(p.base_url) + '" placeholder="https://api.example.com/v1">' +
        '<label>API Key</label><input type="password" id="provider-api_key" value="' + (p.api_key ? escapeHtml(MASKED_KEY) : '') + '" placeholder="留空则保留原值">' +
        '<div class="config-form-actions">' +
            '<button class="btn-task" onclick="saveProvider()">保存</button>' +
            '<button class="btn-task" onclick="renderModelConfigDetail()">取消</button>' +
        '</div>' +
    '</div>';
}

function applyProviderPreset(presetId) {
    var preset = PROVIDER_PRESETS.find(function(pr) { return pr.id === presetId; });
    if (!preset) return;
    var idInput = document.getElementById('provider-id');
    var baseUrlInput = document.getElementById('provider-base_url');
    if (idInput && !idInput.value.trim()) idInput.value = preset.id;
    if (baseUrlInput) baseUrlInput.value = preset.base_url;
}

function editProvider(id) {
    var data = statusData.modelConfig;
    var p = id ? (data.providers || []).find(function(x) { return x.id === id; }) : null;
    var row = document.getElementById(id ? 'provider-row-' + id : 'providersList');
    if (!row) return;
    row.innerHTML = providerFormHtml(p);
}

async function saveProvider() {
    var idInput = document.getElementById('provider-id');
    var id = idInput ? idInput.value.trim() : '';
    if (!id) return alert('Provider ID 不能为空');
    var body = {
        id: id,
        type: document.getElementById('provider-type').value,
        base_url: document.getElementById('provider-base_url').value.trim(),
        api_key: document.getElementById('provider-api_key').value,
    };
    try {
        await fetchJSON('/api/model-config/provider', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        await loadModelConfig();
    } catch (e) { alert('保存失败: ' + e.message); }
}

async function deleteProvider(id) {
    if (!confirm('确定删除 provider "' + id + '"？引用它的 model 将失效。')) return;
    try {
        await fetchJSON('/api/model-config/provider/' + encodeURIComponent(id), { method: 'DELETE' });
        await loadModelConfig();
    } catch (e) { alert('删除失败: ' + e.message); }
}

function toggleDetectedBubble(el) {
    el.classList.toggle('selected');
}

async function detectModels(id) {
    var row = document.getElementById('provider-row-' + id);
    if (!row) return;
    row.innerHTML = '<div class="config-form"><div class="hint">正在探测模型...</div></div>';
    try {
        var data = await fetchJSON('/api/model-config/provider/' + encodeURIComponent(id) + '/detect-models', { method: 'POST' });
        var models = data.models || [];
        if (!models.length) {
            row.innerHTML = '<div class="config-form"><div class="hint">没有发现新模型（可能都已添加，或 provider 未返回模型列表）。</div><div class="config-form-actions"><button class="btn-task" onclick="renderModelConfigDetail()">返回</button></div></div>';
            return;
        }
        var bubbles = models.map(function(m, i) {
            return '<div class="detect-bubble" role="button" onclick="toggleDetectedBubble(this)" data-id="' + escapeHtml(m.id) + '" data-ctx="' + (m.max_context_size || 128000) + '" data-max-tokens="' + (m.max_tokens || 4096) + '" data-caps="' + escapeHtml((m.capabilities || []).join(',')) + '">' +
                escapeHtml(m.id) +
            '</div>';
        }).join('');
        row.innerHTML = '<div class="config-form">' +
            '<label>探测到 ' + models.length + ' 个模型，点击泡泡选择（provider: ' + escapeHtml(id) + '）</label>' +
            '<div class="detect-bubble-group">' + bubbles + '</div>' +
            '<div class="config-form-actions">' +
                '<button class="btn-task" onclick="addDetectedModels(\'' + escapeHtml(id).replace(/'/g, "\\'") + '\')">添加选中模型</button>' +
                '<button class="btn-task" onclick="renderModelConfigDetail()">取消</button>' +
            '</div>' +
        '</div>';
    } catch (e) {
        row.innerHTML = '<div class="config-form"><div class="error">探测失败: ' + escapeHtml(e.message) + '</div><div class="config-form-actions"><button class="btn-task" onclick="renderModelConfigDetail()">返回</button></div></div>';
    }
}

async function addDetectedModels(id) {
    var selected = [];
    document.querySelectorAll('.detect-bubble.selected').forEach(function(el) {
        selected.push({
            id: el.getAttribute('data-id'),
            ctx: parseInt(el.getAttribute('data-ctx'), 10) || 128000,
            max_tokens: parseInt(el.getAttribute('data-max-tokens'), 10) || 4096,
            caps: (el.getAttribute('data-caps') || '').split(',').filter(function(c) { return c; }),
        });
    });
    if (!selected.length) return alert('请至少选择一个模型');
    var errors = [];
    for (var i = 0; i < selected.length; i++) {
        var m = selected[i];
        try {
            await fetchJSON('/api/model-config/model', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    id: m.id,
                    provider: id,
                    model: m.id,
                    display_name: m.id,
                    max_context_size: m.ctx,
                    max_tokens: m.max_tokens,
                    capabilities: m.caps,
                })
            });
        } catch (e) {
            errors.push(m.id + ': ' + e.message);
        }
    }
    if (errors.length) {
        alert('部分模型添加失败:\n' + errors.join('\n'));
    }
    await loadModelConfig();
}

function toggleOptionBubble(el, groupClass) {
    if (el.classList.contains('selected')) {
        el.classList.remove('selected');
        return;
    }
    document.querySelectorAll('.' + groupClass + ' .option-bubble').forEach(function(b) { b.classList.remove('selected'); });
    el.classList.add('selected');
}

function toggleCapBubble(el) {
    el.classList.toggle('selected');
}

function modelFormHtml(m) {
    m = m || {};
    var providers = (statusData.modelConfig && statusData.modelConfig.providers) || [];
    var providerOptions = providers.map(function(p) {
        return '<option value="' + escapeHtml(p.id) + '"' + (m.provider === p.id ? ' selected' : '') + '>' + escapeHtml(p.id) + '</option>';
    }).join('');

    var currentCtx = m.max_context_size || 128000;
    var ctxBubbles = MODEL_CONTEXT_OPTIONS.map(function(o) {
        return '<div class="option-bubble' + (o.value === currentCtx ? ' selected' : '') + '" role="button" onclick="toggleOptionBubble(this, \'ctx-bubble-group\')" data-value="' + o.value + '">' + escapeHtml(o.label) + '</div>';
    }).join('');

    var currentMaxTokens = m.max_tokens || 4096;
    var maxTokensBubbles = MODEL_MAX_TOKENS_OPTIONS.map(function(o) {
        return '<div class="option-bubble' + (o.value === currentMaxTokens ? ' selected' : '') + '" role="button" onclick="toggleOptionBubble(this, \'maxtokens-bubble-group\')" data-value="' + o.value + '">' + escapeHtml(o.label) + '</div>';
    }).join('');

    var capBubbles = MODEL_CONFIG_CAPS.map(function(c) {
        return '<div class="option-bubble cap-bubble' + ((m.capabilities || []).indexOf(c) !== -1 ? ' selected' : '') + '" role="button" onclick="toggleCapBubble(this)" data-value="' + c + '">' + escapeHtml(c) + '</div>';
    }).join('');

    return '<div class="config-form">' +
        '<label>Model ID（配置键名）</label><input type="text" id="model-id" value="' + escapeHtml(m.id) + '"' + (m.id ? ' disabled' : '') + ' placeholder="例如 gpt-4.1">' +
        '<label>Provider</label><select id="model-provider">' + providerOptions + '</select>' +
        '<label>API Model 名称</label><input type="text" id="model-model" value="' + escapeHtml(m.model) + '" placeholder="例如 gpt-4.1">' +
        '<label>显示名称</label><input type="text" id="model-display_name" value="' + escapeHtml(m.display_name) + '" placeholder="可选">' +
        '<label>上下文长度</label><div class="option-bubble-group ctx-bubble-group">' + ctxBubbles + '</div>' +
        '<label>Max Tokens</label><div class="option-bubble-group maxtokens-bubble-group">' + maxTokensBubbles + '</div>' +
        '<label>Capabilities</label><div class="option-bubble-group cap-bubble-group">' + capBubbles + '</div>' +
        '<div class="config-form-actions">' +
            '<button class="btn-task" onclick="saveModel()">保存</button>' +
            '<button class="btn-task" onclick="renderModelConfigDetail()">取消</button>' +
        '</div>' +
    '</div>';
}

function editModel(id) {
    var data = statusData.modelConfig;
    var m = id ? (data.models || []).find(function(x) { return x.id === id; }) : null;
    var row = document.getElementById(id ? 'model-row-' + id : 'modelsList');
    if (!row) return;
    row.innerHTML = modelFormHtml(m);
}

async function saveModel() {
    var idInput = document.getElementById('model-id');
    var id = idInput ? idInput.value.trim() : '';
    if (!id) return alert('Model ID 不能为空');

    var ctxEl = document.querySelector('.ctx-bubble-group .option-bubble.selected');
    var maxTokensEl = document.querySelector('.maxtokens-bubble-group .option-bubble.selected');
    var caps = [];
    document.querySelectorAll('.cap-bubble-group .option-bubble.selected').forEach(function(b) { caps.push(b.getAttribute('data-value')); });

    var body = {
        id: id,
        provider: document.getElementById('model-provider').value,
        model: document.getElementById('model-model').value.trim(),
        display_name: document.getElementById('model-display_name').value.trim(),
        max_context_size: ctxEl ? parseInt(ctxEl.getAttribute('data-value'), 10) : 128000,
        max_tokens: maxTokensEl ? parseInt(maxTokensEl.getAttribute('data-value'), 10) : 4096,
        capabilities: caps,
    };
    try {
        await fetchJSON('/api/model-config/model', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        await loadModelConfig();
    } catch (e) { alert('保存失败: ' + e.message); }
}

async function deleteModel(id) {
    if (!confirm('确定删除 model "' + id + '"？')) return;
    try {
        await fetchJSON('/api/model-config/model/' + encodeURIComponent(id), { method: 'DELETE' });
        await loadModelConfig();
    } catch (e) { alert('删除失败: ' + e.message); }
}

async function setDefaultModel(id) {
    if (!id) return;
    try {
        await fetchJSON('/api/model-config/default-model', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: id }) });
        await loadModelConfig();
    } catch (e) { alert('设置默认模型失败: ' + e.message); }
}

// === Settings ===
function renderSettings() {
    var isLocal = settings.kw_bind === '127.0.0.1';

    function buildControl(item) {
        if (item.type === 'select') {
            var cur = settings[item.key];
            var opts = item.options.map(function(o) {
                var sel = (o.v === cur) ? ' selected' : '';
                return '<option value="' + escapeHtml(o.v) + '"' + sel + '>' + escapeHtml(o.t) + '</option>';
            }).join('');
            return '<select class="search-box" onchange="setSetting(\'' + item.key + '\', this.value)">' + opts + '</select>';
        }
        if (item.type === 'segment') {
            var cur = settings[item.key];
            var btns = item.options.map(function(o) {
                var active = (o.v === cur) ? ' active' : '';
                return '<button type="button" class="segment-btn' + active + '" onclick="setSetting(\'' + item.key + '\', \'' + escapeHtml(o.v) + '\')">' + escapeHtml(o.t) + '</button>';
            }).join('');
            return '<div class="segment-control">' + btns + '</div>';
        }
        if (item.type === 'text') {
            var val = settings[item.key] || '';
            return '<input type="text" class="search-box" value="' + escapeHtml(val) + '" oninput="setSetting(\'' + item.key + '\', this.value)" onblur="setSetting(\'' + item.key + '\', normalizePublicUrl(this.value))" placeholder="https://your-domain.com:port">';
        }
        if (item.type === 'number') {
            var val = settings[item.key] || 0;
            return '<input type="number" class="search-box" style="width:100px" value="' + escapeHtml(String(val)) + '" oninput="setSetting(\'' + item.key + '\', parseInt(this.value,10)||5494)">';
        }
        if (item.type === 'startup_toggle') {
            if (!startupServiceState.loaded) {
                return '<span style="color:var(--text-tertiary);font-size:0.8rem">检测中...</span>';
            }
            if (!startupServiceState.supported) {
                return '<span style="color:var(--text-tertiary);font-size:0.8rem">仅 macOS / Windows 可用</span>';
            }
            var svc = 'kimi';
            var checked = startupServiceState[svc].enabled ? ' checked' : '';
            return '<label class="toggle-switch">' +
                '<input type="checkbox" onchange="toggleStartupService(\'' + svc + '\', this.checked)"' + checked + '>' +
                '<span class="toggle-slider"></span>' +
            '</label>';
        }
        // toggle
        var checked = settings[item.key] ? ' checked' : '';
        return '<label class="toggle-switch">' +
            '<input type="checkbox" onchange="setSetting(\'' + item.key + '\', this.checked)"' + checked + '>' +
            '<span class="toggle-slider"></span>' +
        '</label>';
    }

    function renderItem(item) {
        // 本机模式下隐藏外网专属设置
        if (isLocal && item.key === 'kw_public_url') return '';

        var infoHtml = '<div class="settings-info">' +
            '<div class="config-item-title">' + escapeHtml(item.label) + '</div>' +
            '<div class="config-item-meta">' + escapeHtml(item.desc) + '</div>' +
        '</div>';

        // 水平布局：标签在左，控件在右
        if (item.row) {
            var wideCls = item.wide ? ' wide' : '';
            return '<div class="settings-item settings-item-row' + wideCls + '">' +
                infoHtml +
                '<div class="settings-control">' + buildControl(item) + '</div>' +
            '</div>';
        }

        // 默认布局：开关在左，标签在右
        return '<div class="settings-item">' +
            '<div class="settings-toggle">' +
                '<label class="toggle-switch">' +
                    '<input type="checkbox" onchange="setSetting(\'' + item.key + '\', this.checked)"' + (settings[item.key] ? ' checked' : '') + '>' +
                    '<span class="toggle-slider"></span>' +
                '</label>' +
            '</div>' +
            infoHtml +
        '</div>';
    }

    var html = SETTINGS_GROUPS.map(function(group) {
        var itemsHtml = group.items.map(renderItem).join('');
        if (!itemsHtml) return '';  // 整组为空则跳过
        return '<div class="settings-group">' +
            '<div class="settings-group-header">' +
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + group.icon + '</svg>' +
                '<span class="settings-group-title">' + escapeHtml(group.title) + '</span>' +
                '<span class="settings-group-desc">' + escapeHtml(group.desc) + '</span>' +
            '</div>' +
            '<div class="settings-group-body">' + itemsHtml + '</div>' +
        '</div>';
    }).join('');

    html += '<div class="config-form-actions" style="margin-top:1rem">' +
        '<button class="btn-task" onclick="resetSettings()">恢复默认</button>' +
    '</div>';
    document.getElementById('settingsList').innerHTML = html;
}

// === Scheduled Tasks ===
function renderTaskSources(sources, logPreview) {
    if (!sources || sources.length === 0) return '';
    var sourceStatus = {};
    if (logPreview) {
        sources.forEach(function(src) {
            var re = new RegExp('\\[' + src + '\\]\\s*(OK|FAIL|ERROR)', 'i');
            var m = logPreview.match(re);
            if (m) sourceStatus[src] = m[1].toUpperCase() === 'OK' ? 'ok' : 'fail';
        });
    }
    return '<div class="task-sources">' + sources.map(function(s) {
        var cls = sourceStatus[s] || 'neutral';
        var icon = cls === 'ok' ? ' \u2713' : (cls === 'fail' ? ' \u2717' : '');
        return '<span class="task-source ' + cls + '">' + s + icon + '</span>';
    }).join('') + '</div>';
}

function renderTaskCard(t) {
    var s = t.status || {};
    var stateCls = 'unregistered', stateLabel = '未注册';
    if (s.registered) {
        if (s.state === 'Ready') { stateCls = 'ready'; stateLabel = '就绪'; }
        else if (s.state === 'Running') { stateCls = 'running'; stateLabel = '运行中'; }
        else if (s.state === 'Disabled') { stateCls = 'disabled'; stateLabel = '已禁用'; }
        else { stateCls = 'ready'; stateLabel = s.state; }
    }
    var resultStatus = s.resultStatus || { label: '未知', ok: null };
    var resultColor = resultStatus.ok === true ? 'var(--success)' : (resultStatus.ok === false ? 'var(--danger)' : 'var(--text-secondary)');
    var resultLabel = '<span style="color:' + resultColor + '">' + resultStatus.label + '</span>';
    var enabledChecked = t.enabled ? ' checked' : '';
    return '<div class="task-card" data-task-id="' + t.id + '"><div class="task-card-header"><span class="task-card-name">' + t.name + '</span><span class="task-state-badge ' + stateCls + '">' + stateLabel + '</span></div><div class="task-card-desc">' + t.description + '</div><div class="task-card-schedule">\u23f0 ' + t.schedule + '</div>' + renderTaskSources(t.sources, t.logPreview) + '<div class="task-card-info">' + (s.lastRun && s.lastRun !== '1999-11-30T00:00:00' ? '<div><span class="label">上次运行:</span> ' + s.lastRun.replace('T', ' ') + '</div>' : '<div><span class="label">上次运行:</span> 尚未运行</div>') + (s.nextRun ? '<div><span class="label">下次运行:</span> ' + s.nextRun.replace('T', ' ') + '</div>' : '') + (resultStatus.label ? '<div><span class="label">运行结果:</span> ' + resultLabel + '</div>' : '') + '</div><div class="task-card-actions"><label class="toggle-switch" title="启用/禁用"><input type="checkbox" onchange="toggleTaskEnabled(\'' + t.id + '\', this.checked)"' + enabledChecked + '><span class="toggle-slider"></span></label><button class="btn-task" onclick="runTask(\'' + t.id + '\', this)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 3 20 12 6 21 6 3"/></svg>立即运行</button><button class="btn-task" onclick="openTaskEdit(\'' + t.id + '\')">编辑</button>' + (t.logFile ? '<button class="btn-task" onclick="openTaskLog(\'' + t.id + '\')">日志</button>' : '') + '<button class="btn-task btn-danger" onclick="deleteTask(\'' + t.id + '\')">删除</button></div></div>';
}

function renderTasksDetail() {
    var data = statusData.tasks;
    var grid = document.getElementById('tasksDetailGrid');
    var stats = document.getElementById('tasksDetailStats');
    if (!data) {
        if (grid) grid.innerHTML = '<div class="empty">数据加载中...</div>';
        if (stats) stats.innerHTML = '';
        loadTasks();
        return;
    }
    var total = data.total || 0;
    var counts = { ready: 0, running: 0, disabled: 0, failed: 0, unregistered: 0 };
    data.tasks.forEach(function(t) {
        var s = t.status || {};
        if (!s.registered) { counts.unregistered++; return; }
        if (s.state === 'Ready') counts.ready++;
        else if (s.state === 'Running') counts.running++;
        else if (s.state === 'Disabled') counts.disabled++;
        else counts.ready++;
        var rs = s.resultStatus || {};
        if (rs.ok === false && s.state !== 'Running') counts.failed++;
    });
    if (stats) {
        var statItems = ['<span>共 <strong>' + total + '</strong> 个</span>'];
        if (counts.running) statItems.push('<span>运行中 <strong>' + counts.running + '</strong></span>');
        if (counts.ready) statItems.push('<span>就绪 <strong>' + counts.ready + '</strong></span>');
        if (counts.failed) statItems.push('<span>失败 <strong>' + counts.failed + '</strong></span>');
        if (counts.disabled) statItems.push('<span>已禁用 <strong>' + counts.disabled + '</strong></span>');
        if (counts.unregistered) statItems.push('<span>未注册 <strong>' + counts.unregistered + '</strong></span>');
        stats.innerHTML = statItems.join('');
    }
    if (!data.tasks.length) { grid.innerHTML = '<div class="empty">暂无定时任务</div>'; return; }
    grid.innerHTML = data.tasks.map(renderTaskCard).join('');
}

async function loadTasks() {
    try {
        var data = await fetchJSON('/api/tasks');
        statusData.tasks = data;
        var total = data.total || 0;

        // Render mini dashboard
        var counts = { ready: 0, running: 0, disabled: 0, failed: 0, unregistered: 0 };
        data.tasks.forEach(function(t) {
            var s = t.status || {};
            if (!s.registered) { counts.unregistered++; return; }
            if (s.state === 'Ready') counts.ready++;
            else if (s.state === 'Running') counts.running++;
            else if (s.state === 'Disabled') counts.disabled++;
            else counts.ready++;
            var rs = s.resultStatus || {};
            if (rs.ok === false && s.state !== 'Running') counts.failed++;
        });
        document.getElementById('tasksMiniMetric').textContent = total;
        var pills = [];
        if (counts.running) pills.push('<span class="task-mini-pill running"><span class="dot"></span>运行中 ' + counts.running + '</span>');
        if (counts.ready) pills.push('<span class="task-mini-pill ready"><span class="dot"></span>就绪 ' + counts.ready + '</span>');
        if (counts.failed) pills.push('<span class="task-mini-pill failed"><span class="dot"></span>失败 ' + counts.failed + '</span>');
        if (counts.disabled) pills.push('<span class="task-mini-pill disabled"><span class="dot"></span>已禁用 ' + counts.disabled + '</span>');
        if (counts.unregistered) pills.push('<span class="task-mini-pill unregistered"><span class="dot"></span>未注册 ' + counts.unregistered + '</span>');
        document.getElementById('tasksMiniStatus').innerHTML = pills.join('') || '<span class="task-mini-pill">暂无任务</span>';

        // If currently on detail page, render it
        if (location.hash === '#/tasks') renderTasksDetail();
    } catch (e) {
        document.getElementById('tasksMiniMetric').textContent = '-';
        document.getElementById('tasksMiniStatus').innerHTML = '<span class="task-mini-pill">加载失败</span>';
        statusData.tasks = null;
        if (location.hash === '#/tasks') {
            var grid = document.getElementById('tasksDetailGrid');
            var stats = document.getElementById('tasksDetailStats');
            if (grid) grid.innerHTML = '<div class="error">加载失败: ' + e.message + '</div>';
            if (stats) stats.innerHTML = '';
        }
    }
}

async function runTask(taskId, btn) {
    btn.disabled = true;
    var orig = btn.innerHTML;
    btn.innerHTML = '运行中...';
    try {
        // POST instead of GET (security fix)
        var data = await postJSON('/api/tasks/' + taskId + '/run');
        if (data.status === 'launched') { btn.innerHTML = '已启动 \u2713'; setTimeout(function() { btn.innerHTML = orig; btn.disabled = false; }, 2000); }
        else { btn.innerHTML = '失败'; setTimeout(function() { btn.innerHTML = orig; btn.disabled = false; }, 2000); }
    } catch (e) { btn.innerHTML = '失败'; setTimeout(function() { btn.innerHTML = orig; btn.disabled = false; }, 2000); }
}

function toggleTaskLog(taskId, btn) {
    var log = document.getElementById('log-' + taskId);
    if (log) { var showing = log.classList.toggle('show'); btn.textContent = showing ? '隐藏日志' : '查看日志'; }
}

// === Task Edit Modal ===
var _currentTaskEditId = null;
var _currentTaskCreate = false;
var _currentLogTaskId = null;

function _setTaskEditTitle(title) {
    var el = document.querySelector('#taskEditModal .modal-header h3');
    if (el) el.childNodes[el.childNodes.length - 1].textContent = ' ' + title;
}

function openTaskCreate() {
    _currentTaskCreate = true;
    _currentTaskEditId = null;
    _setTaskEditTitle('新建定时任务');
    document.getElementById('task-edit-id').value = '';
    var idVisible = document.getElementById('task-edit-id-visible');
    idVisible.value = '';
    idVisible.disabled = false;
    idVisible.placeholder = '例如 wiki-sync-daily';
    document.getElementById('task-edit-name').value = '';
    document.getElementById('task-edit-desc').value = '';
    document.getElementById('task-edit-script').value = '';
    document.getElementById('task-edit-logfile').value = '';
    document.getElementById('task-edit-sources').value = '';
    setTaskEditType('daily');
    document.getElementById('task-edit-time').value = '08:00';
    document.querySelectorAll('#task-edit-days-row input[type="checkbox"]').forEach(function(cb) { cb.checked = false; });
    document.getElementById('task-edit-day').value = 1;
    document.getElementById('task-edit-datetime').value = '';
    document.getElementById('taskEditModal').style.display = '';
    document.body.style.overflow = 'hidden';
}

function openTaskEdit(taskId) {
    var data = statusData.tasks;
    if (!data) return;
    var t = data.tasks.find(function(x) { return x.id === taskId; });
    if (!t) return;
    _currentTaskCreate = false;
    _currentTaskEditId = taskId;
    _setTaskEditTitle('编辑定时任务');

    document.getElementById('task-edit-id').value = t.id;
    var idVisible = document.getElementById('task-edit-id-visible');
    idVisible.value = t.id;
    idVisible.disabled = true;
    document.getElementById('task-edit-name').value = t.name || '';
    document.getElementById('task-edit-desc').value = t.description || '';
    document.getElementById('task-edit-script').value = t.script || '';
    document.getElementById('task-edit-logfile').value = t.logFile || '';
    document.getElementById('task-edit-sources').value = (t.sources || []).join(', ');

    var trigger = t.trigger || { type: 'daily', time: '00:00' };
    setTaskEditType(trigger.type);

    if (trigger.time) document.getElementById('task-edit-time').value = trigger.time;
    if (trigger.type === 'weekly') {
        var days = trigger.daysOfWeek || [0];
        document.querySelectorAll('#task-edit-days-row input[type="checkbox"]').forEach(function(cb) {
            cb.checked = days.indexOf(parseInt(cb.value, 10)) !== -1;
        });
    }
    if (trigger.type === 'monthly') {
        document.getElementById('task-edit-day').value = trigger.day || 1;
    }
    if (trigger.type === 'once') {
        document.getElementById('task-edit-datetime').value = trigger.datetime || '';
    }

    document.getElementById('taskEditModal').style.display = '';
    document.body.style.overflow = 'hidden';
}

function closeTaskEdit() {
    document.getElementById('taskEditModal').style.display = 'none';
    document.body.style.overflow = '';
    _currentTaskEditId = null;
}

function setTaskEditType(type) {
    document.querySelectorAll('#task-edit-type-group .segment-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-value') === type);
    });
    document.getElementById('task-edit-time-row').style.display = (type === 'once') ? 'none' : '';
    document.getElementById('task-edit-days-row').style.display = (type === 'weekly') ? '' : 'none';
    document.getElementById('task-edit-day-row').style.display = (type === 'monthly') ? '' : 'none';
    document.getElementById('task-edit-datetime-row').style.display = (type === 'once') ? '' : 'none';
}

function _collectTaskEditTrigger() {
    var type = document.querySelector('#task-edit-type-group .segment-btn.active');
    type = type ? type.getAttribute('data-value') : 'daily';
    if (type === 'once') {
        return { type: 'once', datetime: document.getElementById('task-edit-datetime').value };
    }
    var time = document.getElementById('task-edit-time').value || '00:00';
    if (type === 'weekly') {
        var days = [];
        document.querySelectorAll('#task-edit-days-row input[type="checkbox"]:checked').forEach(function(cb) {
            days.push(parseInt(cb.value, 10));
        });
        if (!days.length) days = [0];
        return { type: 'weekly', time: time, daysOfWeek: days.sort(function(a,b){return a-b;}) };
    }
    if (type === 'monthly') {
        var day = parseInt(document.getElementById('task-edit-day').value, 10) || 1;
        return { type: 'monthly', time: time, day: day };
    }
    return { type: 'daily', time: time };
}

async function saveTask() {
    var taskId = _currentTaskEditId;
    var isCreate = _currentTaskCreate;
    if (!isCreate && !taskId) return;
    var btn = document.getElementById('task-edit-save-btn');
    var orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '保存中...';

    var sources = document.getElementById('task-edit-sources').value
        .split(/[,，]/)
        .map(function(s) { return s.trim(); })
        .filter(function(s) { return s; });

    var body = {
        name: document.getElementById('task-edit-name').value.trim(),
        description: document.getElementById('task-edit-desc').value.trim(),
        script: document.getElementById('task-edit-script').value.trim(),
        logFile: document.getElementById('task-edit-logfile').value.trim(),
        sources: sources,
        trigger: _collectTaskEditTrigger(),
    };

    try {
        var data;
        if (isCreate) {
            var rawId = document.getElementById('task-edit-id-visible').value.trim();
            if (!rawId) { showToast('请填写任务 ID', 3000); btn.disabled = false; btn.innerHTML = orig; return; }
            body.id = rawId;
            body.taskName = rawId.replace(/-/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); }).replace(/\s+/g, '');
            body.enabled = true;
            data = await postJSON('/api/tasks/create', body);
        } else {
            data = await postJSON('/api/tasks/' + taskId + '/save', body);
        }
        closeTaskEdit();
        if (data.warning) {
            showToast('任务已保存，但计划任务未更新: ' + data.warning, 7000);
        } else {
            showToast(isCreate ? '任务已创建' : '任务已保存', 3000);
        }
        await loadTasks();
    } catch (e) {
        showToast('保存失败: ' + e.message, 5000);
    } finally {
        btn.disabled = false;
        btn.innerHTML = orig;
    }
}

async function deleteTask(taskId) {
    var data = statusData.tasks;
    var t = data && data.tasks.find(function(x) { return x.id === taskId; });
    var name = t ? t.name : taskId;
    if (!confirm('确定删除任务 "' + name + '"？\n这会同时删除 Windows 任务计划程序中的对应任务。')) return;
    try {
        var res = await postJSON('/api/tasks/' + taskId + '/delete');
        if (res.warning) {
            showToast('任务配置已删除，但计划任务未移除: ' + res.warning, 7000);
        } else {
            showToast('任务已删除', 3000);
        }
        await loadTasks();
    } catch (e) {
        showToast('删除失败: ' + e.message, 5000);
    }
}

async function toggleTaskEnabled(taskId, enabled) {
    try {
        var data = await postJSON('/api/tasks/' + taskId + '/toggle', { enabled: enabled });
        if (data.success) {
            if (data.warning) {
                showToast('任务状态已保存，但计划任务未更新: ' + data.warning, 7000);
            } else {
                showToast('任务已' + (data.enabled ? '启用' : '禁用'), 3000);
            }
            await loadTasks();
        } else {
            showToast('设置失败: ' + (data.error || '未知错误'), 5000);
            await loadTasks();
        }
    } catch (e) {
        showToast('设置失败: ' + e.message, 5000);
        await loadTasks();
    }
}

// === Task Log Modal ===
async function openTaskLog(taskId) {
    _currentLogTaskId = taskId;
    var data = statusData.tasks;
    var t = data && data.tasks.find(function(x) { return x.id === taskId; });
    document.getElementById('task-log-meta').textContent = t ? (t.logFile || '') : '';
    document.getElementById('task-log-content').textContent = '加载中...';
    document.getElementById('taskLogModal').style.display = '';
    document.body.style.overflow = 'hidden';
    await refreshTaskLog();
}

function closeTaskLog() {
    document.getElementById('taskLogModal').style.display = 'none';
    document.body.style.overflow = '';
    _currentLogTaskId = null;
}

async function refreshTaskLog() {
    if (!_currentLogTaskId) return;
    try {
        var data = await fetchJSON('/api/tasks/' + _currentLogTaskId + '/log');
        var content = document.getElementById('task-log-content');
        content.textContent = data.log || '（空日志）';
        var meta = document.getElementById('task-log-meta');
        meta.textContent = data.logFile ? '日志文件: ' + data.logFile : '';
    } catch (e) {
        document.getElementById('task-log-content').textContent = '加载失败: ' + e.message;
    }
}

// === Skill management ===
var _currentSkillEditId = null;

function openSkillEdit(skillId) {
    var data = statusData.skills;
    if (!data) return;
    var s = data.skills.find(function(x) { return x.id === skillId; });
    if (!s) return;
    _currentSkillEditId = skillId;
    document.getElementById('skill-edit-id').value = s.id;
    document.getElementById('skill-edit-name').value = s.name || '';
    document.getElementById('skill-edit-desc').value = s.description || '';
    document.getElementById('skill-edit-source').value = s.source || '';
    document.getElementById('skill-edit-sourceurl').value = s.sourceUrl || '';
    document.getElementById('skillEditModal').style.display = '';
    document.body.style.overflow = 'hidden';
}

function closeSkillEdit() {
    document.getElementById('skillEditModal').style.display = 'none';
    document.body.style.overflow = '';
    _currentSkillEditId = null;
}

async function saveSkill() {
    var skillId = _currentSkillEditId;
    if (!skillId) return;
    var btn = document.getElementById('skill-edit-save-btn');
    var orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '保存中...';
    try {
        await postJSON('/api/skills/' + skillId + '/save', {
            name: document.getElementById('skill-edit-name').value.trim(),
            description: document.getElementById('skill-edit-desc').value.trim(),
            source: document.getElementById('skill-edit-source').value.trim(),
            sourceUrl: document.getElementById('skill-edit-sourceurl').value.trim(),
        });
        closeSkillEdit();
        showToast('Skill 已保存', 3000);
        await loadSkills();
    } catch (e) {
        showToast('保存失败: ' + e.message, 5000);
    } finally {
        btn.disabled = false;
        btn.innerHTML = orig;
    }
}

async function deleteSkill(skillId) {
    var data = statusData.skills;
    var s = data && data.skills.find(function(x) { return x.id === skillId; });
    var name = s ? s.name : skillId;
    if (!confirm('确定卸载 Skill "' + name + '"？\n这会删除本地 skill 目录。')) return;
    try {
        await postJSON('/api/skills/' + skillId + '/delete');
        showToast('Skill 已卸载', 3000);
        await loadSkills();
    } catch (e) {
        showToast('卸载失败: ' + e.message, 5000);
    }
}

async function toggleSkillEnabled(skillId, enabled) {
    try {
        var data = await postJSON('/api/skills/' + skillId + '/toggle', { enabled: enabled });
        if (data.success) {
            showToast('Skill 已' + (data.enabled ? '启用' : '禁用'), 3000);
            await loadSkills();
        } else {
            showToast('设置失败: ' + (data.error || '未知错误'), 5000);
            await loadSkills();
        }
    } catch (e) {
        showToast('设置失败: ' + e.message, 5000);
        await loadSkills();
    }
}

// === MCP management ===
var _currentMcpEditId = null;

function openMcpEdit(mcpId) {
    var data = statusData.mcp;
    if (!data) return;
    var s = data.servers.find(function(x) { return x.name === mcpId; });
    if (!s) return;
    _currentMcpEditId = mcpId;
    document.getElementById('mcp-edit-id').value = s.name;
    document.getElementById('mcp-edit-command').value = s.command || '';
    document.getElementById('mcp-edit-args').value = (s.args || []).join('\n');
    document.getElementById('mcp-edit-cwd').value = s.cwd || '';
    document.getElementById('mcp-edit-description').value = s.description || getMcpDesc(s.name) || '';
    var env = s.env || {};
    document.getElementById('mcp-edit-env').value = Object.keys(env).map(function(k) { return k + '=' + env[k]; }).join('\n');
    document.getElementById('mcpEditModal').style.display = '';
    document.body.style.overflow = 'hidden';
}

function closeMcpEdit() {
    document.getElementById('mcpEditModal').style.display = 'none';
    document.body.style.overflow = '';
    _currentMcpEditId = null;
}

async function saveMcp() {
    var mcpId = _currentMcpEditId;
    if (!mcpId) return;
    var btn = document.getElementById('mcp-edit-save-btn');
    var orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '保存中...';

    var args = document.getElementById('mcp-edit-args').value.split('\n').map(function(s) { return s.trim(); }).filter(function(s) { return s; });
    var envLines = document.getElementById('mcp-edit-env').value.split('\n');
    var env = {};
    envLines.forEach(function(line) {
        var idx = line.indexOf('=');
        if (idx > 0) {
            var k = line.slice(0, idx).trim();
            var v = line.slice(idx + 1).trim();
            if (k) env[k] = v;
        }
    });

    var body = {
        command: document.getElementById('mcp-edit-command').value.trim(),
        args: args,
        cwd: document.getElementById('mcp-edit-cwd').value.trim(),
        description: document.getElementById('mcp-edit-description').value.trim(),
    };
    if (Object.keys(env).length) body.env = env;

    try {
        await postJSON('/api/mcp/' + mcpId + '/save', body);
        closeMcpEdit();
        showToast('MCP Server 已保存', 3000);
        await loadMCP();
    } catch (e) {
        showToast('保存失败: ' + e.message, 5000);
    } finally {
        btn.disabled = false;
        btn.innerHTML = orig;
    }
}

async function deleteMcp(mcpId) {
    var data = statusData.mcp;
    var s = data && data.servers.find(function(x) { return x.name === mcpId; });
    if (!confirm('确定删除 MCP Server "' + (s ? s.name : mcpId) + '"？\n这会从配置中移除，不会删除实际文件。')) return;
    try {
        await postJSON('/api/mcp/' + mcpId + '/delete');
        showToast('MCP Server 已删除', 3000);
        await loadMCP();
    } catch (e) {
        showToast('删除失败: ' + e.message, 5000);
    }
}

async function toggleMcpEnabled(mcpId, enabled) {
    try {
        var data = await postJSON('/api/mcp/' + mcpId + '/toggle', { enabled: enabled });
        if (data.success) {
            showToast('MCP Server 已' + (data.enabled ? '启用' : '禁用'), 3000);
            await loadMCP();
        } else {
            showToast('设置失败: ' + (data.error || '未知错误'), 5000);
            await loadMCP();
        }
    } catch (e) {
        showToast('设置失败: ' + e.message, 5000);
        await loadMCP();
    }
}

// === Dashboard version ===
async function loadDashboardVersion() {
    try {
        var data = await fetchJSON('/api/dashboard-version');
        window.dashboardVersion = data.version || '1.0.0';
    } catch (e) {
        window.dashboardVersion = '1.0.0';
    }
}

// === Startup service (macOS launchd / Windows Task Scheduler) ===
async function loadKimiConfig() {
    try {
        var data = await fetchJSON('/api/kimi-config');
        if (data.default_permission_mode) {
            settings.default_permission_mode = data.default_permission_mode;
            saveSettings(settings);
        }
    } catch (e) {
        log.debug('Failed to load kimi config: %s', e.message);
    }
}

async function loadStartupServiceStatus() {
    try {
        var data = await fetchJSON('/api/startup-status');
        startupServiceState = {
            supported: data.supported,
            loaded: true,
            dashboard: data.dashboard || { enabled: false, mode: 'off' },
            kimi: data.kimi || { enabled: false }
        };
        settings.__startup_dashboard_mode = startupServiceState.dashboard.mode || 'off';
        saveSettings(settings);
    } catch (e) {
        startupServiceState = { supported: false, loaded: true, dashboard: { enabled: false, mode: 'off' }, kimi: { enabled: false } };
    }
    if (location.hash === '#/settings') renderSettings();
}

async function toggleStartupService(service, enable) {
    try {
        var payload = { service: service, enable: enable };
        if (service === 'kimi') {
            payload.port = settings.kw_port;
            payload.bind = settings.kw_bind;
            payload.bypass_auth = settings.kw_bypass_auth;
            payload.allowed_hosts = settings.kw_allowed_hosts;
            payload.public_url = settings.kw_public_url;
        }
        var data = await postJSON('/api/startup-toggle', payload);
        if (data.success) {
            startupServiceState[service].enabled = enable;
            var name = service === 'kimi' ? 'Kimi Code' : 'Dashboard';
            showToast(name + ' 开机启动已' + (enable ? '开启' : '关闭'), 3000);
        } else {
            showToast('设置失败: ' + (data.error || '未知错误'), 5000);
            renderSettings();
        }
    } catch (e) {
        showToast('设置失败: ' + e.message, 5000);
        renderSettings();
    }
}

async function setDashboardStartupMode(mode) {
    try {
        var data = await postJSON('/api/startup-toggle', { service: 'dashboard', mode: mode });
        if (data.success) {
            startupServiceState.dashboard.mode = data.mode || mode;
            startupServiceState.dashboard.enabled = (data.mode || mode) !== 'off';
            settings.__startup_dashboard_mode = data.mode || mode;
            saveSettings(settings);
            var labelMap = { normal: '开机自启', elevated: '管理员启动', off: '关闭' };
            var msg = 'Dashboard 已设为 ' + (labelMap[data.mode || mode] || data.mode || mode);
            if (data.note) msg += '，' + data.note;
            showToast(msg, data.note ? 6000 : 3000);
        } else {
            showToast('设置失败: ' + (data.error || '未知错误'), 5000);
            await loadStartupServiceStatus();
        }
    } catch (e) {
        showToast('设置失败: ' + e.message, 5000);
        await loadStartupServiceStatus();
    }
}

// === Load all ===
async function loadAll() {
    var btn = document.getElementById('refreshBtn');
    var icon = document.getElementById('refreshIcon');
    btn.disabled = true;
    icon.classList.add('spin');
    await Promise.all([loadTrends(), loadSkills(), loadMCP(), loadMemory(), loadKimi(), loadToolUsage(), loadModelUsage(), loadTasks(), loadModelConfig()]);
    renderStatusBar();
    applySettings();
    document.getElementById('lastUpdated').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN');
    btn.disabled = false;
    icon.classList.remove('spin');
}

// === Init ===
Promise.all([loadDashboardVersion(), loadStartupServiceStatus(), loadKimiConfig()]).then(loadAll);
checkKimiWebStatus();
setInterval(checkKimiWebStatus, 10000);
window.addEventListener('hashchange', handleRoute);
handleRoute();
