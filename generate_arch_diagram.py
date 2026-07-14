#!/usr/bin/env python3
"""Generate a Kimi Code Dashboard architecture flowchart."""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

plt.rcParams["font.family"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

fig, ax = plt.subplots(figsize=(22, 16))
ax.set_xlim(0, 22)
ax.set_ylim(0, 16)
ax.axis("off")
ax.set_facecolor("#f8f9fa")
fig.patch.set_facecolor("#f8f9fa")

# Color palette
colors = {
    "user": "#e3f2fd",
    "user_edge": "#1976d2",
    "app": "#fff3e0",
    "app_edge": "#f57c00",
    "route": "#e8f5e9",
    "route_edge": "#388e3c",
    "service": "#f3e5f5",
    "service_edge": "#7b1fa2",
    "data": "#e0f7fa",
    "data_edge": "#00838f",
    "frontend": "#fffde7",
    "frontend_edge": "#f9a825",
    "external": "#fce4ec",
    "external_edge": "#c2185b",
}


def box(ax, x, y, w, h, text, color, edge, fontsize=9, bold=False, radius=0.02):
    fb = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0.02,rounding_size={radius}",
        facecolor=color,
        edgecolor=edge,
        linewidth=1.5,
    )
    ax.add_patch(fb)
    weight = "bold" if bold else "normal"
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fontsize, color="#212121", wrap=True, weight=weight)
    return fb


def arrow(ax, x1, y1, x2, y2, color="#666666", style="-|>", lw=1.2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color, lw=lw,
                                connectionstyle="arc3,rad=0"))


# Title
ax.text(11, 15.4, "Kimi Code Dashboard 结构流程图", ha="center", va="center",
        fontsize=22, weight="bold", color="#1565c0")
ax.text(11, 14.9, "Flask 后端 + 原生 JS 前端 + 本地数据源", ha="center", va="center",
        fontsize=12, color="#555555")

# Layer 1: User / Browser
box(ax, 9.5, 13.6, 3, 0.7, "用户浏览器\nhttp://127.0.0.1:8080", colors["user"], colors["user_edge"], fontsize=10, bold=True)

# Layer 2: Flask Entry
box(ax, 8.8, 12.0, 4.4, 0.9, "Flask 入口: app.py\n注册 9 个 Blueprint", colors["app"], colors["app_edge"], fontsize=11, bold=True)
arrow(ax, 11, 13.6, 11, 12.9)

# Layer 3: Blueprints (split into two rows for clarity)
routes = [
    (0.4, 10.2, "skills\n/api/skills"),
    (2.6, 10.2, "mcp\n/api/mcp"),
    (4.8, 10.2, "memory\n/api/memory"),
    (7.0, 10.2, "kimi\n/api/kimi*"),
    (9.2, 10.2, "tasks\n/api/tasks"),
    (11.4, 10.2, "system\n/ + /api/*"),
    (13.6, 10.2, "model_config\n/api/model-config"),
    (15.8, 10.2, "image_bed\n/api/image-bed"),
    (18.0, 10.2, "artifacts\n/api/artifacts"),
]
for x, y, text in routes:
    box(ax, x, y, 1.9, 0.9, text, colors["route"], colors["route_edge"], fontsize=8, bold=True)
    arrow(ax, 11, 12.0, x + 0.95, y + 0.9, color="#888888", lw=1)

ax.text(11, 11.35, "Blueprints (路由层)", ha="center", va="center", fontsize=11, weight="bold", color="#2e7d32")

# Layer 4: Services
services = [
    (3.0, 8.2, "services/helpers.py\nJSON / HTTP / TCP / YAML / PS 转义"),
    (8.5, 8.2, "services/wire_parser.py\nTrends / ToolUsage / ModelUsage\n增量解析 + 60s 缓存"),
    (14.0, 8.2, "services/r2_uploader.py\n产物列表 + R2 图床上传"),
]
for x, y, text in services:
    box(ax, x, y, 4.5, 1.0, text, colors["service"], colors["service_edge"], fontsize=9, bold=True)

# Arrows from routes to services
arrow(ax, 1.35, 10.2, 4.5, 9.2, color="#999999")
arrow(ax, 3.55, 10.2, 5.0, 9.2, color="#999999")
arrow(ax, 5.75, 10.2, 5.5, 9.2, color="#999999")
arrow(ax, 7.95, 10.2, 10.0, 9.2, color="#999999")
arrow(ax, 10.15, 10.2, 10.5, 9.2, color="#999999")
arrow(ax, 12.35, 10.2, 11.0, 9.2, color="#999999")
arrow(ax, 14.55, 10.2, 15.5, 9.2, color="#999999")
arrow(ax, 16.75, 10.2, 16.5, 9.2, color="#999999")
arrow(ax, 18.95, 10.2, 17.0, 9.2, color="#999999")

ax.text(11, 9.55, "Services (服务层)", ha="center", va="center", fontsize=11, weight="bold", color="#6a1b9a")

# Layer 5: Data Sources / External Systems
data_sources = [
    (0.3, 5.8, "~/.agents/.skill-lock.json\n~/.agents/skills/*/SKILL.md", colors["data"], colors["data_edge"]),
    (4.3, 5.8, "~/.kimi-code/mcp.json\n.mcp-disabled.json", colors["data"], colors["data_edge"]),
    (7.5, 5.8, "TencentDB Gateway\nhttp://127.0.0.1:8420", colors["external"], colors["external_edge"]),
    (11.0, 5.8, "~/.kimi-code/sessions/*\nwire.jsonl / logs / credentials", colors["data"], colors["data_edge"]),
    (15.0, 5.8, "~/.kimi-code/bin/kimi.exe\nconfig.toml / tasks.json", colors["data"], colors["data_edge"]),
    (18.5, 5.8, "~/.kimi-code/files/\n~/.kimi-code/sessions/*/blobs/", colors["data"], colors["data_edge"]),
]
for x, y, text, c, e in data_sources:
    box(ax, x, y, 3.6, 1.1, text, c, e, fontsize=8, bold=True)

# Arrows services -> data
arrow(ax, 4.5, 8.2, 2.1, 6.9, color="#999999")
arrow(ax, 5.25, 8.2, 6.1, 6.9, color="#999999")
arrow(ax, 9.5, 8.2, 9.3, 6.9, color="#999999")
arrow(ax, 10.75, 8.2, 13.0, 6.9, color="#999999")
arrow(ax, 14.75, 8.2, 16.8, 6.9, color="#999999")
arrow(ax, 16.5, 8.2, 20.3, 6.9, color="#999999")

ax.text(11, 7.15, "本地数据源 & 外部系统", ha="center", va="center", fontsize=11, weight="bold", color="#006064")

# Layer 6: Frontend (right side)
box(ax, 17.0, 12.0, 4.5, 1.6,
    "Frontend\ntemplates/index.html\nstatic/js/app.js + charts.js\nstatic/css/style.css",
    colors["frontend"], colors["frontend_edge"], fontsize=9, bold=True)
arrow(ax, 17.0, 13.0, 12.6, 12.45, color="#888888", style="<|-")

# Windows Task Scheduler external
box(ax, 8.5, 4.0, 5.0, 0.9, "Windows Task Scheduler\n定时任务注册 / 触发 / 状态查询", colors["external"], colors["external_edge"], fontsize=9, bold=True)
arrow(ax, 10.15, 5.8, 10.25, 4.9, color="#999999")
arrow(ax, 11.5, 5.8, 11.5, 4.9, color="#999999")

# Legend
legend_items = [
    ("用户入口", colors["user"], colors["user_edge"]),
    ("Flask 入口", colors["app"], colors["app_edge"]),
    ("Blueprint 路由", colors["route"], colors["route_edge"]),
    ("Service 服务", colors["service"], colors["service_edge"]),
    ("本地数据", colors["data"], colors["data_edge"]),
    ("外部系统 / 前端", colors["external"], colors["external_edge"]),
]
for i, (label, c, e) in enumerate(legend_items):
    lx = 0.5 + i * 3.5
    ly = 0.5
    box(ax, lx, ly, 1.2, 0.4, "", c, e, radius=0.05)
    ax.text(lx + 1.4, ly + 0.2, label, ha="left", va="center", fontsize=9, color="#333333")

# Footer
ax.text(11, 0.15, "数据来源: ~/.kimi-code/dashboard/ | 生成时间: 2026-07-14",
        ha="center", va="center", fontsize=8, color="#888888")

plt.tight_layout()
output_path = "C:/Users/Administrator/.kimi-code/files/dashboard-arch-flowchart.png"
plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="#f8f9fa", edgecolor="none")
print(f"Saved to {output_path}")
