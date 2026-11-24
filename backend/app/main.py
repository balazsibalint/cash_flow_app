from fastapi import FastAPI

app = FastAPI(title="CashFlow App API")

@app.get("/api/health")
def health_check():
    return {"status": "ok"}