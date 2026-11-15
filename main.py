import uvicorn
from app.config import HOST, PORT

if __name__ == "__main__":
    # The progress streams (SSE) never end on their own, so an open browser tab would
    # hold shutdown until systemd killed the process. Five seconds lets them close.
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False, timeout_graceful_shutdown=5)
