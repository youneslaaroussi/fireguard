from __future__ import annotations

import uvicorn

from .api import create_app
from .config import get_config


def main() -> None:
    config = get_config()
    uvicorn.run(create_app(config), host=config.host, port=config.port)


if __name__ == "__main__":
    main()
