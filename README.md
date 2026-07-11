# Kimi Code Dashboard

Kimi Code CLI 的本地可视化面板，展示 Skill、MCP、记忆状态、Kimi 用量概览、模型分布和定时任务。

## 启动

```bash
cd ~/.kimi-code/dashboard
.venv/Scripts/python.exe app.py
```

然后浏览器打开：http://127.0.0.1:8080

## 项目结构

```
dashboard/
├── app.py              # 入口：创建 Flask app，注册蓝图
├── config.py           # 路径、常量、日志配置
├── .env                # API Key（不提交 git）
├── .gitignore
├── tasks.json          # 定时任务配置
├── services/
│   ├── helpers.py      # JSON/HTTP/TCP/YAML 工具函数 + PowerShell 转义
│   └── wire_parser.py  # 合并 wire.jsonl 解析（增量+缓存+模型统计）
├── routes/
│   ├── skills.py       # /api/skills
│   ├── mcp.py          # /api/mcp
│   ├── memory.py       # /api/memory
│   ├── kimi.py         # /api/kimi, /api/kimi-trends, /api/kimi-quota,
│   │                   #   /api/kimi-update*, /api/tool-usage, /api/model-usage
│   ├── tasks.py        # /api/tasks, /api/tasks/<id>/run (POST), /api/tasks/<id>/log
│   └── system.py       # /api/kimi-web-status, /api/launch-kimi-web (POST), /
├── static/
│   ├── css/style.css   # 样式（从 HTML 分离）
│   └── js/
│       ├── charts.js   # SVG 图表渲染（折线图/热力图/甜甜圈/模型条形图）
│       └── app.js      # 主逻辑（数据加载、路由、事件）
└── templates/
    └── index.html      # 纯 HTML 结构
```

## 安全设计

- 所有状态变更接口（启动 Kimi Web、触发任务、一键更新）均使用 **POST** 方法
- PowerShell 命令中的任务名通过 `ps_escape_single_quote()` 转义，防止注入
- Kimi Web 默认绑定 `127.0.0.1`（非 `0.0.0.0`），仅本机可访问
- `.env` 在 `.gitignore` 中，不会被提交

## 性能优化

- wire.jsonl 解析合并为单次遍历，同时提取 usage 记录、工具调用、模型统计
- 增量解析：跟踪每个文件的 mtime + byte offset，只读新增内容
- 趋势数据、工具用量、模型用量共享 60s TTL 缓存
- 日志写入 `dashboard.log`，不再静默吞掉异常

## 数据说明

- **Skills**：读取 `~/.agents/.skill-lock.json` 与本地 `~/.agents/skills/*/SKILL.md`
- **MCP**：读取 `~/.kimi-code/mcp.json`，并检测 TencentDB Gateway 健康状态
- **Memory**：直接调用本地 TencentDB Gateway（`http://127.0.0.1:8420`）
- **Kimi Usage**：读取本地日志、统计 sessions、检测登录状态
- **Token Trends**：解析 `~/.kimi-code/sessions/*/agents/*/wire.jsonl` 中的 `usage.record` 事件
- **Tool Usage**：解析同一文件中的 `tool.call` 事件
- **Model Usage**：从 `usage.record` 事件的 `model` 字段统计各模型的 token 占比

## 可选：查询 Kimi Code 额度

在 [Kimi Code Console](https://www.kimi.com/code/console?from=kfc_overview_topbar) 创建 API Key，然后写入 `.env`：

```bash
KIMI_API_KEY=your-api-key
```

重启面板即可看到 5 小时窗口与 7 天窗口额度。
