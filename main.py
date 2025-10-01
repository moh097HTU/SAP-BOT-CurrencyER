from fastapi import FastAPI
from routes import router as api_router
import glob, shutil

app = FastAPI(title="AIP-BOT API", version="1.0")

@app.on_event("startup")
def _purge_stale_chrome_profiles():
    # remove any old profiles that might be locked
    for p in glob.glob("/tmp/ch-profile-*"):
        try: shutil.rmtree(p, ignore_errors=True)
        except Exception: pass

@app.get("/healthz")
def healthz():
    return {"ok": True}

app.include_router(api_router)
