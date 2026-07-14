#!/usr/bin/env python3
"""
Kimi Code Dashboard — Entry Point

A local web dashboard for Kimi Code CLI status:
- Skills overview
- MCP server status
- TencentDB memory status (L0-L3)
- Kimi usage, trends, quota, version check
- Model usage distribution
- Tool/skill call statistics
- Scheduled task monitoring

Run: python app.py
Open: http://127.0.0.1:8080
"""

from flask import Flask

from config import log
from routes import artifacts, image_bed, kimi, mcp, memory, model_config, skills, system, tasks


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # Register blueprints
    app.register_blueprint(skills.bp)
    app.register_blueprint(mcp.bp)
    app.register_blueprint(memory.bp)
    app.register_blueprint(kimi.bp)
    app.register_blueprint(tasks.bp)
    app.register_blueprint(system.bp)
    app.register_blueprint(model_config.bp)
    app.register_blueprint(image_bed.bp)
    app.register_blueprint(artifacts.bp)

    return app


app = create_app()

if __name__ == "__main__":
    log.info("Starting Kimi Code Dashboard on http://127.0.0.1:8080")
    app.run(host="127.0.0.1", port=8080, debug=False)
