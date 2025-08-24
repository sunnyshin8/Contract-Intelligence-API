from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Dict, Any, List

from models import ExtractRequest, ExtractResponse, Party, Signatory
from webhook import trigger_webhook_event
from logging_config import get_logger, log_event
from utils import (
    load_document,
    extract_fields_with_llm,
    find_parties,
    find_effective_date,
    find_term,
    find_governing_law,
    find_payment_terms,
    find_signatories,
    find_liability_cap
)

logger = get_logger("extract")

router = APIRouter(
    prefix="/extract",
    tags=["extract"],
    responses={404: {"description": "Not found"}},
)


@router.post("/", response_model=ExtractResponse)
async def extract_fields(request: ExtractRequest, background_tasks: BackgroundTasks):
    """
    Extract structured fields from a document.
    
    Fields extracted:
    - parties[]
    - effective_date
    - term
    - governing_law
    - payment_terms
    - termination
    - auto_renewal
    - confidentiality
    - indemnity
    - liability_cap (number + currency)
    - signatories[] (name, title)
    """
    log_event("extraction_started", {
        "document_id": request.document_id
    }, "extract")
    
    try:
        document = load_document(request.document_id)
        
        log_event("document_loaded", {
            "document_id": request.document_id,
            "pages": len(document.get("text_by_page", {}))
        }, "extract")
        
        all_text = " ".join(document["text_by_page"].values())
        
        llm_result = extract_fields_with_llm(all_text)
        if llm_result:
            log_event("llm_extraction_successful", {
                "document_id": request.document_id,
                "fields_extracted": len(llm_result.keys()) if llm_result else 0
            }, "extract")
            
            response = ExtractResponse(
                document_id=request.document_id,
                parties=[Party(**p) for p in llm_result.get("parties", [])],
                effective_date=llm_result.get("effective_date"),
                term=llm_result.get("term"),
                governing_law=llm_result.get("governing_law"),
                payment_terms=llm_result.get("payment_terms"),
                termination=llm_result.get("termination"),
                auto_renewal=llm_result.get("auto_renewal"),
                confidentiality=llm_result.get("confidentiality"),
                indemnity=llm_result.get("indemnity"),
                liability_cap=llm_result.get("liability_cap"),
                signatories=[Signatory(**s) for s in llm_result.get("signatories", [])],
            )
        else:
            log_event("llm_extraction_failed_fallback_to_regex", {
                "document_id": request.document_id
            }, "extract")
            
            response = ExtractResponse(document_id=request.document_id)
            response.parties = [Party(**party) for party in find_parties(all_text)]
            response.effective_date = find_effective_date(all_text)
            response.term = find_term(all_text)
            response.governing_law = find_governing_law(all_text)
            response.payment_terms = find_payment_terms(all_text)
            response.liability_cap = find_liability_cap(all_text)
            response.signatories = [Signatory(**signatory) for signatory in find_signatories(all_text)]

        log_event("extraction_completed", {
            "document_id": request.document_id,
            "extraction_method": "llm" if llm_result else "regex",
            "parties_found": len(response.parties),
            "signatories_found": len(response.signatories)
        }, "extract")
        
        trigger_webhook_event("extract.complete", {"document_id": request.document_id, "extracted_fields": response.dict()}, background_tasks)
        return response
        
    except FileNotFoundError:
        logger.error(f"Document not found: {request.document_id}")
        log_event("extraction_failed_document_not_found", {
            "document_id": request.document_id
        }, "extract")
        raise HTTPException(
            status_code=404,
            detail=f"Document {request.document_id} not found"
        )
    except Exception as e:
        import traceback
        logger.error(f"Extraction error for document {request.document_id}: {str(e)}")
        logger.error(traceback.format_exc())
        
        log_event("extraction_failed", {
            "document_id": request.document_id,
            "error": str(e)
        }, "extract")
        
        raise HTTPException(
            status_code=500,
            detail=f"Error extracting fields: {str(e)}"
        )