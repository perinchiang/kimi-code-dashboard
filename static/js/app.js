/* app.js — Main application logic for Kimi Code Dashboard */

// === State ===
var trendData = null;
var currentTrendUnit = 'daily';
var pageLoadTime = Date.now();
var statusData = {};
var startupServiceState = { supported: false, loaded: false, dashboard: { enabled: false, mode: 'off' }, kimi: { enabled: false } };
var artifactsData = null;
var currentArtifactSource = 'all';
var currentArtifactQuery = '';
var kimiUpdateState = { checking: false, updateAvailable: false, error: null };
var updateRetryCount = 0;
var selectedProvider = null;
var currentSkillStatusFilter = 'all';
var currentSkillSort = 'name';
var currentMcpStatusFilter = 'all';
var currentTaskStatusFilter = 'all';
var currentHookStatusFilter = 'all';
var _currentSkillDetailId = null;
var _currentHookEditId = null;
var _currentHookCreate = false;

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
    theme_mode: 'system',        // 主题模式: light / dark / system
    kw_bind: '0.0.0.0',          // Kimi Web 绑定地址
    kw_port: 5494,               // Kimi Web 端口
    kw_bypass_auth: true,        // 关闭密码认证 (true=无需密码)
    kw_allowed_hosts: '',         // 允许的域名 (逗号分隔)
    kw_public_urls: [],          // 自定义访问URL列表 (留空自动生成; 多个域名都会加入信任列表)
    default_permission_mode: 'manual', // Kimi Code 默认权限模式 (manual/auto/yolo)
    dashboard_port: 18080,       // Dashboard 服务端口
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
            { key: 'kw_bypass_auth', label: '关闭密码认证', desc: '开启时无需密码直接访问；关闭时 Kimi Web 会自动生成一次性 Token 并拼到访问 URL 中（无需手动输入密码，打开链接即认证）', row: true },
            { key: 'kw_public_urls', label: '自定义访问 URL', desc: '域名会自动加入信任列表，可添加多个；启动 Kimi Web 时默认打开置顶的链接', type: 'public_urls', row: true, wide: true },
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
            { key: 'dashboard_port', label: 'Dashboard 服务端口', desc: '默认 18080；修改后需重启 Dashboard', type: 'dashboard_port', row: true },
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
            { key: 'theme_mode', label: '主题', desc: '选择界面外观', type: 'segment', row: true, options: [
                { v: 'light', t: '亮色' },
                { v: 'dark', t: '暗色' },
                { v: 'system', t: '跟随主题' }
            ]},
        ]
    },
    {
        title: 'PWA',
        desc: '手机主屏幕图标',
        icon: '<rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/>',
        items: [
            { key: 'enable_pwa_icons', label: '启用 PWA 图标', desc: '开启后注入 favicon、apple-touch-icon 和 manifest，方便添加到手机桌面', row: true },
            { type: 'link', label: '外网访问图片不显示？', desc: 'SakuraFrp / 内网穿透下 Kimi Web 图片裂图问题与 CSP 修复教程', href: '/static/help-csp-images.html', row: true },
        ]
    },
    {
        title: 'MCP 图床配置',
        desc: 'S3 兼容对象存储凭证（R2 / S3 / MinIO / OSS 等）',
        icon: '<path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>',
        items: [
            { key: 'image_bed', label: '图床凭证', desc: '凭证写入 ~/.kimi-code/config.toml 的 [image_bed] 段，image-bed-mcp 也会读这份配置', type: 'image_bed', row: true, wide: true },
        ]
    },
    {
        title: '界面显示',
        desc: '控制首页各模块的显示',
        icon: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
        items: [
            { key: 'show_trends', label: 'Token 用量趋势', desc: '首页顶部的用量趋势图表', row: true },
            { key: 'show_minicards', label: '快捷入口卡片', desc: 'Skills / MCP / 定时任务 / 第三方模型 / 产物浏览器 / 工具调用 / 模型用量', row: true },
            { key: 'show_kimi_usage', label: 'Kimi Usage', desc: '登录状态、版本检查、额度信息', row: true },
            { key: 'show_memory', label: 'Memory Status', desc: 'TencentDB 记忆统计与 Gateway 健康', row: true },
            { key: 'show_tool_model_usage', label: '工具调用 / 模型用量', desc: '工具调用与模型用量详情页及首页快捷入口卡片', row: true },
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
        var settings = Object.assign({}, SETTINGS_DEFAULTS, saved);
        // Migrate legacy single public_url to list
        if (!Array.isArray(settings.kw_public_urls)) {
            settings.kw_public_urls = [];
        }
        if (saved.kw_public_url) {
            var legacy = normalizePublicUrl(saved.kw_public_url);
            if (legacy && settings.kw_public_urls.indexOf(legacy) < 0) {
                settings.kw_public_urls.push(legacy);
            }
            delete saved.kw_public_url;
            saveSettings(settings);
        }
        // Migrate legacy theme settings to theme_mode
        if (!settings.theme_mode) {
            settings.theme_mode = (settings.follow_system_theme !== false) ? 'system' : (settings.manual_theme || 'dark');
            saveSettings(settings);
        }
        return settings;
    } catch (e) {
        return Object.assign({}, SETTINGS_DEFAULTS);
    }
}

function saveSettings(settings) {
    try {
        localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch (e) {
        console.warn('saveSettings failed:', e);
        showToast('设置保存失败，可能存储空间已满', 5000);
    }
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
    el.style.cssText = 'position:fixed;bottom:20px;right:20px;max-width:420px;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:10px;padding:14px 18px;box-shadow:0 6px 20px rgba(0,0,0,0.35);z-index:10000;font-size:14px;line-height:1.55;transition:opacity .3s;cursor:default;';
    el.innerHTML = message;
    document.body.appendChild(el);
    setTimeout(function() {
        el.style.opacity = '0';
        setTimeout(function() { el.remove(); }, 300);
    }, duration);
}

// === Confirm Dialog (替代浏览器 confirm/alert) ===
var _confirmDialogCallback = null;
var _confirmDialogCancelCallback = null;
function confirmDialog(msg, onOk, opts) {
    opts = opts || {};
    var dlg = document.getElementById('confirmDialog');
    if (!dlg) { if (typeof onOk === 'function') onOk(); return; }
    document.getElementById('confirmDialogMsg').textContent = msg;
    document.getElementById('confirmDialogTitle').textContent = opts.title || '确认';
    var okBtn = document.getElementById('confirmDialogOk');
    if (opts.danger === false) {
        okBtn.style.background = 'var(--surface)';
        okBtn.style.color = 'var(--text)';
        okBtn.style.borderColor = 'var(--border)';
    } else {
        okBtn.style.background = 'var(--danger)';
        okBtn.style.color = '#fff';
        okBtn.style.borderColor = 'var(--danger)';
    }
    _confirmDialogCallback = typeof onOk === 'function' ? onOk : null;
    _confirmDialogCancelCallback = typeof opts.onCancel === 'function' ? opts.onCancel : null;
    document.body.style.overflow = 'hidden';
    dlg.style.display = '';
}
function closeConfirmDialog() {
    var dlg = document.getElementById('confirmDialog');
    if (dlg) dlg.style.display = 'none';
    var cb = _confirmDialogCallback;
    var cancelCb = _confirmDialogCancelCallback;
    _confirmDialogCallback = null;
    _confirmDialogCancelCallback = null;
    document.body.style.overflow = '';
    // 若 ok 回调还在（说明是 cancel/Esc/遮罩点击触发的关闭，非 ok），且 cancel 回调存在，则触发
    if (cb && typeof cancelCb === 'function') cancelCb();
}
function _confirmDialogOk() {
    var cb = _confirmDialogCallback;
    _confirmDialogCallback = null;
    _confirmDialogCancelCallback = null;
    var dlg = document.getElementById('confirmDialog');
    if (dlg) dlg.style.display = 'none';
    document.body.style.overflow = '';
    if (typeof cb === 'function') cb();
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
    setDisplay('toolModelMiniCard', s.show_tool_model_usage);
    setDisplay('modelUsageMiniCard', s.show_tool_model_usage);

    // Kimi Usage 卡片点击跳转到 Console
    var kimiCard = document.getElementById('section-kimi');
    if (kimiCard) {
        kimiCard.onclick = function() {
            var url = (statusData.kimi && statusData.kimi.consoleUrl) || 'https://www.kimi.com/code/console';
            window.open(url, '_blank');
        };
    }
    // Memory Status 卡片点击跳转到记忆详情页
    var memCard = document.getElementById('section-memory');
    if (memCard) {
        memCard.onclick = function() { location.hash = '#/memory'; };
    }
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
    var ids = ['pwa-favicon', 'pwa-apple-touch-icon', 'pwa-manifest', 'pwa-mobile-capable', 'pwa-apple-status'];

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
    // Chrome deprecates apple-mobile-web-app-capable; use the standard name.
    ensureMeta('pwa-mobile-capable', 'mobile-web-app-capable', 'yes');
    ensureMeta('pwa-apple-status', 'apple-mobile-web-app-status-bar-style', 'black-translucent');
}

function setSetting(key, value) {
    settings[key] = value;
    saveSettings(settings);
    applySettings();
    if (key === 'kw_bind' || key === 'default_permission_mode' || key === 'theme_mode') renderSettings();
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
    saveDashboardPort(SETTINGS_DEFAULTS.dashboard_port);
}

// === Theme ===
// 返回当前实际生效的主题
function getEffectiveTheme() {
    if (settings.theme_mode === 'system') {
        return (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) ? 'light' : 'dark';
    }
    return (settings.theme_mode === 'light') ? 'light' : 'dark';
}

// 应用主题到 <html data-theme=...>
function applyTheme() {
    var effective = getEffectiveTheme();
    document.documentElement.setAttribute('data-theme', effective);
    // 同步 meta theme-color
    var meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) { meta = document.createElement('meta'); meta.name = 'theme-color'; document.head.appendChild(meta); }
    meta.content = effective === 'light' ? '#ffffff' : '#0d1117';
}

// 系统主题变化时，若处于跟随系统模式则实时跟随
if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', function () {
        if (settings.theme_mode === 'system') applyTheme();
    });
}

// 页面加载时立即应用一次
applyTheme();
applyPwaIcons();
applySettings();

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
    var unit = '';
    var value = n;
    if (n >= 100000000) { value = (n / 100000000).toFixed(2); unit = '亿'; }
    else if (n >= 10000) { value = (n / 10000).toFixed(1); unit = '万'; }
    else if (n >= 1000) { value = (n / 1000).toFixed(1); unit = 'k'; }
    else { return n.toString(); }
    return value + '<span class="token-unit">' + unit + '</span>';
}
function formatSize(bytes) {
    if (bytes === undefined || bytes === null || isNaN(bytes)) return '-';
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(2) + ' GB';
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(2) + ' MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return bytes + ' B';
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
    document.getElementById(id).innerHTML = '<div class="error">' + escapeHtml(msg) + '</div>';
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
    var publicUrls = (settings.kw_public_urls || []).map(normalizePublicUrl).filter(Boolean);

    if (btn.classList.contains('running')) {
        confirmDialog('kimiweb 已经在运行了，是否重启 kimiweb？', function() {
            _launchKimiWebInternal(btn, text, publicUrls, true);
        }, { danger: false });
        return;
    }

    // 如果没填自定义 URL，提示用户
    if (publicUrls.length === 0) {
        confirmDialog('未配置自定义访问 URL，将使用本地地址 http://127.0.0.1:' + (settings.kw_port || 5494) + '\n\n是否继续？\n（点击「取消」去设置页填写自定义 URL）', function() {
            _launchKimiWebInternal(btn, text, publicUrls);
        }, {
            danger: false,
            onCancel: function() { window.location.hash = '#/settings'; }
        });
        return;
    }
    _launchKimiWebInternal(btn, text, publicUrls);
}

async function _launchKimiWebInternal(btn, text, publicUrls, restart) {
    btn.disabled = true;
    text.textContent = '启动中...';
    var wasRunning = btn.classList.contains('running');
    if (wasRunning) text.textContent = '重启中...';
    try {
        var cfg = {
            bind: settings.kw_bind || '0.0.0.0',
            port: parseInt(settings.kw_port, 10) || 5494,
            bypass_auth: settings.kw_bypass_auth !== false,
            public_urls: publicUrls,
            restart: restart === true
        };
        var data = await postJSON('/api/launch-kimi-web', cfg);
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
            showToast('启动失败: ' + (data.error || data.status || '未知错误'), 5000);
        }
    } catch (e) {
        text.textContent = '启动失败';
        setTimeout(function() { text.textContent = '启动 Kimi Web'; btn.disabled = false; }, 2000);
        showToast('启动失败: ' + e.message, 5000);
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
        var baseCls = statusData.kimi.loggedIn ? 'ok' : 'warn';
        var cls = kimiUpdateState.checking ? 'checking' : (kimiUpdateState.updateAvailable ? 'warn' : (kimiUpdateState.error ? 'err' : baseCls));
        var title = kimiUpdateState.updateAvailable ? '有新版本，点击更新' : (kimiUpdateState.checking ? '检查中…' : '点击检查更新');
        pills.push('<button class="status-pill ' + cls + '" onclick="onKimiPillClick()" title="' + title + '"><span class="dot"></span>Kimi v' + statusData.kimi.version + ' &middot; ' + statusData.kimi.sessionCount + ' sessions</button>');
    }
    if (statusData.mcp) {
        var cls2 = statusData.mcp.healthy === statusData.mcp.total ? 'ok' : (statusData.mcp.healthy > 0 ? 'warn' : 'err');
        pills.push('<button class="status-pill ' + cls2 + '" onclick="location.hash=\'#/mcp\'"><span class="dot"></span>MCP ' + statusData.mcp.healthy + '/' + statusData.mcp.total + '</button>');
    }
    if (statusData.memory) {
        var cls3 = statusData.memory.gatewayReachable ? 'ok' : 'err';
        var label = statusData.memory.gatewayReachable ? 'Gateway 可达' : 'Gateway 不可达';
        pills.push('<button class="status-pill ' + cls3 + '" onclick="location.hash=\'#/memory\'"><span class="dot"></span>' + label + '</button>');
    }
    if (statusData.skills) {
        pills.push('<button class="status-pill ok" onclick="location.hash=\'#/skills\'"><span class="dot"></span>' + statusData.skills.total + ' Skills &middot; ' + statusData.skills.localCount + ' 本地</button>');
    }
    if (statusData.modelConfig) {
        var mc = statusData.modelConfig;
        pills.push('<button class="status-pill ok" onclick="location.hash=\'#/models\'"><span class="dot"></span>' + (mc.providers || []).length + ' Providers &middot; ' + (mc.models || []).length + ' Models</button>');
    }
    if (statusData.trends && statusData.trends.total) {
        pills.push('<button class="status-pill ok" onclick="location.hash=\'#/\'"><span class="dot"></span>累计 ' + formatTokens(statusData.trends.total.value) + ' tokens</button>');
    }
    bar.innerHTML = pills.join('');
}

function onKimiPillClick() {
    if (kimiUpdateState.checking) return;
    if (kimiUpdateState.updateAvailable) {
        runKimiUpdate();
        return;
    }
    checkKimiUpdate();
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
        document.getElementById('mcpMiniMetric').textContent = data.healthy + '/' + data.total;
        document.getElementById('mcpMiniLabel').textContent = '可用 / 总数';
        var pills = [];
        if (data.disabled) pills.push('<span class="task-mini-pill disabled"><span class="dot"></span>已禁用 ' + data.disabled + '</span>');
        document.getElementById('mcpMiniStatus').innerHTML = pills.join('') || '';
    } catch (e) {
        document.getElementById('mcpMiniMetric').textContent = '!';
        document.getElementById('mcpMiniLabel').textContent = '加载失败';
    }
}

// === Hooks ===
async function loadHooks() {
    try {
        var data = await fetchJSON('/api/hooks');
        statusData.hooks = data;
        document.getElementById('hooksMiniMetric').textContent = data.enabledCount + '/' + data.total;
        document.getElementById('hooksMiniLabel').textContent = '启用 / 总计';
        var pills = [];
        if (data.disabledCount) pills.push('<span class="task-mini-pill disabled"><span class="dot"></span>已禁用 ' + data.disabledCount + '</span>');
        document.getElementById('hooksMiniStatus').innerHTML = pills.join('') || '';
    } catch (e) {
        document.getElementById('hooksMiniMetric').textContent = '!';
        document.getElementById('hooksMiniLabel').textContent = '加载失败';
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
    document.getElementById('view-hooks').style.display = (hash === '#/hooks') ? '' : 'none';
    document.getElementById('view-artifacts').style.display = (hash === '#/artifacts') ? '' : 'none';
    document.getElementById('view-memory').style.display = (hash === '#/memory') ? '' : 'none';
    document.getElementById('view-settings').style.display = (hash === '#/settings') ? '' : 'none';
    document.getElementById('view-tool-model').style.display = (hash === '#/tool-model') ? '' : 'none';
    document.getElementById('view-model-usage').style.display = (hash === '#/model-usage') ? '' : 'none';
    window.scrollTo(0, 0);
    if (hash === '#/skills') renderSkillsDetail();
    else if (hash === '#/mcp') renderMcpDetail();
    else if (hash === '#/models') renderModelConfigDetail();
    else if (hash === '#/tasks') renderTasksDetail();
    else if (hash === '#/hooks') renderHooksDetail();
    else if (hash === '#/artifacts') renderArtifactsDetail();
    else if (hash === '#/memory') renderMemoryDetail();
    else if (hash === '#/settings') renderSettings();
    else if (hash === '#/tool-model') renderToolModelDetail();
    else if (hash === '#/model-usage') renderModelUsageDetail();
}

function _filterSkillsByStatus(skills) {
    if (currentSkillStatusFilter === 'enabled') return skills.filter(function(s) { return s.enabled; });
    if (currentSkillStatusFilter === 'disabled') return skills.filter(function(s) { return !s.enabled; });
    return skills;
}

function _sortSkills(skills) {
    var sorted = skills.slice();
    if (currentSkillSort === 'calls-desc') {
        sorted.sort(function(a, b) {
            var diff = (b.callCount || 0) - (a.callCount || 0);
            if (diff !== 0) return diff;
            return (a.name || '').toLowerCase().localeCompare((b.name || '').toLowerCase());
        });
    } else if (currentSkillSort === 'calls-asc') {
        sorted.sort(function(a, b) {
            var diff = (a.callCount || 0) - (b.callCount || 0);
            if (diff !== 0) return diff;
            return (a.name || '').toLowerCase().localeCompare((b.name || '').toLowerCase());
        });
    } else {
        sorted.sort(function(a, b) {
            return (a.name || '').toLowerCase().localeCompare((b.name || '').toLowerCase());
        });
    }
    return sorted;
}

function setSkillStatusFilter(status) {
    currentSkillStatusFilter = status || 'all';
    var filterEl = document.getElementById('skillStatusFilter');
    if (filterEl) {
        filterEl.querySelectorAll('.seg-item').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.status === status);
        });
    }
    var q = document.getElementById('skillSearchDetail');
    filterSkillsDetail(q ? q.value : '');
}

function renderSkillsDetail() {
    var data = statusData.skills;
    var list = document.getElementById('skillsDetailList');
    var stats = document.getElementById('skillsDetailStats');
    if (!data) { list.innerHTML = '<div class="empty">数据加载中...</div>'; return; }
    stats.innerHTML = '<span>共 <strong>' + data.total + '</strong> 个</span><span>已启用 <strong>' + data.enabledCount + '</strong></span>' + (data.disabledCount ? '<span>已禁用 <strong>' + data.disabledCount + '</strong></span>' : '') + '<span>本地可用 <strong>' + data.localCount + '</strong></span>';
    var filtered = _filterSkillsByStatus(data.skills);
    var sorted = _sortSkills(filtered);
    renderSkillsDetailList(sorted);

    // sync sort dropdown
    _syncSkillSortDropdown();
}

function _skillDetailHtml(s) {
    var lines = [];
    var desc = s.description || getSkillDesc(s) || '暂无简介';
    var callCount = s.callCount || 0;
    lines.push('<div class="mcp-detail-desc"><div class="label">描述</div><div class="detail-content">' + escapeHtml(desc) + '</div></div>');
    lines.push('<div class="mcp-detail-meta"><span class="label">状态</span><span class="badge ' + (s.enabled ? (s.local ? 'badge-local' : 'badge-remote') : 'badge-disabled') + '">' + (s.enabled ? (s.local ? '已启用 · 本地' : '已启用 · 仅 lock') : '未启用') + '</span></div>');
    lines.push('<div class="mcp-detail-meta"><span class="label">调用次数</span><span class="skill-call-count">' + callCount + ' 次</span></div>');
    if (s.skillPath) {
        lines.push('<div class="mcp-detail-meta"><span class="label">路径</span><code style="word-break:break-all;flex:1;">' + escapeHtml(s.skillPath) + '</code><button class="btn-task btn-sm" onclick="copySkillPath(\'' + escapeJsString(s.id) + '\')">复制</button></div>');
    }
    lines.push('<div class="mcp-detail-meta"><span class="label">来源</span><span>' + escapeHtml(s.source || '未知') + '</span></div>');
    if (s.sourceUrl) lines.push('<div class="mcp-detail-meta"><span class="label">来源 URL</span><a href="' + escapeHtml(s.sourceUrl) + '" target="_blank" style="color:var(--accent);text-decoration:underline;font-size:0.75rem;">' + escapeHtml(s.sourceUrl) + '</a></div>');
    if (s.installedAt) lines.push('<div class="mcp-detail-meta"><span class="label">安装时间</span><span>' + escapeHtml(s.installedAt.slice(0, 10)) + '</span></div>');
    return lines.join('');
}

function openSkillDetail(skillId) {
    var data = statusData.skills;
    if (!data) return;
    var s = data.skills.find(function(x) { return x.id === skillId; });
    if (!s) return;
    _currentSkillDetailId = skillId;
    document.getElementById('skill-detail-name').textContent = s.name;
    document.getElementById('skill-detail-content').innerHTML = _skillDetailHtml(s);
    document.getElementById('skillDetailModal').style.display = '';
    document.body.style.overflow = 'hidden';
}

function closeSkillDetail() {
    document.getElementById('skillDetailModal').style.display = 'none';
    document.body.style.overflow = '';
    _currentSkillDetailId = null;
}

function renderSkillCard(s) {
    var enabledChecked = s.enabled ? ' checked' : '';
    var badgeCls = s.enabled ? (s.local ? 'badge-local' : 'badge-remote') : 'badge-disabled';
    var badgeText = s.enabled ? (s.local ? '本地' : '仅 lock') : '已禁用';
    var desc = getSkillDesc(s);
    var callCount = s.callCount || 0;
    var safeId = escapeJsString(s.id);
    var actions = '<div class="skill-card-actions">' +
        '<label class="toggle-switch" title="启用/禁用" onclick="event.stopPropagation()"><input type="checkbox" onchange="toggleSkillEnabled(\'' + s.id + '\', this.checked)"' + enabledChecked + '><span class="toggle-slider"></span></label>' +
        '<button class="btn-task btn-danger" onclick="event.stopPropagation();deleteSkill(\'' + s.id + '\')">卸载</button>' +
    '</div>';
    return '<div class="skill-card ' + (s.enabled ? '' : 'disabled') + '" data-skill-id="' + s.id + '" onclick="openSkillDetail(\'' + s.id + '\')">' +
        '<div class="skill-card-header"><div class="skill-name-wrap"><span class="skill-card-name">' + escapeHtml(s.name) + '</span><button class="btn-task btn-sm skill-copy-btn" title="复制 ID" onclick="event.stopPropagation();copySkillId(\'' + safeId + '\')">复制</button></div><span class="badge ' + badgeCls + '">' + badgeText + '</span></div>' +
        '<div class="skill-card-desc">' + desc + '</div>' +
        '<div class="skill-card-meta"><span class="label">调用:</span> <span class="skill-call-count">' + callCount + ' 次</span></div>' +
        '<div class="skill-card-meta"><span class="label">来源:</span> ' + (s.source || '未知') + '</div>' +
        (s.installedAt ? '<div class="skill-card-meta"><span class="label">安装时间:</span> ' + s.installedAt.slice(0, 10) + '</div>' : '') +
        actions +
    '</div>';
}

function renderSkillsDetailList(skills) {
    var list = document.getElementById('skillsDetailList');
    list.className = 'skill-grid';
    if (!skills || !skills.length) { list.innerHTML = '<div class="empty">暂无 Skills</div>'; return; }
    list.innerHTML = skills.map(renderSkillCard).join('');
}

function filterSkillsDetail(q) {
    var skills = statusData.skills ? _filterSkillsByStatus(statusData.skills.skills) : [];
    var ql = (q || '').toLowerCase().trim();
    var filtered = ql ? skills.filter(function(s) {
        return (s.name || '').toLowerCase().indexOf(ql) !== -1 || (s.description || '').toLowerCase().indexOf(ql) !== -1 || (s.id || '').toLowerCase().indexOf(ql) !== -1;
    }) : skills;
    var sorted = _sortSkills(filtered);
    if (!sorted.length) { document.getElementById('skillsDetailList').innerHTML = '<div class="empty">未找到匹配的 Skill</div>'; return; }
    renderSkillsDetailList(sorted);
}

var SKILL_SORT_LABELS = { name: '名称', 'calls-desc': '调用次数（多→少）', 'calls-asc': '调用次数（少→多）' };

function _syncSkillSortDropdown() {
    var label = document.getElementById('skillSortLabel');
    if (label) label.textContent = SKILL_SORT_LABELS[currentSkillSort] || '名称';
    document.querySelectorAll('#skillSortDropdown .custom-dropdown-item').forEach(function(item) {
        item.classList.toggle('active', item.dataset.value === currentSkillSort);
    });
    closeSkillSortDropdown();
}

function toggleSkillSortDropdown() {
    var dd = document.getElementById('skillSortDropdown');
    if (!dd) return;
    var isOpen = dd.classList.toggle('open');
    var trigger = dd.querySelector('.custom-dropdown-trigger');
    if (trigger) trigger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
}

function closeSkillSortDropdown() {
    var dd = document.getElementById('skillSortDropdown');
    if (!dd) return;
    dd.classList.remove('open');
    var trigger = dd.querySelector('.custom-dropdown-trigger');
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
}

function setSkillSort(sort) {
    currentSkillSort = sort || 'name';
    _syncSkillSortDropdown();
    var q = document.getElementById('skillSearchDetail');
    filterSkillsDetail(q ? q.value : '');
}

function _filterMcpByStatus(servers) {
    if (currentMcpStatusFilter === 'enabled') return servers.filter(function(s) { return s.enabled; });
    if (currentMcpStatusFilter === 'disabled') return servers.filter(function(s) { return !s.enabled; });
    return servers;
}

function setMcpStatusFilter(status) {
    currentMcpStatusFilter = status || 'all';
    var filterEl = document.getElementById('mcpStatusFilter');
    if (filterEl) {
        filterEl.querySelectorAll('.seg-item').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.status === status);
        });
    }
    var q = document.getElementById('mcpSearchDetail');
    filterMcpDetail(q ? q.value : '');
}

function renderMcpDetail() {
    var data = statusData.mcp;
    var list = document.getElementById('mcpDetailList');
    var stats = document.getElementById('mcpDetailStats');
    if (!data) { list.innerHTML = '<div class="empty">数据加载中...</div>'; return; }
    stats.innerHTML = '<span>共 <strong>' + data.total + '</strong> 个</span><span>已启用 <strong>' + data.enabled + '</strong></span>' + (data.disabled ? '<span>已禁用 <strong>' + data.disabled + '</strong></span>' : '') + '<span>可用 <strong>' + data.healthy + '</strong></span>';
    list.className = 'mcp-grid';
    var filtered = _filterMcpByStatus(data.servers);
    if (!filtered.length) { list.innerHTML = '<div class="empty">未配置 MCP</div>'; return; }
    list.innerHTML = filtered.map(renderMcpCard).join('');
}

function filterMcpDetail(q) {
    var servers = statusData.mcp ? _filterMcpByStatus(statusData.mcp.servers) : [];
    var ql = (q || '').toLowerCase().trim();
    var filtered = ql ? servers.filter(function(s) {
        return (s.name || '').toLowerCase().indexOf(ql) !== -1 || (s.description || '').toLowerCase().indexOf(ql) !== -1 || (s.command || '').toLowerCase().indexOf(ql) !== -1;
    }) : servers;
    if (!filtered.length) { document.getElementById('mcpDetailList').innerHTML = '<div class="empty">未找到匹配的 MCP</div>'; return; }
    document.getElementById('mcpDetailList').innerHTML = filtered.map(renderMcpCard).join('');
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
    var callCount = s.callCount || 0;
    var lines = [];
    if (desc) lines.push('<div class="mcp-detail-desc"><div class="label">描述</div><div class="detail-content">' + escapeHtml(desc) + '</div></div>');
    lines.push('<div class="mcp-detail-meta"><span class="label">类型</span><span class="badge ' + info.cls + '">' + info.label + '</span></div>');
    lines.push('<div class="mcp-detail-meta"><span class="label">状态</span><span class="status ' + s.status + '"><span class="status-dot"></span>' + s.status + '</span></div>');
    lines.push('<div class="mcp-detail-meta"><span class="label">调用次数</span><span class="skill-call-count">' + callCount + ' 次</span></div>');
    lines.push('<div class="mcp-detail-meta"><span class="label">命令</span><code>' + escapeHtml(s.command) + '</code></div>');
    if (s.args && s.args.length) {
        lines.push('<div class="mcp-detail-meta"><span class="label">参数</span></div>');
        lines.push('<ul class="mcp-detail-list">' + s.args.map(function(a) { return '<li><code>' + escapeHtml(a) + '</code></li>'; }).join('') + '</ul>');
    }
    if (s.cwd) lines.push('<div class="mcp-detail-meta"><span class="label">cwd</span><code>' + escapeHtml(s.cwd) + '</code></div>');
    if (s.env && Object.keys(s.env).length) {
        lines.push('<div class="mcp-detail-meta"><span class="label">环境变量</span></div>');
        lines.push('<ul class="mcp-detail-list">' + Object.keys(s.env).map(function(k) { return '<li>' + escapeHtml(k) + '=<span class="mcp-secret">***</span></li>'; }).join('') + '</ul>');
    }
    if (s.detail && s.status === 'offline') {
        lines.push('<div class="mcp-detail-meta row-error"><span class="label">诊断信息</span><span>' + escapeHtml(s.detail) + '</span></div>');
    }
    return lines.join('');
}

function _buildMcpDiagnosticPrompt(s) {
    var lines = [
        '请帮我诊断下面这个 MCP Server 为什么无法启动或处于 offline 状态，并给出修复建议。',
        '',
        'MCP 名称: ' + (s.name || ''),
        '状态: ' + (s.status || 'unknown'),
        '诊断信息: ' + (s.detail || '无'),
        '命令: ' + (s.command || ''),
        '参数: ' + (s.args && s.args.length ? s.args.join(' ') : '无'),
        '工作目录: ' + (s.cwd || '无'),
        '环境变量键: ' + (s.env && Object.keys(s.env).length ? Object.keys(s.env).join(', ') : '无'),
        '',
        '请检查命令是否存在、参数是否正确、依赖是否安装，并告诉我应该怎么修复。'
    ];
    return lines.join('\n');
}

async function copyMcpDiagnosticPrompt(mcpName) {
    var data = statusData.mcp;
    var s = data && data.servers.find(function(x) { return x.name === mcpName; });
    if (!s) return;
    var prompt = _buildMcpDiagnosticPrompt(s);
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(prompt);
        } else {
            var ta = document.createElement('textarea');
            ta.value = prompt;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }
        showToast('已复制到剪贴板，去告诉kimi code诊断一下吧！', 3000);
    } catch (e) {
        showToast('复制失败，请手动复制', 3000);
    }
}

// 通用复制 helper（仅给 skill 复制按钮用，不改动现有 copyMcpDiagnosticPrompt/copyArtifactUrl）
async function _copyToClipboard(text, successMsg) {
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
        } else {
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }
        showToast(successMsg || '已复制到剪贴板', 2000);
    } catch (e) {
        showToast('复制失败，请手动复制', 3000);
    }
}

// 卡片「复制」按钮：复制 skill ID
function copySkillId(skillId) {
    _copyToClipboard(skillId, '已复制 Skill ID');
}

// 详情弹窗「复制」按钮：按 skillId 查路径并复制
function copySkillPath(skillId) {
    var data = statusData.skills;
    var s = data && data.skills.find(function(x) { return x.id === skillId; });
    if (!s || !s.skillPath) { showToast('该 skill 无本地路径', 3000); return; }
    _copyToClipboard(s.skillPath, '已复制 Skill 路径');
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
    var isOffline = s.status === 'offline';
    var safeName = escapeJsString(s.name);
    var displayName = escapeHtml(s.name);
    var callCount = s.callCount || 0;
    var diagBtn = isOffline ? '<button class="btn-task mcp-diag-btn" title="复制诊断 prompt 给 AI" onclick="event.stopPropagation();copyMcpDiagnosticPrompt(\'' + safeName + '\')">诊断</button>' : '';
    return '<div class="mcp-card ' + (s.enabled ? '' : 'disabled') + (isOffline ? ' offline' : '') + '" data-mcp-id="' + displayName + '" onclick="if(!event.target.closest(\'.toggle-switch\') && !event.target.closest(\'.mcp-diag-btn\'))openMcpDetail(\'' + safeName + '\')">' +
        '<div class="mcp-card-header"><span class="mcp-card-name">' + displayName + '</span><span class="status ' + statusCls + '"><span class="status-dot"></span>' + s.status + '</span></div>' +
        (desc ? '<div class="mcp-card-desc">' + escapeHtml(desc) + '</div>' : '') +
        '<div class="skill-card-meta"><span class="label">调用:</span> <span class="skill-call-count">' + callCount + ' 次</span></div>' +
        (isOffline && s.detail ? '<div class="mcp-card-error">' + escapeHtml(s.detail) + '</div>' : '') +
        '<div class="mcp-card-actions">' +
            '<label class="toggle-switch" title="启用/禁用" onclick="event.stopPropagation()"><input type="checkbox" onchange="toggleMcpEnabled(\'' + safeName + '\', this.checked)"' + enabledChecked + '><span class="toggle-slider"></span></label>' +
            diagBtn +
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
        document.getElementById('memoryChart').innerHTML = renderDonut(values, total, null, '总记忆');
        attachDonutHover();
    } catch (e) { setError('memorySummary', '加载失败: ' + e.message); }
}

// === Memory Detail ===
var memoryDetailState = { level: 'l0', query: '', data: null };

async function renderMemoryDetail() {
    var list = document.getElementById('memoryDetailList');
    var stats = document.getElementById('memoryDetailStats');
    if (!list) return;
    list.innerHTML = '<div class="empty">加载中...</div>';
    if (stats) stats.innerHTML = '';
    try {
        var url = '/api/memory/items?level=' + memoryDetailState.level + '&limit=500';
        if (memoryDetailState.query) url += '&q=' + encodeURIComponent(memoryDetailState.query);
        var data = await fetchJSON(url);
        memoryDetailState.data = data;
        if (!data.gatewayReachable) {
            list.innerHTML = '<div class="error">Gateway 未连接（127.0.0.1:8420）</div>';
            return;
        }
        if (stats) stats.innerHTML = '<span>共 <strong>' + data.total + '</strong> 条</span>';
        if (!data.items || data.items.length === 0) {
            list.innerHTML = '<div class="empty">暂无记忆数据</div>';
            return;
        }
        list.className = 'detail-list';
        list.innerHTML = data.items.map(renderMemoryItem).join('');
    } catch (e) {
        list.innerHTML = '<div class="error">加载失败: ' + escapeHtml(e.message) + '</div>';
    }
}

function renderMemoryItem(m, idx) {
    var title, subtitle, preview, badge;
    if (memoryDetailState.level === 'l0') {
        var roleLabel = (m.role || 'user') === 'user' ? '用户' : (m.role === 'assistant' ? 'Kimi' : m.role);
        var roleClass = m.role === 'user' ? 'mem-role-user' : 'mem-role-ai';
        title = '<span class="mem-role ' + roleClass + '">' + escapeHtml(roleLabel) + '</span>';
        subtitle = '<span class="mem-ts">' + escapeHtml(m.timestamp || '') + '</span>' +
            (m.session ? '<span class="mem-sep">·</span><span class="mem-session" title="' + escapeHtml(m.session) + '">' + escapeHtml(m.session.substring(0, 12)) + (m.session.length > 12 ? '…' : '') + '</span>' : '');
        preview = (m.content || '').substring(0, 280);
    } else {
        var typeMap = { episodic: '情节', instruction: '指令', persona: '人格', semantic: '语义' };
        var typeLabel = typeMap[m.type] || m.type || '记忆';
        title = '<span class="mem-type-badge mem-type-' + escapeHtml(m.type || '') + '">' + escapeHtml(typeLabel) + '</span>';
        subtitle = '<span>优先级 ' + (m.priority || 0) + '</span>';
        if (m.scene) subtitle += '<span class="mem-sep">·</span><span class="mem-scene">' + escapeHtml(m.scene) + '</span>';
        subtitle += '<span class="mem-sep">·</span><span class="mem-score">score ' + (m.score || 0).toFixed(2) + '</span>';
        preview = (m.content || '').substring(0, 280);
    }
    var hasMore = m.content && m.content.length > 280;
    return '<div class="mem-card" onclick="openMemoryModal(' + idx + ')">' +
        '<div class="mem-card-header">' + title + subtitle + '</div>' +
        '<div class="mem-card-body">' + escapeHtml(preview) + (hasMore ? '<span class="mem-more">…</span>' : '') + '</div>' +
    '</div>';
}

function filterMemoryDetail(q) {
    memoryDetailState.query = q || '';
    renderMemoryDetail();
}

function setMemoryLevel(level) {
    memoryDetailState.level = level;
    var buttons = document.querySelectorAll('#memoryLevelFilter .seg-item');
    buttons.forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-mem-level') === level);
    });
    renderMemoryDetail();
}

function openMemoryModal(idx) {
    var data = memoryDetailState.data;
    if (!data || !data.items || !data.items[idx]) return;
    var m = data.items[idx];
    var title, metaRows, content;
    if (memoryDetailState.level === 'l0') {
        var roleLabel = (m.role || 'user') === 'user' ? '用户' : (m.role === 'assistant' ? 'Kimi' : m.role);
        title = roleLabel + ' 的对话';
        metaRows = [
            ['角色', escapeHtml(m.role || '-')],
            ['时间', escapeHtml(m.timestamp || '-')],
            ['Session', escapeHtml(m.session || '-')],
            ['相似度', (m.score || 0).toFixed(3)],
        ];
    } else {
        var typeMap = { episodic: '情节记忆', instruction: '指令记忆', persona: '人格画像', semantic: '语义记忆' };
        title = typeMap[m.type] || m.type || '记忆详情';
        metaRows = [
            ['类型', escapeHtml(m.type || '-')],
            ['优先级', m.priority || 0],
            ['场景', escapeHtml(m.scene || '-')],
            ['相似度', (m.score || 0).toFixed(3)],
        ];
    }
    var metaHtml = metaRows.map(function(r) {
        return '<div class="mem-modal-meta-row"><span class="mem-modal-meta-label">' + r[0] + '</span><span class="mem-modal-meta-val">' + r[1] + '</span></div>';
    }).join('');
    var body = '<div class="mem-modal-meta">' + metaHtml + '</div>' +
        '<div class="mem-modal-content">' + escapeHtml(m.content || '') + '</div>';
    document.getElementById('memoryModalTitle').textContent = title;
    document.getElementById('memoryModalBody').innerHTML = body;
    document.body.style.overflow = 'hidden';
    document.getElementById('memoryModal').style.display = '';
}

function closeMemoryModal() {
    var modal = document.getElementById('memoryModal');
    if (modal) modal.style.display = 'none';
    document.body.style.overflow = '';
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
        document.getElementById('kimiSummary').innerHTML =
            '<div class="metric">' + data.sessionCount + '</div>' +
            '<div class="metric-label">本地会话数量 &middot; ' + escapeHtml(deviceLabel) + '</div>';

        var quotaHtml = '';
        if (!quota.configured) {
            quotaHtml = '<div class="hint"><strong>额度查询</strong><br>前往「第三方模型配置」页(<code>#/models</code>)添加 Kimi provider 并填入 API Key（推荐），或在本项目 <code>.env</code> 写入 <code>KIMI_API_KEY=your-api-key</code> 后刷新，即可显示 5 小时窗口与 7 天窗口额度。<br>API Key 可在 <a class="console-link" href="' + data.consoleUrl + '" target="_blank" rel="noopener">Kimi Code Console</a> 创建。</div>';
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
    kimiUpdateState = { checking: true, updateAvailable: false, error: null };
    renderStatusBar();
    try {
        var r = await fetchJSON('/api/kimi-update');
        // /api/kimi-update 同时返回 Kimi 和 Dashboard 的检查结果
        renderVersionCheck(r && r.kimi ? r.kimi : r);
    } catch (e) {
        kimiUpdateState = { checking: false, updateAvailable: false, error: e.message };
        renderStatusBar();
        setUpdateSlot('<button class="vc-btn vc-btn-sm" onclick="checkKimiUpdate()">检查更新</button>');
        if (box) box.innerHTML = '<div class="vc-row vc-error">版本检查失败: ' + e.message + '</div>';
    }
}

function renderVersionCheck(r) {
    var box = document.getElementById('kimiVersionCheck');
    if (r && r.error) {
        kimiUpdateState = { checking: false, updateAvailable: false, error: r.error };
        renderStatusBar();
        setUpdateSlot('<button class="vc-btn vc-btn-sm" onclick="checkKimiUpdate()">重试</button>');
        if (box) box.innerHTML = '<div class="vc-row"><span class="vc-error">最新版查询失败: ' + (r.message || r.error) + '</span></div>';
        showToast('版本检查失败: ' + escapeHtml(r.message || r.error), 5000);
        return;
    }
    if (r && r.updateAvailable) {
        kimiUpdateState = { checking: false, updateAvailable: true, error: null };
        renderStatusBar();
        var notes = (r.releaseNotes || '').replace(/"/g, '&quot;').replace(/\n/g, ' ');
        setUpdateSlot('<button class="vc-btn vc-btn-sm" onclick="runKimiUpdate()">\u2b07 更新 Kimi Code</button>');
        var html = '<div class="vc-row"><span class="vc-tag">当前 <strong>' + r.current + '</strong></span><span class="vc-tag vc-tag-warn">\u2192 最新 <strong>' + r.latest + '</strong></span>';
        if (notes) html += '<a class="vc-link" href="' + r.releaseUrl + '" target="_blank" rel="noopener" title="' + notes + '">更新内容</a>';
        else if (r.releaseUrl) html += '<a class="vc-link" href="' + r.releaseUrl + '" target="_blank" rel="noopener">Release</a>';
        html += '</div>';
        if (box) box.innerHTML = html;
        showToast('发现新版本 <strong>' + escapeHtml(r.latest) + '</strong>，点击状态栏 Kimi pill 即可更新', 6000);
        return;
    }
    if (r && r.current) {
        kimiUpdateState = { checking: false, updateAvailable: false, error: null };
        renderStatusBar();
        setUpdateSlot('<span class="vc-tag vc-tag-ok" style="font-size:0.72rem;padding:0.12rem 0.45rem;cursor:pointer" onclick="checkKimiUpdate()" title="点击重新检查">\u2713 已是最新</span>');
        if (box) box.innerHTML = '';
        showToast('当前已是最新版本 <strong>' + escapeHtml(r.current) + '</strong>', 3000);
        return;
    }
    // 默认/初始状态：手动检查按钮放在 Console 右侧 slot 里
    kimiUpdateState = { checking: false, updateAvailable: false, error: null };
    renderStatusBar();
    setUpdateSlot('<button class="vc-btn vc-btn-sm" onclick="checkKimiUpdate()">检查更新</button>');
    if (box) box.innerHTML = '';
}

function openKimiUpdateModal() {
    var modal = document.getElementById('kimiUpdateModal');
    if (modal) {
        modal.style.display = '';
        document.body.style.overflow = 'hidden';
    }
}

function closeKimiUpdateModal() {
    var modal = document.getElementById('kimiUpdateModal');
    if (modal) modal.style.display = 'none';
    document.body.style.overflow = '';
}

async function runKimiUpdate() {
    openKimiUpdateModal();
    var box = document.getElementById('kimiVersionCheck');
    if (box) box.innerHTML = '<div class="vc-row"><span class="vc-spinner"></span><span style="font-size:0.78rem;color:var(--text-secondary)">正在下载并更新…</span></div><pre class="vc-log" id="vcLog"></pre>';
    if (updatePollTimer) { clearTimeout(updatePollTimer); updatePollTimer = null; }
    kimiUpdateState = { checking: true, updateAvailable: false, error: null };
    renderStatusBar();
    try {
        // POST instead of GET (security fix)
        var r = await postJSON('/api/kimi-update/run');
        if (r.status === 'error') {
            kimiUpdateState = { checking: false, updateAvailable: false, error: r.error };
            renderStatusBar();
            if (box) box.innerHTML = '<div class="vc-row vc-error">启动更新失败: ' + r.error + '</div><button class="vc-btn vc-btn-sm" onclick="checkKimiUpdate()">返回</button>';
            return;
        }
        if (r.status === 'already_running') {
            // 已有更新进程在跑，直接进入轮询
        }
        pollUpdateStatus();
    } catch (e) {
        kimiUpdateState = { checking: false, updateAvailable: false, error: e.message };
        renderStatusBar();
        if (box) box.innerHTML = '<div class="vc-row vc-error">启动更新失败: ' + e.message + '</div>';
    }
}

function pollUpdateStatus() {
    if (updatePollTimer) clearTimeout(updatePollTimer);
    fetchJSON('/api/kimi-update/status').then(function(s) {
        var log = document.getElementById('vcLog');
        if (log && s.log) { log.textContent = s.log.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, ''); log.scrollTop = log.scrollHeight; }
        updateRetryCount = 0;
        if (s.running) {
            kimiUpdateState = { checking: true, updateAvailable: false, error: null };
            renderStatusBar();
            updatePollTimer = setTimeout(pollUpdateStatus, 1200);
        }
        else {
            kimiUpdateState = { checking: false, updateAvailable: false, error: null };
            renderStatusBar();
            var box = document.getElementById('kimiVersionCheck');
            if (!box) return;
            if (s.status === 'success') {
                box.innerHTML = '<div class="vc-row"><span class="vc-ok">\u2713 更新完成！</span></div><div class="vc-meta" style="margin-top:0.4rem">请刷新页面以加载新版本。</div><button class="vc-btn" style="margin-top:0.4rem" onclick="location.reload()">刷新页面</button>';
            } else if (s.status === 'manual_update' || s.manualUpdate) {
                var cmd = s.manualCommand || '';
                var escapedCmd = escapeHtml(cmd);
                box.innerHTML = '<div class="vc-row"><span class="vc-tag vc-tag-warn">\u26a0 此版本不支持自动更新</span></div><div class="vc-meta" style="margin-top:0.4rem">请手动运行以下命令更新：</div><pre class="vc-log" style="margin-top:0.4rem;user-select:text;cursor:text">' + escapedCmd + '</pre><div class="vc-row" style="margin-top:0.4rem"><button class="vc-btn vc-btn-sm" onclick="_copyToClipboard(this.getAttribute(\'data-cmd\'), \'已复制更新命令\')" data-cmd="' + escapedCmd + '">复制命令</button><button class="vc-btn vc-btn-sm" onclick="checkKimiUpdate()">返回</button></div>';
            } else {
                box.innerHTML = '<div class="vc-row vc-error">\u2717 更新未成功 (exit ' + s.exitCode + ')</div><pre class="vc-log">' + (s.log || '').replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '') + '</pre><button class="vc-btn vc-btn-sm" style="margin-top:0.4rem" onclick="checkKimiUpdate()">返回</button>';
            }
        }
    }).catch(function() {
        updateRetryCount++;
        if (updateRetryCount > 10) {
            showToast('更新状态轮询失败，已停止重试', 5000);
            return;
        }
        updatePollTimer = setTimeout(pollUpdateStatus, 2500 * Math.min(updateRetryCount, 5));
    });
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
    document.getElementById('trendTotal').innerHTML = formatTokens(total);
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
    document.getElementById('trendActiveDays').textContent = '-';
    document.getElementById('trendStreakDays').textContent = '-';
    try {
        trendData = await fetchJSON('/api/kimi-trends');
        statusData.trends = trendData;
        renderTrend(currentTrendUnit);
        if (trendData.total) {
            var activeDaysEl = document.getElementById('trendActiveDays');
            var streakBadgeEl = document.getElementById('trendStreakBadge');
            var streakDaysEl = document.getElementById('trendStreakDays');
            if (activeDaysEl) {
                activeDaysEl.textContent = trendData.total.activeDays || 0;
                activeDaysEl.className = 'metric';
            }
            if (streakBadgeEl) {
                streakBadgeEl.style.display = (trendData.total.streakDays || 0) > 0 ? 'inline-flex' : 'none';
            }
            if (streakDaysEl) {
                streakDaysEl.textContent = trendData.total.streakDays || 0;
            }
            var rateEl = document.getElementById('trendCacheRate');
            var evalEl = document.getElementById('trendCacheRateEval');
            var ev = trendData.total.cacheEvaluation;
            if (rateEl) {
                rateEl.textContent = (trendData.total.cacheRate || 0) + '%';
                rateEl.className = 'metric';
            }
            if (evalEl) {
                if (ev && ev.level !== 'none') {
                    evalEl.textContent = ev.label;
                    evalEl.className = 'cache-eval-badge cache-eval-' + ev.level;
                    evalEl.title = '缓存命中率 ' + (trendData.total.cacheRate || 0) + '%';
                } else {
                    evalEl.textContent = '';
                    evalEl.className = 'cache-eval-badge';
                }
            }
        }
    } catch (e) {
        setError('trendChart', '加载失败: ' + e.message);
        document.getElementById('trendTotal').textContent = '-';
        document.getElementById('trendActiveDays').textContent = '-';
        document.getElementById('trendStreakDays').textContent = '-';
        var streakBadgeErr = document.getElementById('trendStreakBadge');
        if (streakBadgeErr) streakBadgeErr.style.display = 'none';
        var rateElErr = document.getElementById('trendCacheRate');
        var evalElErr = document.getElementById('trendCacheRateEval');
        if (rateElErr) { rateElErr.textContent = '-'; rateElErr.className = 'metric'; }
        if (evalElErr) { evalElErr.textContent = ''; evalElErr.className = 'cache-eval-badge'; }
    }
}

// === Tool Usage ===
var toolSortState = { tool: false, skill: false, model: false }; // false=desc, true=asc
// Model usage trend is fixed to last 7 days (centered if sparse)

async function loadToolUsage() {
    try {
        var data = await fetchJSON('/api/tool-usage');
        statusData.toolUsage = data;
        renderToolUsageMiniCard();
        renderToolModelDetail();
    } catch (e) {
        var toolList = document.getElementById('toolUsageListDetail');
        if (toolList) toolList.innerHTML = '<div class="error">加载失败: ' + e.message + '</div>';
        renderToolUsageMiniCard();
        renderToolModelDetail();
    }
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

function renderToolLeaderboard(listId) {
    listId = listId || 'toolUsageList';
    var data = statusData.toolUsage;
    if (!data || !data.tools) return;
    var sorted = data.tools.slice().sort(function(a, b) {
        return toolSortState.tool ? a.count - b.count : b.count - a.count;
    });
    var maxTool = data.tools.length > 0 ? data.tools[0].count : 1;
    renderLeaderboardList(listId, sorted, maxTool, data.totalToolCalls || 1, 'tool');
}

function renderSkillLeaderboard(listId) {
    listId = listId || 'skillUsageList';
    var data = statusData.toolUsage;
    if (!data || !data.skills) return;
    if (data.skills.length === 0) {
        var el = document.getElementById(listId);
        if (el) el.innerHTML = '<div class="empty">暂无 Skill 调用记录</div>';
        return;
    }
    var sorted = data.skills.slice().sort(function(a, b) {
        return toolSortState.skill ? a.count - b.count : b.count - a.count;
    });
    var maxSkill = data.skills[0].count;
    var descFn = function(s) { return SKILL_DESC[s.name] || ''; };
    renderLeaderboardList(listId, sorted, maxSkill, data.totalSkillCalls || 1, 'skill', descFn);
}

function toggleSort(type) {
    toolSortState[type] = !toolSortState[type];
    var btnId = type === 'tool' ? 'sortToolBtn' : type === 'skill' ? 'sortSkillBtn' : 'sortModelBtn';
    var detailBtnId = btnId + 'Detail';
    var btn = document.getElementById(detailBtnId);
    if (btn) {
        if (toolSortState[type]) btn.classList.add('asc');
        else btn.classList.remove('asc');
    }
    if (type === 'tool') renderToolLeaderboard('toolUsageListDetail');
    else if (type === 'skill') renderSkillLeaderboard('skillUsageListDetail');
}

// === Model Usage (new feature) ===
async function loadModelUsage() {
    try {
        var data = await fetchJSON('/api/model-usage');
        statusData.modelUsage = data;
        renderToolUsageMiniCard();
        renderModelUsageMiniCard();
        renderToolModelDetail();
        renderModelUsageDetail();
    } catch (e) {
        var trendChart = document.getElementById('modelTrendChart');
        if (trendChart) trendChart.innerHTML = '<div class="error">加载失败: ' + e.message + '</div>';
        var distChart = document.getElementById('modelDistributionChart');
        if (distChart) distChart.innerHTML = '<div class="error">加载失败: ' + e.message + '</div>';
        renderToolUsageMiniCard();
        renderModelUsageMiniCard();
        renderToolModelDetail();
        renderModelUsageDetail();
    }
}

var MODEL_USAGE_COLORS = ['var(--accent)', 'var(--purple)', 'var(--success)', 'var(--warning)', 'var(--danger)', 'var(--chart-6)', 'var(--chart-7)', 'var(--chart-8)', 'var(--chart-9)', 'var(--chart-10)'];

function getModelColorMap(models) {
    var map = {};
    if (!models) return map;
    models.forEach(function(m, i) {
        var name = typeof m === 'string' ? m : (m.model || m.name || 'unknown');
        map[name] = MODEL_USAGE_COLORS[i % MODEL_USAGE_COLORS.length];
    });
    return map;
}

function _renderModelColorLegend(models, colorMap) {
    if (!models || models.length === 0) return '';
    var items = models.map(function(m) {
        var name = m.model || m.name || 'unknown';
        var shortName = name.replace('kimi-code/', '');
        var color = colorMap[name] || 'var(--accent)';
        return '<span class="bar-legend-item"><span class="bar-legend-swatch" style="background:' + color + '"></span>' + escapeHtml(shortName) + '</span>';
    }).join('');
    return '<div class="bar-chart-legend">' + items + '</div>';
}

function _getModelDistributionData(mode) {
    var data = statusData.modelUsage;
    if (!data) return [];
    var range = statusData.modelRange || 'all';
    var windowKey = (range === '24h' || range === '7d' || range === '30d') ? range : 'all';
    var win = (data.windows && data.windows[windowKey]) || data;
    var models = win.models || data.models || [];
    var field = mode === 'calls' ? 'calls' : 'total';
    return models.map(function(m) {
        return { label: m.model.replace('kimi-code/', ''), value: m[field] || 0, rawModel: m.model,
                 calls: m.calls || 0, total: m.total || 0 };
    }).filter(function(d) { return d.value > 0; });
}

// === Tool Usage mini card ===
function renderToolUsageMiniCard() {
    var metricEl = document.getElementById('toolModelMiniMetric');
    var labelEl = document.getElementById('toolModelMiniLabel');
    var statusEl = document.getElementById('toolModelMiniStatus');
    if (!metricEl || !labelEl || !statusEl) return;

    var toolData = statusData.toolUsage;
    var toolCalls = toolData ? Number(toolData.totalToolCalls || 0) : null;
    var skillCalls = toolData ? Number(toolData.totalSkillCalls || 0) : null;

    if (toolCalls === null) {
        metricEl.innerHTML = '<div class="skeleton sk-metric"></div>';
        labelEl.textContent = '加载中';
        statusEl.innerHTML = '';
        return;
    }

    metricEl.textContent = toolCalls;
    labelEl.textContent = '工具调用';

    var pills = [];
    if (skillCalls !== null && skillCalls > 0) {
        pills.push('<span class="task-mini-pill"><span class="dot"></span>Skill ' + skillCalls + '</span>');
    }
    if (toolCalls > 0 && (skillCalls === null || skillCalls === 0)) {
        pills.push('<span class="task-mini-pill"><span class="dot"></span>MCP ' + toolCalls + '</span>');
    }
    statusEl.innerHTML = pills.join('') || '<span class="task-mini-pill">暂无用量</span>';
}

// === Model Usage mini card ===
function renderModelUsageMiniCard() {
    var metricEl = document.getElementById('modelUsageMiniMetric');
    var labelEl = document.getElementById('modelUsageMiniLabel');
    var statusEl = document.getElementById('modelUsageMiniStatus');
    if (!metricEl || !labelEl || !statusEl) return;

    var modelData = statusData.modelUsage;
    var modelTokens = modelData ? Number(modelData.totalTokens || 0) : null;
    var topModel = (modelData && modelData.models && modelData.models[0]) ? modelData.models[0].model : null;

    if (modelTokens === null) {
        metricEl.innerHTML = '<div class="skeleton sk-metric"></div>';
        labelEl.textContent = '加载中';
        statusEl.innerHTML = '';
        return;
    }

    metricEl.innerHTML = formatTokens(modelTokens);
    labelEl.textContent = 'Token 用量';

    var pills = [];
    if (topModel) {
        pills.push('<span class="task-mini-pill"><span class="dot"></span>' + topModel.replace('kimi-code/', '') + '</span>');
    }
    statusEl.innerHTML = pills.join('') || '<span class="task-mini-pill">暂无用量</span>';
}

function renderToolModelDetail() {
    var toolData = statusData.toolUsage;

    var toolTotalEl = document.getElementById('toolCallTotalDetail');
    var skillTotalEl = document.getElementById('skillCallTotalDetail');
    if (toolTotalEl) toolTotalEl.textContent = toolData ? (toolData.totalToolCalls || 0) : '-';
    if (skillTotalEl) skillTotalEl.textContent = toolData ? (toolData.totalSkillCalls || 0) : '-';

    renderToolLeaderboard('toolUsageListDetail');
    renderSkillLeaderboard('skillUsageListDetail');
}

function renderModelUsageDetail() {
    var data = statusData.modelUsage;
    var totalTokensEl = document.getElementById('modelTotalTokens');
    var totalCallsEl = document.getElementById('modelTotalCalls');
    var topModelEl = document.getElementById('modelTopModel');

    if (!data) {
        if (totalTokensEl) totalTokensEl.textContent = '-';
        if (totalCallsEl) totalCallsEl.textContent = '-';
        if (topModelEl) topModelEl.textContent = '-';
        return;
    }

    // Summary cards always reflect the global totals (independent of range filter)
    if (totalTokensEl) totalTokensEl.innerHTML = formatTokens(data.totalTokens || 0);
    if (totalCallsEl) totalCallsEl.textContent = (data.totalCalls || 0).toLocaleString();
    if (topModelEl) topModelEl.textContent = (data.models && data.models[0]) ? data.models[0].model.replace('kimi-code/', '') : '-';

    var modelColorMap = getModelColorMap(data.models);

    // Trend stacked bar chart (last 7 days, centered if sparse) — unaffected by range filter
    var trendChartEl = document.getElementById('modelTrendChart');
    var rawTrendData = (data.trends && (data.trends.daily || data.trends.last7days)) || [];
    var trendData = _prepareModelTrendData(rawTrendData);
    if (trendChartEl) {
        var chartHtml = renderStackedBarChart(trendData, modelColorMap);
        var legendHtml = _renderModelColorLegend(data.models, modelColorMap);
        trendChartEl.innerHTML = chartHtml + legendHtml;
        if (chartHtml.indexOf('stackedBarSvg') >= 0) {
            attachStackedBarHover(trendData, 'modelTrendTooltip', modelColorMap);
        }
    }

    // Distribution donut + table
    var distChartEl = document.getElementById('modelDistributionChart');
    var distMode = (statusData.modelDistMode || 'token');
    var distData = _getModelDistributionData(distMode);
    if (distChartEl) {
        if (distData.length > 0) {
            var total = distData.reduce(function(s, d) { return s + d.value; }, 0);
            distChartEl.innerHTML = renderModelDistribution(distData, total, modelColorMap, distMode);
            attachDonutHover('modelDistributionChart', 'modelDistributionTooltip', function(v) { return distMode === 'calls' ? Number(v).toLocaleString() + ' 次' : formatTokens(Number(v)); });
            attachModelDistributionTableHover('modelDistributionChart', 'modelDistributionTooltip', modelColorMap, distMode);
        } else {
            distChartEl.innerHTML = '<div class="empty">暂无模型分布数据</div>';
        }
    }

    // Mode toggle (按 Token / 按调用次数)
    var modeSeg = document.getElementById('modelDistMode');
    if (modeSeg && !modeSeg.dataset.bound) {
        modeSeg.dataset.bound = '1';
        modeSeg.addEventListener('click', function(e) {
            var btn = e.target.closest('.segment-btn');
            if (!btn) return;
            var mode = btn.getAttribute('data-mode');
            if (mode === (statusData.modelDistMode || 'token')) return;
            statusData.modelDistMode = mode;
            modeSeg.querySelectorAll('.segment-btn').forEach(function(b) {
                b.classList.toggle('active', b === btn);
            });
            renderModelUsageDetail();
        });
    }

    // Time range toggle (全部 / 近30天 / 近7天 / 近24小时)
    var rangeSeg = document.getElementById('modelRangeFilter');
    if (rangeSeg && !rangeSeg.dataset.bound) {
        rangeSeg.dataset.bound = '1';
        rangeSeg.addEventListener('click', function(e) {
            var btn = e.target.closest('.segment-btn');
            if (!btn) return;
            var range = btn.getAttribute('data-range');
            if (range === (statusData.modelRange || 'all')) return;
            statusData.modelRange = range;
            rangeSeg.querySelectorAll('.segment-btn').forEach(function(b) {
                b.classList.toggle('active', b === btn);
            });
            renderModelUsageDetail();
        });
    }
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
    { value: 1048576, label: '1M' },
];
var MODEL_MAX_TOKENS_OPTIONS = [
    { value: 4096, label: '4K' },
    { value: 8192, label: '8K' },
    { value: 16384, label: '16K' },
    { value: 32768, label: '32K' },
    { value: 64000, label: '64K' },
    { value: 128000, label: '128K' },
];
var MODEL_EFFORT_OPTIONS = [
    { value: '', label: '关闭' },
    { value: 'low', label: 'low' },
    { value: 'high', label: 'high' },
    { value: 'max', label: 'max' },
];
var MASKED_KEY = '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022';

function isProtectedProvider(p) {
    // 受保护的内置 provider：id 以 managed: 开头，或类型为 kimi（Kimi / Moonshot 托管）
    return (p.id || '').indexOf('managed:') === 0 || p.type === 'kimi';
}

function escapeHtml(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function escapeJsString(s) {
    return String(s || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
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

function selectProvider(id) {
    selectedProvider = id || null;
    renderModelConfigDetail();
}

function renderModelConfigDetail() {
    var data = statusData.modelConfig;
    if (!data) { document.getElementById('providersList').innerHTML = '<div class="empty">加载中...</div>'; return; }

    var providers = data.providers || [];
    var models = data.models || [];

    // 若选中的 provider 已不存在则清空
    if (selectedProvider && !providers.find(function(p) { return p.id === selectedProvider; })) {
        selectedProvider = null;
    }
    // 默认选中第一个 provider
    if (!selectedProvider && providers.length) {
        selectedProvider = providers[0].id;
    }

    // Providers list（可点击选中）
    var providersHtml = providers.map(function(p) {
        var isSelected = p.id === selectedProvider;
        var protected = isProtectedProvider(p);
        var actionsHtml = protected ? '' :
            '<div class="config-item-actions">' +
                '<button class="btn-task" onclick="event.stopPropagation(); detectModels(\'' + escapeJsString(p.id) + '\')">探测模型</button>' +
                '<button class="btn-task" onclick="event.stopPropagation(); editProvider(\'' + escapeJsString(p.id) + '\')">编辑</button>' +
                '<button class="btn-task" onclick="event.stopPropagation(); deleteProvider(\'' + escapeJsString(p.id) + '\')">删除</button>' +
            '</div>';
        var badgeHtml = '<span class="badge badge-local">' + escapeHtml(MODEL_CONFIG_TYPE_LABEL[p.type] || p.type) + '</span>' +
            (protected ? '<span class="badge badge-remote">内置</span>' : '');
        return '<div class="config-item provider-selectable' + (isSelected ? ' selected' : '') + '" id="provider-row-' + escapeHtml(p.id) + '" onclick="selectProvider(\'' + escapeJsString(p.id) + '\')">' +
            '<div class="config-item-title"><span>' + escapeHtml(p.id) + '</span>' + badgeHtml + '</div>' +
            '<div class="config-item-meta">' + escapeHtml(p.base_url) + '</div>' +
            actionsHtml +
        '</div>';
    }).join('');
    if (!providersHtml) providersHtml = '<div class="empty">暂无 Provider，点击右上角添加</div>';
    document.getElementById('providersList').innerHTML = providersHtml;

    // Models list：只显示当前选中 provider 的模型
    var filteredModels = models.filter(function(m) {
        return m.provider === selectedProvider;
    });
    var modelsHtml = filteredModels.map(function(m) {
        var isDefault = m.id === data.default_model;
        var modelProvider = providers.find(function(p) { return p.id === m.provider; });
        var providerProtected = modelProvider && isProtectedProvider(modelProvider);
        var meta = 'model=' + escapeHtml(m.model) + ' &middot; ctx=' + (m.max_context_size || 0).toLocaleString();
        if (m.max_output_size) meta += ' &middot; max_output=' + m.max_output_size.toLocaleString();
        if (m.default_effort) meta += ' &middot; effort=' + escapeHtml(m.default_effort);
        var defaultBtn = isDefault
            ? '<span class="badge badge-local">默认</span>'
            : '<button class="btn-task btn-sm" onclick="setDefaultModel(\'' + escapeJsString(m.id) + '\')">设为默认</button>';
        var modelActionsHtml = providerProtected ? '' :
            '<div class="config-item-actions">' +
                '<button class="btn-task" onclick="editModel(\'' + escapeJsString(m.id) + '\')">编辑</button>' +
                '<button class="btn-task" onclick="deleteModel(\'' + escapeJsString(m.id) + '\')">删除</button>' +
            '</div>';
        return '<div class="config-item" id="model-row-' + escapeHtml(m.id) + '">' +
            '<div class="config-item-title"><span>' + escapeHtml(m.id) + '</span>' + defaultBtn + '</div>' +
            '<div class="config-item-meta">' + meta + '</div>' +
            '<div class="config-item-caps">' + (m.capabilities || []).map(function(c) { return '<span class="cap-badge">' + escapeHtml(c) + '</span>'; }).join('') + '</div>' +
            modelActionsHtml +
        '</div>';
    }).join('');
    if (!modelsHtml) {
        modelsHtml = '<div class="empty">' + (selectedProvider ? '该 provider 下暂无 Model，点击右上角添加' : '请先在左侧选择一个 Provider') + '</div>';
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
    return '<div class="config-form" onclick="event.stopPropagation()">' +
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
    if (!id) { showToast('Provider ID 不能为空', 5000); return; }
    var body = {
        id: id,
        type: document.getElementById('provider-type').value,
        base_url: document.getElementById('provider-base_url').value.trim(),
        api_key: document.getElementById('provider-api_key').value,
    };
    try {
        await fetchJSON('/api/model-config/provider', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        await loadModelConfig();
    } catch (e) { showToast('保存失败: ' + e.message, 5000); }
}

async function deleteProvider(id) {
    confirmDialog('确定删除 provider "' + id + '"？引用它的 model 将失效。', function() {
        (async function() {
            try {
                await fetchJSON('/api/model-config/provider/' + encodeURIComponent(id), { method: 'DELETE' });
                await loadModelConfig();
            } catch (e) { showToast('删除失败: ' + e.message, 5000); }
        })();
    });
}

function toggleDetectedBubble(el) {
    el.classList.toggle('selected');
}

async function detectModels(id) {
    var row = document.getElementById('provider-row-' + id);
    if (!row) return;
    row.innerHTML = '<div class="config-form" onclick="event.stopPropagation()"><div class="hint">正在探测模型...</div></div>';
    try {
        var data = await fetchJSON('/api/model-config/provider/' + encodeURIComponent(id) + '/detect-models', { method: 'POST' });
        var models = data.models || [];
        if (!models.length) {
            row.innerHTML = '<div class="config-form" onclick="event.stopPropagation()"><div class="hint">没有发现新模型（可能都已添加，或 provider 未返回模型列表）。</div><div class="config-form-actions"><button class="btn-task" onclick="renderModelConfigDetail()">返回</button></div></div>';
            return;
        }
        var bubbles = models.map(function(m, i) {
            return '<div class="detect-bubble" role="button" onclick="toggleDetectedBubble(this)" data-id="' + escapeHtml(m.id) + '" data-ctx="' + (m.max_context_size || 128000) + '" data-max-tokens="' + (m.max_output_size || 4096) + '" data-caps="' + escapeHtml((m.capabilities || []).join(',')) + '">' +
                escapeHtml(m.id) +
            '</div>';
        }).join('');
        row.innerHTML = '<div class="config-form" onclick="event.stopPropagation()">' +
            '<label>探测到 ' + models.length + ' 个模型，点击泡泡选择（provider: ' + escapeHtml(id) + '）</label>' +
            '<div class="detect-bubble-group">' + bubbles + '</div>' +
            '<div class="config-form-actions">' +
                '<button class="btn-task" onclick="addDetectedModels(\'' + escapeJsString(id) + '\')">添加选中模型</button>' +
                '<button class="btn-task" onclick="renderModelConfigDetail()">取消</button>' +
            '</div>' +
        '</div>';
    } catch (e) {
        row.innerHTML = '<div class="config-form" onclick="event.stopPropagation()"><div class="error">探测失败: ' + escapeHtml(e.message) + '</div><div class="config-form-actions"><button class="btn-task" onclick="renderModelConfigDetail()">返回</button></div></div>';
    }
}

async function addDetectedModels(id) {
    var selected = [];
    document.querySelectorAll('.detect-bubble.selected').forEach(function(el) {
        selected.push({
            id: el.getAttribute('data-id'),
            ctx: parseInt(el.getAttribute('data-ctx'), 10) || 128000,
            max_output_size: parseInt(el.getAttribute('data-max-tokens'), 10) || 4096,
            caps: (el.getAttribute('data-caps') || '').split(',').filter(function(c) { return c; }),
        });
    });
    if (!selected.length) { showToast('请至少选择一个模型', 5000); return; }
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
                    max_output_size: m.max_output_size,
                    capabilities: m.caps,
                })
            });
        } catch (e) {
            errors.push(m.id + ': ' + e.message);
        }
    }
    if (errors.length) {
        showToast('部分模型添加失败:\n' + errors.join('\n'), 8000);
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
    var isEdit = !!m.id;
    var providers = (statusData.modelConfig && statusData.modelConfig.providers) || [];
    var providerOptions = providers.map(function(p) {
        return '<option value="' + escapeHtml(p.id) + '"' + (m.provider === p.id ? ' selected' : '') + '>' + escapeHtml(p.id) + '</option>';
    }).join('');

    var currentCtx = m.max_context_size || 128000;
    var ctxBubbles = MODEL_CONTEXT_OPTIONS.map(function(o) {
        return '<div class="option-bubble' + (o.value === currentCtx ? ' selected' : '') + '" role="button" onclick="toggleOptionBubble(this, \'ctx-bubble-group\')" data-value="' + o.value + '">' + escapeHtml(o.label) + '</div>';
    }).join('');

    var currentMaxTokens = m.max_output_size || 4096;
    var maxTokensBubbles = MODEL_MAX_TOKENS_OPTIONS.map(function(o) {
        return '<div class="option-bubble' + (o.value === currentMaxTokens ? ' selected' : '') + '" role="button" onclick="toggleOptionBubble(this, \'maxtokens-bubble-group\')" data-value="' + o.value + '">' + escapeHtml(o.label) + '</div>';
    }).join('');

    var capBubbles = MODEL_CONFIG_CAPS.map(function(c) {
        return '<div class="option-bubble cap-bubble' + ((m.capabilities || []).indexOf(c) !== -1 ? ' selected' : '') + '" role="button" onclick="toggleCapBubble(this)" data-value="' + c + '">' + escapeHtml(c) + '</div>';
    }).join('');

    var currentEffort = m.default_effort || '';
    var effortBubbles = MODEL_EFFORT_OPTIONS.map(function(o) {
        return '<div class="option-bubble' + (o.value === currentEffort ? ' selected' : '') + '" role="button" onclick="toggleOptionBubble(this, \'effort-bubble-group\')" data-value="' + escapeHtml(o.value) + '">' + escapeHtml(o.label) + '</div>';
    }).join('');

    return '<div class="config-form">' +
        '<label>API Model</label><input type="text" id="model-api_model" value="' + escapeHtml(m.model || m.id || '') + '" placeholder="例如 gpt-4.1">' +
        (isEdit ? '<input type="hidden" id="model-id" value="' + escapeHtml(m.id) + '">' : '') +
        '<label>Provider</label><select id="model-provider">' + providerOptions + '</select>' +
        '<label>上下文长度</label><div class="option-bubble-group ctx-bubble-group">' + ctxBubbles + '</div>' +
        '<label>Max Tokens</label><div class="option-bubble-group maxtokens-bubble-group">' + maxTokensBubbles + '</div>' +
        '<label>思考强度（同 K3）</label><div class="option-bubble-group effort-bubble-group">' + effortBubbles + '</div>' +
        '<label>Capabilities</label><div class="option-bubble-group cap-bubble-group">' + capBubbles + '</div>' +
        '<div class="config-form-actions">' +
            '<button class="btn-task" onclick="saveModel()">保存</button>' +
            '<button class="btn-task" onclick="renderModelConfigDetail()">取消</button>' +
        '</div>' +
    '</div>';
}

function editModelForSelectedProvider() {
    editModel(null, selectedProvider);
}

function editModel(id, preferredProvider) {
    var data = statusData.modelConfig;
    var m = id ? (data.models || []).find(function(x) { return x.id === id; }) : { provider: preferredProvider || '' };
    var row = document.getElementById(id ? 'model-row-' + id : 'modelsList');
    if (!row) return;
    row.innerHTML = modelFormHtml(m);
}

async function saveModel() {
    var idInput = document.getElementById('model-id');
    var apiModelInput = document.getElementById('model-api_model');
    var apiModel = apiModelInput ? apiModelInput.value.trim() : '';
    var id = idInput ? idInput.value.trim() : apiModel;
    if (!id || !apiModel) { showToast('API Model 不能为空', 5000); return; }

    var ctxEl = document.querySelector('.ctx-bubble-group .option-bubble.selected');
    var maxTokensEl = document.querySelector('.maxtokens-bubble-group .option-bubble.selected');
    var effortEl = document.querySelector('.effort-bubble-group .option-bubble.selected');
    var effortVal = effortEl ? effortEl.getAttribute('data-value') : '';
    var caps = [];
    document.querySelectorAll('.cap-bubble-group .option-bubble.selected').forEach(function(b) { caps.push(b.getAttribute('data-value')); });

    var body = {
        id: id,
        provider: document.getElementById('model-provider').value,
        model: apiModel,
        display_name: apiModel,
        max_context_size: ctxEl ? parseInt(ctxEl.getAttribute('data-value'), 10) : 128000,
        max_output_size: maxTokensEl ? parseInt(maxTokensEl.getAttribute('data-value'), 10) : 4096,
        capabilities: caps,
        default_effort: effortVal,
        support_efforts: effortVal ? ['low', 'high', 'max'] : [],
    };
    try {
        await fetchJSON('/api/model-config/model', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        await loadModelConfig();
    } catch (e) { showToast('保存失败: ' + e.message, 5000); }
}

async function deleteModel(id) {
    confirmDialog('确定删除 model "' + id + '"？', function() {
        (async function() {
            try {
                await fetchJSON('/api/model-config/model/' + encodeURIComponent(id), { method: 'DELETE' });
                await loadModelConfig();
            } catch (e) { showToast('删除失败: ' + e.message, 5000); }
        })();
    });
}

async function setDefaultModel(id) {
    if (!id) return;
    try {
        await fetchJSON('/api/model-config/default-model', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: id }) });
        await loadModelConfig();
    } catch (e) { showToast('设置默认模型失败: ' + e.message, 5000); }
}

// === Settings ===
function renderSettings() {
    var isLocal = settings.kw_bind === '127.0.0.1';

    function buildControl(item) {
        if (item.type === 'link') {
            return '<a href="' + escapeHtml(item.href || '#') + '" target="_blank" class="btn-task" style="text-decoration:none;padding:0.45rem 0.75rem;font-size:0.85rem;">🌐 查看教程</a>';
        }
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
        if (item.type === 'public_urls') {
            return buildPublicUrlInput();
        }
        if (item.type === 'number') {
            var val = settings[item.key] || 0;
            return '<input type="number" class="search-box" style="width:100px" value="' + escapeHtml(String(val)) + '" onchange="setSetting(\'' + item.key + '\', parseInt(this.value,10) || 5494)">';
        }
        if (item.type === 'dashboard_port') {
            var dashboardPort = settings.dashboard_port || SETTINGS_DEFAULTS.dashboard_port;
            return '<input type="number" min="1" max="65535" class="search-box" style="width:100px" value="' + escapeHtml(String(dashboardPort)) + '" onchange="saveDashboardPort(this.value)">';
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

    function buildPublicUrlInput() {
        return '<div style="display:flex;align-items:center;justify-content:flex-end;gap:0.4rem;width:100%;">' +
            '<input type="text" class="public-url-input search-box" style="flex:1;min-width:0;max-width:360px;" placeholder="https://your-domain.com:port" onkeydown="if(event.key===&quot;Enter&quot;){event.preventDefault();addPublicUrlFromEvent(this);}">' +
            '<button type="button" class="btn-task" style="padding:0.4rem 0.75rem;font-size:0.8rem;" onclick="addPublicUrlFromEvent(this.previousElementSibling)">+</button>' +
        '</div>';
    }

    function buildPublicUrlTags() {
        var urls = Array.isArray(settings.kw_public_urls) ? settings.kw_public_urls : [];
        if (urls.length === 0) return '';
        var btnStyle = 'padding:0.15rem 0.35rem;background:transparent;border:none;border-radius:4px;color:var(--text-tertiary);cursor:pointer;font-size:0.75rem;line-height:1;';
        var tags = urls.map(function(url, idx) {
            var topBtn = idx === 0 ? '' :
                '<button type="button" title="置顶" style="' + btnStyle + '" onclick="movePublicUrlToTop(' + idx + ')">置顶</button>';
            return '<div class="public-url-tag" style="display:flex;align-items:center;gap:0.35rem;padding:0.3rem 0.6rem;background:var(--surface);border:1px solid var(--border);border-radius:999px;font-size:0.78rem;color:var(--text-secondary);">' +
                '<span style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHtml(url) + '</span>' +
                topBtn +
                '<button type="button" title="删除" style="' + btnStyle + '" onclick="removePublicUrl(' + idx + ')">×</button>' +
            '</div>';
        }).join('');
        return '<div class="public-url-tags" style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-top:0.5rem;">' + tags + '</div>';
    }

    function renderItem(item) {
        // 本机模式下隐藏外网专属设置
        if (isLocal && item.key === 'kw_public_urls') return '';

        var infoHtml = '<div class="settings-info">' +
            '<div class="config-item-title">' + escapeHtml(item.label) + '</div>' +
            '<div class="config-item-meta">' + escapeHtml(item.desc) + '</div>' +
        '</div>';

        // 自定义访问 URL：标签在左，输入框在右，已添加 URL 在描述下方跨行显示
        if (item.type === 'public_urls') {
            return '<div class="settings-item public-urls-item" style="flex-direction:column;align-items:stretch;">' +
                '<div style="display:flex;align-items:center;justify-content:space-between;gap:1.5rem;width:100%;">' +
                    infoHtml +
                    '<div class="settings-control">' + buildPublicUrlInput() + '</div>' +
                '</div>' +
                buildPublicUrlTags() +
            '</div>';
        }

        // 图床配置：整行表单
        if (item.type === 'image_bed') {
            return '<div class="settings-item image-bed-item" style="flex-direction:column;align-items:stretch;">' +
                infoHtml +
                '<div class="image-bed-form" id="imageBedForm" style="margin-top:0.5rem;">' +
                    '<div class="skeleton sk-line" style="width:60%"></div>' +
                '</div>' +
            '</div>';
        }

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
    // 异步加载图床配置表单
    loadImageBedConfig();
}

// === 自定义访问 URL 管理（必须为全局函数，供 HTML onclick 调用）===
function addPublicUrlFromEvent(input) {
    var url = normalizePublicUrl(input && input.value ? input.value : '');
    if (!url) {
        return;
    }
    var urls = Array.isArray(settings.kw_public_urls) ? settings.kw_public_urls.slice() : [];
    if (urls.indexOf(url) >= 0) {
        showToast('该 URL 已存在', 3000);
        return;
    }
    urls.push(url);
    settings.kw_public_urls = urls;
    saveSettings(settings);
    renderSettings();
}

function removePublicUrl(idx) {
    var urls = Array.isArray(settings.kw_public_urls) ? settings.kw_public_urls.slice() : [];
    urls.splice(idx, 1);
    settings.kw_public_urls = urls;
    saveSettings(settings);
    renderSettings();
}

function movePublicUrlToTop(idx) {
    var urls = Array.isArray(settings.kw_public_urls) ? settings.kw_public_urls.slice() : [];
    if (idx <= 0 || idx >= urls.length) return;
    var url = urls.splice(idx, 1)[0];
    urls.unshift(url);
    settings.kw_public_urls = urls;
    saveSettings(settings);
    renderSettings();
}

// === 图床配置（R2）===
var imageBedConfig = null;

async function loadImageBedConfig() {
    var container = document.getElementById('imageBedForm');
    if (!container) return;
    try {
        var data = await fetchJSON('/api/image-bed/config');
        imageBedConfig = data;
        renderImageBedForm(data);
    } catch (e) {
        container.innerHTML = '<div class="error">加载失败: ' + escapeHtml(e.message) + '</div>';
    }
}

function renderImageBedForm(cfg) {
    var container = document.getElementById('imageBedForm');
    if (!container) return;
    var statusBadge = cfg.enabled
        ? '<span class="src-tag src-ai" style="margin-left:0.5rem;">已启用</span>'
        : '<span class="src-tag src-user" style="margin-left:0.5rem;">未配置</span>';
    var inputStyle = 'width:100%;padding:0.35rem 0.6rem;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text);font-size:0.82rem;';
    var labelStyle = 'display:block;font-size:0.75rem;color:var(--text-tertiary);margin-bottom:0.2rem;margin-top:0.5rem;';
    var field = function(id, label, val, placeholder, type) {
        return '<div>' +
            '<label style="' + labelStyle + '">' + label + '</label>' +
            '<input type="' + (type || 'text') + '" id="' + id + '" style="' + inputStyle + '" value="' + escapeHtml(val || '') + '" placeholder="' + escapeHtml(placeholder || '') + '">' +
        '</div>';
    };
    // Provider 选择 + 对应 endpoint 占位符
    var providers = [
        { v: 'r2',   t: 'Cloudflare R2',  endpoint: 'https://<account_id>.r2.cloudflarestorage.com' },
        { v: 's3',   t: 'AWS S3',          endpoint: 'https://s3.<region>.amazonaws.com' },
        { v: 'minio',t: 'MinIO',           endpoint: 'http://localhost:9000' },
        { v: 'oss',  t: '阿里云 OSS',      endpoint: 'https://<region>.aliyuncs.com' },
        { v: 'cos',  t: '腾讯云 COS',      endpoint: 'https://cos.<region>.myqcloud.com' },
        { v: 'other',t: '其他（S3 兼容）',  endpoint: '' },
    ];
    var currentProvider = cfg.provider || 'r2';
    var providerOpts = providers.map(function(p) {
        var sel = p.v === currentProvider ? ' selected' : '';
        return '<option value="' + p.v + '"' + sel + '>' + escapeHtml(p.t) + '</option>';
    }).join('');
    var currentEndpointPlaceholder = (providers.find(function(p){return p.v===currentProvider;})||{}).endpoint || '';
    var providerField = '<div>' +
        '<label style="' + labelStyle + '">服务提供商</label>' +
        '<select id="ib_provider" style="' + inputStyle + '" onchange="onImageBedProviderChange()">' + providerOpts + '</select>' +
    '</div>';
    container.innerHTML =
        '<div style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:0.3rem;">当前状态: ' + (cfg.enabled ? '已启用' : '未配置') + statusBadge + '</div>' +
        providerField +
        field('ib_endpoint', 'Endpoint URL', cfg.endpoint_url, currentEndpointPlaceholder) +
        field('ib_access_key', 'Access Key', cfg.access_key_masked, cfg.has_access_key ? '已配置（留空保留原值）' : '输入 Access Key') +
        field('ib_secret_key', 'Secret Key', cfg.secret_key_masked, cfg.has_secret_key ? '已配置（留空保留原值）' : '输入 Secret Key', 'password') +
        field('ib_bucket', 'Bucket', cfg.bucket, 'your-bucket-name') +
        field('ib_public_url', '公开访问域名', cfg.public_base_url, 'https://cdn.example.com') +
        field('ib_path_template', '路径模板', cfg.path_template, '{file_id}') +
        '<div style="display:flex;gap:0.5rem;margin-top:0.8rem;">' +
            '<button class="btn-task" onclick="saveImageBedConfig()">保存配置</button>' +
            '<button class="btn-task" onclick="testImageBedConnection()">测试连接</button>' +
        '</div>' +
        '<div id="imageBedResult" style="margin-top:0.5rem;font-size:0.78rem;"></div>';
}

function onImageBedProviderChange() {
    var sel = document.getElementById('ib_provider');
    var endpointInput = document.getElementById('ib_endpoint');
    if (!sel || !endpointInput) return;
    var providers = {
        r2:    'https://<account_id>.r2.cloudflarestorage.com',
        s3:    'https://s3.<region>.amazonaws.com',
        minio: 'http://localhost:9000',
        oss:   'https://<region>.aliyuncs.com',
        cos:   'https://cos.<region>.myqcloud.com',
        other: ''
    };
    var placeholder = providers[sel.value] || '';
    endpointInput.placeholder = placeholder;
}

async function saveImageBedConfig() {
    var resultEl = document.getElementById('imageBedResult');
    if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-tertiary);">保存中...</span>';
    try {
        var body = {
            provider: document.getElementById('ib_provider').value,
            endpoint_url: document.getElementById('ib_endpoint').value,
            access_key: document.getElementById('ib_access_key').value,
            secret_key: document.getElementById('ib_secret_key').value,
            bucket: document.getElementById('ib_bucket').value,
            public_base_url: document.getElementById('ib_public_url').value,
            path_template: document.getElementById('ib_path_template').value,
        };
        var data = await postJSON('/api/image-bed/config', body);
        if (data.success) {
            showToast('图床配置已保存', 3000);
            if (resultEl) resultEl.innerHTML = '<span style="color:var(--accent);">保存成功</span>';
            await loadImageBedConfig();
        } else {
            if (resultEl) resultEl.innerHTML = '<span class="error">保存失败: ' + escapeHtml(data.error || '') + '</span>';
        }
    } catch (e) {
        if (resultEl) resultEl.innerHTML = '<span class="error">保存失败: ' + escapeHtml(e.message) + '</span>';
    }
}

async function testImageBedConnection() {
    var resultEl = document.getElementById('imageBedResult');
    if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-tertiary);">测试中...</span>';
    try {
        var data = await postJSON('/api/image-bed/test');
        if (data.ok) {
            if (resultEl) resultEl.innerHTML = '<span style="color:var(--accent);">✓ ' + escapeHtml(data.msg) + '</span>';
        } else {
            if (resultEl) resultEl.innerHTML = '<span class="error">✗ ' + escapeHtml(data.msg) + '</span>';
        }
    } catch (e) {
        if (resultEl) resultEl.innerHTML = '<span class="error">测试失败: ' + escapeHtml(e.message) + '</span>';
    }
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
    var resultLabel = '<span style="color:' + resultColor + '">' + escapeHtml(resultStatus.label) + '</span>';
    var enabledChecked = t.enabled ? ' checked' : '';
    var safeId = escapeJsString(t.id);
    var displayName = escapeHtml(t.name);
    var displayDesc = escapeHtml(t.description);
    var displaySchedule = escapeHtml(t.schedule);
    return '<div class="task-card" data-task-id="' + displayName + '"><div class="task-card-header"><span class="task-card-name">' + displayName + '</span><span class="task-state-badge ' + stateCls + '">' + stateLabel + '</span></div><div class="task-card-desc">' + displayDesc + '</div><div class="task-card-schedule">\u23f0 ' + displaySchedule + '</div>' + renderTaskSources(t.sources, t.logPreview) + '<div class="task-card-info">' + (s.lastRun && s.lastRun !== '1999-11-30T00:00:00' ? '<div><span class="label">上次运行:</span> ' + s.lastRun.replace('T', ' ') + '</div>' : '<div><span class="label">上次运行:</span> 尚未运行</div>') + (s.nextRun ? '<div><span class="label">下次运行:</span> ' + s.nextRun.replace('T', ' ') + '</div>' : '') + (resultStatus.label ? '<div><span class="label">运行结果:</span> ' + resultLabel + '</div>' : '') + '</div><div class="task-card-actions"><label class="toggle-switch" title="启用/禁用"><input type="checkbox" onchange="toggleTaskEnabled(\'' + safeId + '\', this.checked)"' + enabledChecked + '><span class="toggle-slider"></span></label><button class="btn-task" onclick="runTask(\'' + safeId + '\', this)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 3 20 12 6 21 6 3"/></svg>立即运行</button><button class="btn-task" onclick="openTaskEdit(\'' + safeId + '\')">编辑</button>' + (t.logFile ? '<button class="btn-task" onclick="openTaskLog(\'' + safeId + '\')">日志</button>' : '') + '<button class="btn-task btn-danger" onclick="deleteTask(\'' + safeId + '\')">删除</button></div></div>';
}

function _filterTasksByStatus(tasks) {
    if (currentTaskStatusFilter === 'enabled') return tasks.filter(function(t) { return t.enabled; });
    if (currentTaskStatusFilter === 'disabled') return tasks.filter(function(t) { return !t.enabled; });
    return tasks;
}

function setTaskStatusFilter(status) {
    currentTaskStatusFilter = status || 'all';
    var filterEl = document.getElementById('taskStatusFilter');
    if (filterEl) {
        filterEl.querySelectorAll('.seg-item').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.status === status);
        });
    }
    var q = document.getElementById('taskSearchDetail');
    filterTasksDetail(q ? q.value : '');
}

function filterTasksDetail(q) {
    var tasks = statusData.tasks ? _filterTasksByStatus(statusData.tasks.tasks) : [];
    var ql = (q || '').toLowerCase().trim();
    var filtered = ql ? tasks.filter(function(t) {
        return (t.name || '').toLowerCase().indexOf(ql) !== -1 || (t.description || '').toLowerCase().indexOf(ql) !== -1 || (t.id || '').toLowerCase().indexOf(ql) !== -1;
    }) : tasks;
    var grid = document.getElementById('tasksDetailGrid');
    if (!filtered.length) { grid.innerHTML = '<div class="empty">未找到匹配的定时任务</div>'; return; }
    grid.innerHTML = filtered.map(renderTaskCard).join('');
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
    var filtered = _filterTasksByStatus(data.tasks);
    if (!filtered.length) { grid.innerHTML = '<div class="empty">暂无定时任务</div>'; return; }
    grid.innerHTML = filtered.map(renderTaskCard).join('');
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
    confirmDialog('确定删除任务 "' + name + '"？\n这会同时删除 Windows 任务计划程序中的对应任务。', function() {
        (async function() {
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
        })();
    });
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

// === Hooks Detail ===
function renderHookCard(h) {
    var stateCls = h.enabled ? 'ready' : 'disabled';
    var stateLabel = h.enabled ? '已启用' : '已禁用';
    var timeoutText = h.timeout ? h.timeout + 's' : '默认 30s';
    var matcherText = h.matcher ? '<code>' + escapeHtml(h.matcher) + '</code>' : '<span class="text-secondary">无 matcher</span>';
    var description = h.description ? escapeHtml(h.description) : '<span class="text-secondary">暂无描述</span>';
    return '<div class="task-card" data-hook-id="' + h.id + '"><div class="task-card-header"><span class="task-card-name">' + escapeHtml(h.event) + '</span><span class="task-state-badge ' + stateCls + '">' + stateLabel + '</span></div><div class="task-card-desc hook-card-desc">' + description + '</div><div class="task-card-info"><div><span class="label">matcher:</span> ' + matcherText + '</div><div><span class="label">timeout:</span> ' + timeoutText + '</div></div><div class="task-card-actions"><label class="toggle-switch" title="启用/禁用"><input type="checkbox" onchange="toggleHook(\'' + h.id + '\')"' + (h.enabled ? ' checked' : '') + '><span class="toggle-slider"></span></label><button class="btn-task" onclick="openHookEdit(\'' + h.id + '\')">编辑</button><button class="btn-task btn-danger" onclick="deleteHook(\'' + h.id + '\')">删除</button></div></div>';
}

function _filterHooksByStatus(hooks) {
    if (currentHookStatusFilter === 'enabled') return hooks.filter(function(h) { return h.enabled; });
    if (currentHookStatusFilter === 'disabled') return hooks.filter(function(h) { return !h.enabled; });
    return hooks;
}

function setHookStatusFilter(status) {
    currentHookStatusFilter = status || 'all';
    var filterEl = document.getElementById('hookStatusFilter');
    if (filterEl) {
        filterEl.querySelectorAll('.seg-item').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.status === status);
        });
    }
    var q = document.getElementById('hookSearchDetail');
    filterHooksDetail(q ? q.value : '');
}

function filterHooksDetail(q) {
    var hooks = statusData.hooks ? _filterHooksByStatus(statusData.hooks.hooks) : [];
    var ql = (q || '').toLowerCase().trim();
    var filtered = ql ? hooks.filter(function(h) {
        return (h.event || '').toLowerCase().indexOf(ql) !== -1 ||
            (h.matcher || '').toLowerCase().indexOf(ql) !== -1 ||
            (h.command || '').toLowerCase().indexOf(ql) !== -1 ||
            (h.description || '').toLowerCase().indexOf(ql) !== -1;
    }) : hooks;
    var grid = document.getElementById('hooksDetailGrid');
    if (!filtered.length) { grid.innerHTML = '<div class="empty">暂无 Hooks</div>'; return; }
    grid.innerHTML = filtered.map(renderHookCard).join('');
}

function renderHooksDetail() {
    var data = statusData.hooks;
    var grid = document.getElementById('hooksDetailGrid');
    var stats = document.getElementById('hooksDetailStats');
    if (!data) {
        if (grid) grid.innerHTML = '<div class="empty">数据加载中...</div>';
        if (stats) stats.innerHTML = '';
        loadHooks();
        return;
    }
    if (stats) {
        var statItems = ['<span>共 <strong>' + data.total + '</strong> 个</span>'];
        if (data.enabledCount) statItems.push('<span>已启用 <strong>' + data.enabledCount + '</strong></span>');
        if (data.disabledCount) statItems.push('<span>已禁用 <strong>' + data.disabledCount + '</strong></span>');
        stats.innerHTML = statItems.join('');
    }
    filterHooksDetail(document.getElementById('hookSearchDetail').value);
}

// === Hook Edit Modal ===
function openHookEdit(hookId) {
    var data = statusData.hooks;
    var h = hookId ? data.hooks.find(function(x) { return x.id === hookId; }) : null;
    _currentHookCreate = !hookId;
    _currentHookEditId = hookId || null;
    document.getElementById('hook-edit-title').textContent = hookId ? '编辑 Hook' : '新建 Hook';
    document.getElementById('hook-edit-id').value = hookId || '';
    document.getElementById('hook-edit-event').value = h ? h.event : 'Stop';
    document.getElementById('hook-edit-description').value = h ? (h.description || '') : '';
    document.getElementById('hook-edit-matcher').value = h ? (h.matcher || '') : '';
    document.getElementById('hook-edit-command').value = h ? h.command : '';
    document.getElementById('hook-edit-timeout').value = h && h.timeout ? h.timeout : '';
    document.getElementById('hook-edit-enabled').checked = h ? h.enabled : true;
    document.getElementById('hookEditModal').style.display = '';
    document.body.style.overflow = 'hidden';
}

function closeHookEdit() {
    document.getElementById('hookEditModal').style.display = 'none';
    document.body.style.overflow = '';
    _currentHookEditId = null;
    _currentHookCreate = false;
}

async function saveHook() {
    var hookId = _currentHookEditId;
    var isCreate = _currentHookCreate;
    var btn = document.getElementById('hook-edit-save-btn');
    var orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '保存中...';

    var body = {
        event: document.getElementById('hook-edit-event').value.trim(),
        description: document.getElementById('hook-edit-description').value.trim(),
        matcher: document.getElementById('hook-edit-matcher').value.trim(),
        command: document.getElementById('hook-edit-command').value.trim(),
        timeout: document.getElementById('hook-edit-timeout').value,
        enabled: document.getElementById('hook-edit-enabled').checked,
    };

    if (!body.event || !body.command) {
        showToast('事件和命令不能为空', 3000);
        btn.disabled = false;
        btn.innerHTML = orig;
        return;
    }

    try {
        var data;
        if (isCreate) {
            data = await postJSON('/api/hooks', body);
        } else {
            data = await postJSON('/api/hooks/' + hookId, body);
        }
        if (data.success) {
            closeHookEdit();
            showToast(isCreate ? 'Hook 已创建' : 'Hook 已保存', 3000);
            await loadHooks();
            if (location.hash === '#/hooks') renderHooksDetail();
        } else {
            showToast('保存失败: ' + (data.error || '未知错误'), 5000);
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, 5000);
    } finally {
        btn.disabled = false;
        btn.innerHTML = orig;
    }
}

async function toggleHook(hookId) {
    try {
        var data = await postJSON('/api/hooks/' + hookId + '/toggle');
        if (data.success) {
            showToast('Hook 状态已切换', 3000);
            await loadHooks();
            if (location.hash === '#/hooks') renderHooksDetail();
        } else {
            showToast('设置失败: ' + (data.error || '未知错误'), 5000);
            await loadHooks();
        }
    } catch (e) {
        showToast('设置失败: ' + e.message, 5000);
        await loadHooks();
    }
}

async function deleteHook(hookId) {
    var data = statusData.hooks;
    var h = data && data.hooks.find(function(x) { return x.id === hookId; });
    var label = h ? h.event + (h.matcher ? ' (' + h.matcher + ')' : '') : hookId;
    confirmDialog('确定删除 Hook "' + label + '"？', function() {
        (async function() {
            try {
                var res = await postJSON('/api/hooks/' + hookId + '/delete');
                if (res.success) {
                    showToast('Hook 已删除', 3000);
                    await loadHooks();
                    if (location.hash === '#/hooks') renderHooksDetail();
                } else {
                    showToast('删除失败: ' + (res.error || '未知错误'), 5000);
                }
            } catch (e) {
                showToast('删除失败: ' + e.message, 5000);
            }
        })();
    });
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
    confirmDialog('确定卸载 Skill "' + name + '"？\n这会删除本地 skill 目录。', function() {
        (async function() {
            try {
                await postJSON('/api/skills/' + skillId + '/delete');
                showToast('Skill 已卸载', 3000);
                await loadSkills();
            } catch (e) {
                showToast('卸载失败: ' + e.message, 5000);
            }
        })();
    });
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
    confirmDialog('确定删除 MCP Server "' + (s ? s.name : mcpId) + '"？\n这会从配置中移除，不会删除实际文件。', function() {
        (async function() {
            try {
                await postJSON('/api/mcp/' + mcpId + '/delete');
                showToast('MCP Server 已删除', 3000);
                await loadMCP();
            } catch (e) {
                showToast('删除失败: ' + e.message, 5000);
            }
        })();
    });
}

async function toggleMcpEnabled(mcpId, enabled) {
    try {
        var data = await postJSON('/api/mcp/' + mcpId + '/toggle', { enabled: enabled });
        if (data.success) {
            showToast('MCP Server 已' + (data.enabled ? '启用' : '禁用') + '，需要重启 Kimi Code 才能生效', 4000);
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
        var el = document.getElementById('headerDashboardVersion');
        if (el) el.textContent = 'v' + (data.version || '1.0.0');
    } catch (e) {
        window.dashboardVersion = '1.0.0';
    }
}

// === Startup service (macOS launchd / Windows Task Scheduler) ===
async function loadDashboardPort() {
    try {
        var data = await fetchJSON('/api/dashboard-port');
        var port = parseInt(data.port, 10);
        if (port >= 1 && port <= 65535) {
            settings.dashboard_port = port;
            saveSettings(settings);
        }
    } catch (e) {
        console.warn('Failed to load dashboard port:', e.message);
    }
    if (location.hash === '#/settings') renderSettings();
}

async function saveDashboardPort(value) {
    var port = parseInt(value, 10);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
        showToast('端口必须在 1–65535 之间', 4000);
        renderSettings();
        return;
    }
    try {
        var data = await postJSON('/api/dashboard-port', { port: port });
        if (data.success) {
            settings.dashboard_port = parseInt(data.port, 10) || port;
            saveSettings(settings);
            renderSettings();
            showToast('Dashboard 端口已保存，重启 Dashboard 后生效', 5000);
        } else {
            showToast('保存失败: ' + (data.error || '未知错误'), 5000);
            renderSettings();
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, 5000);
        renderSettings();
    }
}

async function loadKimiConfig() {
    try {
        var data = await fetchJSON('/api/kimi-config');
        if (data.default_permission_mode) {
            settings.default_permission_mode = data.default_permission_mode;
            saveSettings(settings);
        }
    } catch (e) {
        console.warn('Failed to load kimi config:', e.message);
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
            payload.public_urls = (settings.kw_public_urls || []).map(normalizePublicUrl).filter(Boolean);
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

// === Artifacts Browser ===
async function loadArtifacts() {
    try {
        var data = await fetchJSON('/api/artifacts/all?limit=500');
        artifactsData = data;
        var total = (data.items || []).length;
        document.getElementById('artifactsMiniMetric').textContent = total;
        document.getElementById('artifactsMiniLabel').textContent = '本地 + AI';
        var aiCount = (data.items || []).filter(function(x) { return x.source === 'ai'; }).length;
        var userCount = total - aiCount;
        var pills = [];
        if (aiCount) pills.push('<span class="task-mini-pill"><span class="dot"></span>AI ' + aiCount + '</span>');
        if (userCount) pills.push('<span class="task-mini-pill"><span class="dot"></span>用户 ' + userCount + '</span>');
        document.getElementById('artifactsMiniStatus').innerHTML = pills.join('') || '<span class="task-mini-pill">暂无产物</span>';
        if (location.hash === '#/artifacts') renderArtifactsDetail();
    } catch (e) {
        document.getElementById('artifactsMiniMetric').textContent = '!';
        document.getElementById('artifactsMiniLabel').textContent = '加载失败';
        document.getElementById('artifactsMiniStatus').innerHTML = '<span class="task-mini-pill">加载失败</span>';
        artifactsData = null;
        if (location.hash === '#/artifacts') {
            var grid = document.getElementById('artifactsGrid');
            var stats = document.getElementById('artifactsDetailStats');
            if (grid) grid.innerHTML = '<div class="error">加载失败: ' + escapeHtml(e.message) + '</div>';
            if (stats) stats.innerHTML = '';
        }
    }
}

function getArtifactContentUrl(id) {
    var isSha = /^[a-f0-9]{64}$/i.test(id);
    return isSha ? '/api/artifacts/blobs/' + encodeURIComponent(id) + '/content' : '/api/artifacts/' + encodeURIComponent(id) + '/content';
}

function getArtifactUploadUrl(id) {
    var isSha = /^[a-f0-9]{64}$/i.test(id);
    return isSha ? '/api/artifacts/blobs/' + encodeURIComponent(id) + '/upload' : '/api/artifacts/' + encodeURIComponent(id) + '/upload';
}

function renderArtifactsDetail() {
    var data = artifactsData;
    var grid = document.getElementById('artifactsGrid');
    var stats = document.getElementById('artifactsDetailStats');
    if (!data || !data.items) { grid.innerHTML = '<div class="empty">数据加载中...</div>'; return; }

    var items = data.items.filter(function(x) {
        if (currentArtifactSource !== 'all' && x.source !== currentArtifactSource) return false;
        var q = currentArtifactQuery.trim().toLowerCase();
        if (!q) return true;
        return (x.name || '').toLowerCase().indexOf(q) >= 0 || (x.id || '').toLowerCase().indexOf(q) >= 0 || (x.media_type || '').toLowerCase().indexOf(q) >= 0;
    });

    if (stats) {
        var total = data.items.length;
        var shown = items.length;
        stats.innerHTML = '<span>共 <strong>' + total + '</strong> 个</span>' + (shown !== total ? '<span>筛选后 <strong>' + shown + '</strong> 个</span>' : '');
    }

    if (!items.length) { grid.innerHTML = '<div class="empty">没有匹配的产物</div>'; return; }
    grid.innerHTML = items.map(renderArtifactCard).join('');
}

function renderArtifactCard(x) {
    var contentUrl = getArtifactContentUrl(x.id);
    var isImage = (x.media_type || '').indexOf('image/') === 0;
    var srcTag = x.source === 'ai' ? '<span class="src-tag src-ai">AI</span>' : '<span class="src-tag src-user">用户</span>';
    var cloudBadge = x.uploaded_url ?
        '<span class="artifact-cloud-badge" title="已上传到图床"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></span>' : '';
    var thumb;
    if (isImage) {
        thumb = '<div class="artifact-thumb"><img src="' + escapeHtml(contentUrl) + '" alt="" loading="lazy">' + cloudBadge + '</div>';
    } else {
        var ext = (x.name || '').split('.').pop().toUpperCase() || 'FILE';
        thumb = '<div class="artifact-thumb"><div class="artifact-thumb-fallback"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg><span>' + escapeHtml(ext) + '</span></div>' + cloudBadge + '</div>';
    }
    return '<div class="artifact-card" onclick="openArtifactModal(\'' + escapeJsString(x.id) + '\')">' +
        thumb +
        '<div class="artifact-meta"><div class="artifact-name" title="' + escapeHtml(x.name || x.id) + '">' + escapeHtml(x.name || x.id) + ' ' + srcTag + '</div><div class="artifact-sub">' + escapeHtml(formatSize(x.size)) + ' &middot; ' + escapeHtml(formatDate(x.created_at)) + '</div></div>' +
        '</div>';
}

function filterArtifacts(q) {
    currentArtifactQuery = q || '';
    renderArtifactsDetail();
}

function setArtifactSource(source) {
    currentArtifactSource = source || 'all';
    var buttons = document.querySelectorAll('#artifactFilter .seg-item');
    buttons.forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-art-source') === source);
    });
    renderArtifactsDetail();
}

function openArtifactModal(id) {
    var data = artifactsData;
    if (!data || !data.items) return;
    var x = data.items.find(function(item) { return item.id === id; });
    if (!x) return;
    var modal = document.getElementById('artifactModal');
    var title = document.getElementById('artifactModalTitle');
    var body = document.getElementById('artifactModalBody');
    var contentUrl = getArtifactContentUrl(x.id);
    var isImage = (x.media_type || '').indexOf('image/') === 0;
    var sourceLabel = x.source === 'ai' ? 'AI 生成' : '用户上传';
    var sourceClass = x.source === 'ai' ? 'pill-ai' : 'pill-user';

    title.textContent = x.name || x.id;

    var preview = '';
    if (isImage) {
        preview = '<div style="text-align:center;margin-bottom:1rem;"><a href="' + escapeHtml(contentUrl) + '" target="_blank"><img src="' + escapeHtml(contentUrl) + '" style="max-width:100%;max-height:60vh;border-radius:var(--radius-sm);border:1px solid var(--border);"></a></div>';
    } else {
        preview = '<div style="text-align:center;margin-bottom:1rem;padding:2rem;background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border);"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg><div style="margin-top:0.5rem;"><a class="btn-task" href="' + escapeHtml(contentUrl) + '" target="_blank" download>下载文件</a></div></div>';
    }

    var uploadSection;
    if (x.uploaded_url) {
        uploadSection = '<div class="artifact-info-row"><span class="info-label">图床 URL</span><input class="info-input" id="artifactUploadedUrl" readonly value="' + escapeHtml(x.uploaded_url) + '"><button class="btn-task" onclick="copyArtifactUrl()">复制</button></div>';
    } else {
        uploadSection = '<div class="artifact-info-row"><span class="info-label">图床</span><span style="color:var(--text-secondary);font-size:0.78rem;">尚未上传</span><button class="btn-task" id="artifactUploadBtn" onclick="uploadArtifact(\'' + escapeJsString(x.id) + '\')">上传到图床</button></div>';
    }

    body.innerHTML = preview +
        '<div class="artifact-info-row"><span class="info-label">ID</span><code>' + escapeHtml(x.id) + '</code></div>' +
        '<div class="artifact-info-row"><span class="info-label">来源</span><span class="pill ' + sourceClass + '">' + sourceLabel + '</span></div>' +
        '<div class="artifact-info-row"><span class="info-label">类型</span><code>' + escapeHtml(x.media_type || '未知') + '</code></div>' +
        '<div class="artifact-info-row"><span class="info-label">大小</span><span style="font-size:0.85rem;">' + escapeHtml(formatSize(x.size)) + '</span></div>' +
        '<div class="artifact-info-row"><span class="info-label">创建时间</span><span style="font-size:0.85rem;">' + escapeHtml(formatDate(x.created_at)) + '</span></div>' +
        uploadSection +
        '<div class="artifact-info-row"><span class="info-label">本地链接</span><a class="btn-task" href="' + escapeHtml(contentUrl) + '" target="_blank">' + (isImage ? '查看原图' : '下载文件') + '</a></div>';

    document.body.style.overflow = 'hidden';
    modal.style.display = '';
}

function closeArtifactModal() {
    var modal = document.getElementById('artifactModal');
    if (modal) modal.style.display = 'none';
    document.body.style.overflow = '';
}

async function uploadArtifact(id) {
    var btn = document.getElementById('artifactUploadBtn');
    if (btn) { btn.disabled = true; btn.textContent = '上传中...'; }
    try {
        var data = await postJSON(getArtifactUploadUrl(id));
        if (data.success) {
            showToast('上传成功', 3000);
            // 更新本地缓存数据并刷新弹窗
            if (artifactsData && artifactsData.items) {
                var x = artifactsData.items.find(function(item) { return item.id === id; });
                if (x) { x.uploaded_url = data.url; x.uploaded_at = new Date().toISOString(); }
            }
            openArtifactModal(id);
            renderArtifactsDetail();
        } else {
            showToast('上传失败: ' + (data.error || '未知错误'), 5000);
            if (btn) { btn.disabled = false; btn.textContent = '上传到图床'; }
        }
    } catch (e) {
        showToast('上传失败: ' + e.message, 5000);
        if (btn) { btn.disabled = false; btn.textContent = '上传到图床'; }
    }
}

function copyArtifactUrl() {
    var input = document.getElementById('artifactUploadedUrl');
    if (!input) return;
    input.select();
    try {
        document.execCommand('copy');
        showToast('已复制到剪贴板', 2000);
    } catch (e) {
        showToast('复制失败，请手动复制', 3000);
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
    await Promise.all([loadTrends(), loadSkills(), loadMCP(), loadHooks(), loadMemory(), loadKimi(), loadToolUsage(), loadModelUsage(), loadTasks(), loadModelConfig(), loadArtifacts()]);
    renderStatusBar();
    applySettings();
    document.getElementById('lastUpdated').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN');
    showToast('数据已刷新', 2000);
}

// === Init ===
Promise.all([loadDashboardVersion(), loadDashboardPort(), loadStartupServiceStatus(), loadKimiConfig()]).then(loadAll);
checkKimiWebStatus();
var kimiWebTimer = setInterval(checkKimiWebStatus, 10000);
document.addEventListener('visibilitychange', function() {
    if (document.hidden) {
        if (kimiWebTimer) { clearInterval(kimiWebTimer); kimiWebTimer = null; }
    } else if (!kimiWebTimer) {
        checkKimiWebStatus();
        kimiWebTimer = setInterval(checkKimiWebStatus, 10000);
    }
});
window.addEventListener('hashchange', handleRoute);
document.addEventListener('click', function(e) {
    var dd = document.getElementById('skillSortDropdown');
    if (dd && !dd.contains(e.target)) closeSkillSortDropdown();
});
document.addEventListener('keydown', function(e) {
    if (e.key !== 'Escape') return;
    var modals = document.querySelectorAll('.modal-overlay');
    for (var i = modals.length - 1; i >= 0; i--) {
        if (modals[i].style.display !== 'none') {
            var closeBtn = modals[i].querySelector('.modal-close');
            if (closeBtn) closeBtn.click();
            return;
        }
    }
});
// confirmDialog 按钮事件绑定
(function() {
    var okBtn = document.getElementById('confirmDialogOk');
    var cancelBtn = document.getElementById('confirmDialogCancel');
    var dlg = document.getElementById('confirmDialog');
    if (okBtn) okBtn.addEventListener('click', _confirmDialogOk);
    if (cancelBtn) cancelBtn.addEventListener('click', closeConfirmDialog);
    if (dlg) dlg.addEventListener('click', function(e) { if (e.target === dlg) closeConfirmDialog(); });
})();
handleRoute();
