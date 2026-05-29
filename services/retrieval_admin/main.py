from __future__ import annotations

import uvicorn


def main() -> None:
    """Start the Retrieval Admin Service using uvicorn on port 8010."""
    uvicorn.run("app.api:create_app", factory=True, host="0.0.0.0", port=8010)


if __name__ == "__main__":
    main()
