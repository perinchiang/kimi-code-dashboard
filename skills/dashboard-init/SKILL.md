---
name: dashboard-init
description: 初始化并教学 Kimi Code Dashboard：为 Skills / MCP Servers 生成中文描述、教 AI 创建定时任务与生命周期 Hooks，说明 Dashboard 的启动/更新/重启等日常操作，并指导安装 image-bed MCP 与 kimi-code-memory-mcp。当用户安装新 skill/MCP、发现卡片没有中文说明、说"补齐描述""初始化 dashboard""给 skill/mcp 加描述""帮我加个定时任务""教 AI 生成定时任务""帮我加个 hook""怎么启动 dashboard""怎么更新 dashboard""装图床 MCP""上传图片到图床""image bed""记忆 MCP""memory mcp"时调用。
---

# Dashboard 初始化与使用教学 Skill

本 skill 用于让 Kimi Code Dashboard 的 Skills / MCP 卡片对中文用户更友好，并指导 AI 如何回答 Dashboard 的日常使用问题。

## 触发场景

- 用户安装了一个新的 skill 或 MCP server，Dashboard 里只显示名字没有说明
- 用户说"初始化 dashboard""补齐描述""给 skill 加中文描述""mcp 没说明"
- 用户想把现有所有 skill/MCP 批量加上中文简介

## 工作流程

1. **扫描 Skill**
   - 读取 `~/.agents/.skill-lock.json` 获取已安装 skill 列表
   - 对每个 skill，读取 `~/.agents/skills/<id>/SKILL.md`
   - 检查 frontmatter 中 `description` 字段：
     - 如果为空、只有触发词、或明显是英文且用户要中文，则生成一段 30~60 字的中文描述
     - 如果已有合适中文描述，跳过
   - 把新描述写回 frontmatter（注意 YAML 中如果含冒号需加引号）
   - 同步更新 `.skill-lock.json` 中对应 skill 的 `description` 字段

2. **扫描 MCP Server**
   - 读取 `~/.kimi-code/mcp.json`
   - 对每个 `mcpServers` 条目：
     - 如果已有 `description` 字段且不为空，跳过
     - 否则根据其 `name`、`command`、`args` 推断用途，生成 20~40 字中文描述
     - 写入 `mcp.json` 的 `description` 字段
   - 如果 server 在 `~/.kimi-code/.mcp-disabled.json` 中，也一并处理

3. **生成描述的原则**
   - 用中文，简短，说清用途
   - 包含典型触发场景（如"用于...""提供...能力"）
   - 不要照搬原文，用自己的话概括
   - 如果原描述已很好（即使是英文），可保留或只做轻微中文化

4. **完成后**
   - 列出所有被更新的 skill 和 MCP
   - 提示用户刷新 Dashboard 页面查看最新效果
   - 如果改了 `app.js` 里的 `MCP_DESC` 字典，提醒需要重启 Dashboard

## 3. 推荐 MCP：image-bed（图床上传）

当用户说"装图床 MCP""上传图片到图床""image bed""怎么用图床""外网引用图片"时，引导安装并配置 image-bed MCP。

### 3.1 用途

AI 在本地 Kimi Code 里生成的截图/产物默认存在 `~/.kimi-code/files/` 或会话 `blobs/`，外网无法直接访问。安装 image-bed MCP 后，AI 可以把这些图片上传到 Cloudflare R2（或兼容 S3 的图床），拿到公开外链，再在外网会话中引用。

### 3.2 前提

1. Dashboard 已启动（默认 http://127.0.0.1:18080）。
2. Dashboard 设置页已配置好 `[image_bed]` 图床凭证并测试连接通过。
3. 建议开启 Dashboard 开机自启，否则 AI 调用时会提示"无法连接 Dashboard"。

### 3.3 安装

```bash
pip install git+https://github.com/perinchiang/image-bed-mcp.git
```

然后把以下内容加进 `~/.kimi-code/mcp.json`：

```json
{
  "mcpServers": {
    "image-bed": {
      "command": "image-bed-mcp",
      "description": "上传 Kimi Code 产物到 R2 图床，供外网引用图片"
    }
  }
}
```

保存后重启 Kimi Code CLI（或重新加载 MCP），让新 server 生效。

### 3.4 Tools

- `list_kimi_artifacts(file_type="all", keyword="")`：列出本地产物及图床上传状态，支持搜索文件名。
- `upload_artifact_to_image_bed(file_id)`：上传指定产物到图床，返回外链 URL。已上传过的会命中缓存。
- `get_artifact_upload_status(file_id)`：查询单个产物的上传状态。

### 3.5 常见问题

- **无法连接 Dashboard**：Dashboard 没启动，或 `KIMI_DASHBOARD_BASE` 环境变量指向错误地址。
- **上传失败「图床未配置」**：去 Dashboard 设置页填写 R2 / S3 凭证并测试连接。
- **找不到产物**：确认 `file_id` 来自 `list_kimi_artifacts` 的返回列表。

## 4. 初始化 / 创建定时任务

当用户说"帮我加个定时任务""每天几点跑什么""每周同步一次""教 AI 生成定时任务"时，按下面流程处理。

### 4.1 分析用户需求

- 明确任务目标：要做什么、数据来源、输出到哪里
- 选择触发频率：
  - 每天固定时间 → `daily`
  - 每周某些天 → `weekly`（`daysOfWeek` 用 0=周日 到 6=周六）
  - 每月某一天 → `monthly`
  - 只跑一次 → `once`
- 确认脚本是否已经存在；如果不存在，需要新建 Python 脚本并放到 `scriptsDir`

### 4.2 任务配置格式

配置文件：`~/.kimi-code/dashboard/tasks.json`

一个任务条目示例：

```json
{
  "id": "wiki-sync-daily",
  "name": "WikiSync 每日同步",
  "description": "GitHub/Bilibili/Spotify/Steam/Xteink/Garmin 数据同步到 Wiki",
  "script": "wiki-sync-daily.py",
  "schedule": "每日 08:00",
  "trigger": {
    "type": "daily",
    "time": "08:00"
  },
  "enabled": true,
  "logFile": "wiki-sync-daily.log",
  "sources": ["GitHub", "Bilibili", "Spotify", "Steam", "Xteink", "Garmin"],
  "taskName": "WikiSync-Daily"
}
```

字段说明：

| 字段 | 说明 |
|------|------|
| `id` | 小写、唯一、用 kebab-case，例如 `bark-notify-weekly` |
| `name` | 显示名称，简短中文 |
| `description` | 30~60 字中文说明 |
| `script` | `scriptsDir` 下的 Python 脚本相对路径 |
| `schedule` | 人类可读字符串，例如"每日 08:00""每周日 21:30" |
| `trigger` | 机器解析的触发器对象，见下表 |
| `enabled` | 是否启用 |
| `logFile` | 脚本输出的日志文件名（相对 `scriptsDir`），可选 |
| `sources` | 数据来源标签，用于看板展示，可选 |
| `taskName` | Windows 任务计划程序里的名字，建议大驼峰，例如 `WikiSync-Daily` |

### 4.3 trigger 类型

```json
// 每日
{ "type": "daily", "time": "08:00" }

// 每周日、三 21:30
{ "type": "weekly", "time": "21:30", "daysOfWeek": [0, 3] }

// 每月 1 日 09:00
{ "type": "monthly", "time": "09:00", "day": 1 }

// 只跑一次
{ "type": "once", "datetime": "2026-07-20T09:00:00" }
```

### 4.4 脚本约定

- 脚本放在 `tasks.json` 中 `scriptsDir` 指定的目录下
- 脚本自己负责日志写入到 `logFile` 指定的文件
- 日志里如果包含 `[SourceName] OK` 或 `[SourceName] FAIL`，看板会自动显示来源状态
- 脚本开头建议加上 shebang 和编码声明：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging, sys, datetime

LOG_FILE = "wiki-sync-daily.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

def main():
    logging.info("[GitHub] OK")
    # ...

if __name__ == "__main__":
    main()
```

### 4.5 创建方式

如果 Dashboard 后端已经支持 `POST /api/tasks/create`，优先调用 API：

```python
import requests, json

body = {
    "id": "bark-notify-weekly",
    "name": "Bark 周报提醒",
    "description": "每周日晚上推送一次本周同步状态",
    "script": "sync-notify-weekly.py",
    "trigger": {"type": "weekly", "time": "21:30", "daysOfWeek": [0]},
    "enabled": True,
    "logFile": "sync-notify-weekly.log",
    "sources": ["Bark"],
    "taskName": "BarkNotify-Weekly",
}

r = requests.post("http://127.0.0.1:18080/api/tasks/create", json=body)
print(r.json())
```

如果 API 不存在或调用失败，则直接修改 `tasks.json`：

1. 读取现有配置
2. 检查 `id` 是否已存在，避免重复
3. 追加新任务到 `tasks` 数组
4. 确保 `schedule` 字段与 `trigger` 一致
5. 保存文件
6. 如果脚本文件不存在，先创建脚本

### 4.6 注册到 Windows 任务计划程序

- 只有以管理员身份运行的 Dashboard 才能调用 `Register-ScheduledTask`
- 如果保存成功但任务显示"未注册"，提示用户：
  > 配置已保存。因为注册 Windows 计划任务需要管理员权限，请右键以管理员身份重启 Dashboard，任务会自动注册。
- 非 Windows 系统（如 macOS/Linux）目前 Dashboard 不会调用系统调度器，只把配置保存在 `tasks.json` 中

### 4.7 命名建议

- `id`：kebab-case，例如 `garmin-sync-daily`
- `taskName`：PascalCase，例如 `GarminSync-Daily`
- `script`：与 `id` 对应，例如 `garmin-sync-daily.py`
- `logFile`：与 `id` 对应，例如 `garmin-sync-daily.log`

## 5. 创建生命周期 Hooks

当用户说"帮我加个 hook""加个 bark 通知""危险命令拦截""hook 怎么用""会话结束通知我"时，按下面流程处理。

### 5.1 基本概念

- Hooks 配置在 `~/.kimi-code/config.toml` 中。
- 启用中的 hook 放在 `[[hooks]]` 数组；禁用中的放在 `[[disabled_hooks]]` 数组。
- Kimi CLI 严格校验 hook 对象，**只允许** `event`、`command`、`matcher`、`timeout` 四个字段。
- 不要往 hook 对象里塞 `enabled`、`id` 等字段，否则 `kimi doctor config` 会报错。

### 5.2 常用事件

| 事件 | 说明 |
|---|---|
| `Stop` | 会话/任务结束时，最常用 |
| `PreToolUse` | 工具调用前，可配合 `matcher` 做审计/拦截 |
| `PostToolUse` | 工具调用后 |
| `UserPromptSubmit` | 用户提交提示前 |
| `SessionStart` | 会话开始时 |

### 5.3 创建方式

如果 Dashboard 在运行，**优先调用 Dashboard API**：

```python
import requests

body = {
    "event": "Stop",
    "command": "curl -s \"https://api.day.app/YOUR_BARK_KEY/Kimi%20Code/%E4%BC%9A%E8%AF%9D%E7%BB%93%E6%9D%9F\"",
    "matcher": "",
    "timeout": 10,
    "enabled": True,
}

r = requests.post("http://127.0.0.1:18080/api/hooks", json=body)
print(r.json())
```

API 端点：

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/api/hooks` | 列出所有 hooks |
| POST | `/api/hooks` | 新建 hook |
| POST | `/api/hooks/<id>` | 更新 hook |
| POST | `/api/hooks/<id>/toggle` | 启用/禁用切换 |
| POST | `/api/hooks/<id>/delete` | 删除 hook |

如果 Dashboard 没运行，则直接修改 `~/.kimi-code/config.toml`：

1. 备份原文件。
2. 用 `tomllib` 读取、`tomli_w` 写回，保留其他配置。
3. 追加到 `[[hooks]]` 或 `[[disabled_hooks]]`。
4. 运行 `kimi doctor config ~/.kimi-code/config.toml` 验证。

### 5.4 命名与示例

- Bark 通知：用 `Stop` 事件，命令里填 `curl -s "https://api.day.app/<key>/<title>/<body>"`。
- 危险命令审计：用 `PreToolUse` + `matcher = "Shell"`，命令里写日志。
- 详细示例和注意事项见独立的 `kimi-hooks` skill。

## 6. Dashboard 启动、更新与重启

当用户问"怎么启动 Dashboard""怎么更新 Dashboard""Dashboard 为什么没生效"时，按下面说明回答。

### 6.1 启动菜单

在终端输入 `kimi dashboard` 会弹出数字菜单（Windows 依赖 PowerShell Profile 包装；macOS/Linux 可用别名）：

```text
===== Kimi Code 启动菜单 =====
1. 启动 Dashboard
2. 启动本地 Kimi Code Web
3. 启动外网访问 Kimi Code Web
4. 停止 Kimi Code Web（kimi web kill）
5. 更新 Kimi Code
6. 更新 Dashboard
7. 完全卸载 Dashboard
8. 重启 Dashboard
0. 退出
==============================
```

- **选项 1**：后台启动 Dashboard，默认打开 `http://127.0.0.1:18080`；实际端口读取 `dashboard-config.json`。
- **选项 6**：在 Dashboard 目录执行 `git pull origin master`，有更新时自动重启 Dashboard 生效。
- **选项 8**：结束占用当前或上一个 Dashboard 配置端口的旧进程并重新启动。

### 6.2 更新后何时重启

- 修改了 `static/js/app.js`、`static/css/style.css`、`templates/index.html` 等前端文件：刷新浏览器即可（建议 `Ctrl + F5` 硬刷新，模板里的 `?v=N` 会强制客户端加载新版本）。
- 修改了 `routes/`、`config.py`、`services/` 等后端文件，或在设置页修改了 Dashboard 端口：必须重启 Dashboard 进程才能生效。选项 1 只会检测当前配置端口；需要重启时使用选项 8（`kimi dashboard 8`）。

### 6.3 快速重启方法

如果用户发现更新没生效，可以：

1. 执行 `kimi dashboard 8` 一键重启；它会处理当前及上一个配置端口。手动排查时以 `dashboard-config.json` 中的端口为准。
2. 再执行 `kimi dashboard 1` 重新启动。

## 7. 可选 MCP 搭档推荐

Dashboard 安装并完成初始化后，可主动向用户介绍两个可选 MCP。它们用于补足 Kimi Code CLI 在特定场景下的小缺口，但都不是必装的。**只推荐一次，不强制安装，不默认写入配置**。

### 7.1 image-bed MCP（图床上传）

适用场景：用户需要把 Kimi Code 生成的截图、产物图片上传到 R2 / S3 / MinIO / OSS / COS 等兼容对象存储，拿到外网可访问的公开链接。

安装与配置细节见上文第 3 节“推荐 MCP：image-bed（图床上传）”。

### 7.2 kimi-code-memory-mcp（长期向量记忆）

适用场景：用户希望 Kimi Code 拥有长期向量记忆，并在 Dashboard 的 Memory Status 模块中以甜甜圈图查看 L0–L3 四级记忆分布。

仓库地址：https://github.com/perinchiang/kimi-code-memory-mcp

安装后，Dashboard 会通过本地 TencentDB Gateway（默认 `http://127.0.0.1:8420`）读取记忆统计。

### 7.3 推荐话术

安装或初始化完成后，可自然地问一句：

> Dashboard 装好了。还有两个可选搭档 MCP，看你是否需要：
> - **image-bed MCP**：用于把产物图片上传到图床，外网引用
> - **kimi-code-memory-mcp**：用于长期向量记忆，配合 Dashboard 的 Memory Status 使用
>
> 都不是必须的，需要的话告诉我，我帮你配置。

## 注意事项

- 修改前先看一眼现有内容，避免覆盖用户手写的优质描述
- YAML frontmatter 编辑时要保留 `---` 分隔符和原有字段
- `mcp.json` 写入时要保持 JSON 格式，`description` 放在 `command`/`args`/`cwd`/`env` 附近即可
- 本 skill 不直接操作 Dashboard 进程，只修改数据文件；定时任务和 Hooks 除外，可调用 `/api/tasks/create`、`/api/hooks` 等 API
- 涉及 Dashboard 进程的操作（启动、更新后重启）通过 `kimi dashboard` 菜单完成，不需要 AI 手动起 Flask 进程
