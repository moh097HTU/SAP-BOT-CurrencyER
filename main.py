from fastapi import FastAPI
from routes import router as api_router

app = FastAPI(title="AIP-BOT API", version="1.0")
app.include_router(api_router)
