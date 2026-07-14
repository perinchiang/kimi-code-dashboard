---
name: kimi-hooks
description: 教 AI 使用 Kimi Code CLI 生命周期钩子 Hooks：帮用户创建 Bark 通知、拦截/审计危险命令、桌面通知等。当用户说"加个 hook""bark 通知""危险命令拦截""hook 怎么用""会话结束通知我"时调用。
---

# Kimi Hooks Skill

本 skill 用于指导 AI 帮助用户配置 Kimi Code CLI 的**生命周期钩子（Hooks）**。

## 触发场景

- 用户说"帮我加个 hook / 加个钩子"
- 用户提到"Bark 通知""会话结束通知""任务完成推送"
- 用户提到"危险命令拦截""审计工具调用""Shell 命令二次确认"
- 用户问"hook 是什么""hook 怎么用"
- 用户想在特定事件发生时自动执行某个命令

## 什么是 Hooks

Kimi Code CLI 在 `~/.kimi-code/config.toml` 中支持 `[[hooks]]` 生命周期钩子：

- 在关键事件（如工具调用前、会话结束时）触发
- 执行一段本地 shell 命令
- 典型用途：推送通知、审计日志、拦截危险操作、调用外部自动化脚本

## 配置位置

- 启用中的 hooks：`~/.kimi-code/config.toml` 顶层 `[[hooks]]` 数组
- 禁用中的 hooks：顶层 `[[disabled_hooks]]` 数组
- **Kimi CLI 会严格校验 hook 对象**：只允许 `event`、`command`、`matcher`、`timeout` 四个字段
- **不要**在单个 hook 对象里加 `enabled`、`id` 等自定义字段，否则 `kimi doctor config` 会报 `Unrecognized key`

## 支持的事件

常见事件（具体以 Kimi Code CLI 文档为准）：

| 事件 | 触发时机 |
|---|---|
| `Stop` | 会话或任务结束时（最常用，适合推送完成通知） |
| `PreToolUse` | 工具调用前，可配合 `matcher` 拦截/审计特定工具 |
| `PostToolUse` | 工具调用后，可用于记录结果或发送通知 |
| `UserPromptSubmit` | 用户提交新提示前 |
| `SessionStart` | 新会话开始时 |

## 常用示例

### 1. Bark 推送通知（会话结束）

```toml
[[hooks]]
event = "Stop"
command = "curl -s \"https://api.day.app/YOUR_BARK_KEY/Kimi%20Code/%E4%BC%9A%E8%AF%9D%E7%BB%93%E6%9D%9F\""
timeout = 10
```

### 2. Bark 推送通知（Shell 命令执行后）

```toml
[[hooks]]
event = "PostToolUse"
matcher = "Shell"
command = "curl -s \"https://api.day.app/YOUR_BARK_KEY/Shell%20%E5%B7%B2%E6%89%A7%E8%A1%8C/%E8%AF%B7%E6%9F%A5%E7%9C%8B%E7%BB%93%E6%9E%9C\""
timeout = 10
```

### 3. 审计 Shell 工具调用

```toml
[[hooks]]
event = "PreToolUse"
matcher = "Shell"
command = "echo \"[AUDIT] $(date -Iseconds): Shell tool invoked\" >> ~/.kimi-code/hooks-audit.log"
timeout = 5
```

## 操作方式

### 优先：通过 Dashboard API（推荐）

如果 Kimi Code Dashboard 在运行（默认 `http://127.0.0.1:8080`）：

1. 先 `GET /api/hooks` 查看现有 hooks，避免重复。
2. 根据用户需求构造 body：

```json
{
  "event": "Stop",
  "command": "curl -s \"https://api.day.app/YOUR_BARK_KEY/Kimi%20Code/%E4%BC%9A%E8%AF%9D%E7%BB%93%E6%9D%9F\"",
  "matcher": "",
  "timeout": 10,
  "enabled": true
}
```

3. 调用对应 API：
   - 创建：`POST /api/hooks`
   - 更新：`POST /api/hooks/<id>`
   - 启用/禁用切换：`POST /api/hooks/<id>/toggle`
   - 删除：`POST /api/hooks/<id>/delete`

### 备选：直接修改 config.toml

如果 Dashboard 没运行：

1. 备份 `~/.kimi-code/config.toml`。
2. 用 Python `tomllib` 读取、`tomli_w` 写回，保留 `providers`、`models`、`services`、`mcp` 等其他字段。
3. 将 hook 追加到 `[[hooks]]`（启用）或 `[[disabled_hooks]]`（禁用）。
4. 写回后运行 `kimi doctor config ~/.kimi-code/config.toml` 验证配置有效。

## 注意事项

- `event` 和 `command` 必填，`matcher` 和 `timeout` 可选。
- `timeout` 为正整数，默认 30 秒。
- `command` 中如果包含 URL 或中文，注意 shell 转义和 URL 编码。
- 修改 `config.toml` 前务必先备份。
- 如果用户只想在电脑桌面弹通知，可以提醒他 TUI 本身已支持 `notifications.enabled`（窗口失焦时通知），Bark 更适合推到手机。
