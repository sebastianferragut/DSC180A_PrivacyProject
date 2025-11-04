# api.py
from fastapi import FastAPI
from pydantic import BaseModel, HttpUrl
from scanner import scan_privacy_click_depth, write_result_json

app = FastAPI(title="Privacy Click-Depth API")

class ScanIn(BaseModel):
    start_url: HttpUrl
    max_depth: int = 6

@app.post("/scan")
def scan(in_: ScanIn):
    result = scan_privacy_click_depth(str(in_.start_url), max_depth=in_.max_depth)
    path = write_result_json(result)  # no DB; we persist to ./results/
    return {**result, "saved_to": path}