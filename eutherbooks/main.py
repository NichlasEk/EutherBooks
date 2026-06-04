from __future__ import annotations

import uvicorn


def run() -> None:
    uvicorn.run("eutherbooks.api:app", host="0.0.0.0", port=8088, reload=False)


if __name__ == "__main__":
    run()

