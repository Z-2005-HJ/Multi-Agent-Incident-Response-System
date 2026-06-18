from __future__ import annotations

import logging

import uvicorn


logging.basicConfig(
    filename="server.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


if __name__ == "__main__":
    logging.info("Starting uvicorn server on 127.0.0.1:8000")
    try:
        uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info", log_config=None)
    except Exception:
        logging.exception("Server failed to start")
        raise
