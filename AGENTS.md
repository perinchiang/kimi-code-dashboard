# Kimi Code Dashboard — Agent 工作规范

## 工作流
- 每个独立功能或 bug 修复完成后，执行 `git add -A && git commit -m "..." && git push origin master`。
- 提交前运行基础检查：
  - `node --check static/js/app.js`
  - `.venv/Scripts/python -m py_compile app.py`
- 不需要额外确认即可直接 push，除非变更涉及删除数据、修改远程配置或破坏性行为。

## 代码风格
- 保持与周边代码一致：使用现有命名、注释密度和结构。
- JS 使用 `var`（项目未使用 ES6 `let/const`），函数优先使用函数声明。
- HTML/CSS/JS 静态资源修改后，同步更新 `templates/index.html` 中的缓存版本号：
  - `style.css?v=N`
  - `app.js?v=N`
- 只做最小改动，不顺手重构无关代码。

## 项目结构
- Flask 后端入口：`app.py`
- 路由：`routes/`
- 前端：`templates/index.html`、`static/js/app.js`、`static/css/style.css`
- 服务/工具：`services/`

## 提交信息
- 使用中文描述本次改动的用户可见效果，例如：
  - `feat: 第三方模型配置页支持左侧 provider 单击切换`
  - `fix: Provider 卡片按钮区域阻止事件冒泡导致需双击`

## 禁止
- 不要运行 `git reset`、`git rebase`、`git push --force`。
- 不要修改 `.env` 等敏感文件。
- 不要在工作目录外读写文件。
