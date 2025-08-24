from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from typing import List, Dict, Any
from datetime import datetime
import os

from models import DocumentResponse, BatchIngestResponse
from webhook import trigger_webhook_event
from logging_config import get_logger, log_event
from utils import (
    generate_document_id,
    save_pdf,
    extract_text_from_pdf,
    save_extracted_text
)

logger = get_logger("ingest")

router = APIRouter(
    prefix="/ingest",
    tags=["ingest"],
    responses={404: {"description": "Not found"}},
)

@router.post("/", response_model=BatchIngestResponse)
async def ingest_documents(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    """
    Upload and ingest 1..n contract PDF documents.
    
    - Extracts text from PDF
    - Stores document text and metadata
    - Returns document IDs for future reference
    """
    log_event("ingest_started", {
        "file_count": len(files) if files else 0
    }, "ingest")
    
    if not files:
        logger.warning("Ingest attempt with no files provided")
        raise HTTPException(status_code=400, detail="No files provided")
    
    for file in files:
        if not file.filename.lower().endswith('.pdf'):
            logger.error(f"Invalid file type attempted: {file.filename}")
            raise HTTPException(
                status_code=400, 
                detail=f"File {file.filename} is not a PDF"
            )
    
    document_responses = []
    
    for file in files:
        try:
            document_id = generate_document_id()
            
            log_event("document_processing_started", {
                "document_id": document_id,
                "filename_length": len(file.filename) if file.filename else 0
            }, "ingest")
            
            content = await file.read()
            
            pdf_path = save_pdf(content, file.filename, document_id)
            
            text_by_page = extract_text_from_pdf(pdf_path)
            
            metadata = {
                "filename": file.filename,
                "upload_timestamp": datetime.now().isoformat(),
                "size_bytes": len(content),
                "pages": len(text_by_page)
            }
            
            save_extracted_text(document_id, text_by_page, metadata)
            
            log_event("document_ingested", {
                "document_id": document_id,
                "size_bytes": len(content),
                "pages": len(text_by_page)
            }, "ingest")
            
            document_responses.append(
                DocumentResponse(
                    document_id=document_id,
                    filename=file.filename,
                    upload_timestamp=datetime.now()
                )
            )

        except Exception as e:
            logger.error(f"Error processing file: {str(e)}")
            log_event("document_processing_failed", {
                "error": str(e),
                "file_size": len(content) if 'content' in locals() else 0
            }, "ingest")
            raise HTTPException(
                status_code=500,
                detail=f"Error processing file {file.filename}: {str(e)}"
            )

    trigger_webhook_event("ingest.complete", {"documents": document_responses}, background_tasks)

    log_event("ingest_completed", {
        "total_uploaded": len(document_responses),
        "successful_uploads": len(document_responses)
    }, "ingest")

    return BatchIngestResponse(
        documents=document_responses,
        total_uploaded=len(document_responses)
    )
