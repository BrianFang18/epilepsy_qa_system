from __future__ import annotations

import uvicorn

from app.config import get_settings

# 启动后端服务
if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "dev",
    )
