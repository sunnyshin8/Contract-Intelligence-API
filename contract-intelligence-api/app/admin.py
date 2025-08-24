from fastapi import APIRouter, Request
from typing import Dict, Any
from datetime import datetime
import platform
import os
import psutil
import prometheus_client
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response

from models import HealthResponse
from logging_config import get_logger, log_event

logger = get_logger("admin")

router = APIRouter(
    tags=["admin"],
)

INGEST_COUNTER = Counter(
    "contract_ingest_total",
    "Total number of contracts ingested",
    ["status"]
)

EXTRACT_COUNTER = Counter(
    "contract_extract_total",
    "Total number of contract field extractions",
    ["status"]
)

ASK_COUNTER = Counter(
    "contract_ask_total",
    "Total number of questions asked",
    ["status"]
)

AUDIT_COUNTER = Counter(
    "contract_audit_total",
    "Total number of contract audits",
    ["status"]
)

REQUEST_TIME = Histogram(
    "request_processing_seconds",
    "Time spent processing requests",
    ["endpoint"]
)


@router.get("/healthz", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint for the API.
    
    Returns basic health information about the service.
    """
    log_event("health_check_requested", {}, "admin")
    
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    data_dir_accessible = os.path.isdir(data_dir) and os.access(data_dir, os.R_OK | os.W_OK)
  
    system_info = {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "memory_usage_percent": psutil.virtual_memory().percent,
        "cpu_usage_percent": psutil.cpu_percent(interval=0.1),
        "disk_usage_percent": psutil.disk_usage("/").percent
    }

    system_status = "healthy" if system_info["memory_usage_percent"] < 80 and system_info["cpu_usage_percent"] < 80 and system_info["disk_usage_percent"] < 80 else "unhealthy"

    disk_status = "healthy" if data_dir_accessible else "unhealthy"
    
    return HealthResponse(
        system_status=system_status,
        system_info=system_info,
        disk_status=disk_status,
        version="1.0.0",
        timestamp=datetime.now()
    )


@router.get("/metrics")
async def metrics():
    """
    Prometheus metrics endpoint.
    
    Returns metrics in Prometheus format.
    """
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


@router.get("/stats")
async def stats():
    """
    Human-readable statistics endpoint.
    
    Returns current statistics in a JSON format.
    """
    pdf_dir = os.path.join(os.path.dirname(__file__), "data", "pdfs")
    extracted_dir = os.path.join(os.path.dirname(__file__), "data", "extracted")
    
    pdf_count = len([f for f in os.listdir(pdf_dir) if f.endswith(".pdf")]) if os.path.exists(pdf_dir) else 0
    extracted_count = len([f for f in os.listdir(extracted_dir) if f.endswith(".json")]) if os.path.exists(extracted_dir) else 0
    
    ingest_success = INGEST_COUNTER.labels(status="success")._value.get()
    ingest_failure = INGEST_COUNTER.labels(status="failure")._value.get()
    extract_success = EXTRACT_COUNTER.labels(status="success")._value.get()
    extract_failure = EXTRACT_COUNTER.labels(status="failure")._value.get()
    ask_success = ASK_COUNTER.labels(status="success")._value.get()
    ask_failure = ASK_COUNTER.labels(status="failure")._value.get()
    audit_success = AUDIT_COUNTER.labels(status="success")._value.get()
    audit_failure = AUDIT_COUNTER.labels(status="failure")._value.get()
    
    return {
        "documents": {
            "total_pdfs_stored": pdf_count,
            "total_documents_processed": extracted_count
        },
        "api_calls": {
            "ingest": {
                "success": ingest_success,
                "failure": ingest_failure,
                "total": ingest_success + ingest_failure
            },
            "extract": {
                "success": extract_success,
                "failure": extract_failure,
                "total": extract_success + extract_failure
            },
            "ask": {
                "success": ask_success,
                "failure": ask_failure,
                "total": ask_success + ask_failure
            },
            "audit": {
                "success": audit_success,
                "failure": audit_failure,
                "total": audit_success + audit_failure
            }
        },
        "system": {
            "memory_usage_percent": psutil.virtual_memory().percent,
            "cpu_usage_percent": psutil.cpu_percent(interval=0.1),
            "disk_usage_percent": psutil.disk_usage("/").percent
        }
    }
