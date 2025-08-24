from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html
import time
import os
from dotenv import load_dotenv

load_dotenv()

from logging_config import setup_logging, get_logger, log_event
logger = get_logger("main")

from ingest import router as ingest_router
from extract import router as extract_router
from ask import router as ask_router
from stream import router as stream_router
from audit import router as audit_router
from webhook import router as webhook_router
from admin import router as admin_router
from admin import REQUEST_TIME, INGEST_COUNTER, EXTRACT_COUNTER, ASK_COUNTER, AUDIT_COUNTER

app = FastAPI(
    title="Contract Intelligence API",
    description="API for contract ingestion, field extraction, question answering (RAG), and risk auditing",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_timing_middleware(request: Request, call_next):
    start_time = time.time()
    
    path = request.url.path
    if path.startswith("/ingest"):
        endpoint = "ingest"
    elif path.startswith("/extract"):
        endpoint = "extract"
    elif path.startswith("/ask"):
        endpoint = "ask"
    elif path.startswith("/audit"):
        endpoint = "audit"
    else:
        endpoint = "other"
    
    log_event("request_started", {
        "endpoint": endpoint,
        "method": request.method,
        "path": path,
        "client_ip": request.client.host if request.client else "unknown"
    }, "middleware")
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    REQUEST_TIME.labels(endpoint=endpoint).observe(process_time)
    
    status_code = response.status_code
    status = "success" if 200 <= status_code < 300 else "failure"
    
    log_event("request_completed", {
        "endpoint": endpoint,
        "method": request.method,
        "status_code": status_code,
        "status": status,
        "process_time_ms": round(process_time * 1000, 2)
    }, "middleware")
    
    if endpoint == "ingest":
        INGEST_COUNTER.labels(status=status).inc()
    elif endpoint == "extract":
        EXTRACT_COUNTER.labels(status=status).inc()
    elif endpoint == "ask":
        ASK_COUNTER.labels(status=status).inc()
    elif endpoint == "audit":
        AUDIT_COUNTER.labels(status=status).inc()
    
    response.headers["X-Process-Time"] = str(process_time)
    return response

app.include_router(ingest_router)
app.include_router(extract_router)
app.include_router(ask_router)
app.include_router(stream_router)
app.include_router(audit_router)
app.include_router(webhook_router)
app.include_router(admin_router)

try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except:
    pass

@app.get("/")
async def root():
    return {
        "name": "Contract Intelligence API",
        "version": "1.0.0",
        "description": "API for contract ingestion, field extraction, question answering (RAG), and risk auditing",
        "docs_url": "/docs",
        "healthz_url": "/healthz",
        "metrics_url": "/metrics"
    }

@app.on_event("startup")
async def startup_event():
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    pdf_dir = os.path.join(data_dir, "pdfs")
    extracted_dir = os.path.join(data_dir, "extracted")
    
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(extracted_dir, exist_ok=True)
    
    log_event("application_started", {
        "data_dir": data_dir,
        "pdf_dir": pdf_dir,
        "extracted_dir": extracted_dir,
        "gemini_api_configured": bool(os.getenv("GEMINI_API_KEY"))
    }, "startup")
    
    print(f"🚀 Contract Intelligence API started")
    print(f"📁 Data directory: {data_dir}")
    print(f"📄 PDF storage: {pdf_dir}")
    print(f"📊 Extracted data: {extracted_dir}")
    
    if not os.getenv("GEMINI_API_KEY"):
        logger.warning("GEMINI_API_KEY environment variable not set - RAG functionality will not work")
        print("⚠️  WARNING: GEMINI_API_KEY environment variable not set")
        print("   RAG question answering will not work without an API key")
    
    print(f"📚 API documentation available at: http://localhost:8000/docs")

@app.on_event("shutdown")
async def shutdown_event():
    """Log application shutdown."""
    log_event("application_shutdown", {}, "shutdown")
    logger.info("Contract Intelligence API shutting down")
