import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "wms2ship.main:app",
        host=os.getenv("WMS_BIND_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8080")),
    )
