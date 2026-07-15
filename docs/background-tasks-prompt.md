# Prompt：在 Kimi Code Dashboard 中集成后台任务中心

## 背景
当前 Kimi Code Dashboard 已有一个"定时任务"页面（基于 Windows Task Scheduler 的 Cron 式任务），通过 `/api/tasks` 管理。  
Kimi Code CLI 本身还有一个运行时后台任务机制（对应 TUI 中的 `/tasks` 命令），用于展示当前会话中 Agent 发起的长时间运行任务（主要是 Bash 命令）。这些任务以 JSON 元数据 + `output.log` 的形式存储在 session 目录下。

目标是在 dashboard 中集成这个后台任务列表，**不新增首页 mini card**，而是把现有"定时任务"卡片升级为"任务中心"，页面内用 tab 区分"定时任务"和"后台任务"。

## 现有数据结构

### 后台任务存储位置
```
~/.kimi-code/sessions/<workdir>/<session_id>/agents/<agent_id>/tasks/<task_id>.json
~/.kimi-code/sessions/<workdir>/<session_id>/agents/<agent_id>/tasks/<task_id>/output.log
```

### task JSON 示例
```json
{
  "taskId": "bash-uwtmuzh7",
  "description": "Bash: env | grep -iE 'KIMI|EXPERIMENT' || echo \"no kimi env vars\" …",
  "status": "completed",
  "detached": false,
  "startedAt": 1784045842080,
  "endedAt": 1784045842260,
  "timeoutMs": 60000,
  "kind": "process",
  "command": "env | grep -iE 'KIMI|EXPERIMENT' || echo \"no kimi env vars\" ; echo \"---\" ; ps aux | grep -i kimi | grep -v grep",
  "pid": 36016,
  "exitCode": 0
}
```

### 现有 API
- `GET /api/tasks`：返回定时任务列表（保持不动）

## 需求

### 1. 后端 API
新增两个只读接口：

#### `GET /api/background-tasks`
扫描 `~/.kimi-code/sessions/*/agents/*/tasks/*.json`，返回后台任务列表。

返回格式：
```json
{
  "running": 1,
  "completed": 5,
  "failed": 1,
  "total": 7,
  "tasks": [
    {
      "taskId": "bash-uwtmuzh7",
      "description": "...",
      "status": "completed",
      "command": "...",
      "pid": 36016,
      "exitCode": 0,
      "startedAt": 1784045842080,
      "endedAt": 1784045842260,
      "sessionId": "session_5dce4806-f2cb-4cd5-9fdf-8e35db99b45f",
      "sessionShort": "5dce4806",
      "workDirName": "wd_dashboard_b66728cbb844",
      "outputPath": "C:/Users/.../tasks/bash-uwtmuzh7/output.log"
    }
  ]
}
```

排序规则：
1. 运行中的任务置顶
2. 其余按 `startedAt` 倒序（新的在前）

性能注意：
- session 目录可能较多，扫描时不要阻塞请求太久
- 可以只扫描一层深度，不需要递归进 agent 子目录之外的地方
- 日志文件不要在这里读取，只返回路径

#### `GET /api/background-tasks/<task_id>/log`
读取对应任务的 `output.log`，返回最后 200 行。

返回格式：
```json
{
  "taskId": "bash-uwtmuzh7",
  "log": "PATH=...\n---\n..."
}
```

注意处理文件不存在的情况。

### 2. 前端首页卡片增强
现有首页 mini card："定时任务"（`#tasksMiniCard`）。

保持卡片本身不变，只增强 `tasksMiniStatus` 区域：

- 无后台任务时：保持当前样式，可显示"暂无任务"或什么都不显示
- 有运行中后台任务时：显示一个蓝色脉冲 pill，例如 `▶ 运行中 2`
- 只有已完成/失败任务、没有运行中时：显示一个灰色 pill，例如 `● 后台 3`

点击卡片仍跳转到 `#/tasks`。

### 3. 任务详情页改造
`#/tasks` 页面现有"定时任务"列表，需要增加顶部 tab：

```
[ 定时任务 ]  [ 后台任务 ]
```

默认选中"定时任务"，保持现有功能和样式不变。

切换到"后台任务" tab 时，显示后台任务列表。

#### 后台任务列表设计
每条任务显示为一个卡片：

```
┌────────────────────────────────────────────────────────────┐
│ ▶ 运行中    Bash: env | grep -iE 'KIMI|EXPERIMENT'...       │
│             会话：wd_dashboard_.../5dce4806  PID: 36016      │
│             开始：14:32  已运行：2m13s                       │
│             [展开命令]  [查看日志]                           │
└────────────────────────────────────────────────────────────┘
```

状态样式：
- 运行中：蓝色左侧边框 + 脉冲圆点
- 已完成：绿色左侧边框 + ✓
- 已失败：红色左侧边框 + ✗
- 其他状态：灰色

命令默认折叠，点击"展开命令"显示完整 `command`。

日志查看：点击"查看日志"弹出 drawer/弹窗，显示 `output.log` 最后 200 行。

#### 筛选
后台任务 tab 顶部提供状态筛选：`全部` / `运行中` / `已完成` / `已失败`。

### 4. 样式要求
- tab 样式与现有 dashboard 风格一致（暗色/亮色主题兼容）
- 后台任务卡片风格与现有 skills/mcp 卡片类似
- 日志弹窗使用等宽字体，暗色背景（类似终端）
- 新增样式写入 `static/css/style.css`
- 更新 `templates/index.html` 中的缓存版本号：`style.css?v=` 和 `app.js?v=`

### 5. 代码约束
- 后端使用 Flask Blueprint，优先在 `routes/tasks.py` 中新增接口
- 前端使用项目现有风格：用 `var` 声明变量，函数优先使用函数声明
- 不要引入新的第三方库
- 只读操作，不要修改 session 目录下的任何文件
- 路径解析要安全，防止路径穿越

### 6. 验证
完成后运行：
```bash
node --check static/js/app.js
.venv/Scripts/python -m py_compile app.py
```

并手动验证：
1. 无后台任务时首页不显示额外噪音
2. 有后台任务运行时首页显示"运行中 N"
3. `#/tasks` 页面 tab 切换正常
4. 后台任务列表正确显示状态、PID、退出码
5. 日志弹窗能正确显示 output.log 内容

## 交付物
- `routes/tasks.py` 新增后台任务相关接口
- `static/js/app.js` 新增后台任务数据加载、tab 切换、列表渲染、日志弹窗逻辑
- `templates/index.html` 新增后台任务 tab DOM 和缓存版本号更新
- `static/css/style.css` 新增后台任务相关样式
