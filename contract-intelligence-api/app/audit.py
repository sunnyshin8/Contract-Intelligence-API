from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List, Dict, Any, Optional
import re

from models import ExtractRequest, AuditResponse, RiskFinding, RiskSeverity, Citation
from webhook import trigger_webhook_event
from logging_config import get_logger, log_event
from utils import load_document

logger = get_logger("audit")

router = APIRouter(
    prefix="/audit",
    tags=["audit"],
    responses={404: {"description": "Not found"}},
)


def check_auto_renewal(text: str) -> Optional[RiskFinding]:
    """Check for auto-renewal clauses with short notice periods."""
    auto_renewal_patterns = [
        r"auto(?:matically)?[\s-]+renew(?:s|ed|ing|al)?",
        r"renew(?:s|ed|ing|al)?[\s-]+auto(?:matically)?",
    ]
    
    notice_period_patterns = [
        r"(\d+)[\s-]+(day|month|year)s?[\s-]+(?:prior|advance)[\s-]+(?:written[\s-]+)?notice",
        r"notice[\s-]+(?:of|in)[\s-]+(\d+)[\s-]+(day|month|year)s?",
        r"written[\s-]+notice[\s-]+(?:of|in)[\s-]+(\d+)[\s-]+(day|month|year)s?"
    ]
    
    auto_renewal_exists = False
    auto_renewal_match = None
    
    for pattern in auto_renewal_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            auto_renewal_exists = True
            auto_renewal_match = match
            break
    
    if not auto_renewal_exists:
        return None
    
    notice_period_days = None
    
    if auto_renewal_match:
        context_start = max(0, auto_renewal_match.start() - 500)
        context_end = min(len(text), auto_renewal_match.end() + 500)
        context = text[context_start:context_end]
        
        for pattern in notice_period_patterns:
            match = re.search(pattern, context, re.IGNORECASE)
            if match:
                value = int(match.group(1))
                unit = match.group(2).lower()
                
                if unit.startswith("day"):
                    notice_period_days = value
                elif unit.startswith("month"):
                    notice_period_days = value * 30
                elif unit.startswith("year"):
                    notice_period_days = value * 365
                break
    
    if notice_period_days is not None:
        if notice_period_days < 30:
            citation = Citation(
                document_id="",
                page=0,
                start_char=auto_renewal_match.start(),
                end_char=auto_renewal_match.end(),
                text=auto_renewal_match.group(0)
            )
            
            return RiskFinding(
                severity=RiskSeverity.HIGH,
                description=f"Auto-renewal clause with short notice period ({notice_period_days} days)",
                clause_type="auto_renewal",
                evidence=[citation]
            )
        elif notice_period_days < 60:
            citation = Citation(
                document_id="",
                page=0,
                start_char=auto_renewal_match.start(),
                end_char=auto_renewal_match.end(),
                text=auto_renewal_match.group(0)
            )
            
            return RiskFinding(
                severity=RiskSeverity.MEDIUM,
                description=f"Auto-renewal clause with moderate notice period ({notice_period_days} days)",
                clause_type="auto_renewal",
                evidence=[citation]
            )
    elif auto_renewal_exists:
        citation = Citation(
            document_id="",
            page=0,
            start_char=auto_renewal_match.start(),
            end_char=auto_renewal_match.end(),
            text=auto_renewal_match.group(0)
        )
        
        return RiskFinding(
            severity=RiskSeverity.MEDIUM,
            description="Auto-renewal clause with no clear notice period specified",
            clause_type="auto_renewal",
            evidence=[citation]
        )
    
    return None


def check_unlimited_liability(text: str) -> Optional[RiskFinding]:
    """Check for unlimited liability clauses."""
    unlimited_patterns = [
        r"unlimited\s+liability",
        r"without\s+limitation\s+of\s+liability",
        r"no\s+(?:cap|limitation|limit)\s+(?:on|of|to)\s+liability"
    ]
    
    for pattern in unlimited_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            citation = Citation(
                document_id="",
                page=0,
                start_char=match.start(),
                end_char=match.end(),
                text=match.group(0)
            )
            
            return RiskFinding(
                severity=RiskSeverity.HIGH,
                description="Unlimited liability clause",
                clause_type="liability",
                evidence=[citation]
            )
    
    liability_cap_patterns = [
        r"liability\s+(?:shall\s+|will\s+)?(?:be\s+|not\s+exceed\s+|limited\s+to\s+)",
        r"maximum\s+(?:aggregate\s+)?liability",
        r"limitation\s+of\s+liability"
    ]
    
    has_liability_cap = False
    for pattern in liability_cap_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            has_liability_cap = True
            break
    
    if not has_liability_cap:
        return RiskFinding(
            severity=RiskSeverity.MEDIUM,
            description="No explicit liability cap found",
            clause_type="liability",
            evidence=[]
        )
    
    return None


def check_broad_indemnity(text: str) -> Optional[RiskFinding]:
    """Check for overly broad indemnity clauses."""
    indemnity_patterns = [
        r"indemnify\s+(?:and\s+(?:hold\s+harmless|defend))?",
        r"indemnification",
        r"hold\s+harmless"
    ]
    
    broad_indemnity_indicators = [
        r"any\s+and\s+all",
        r"including\s+but\s+not\s+limited\s+to",
        r"whatsoever",
        r"however\s+arising",
        r"regardless\s+of(?:\s+the)?\s+cause",
        r"whether\s+or\s+not\s+\w+\s+was\s+negligent"
    ]
    
    for pattern in indemnity_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            context_start = max(0, match.start() - 500)
            context_end = min(len(text), match.end() + 500)
            context = text[context_start:context_end]
            
            broad_indicators_found = []
            for indicator in broad_indemnity_indicators:
                if re.search(indicator, context, re.IGNORECASE):
                    broad_indicators_found.append(indicator)
            
            if broad_indicators_found:
                citation = Citation(
                    document_id="",
                    page=0,
                    start_char=match.start(),
                    end_char=match.end(),
                    text=match.group(0)
                )
                
                return RiskFinding(
                    severity=RiskSeverity.HIGH if len(broad_indicators_found) > 1 else RiskSeverity.MEDIUM,
                    description=f"Broad indemnity clause using terms like: {', '.join(broad_indicators_found)}",
                    clause_type="indemnity",
                    evidence=[citation]
                )
    
    return None


def check_termination_restrictions(text: str) -> Optional[RiskFinding]:
    """Check for restrictive termination clauses."""
    termination_patterns = [
        r"terminat(?:e|ion)",
        r"cancel(?:lation)?"
    ]
    
    restriction_patterns = [
        r"(?:may\s+not|cannot|shall\s+not)\s+terminat(?:e|ion)",
        r"(?:no|without)\s+right\s+to\s+terminat(?:e|ion)",
        r"for\s+cause\s+only",
        r"solely\s+for\s+(?:material\s+)?breach",
        r"(?:minimum|initial)\s+term\s+of\s+(\d+)\s+(year|month)"
    ]
    
    for pattern in termination_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            context_start = max(0, match.start() - 300)
            context_end = min(len(text), match.end() + 300)
            context = text[context_start:context_end]
            
            for restriction in restriction_patterns:
                r_match = re.search(restriction, context, re.IGNORECASE)
                if r_match:
                    if "minimum" in restriction or "initial" in restriction:
                        value = int(r_match.group(1))
                        unit = r_match.group(2).lower()
                        
                        months = value if unit.startswith("month") else value * 12
                        
                        if months >= 24:
                            citation = Citation(
                                document_id="",
                                page=0,
                                start_char=r_match.start() + context_start,
                                end_char=r_match.end() + context_start,
                                text=r_match.group(0)
                            )
                            
                            return RiskFinding(
                                severity=RiskSeverity.MEDIUM,
                                description=f"Long minimum term ({value} {unit}s) with limited termination rights",
                                clause_type="termination",
                                evidence=[citation]
                            )
                    else:
                        citation = Citation(
                            document_id="",
                            page=0,
                            start_char=r_match.start() + context_start,
                            end_char=r_match.end() + context_start,
                            text=r_match.group(0)
                        )
                        
                        return RiskFinding(
                            severity=RiskSeverity.HIGH,
                            description="Restrictive termination clause limiting termination rights",
                            clause_type="termination",
                            evidence=[citation]
                        )
    
    return None


def find_page_for_citation(citation: Citation, text_by_page: Dict[int, str]) -> Citation:
    """Find the page number for a citation based on the text."""
    for page_num, page_text in text_by_page.items():
        if citation.text in page_text:
            citation.page = int(page_num)
            citation.start_char = page_text.find(citation.text)
            citation.end_char = citation.start_char + len(citation.text)
            break
    return citation


@router.post("/", response_model=AuditResponse)
async def audit_contract(request: ExtractRequest, background_tasks: BackgroundTasks):
    """
    Audit a contract for risky clauses.
    
    Detects:
    - Auto-renewal with short notice period
    - Unlimited liability
    - Broad indemnity language
    - Restrictive termination clauses
    
    Returns list of findings with severity and evidence spans.
    """
    log_event("audit_started", {
        "document_id": request.document_id
    }, "audit")
    
    try:
        document = load_document(request.document_id)
        
        log_event("document_loaded_for_audit", {
            "document_id": request.document_id,
            "pages": len(document.get("text_by_page", {}))
        }, "audit")
        
        all_text = " ".join(document["text_by_page"].values())
        
        findings = []
        
        auto_renewal_finding = check_auto_renewal(all_text)
        if auto_renewal_finding:
            for citation in auto_renewal_finding.evidence:
                citation.document_id = request.document_id
                citation = find_page_for_citation(citation, document["text_by_page"])
            findings.append(auto_renewal_finding)
        
        liability_finding = check_unlimited_liability(all_text)
        if liability_finding:
            for citation in liability_finding.evidence:
                citation.document_id = request.document_id
                citation = find_page_for_citation(citation, document["text_by_page"])
            findings.append(liability_finding)
        
        indemnity_finding = check_broad_indemnity(all_text)
        if indemnity_finding:
            for citation in indemnity_finding.evidence:
                citation.document_id = request.document_id
                citation = find_page_for_citation(citation, document["text_by_page"])
            findings.append(indemnity_finding)
        
        termination_finding = check_termination_restrictions(all_text)
        if termination_finding:
            for citation in termination_finding.evidence:
                citation.document_id = request.document_id
                citation = find_page_for_citation(citation, document["text_by_page"])
            findings.append(termination_finding)
        
        log_event("audit_completed", {
            "document_id": request.document_id,
            "findings_count": len(findings),
            "risk_levels": [f.severity.value for f in findings]
        }, "audit")
        
        trigger_webhook_event("audit.complete", {"document_id": request.document_id, "findings": [f.dict() for f in findings]}, background_tasks)

        return AuditResponse(
            document_id=request.document_id,
            findings=findings
        )
        
    except FileNotFoundError:
        logger.error(f"Document not found for audit: {request.document_id}")
        log_event("audit_failed_document_not_found", {
            "document_id": request.document_id
        }, "audit")
        raise HTTPException(
            status_code=404,
            detail=f"Document {request.document_id} not found"
        )
    except Exception as e:
        logger.error(f"Error auditing contract {request.document_id}: {str(e)}")
        log_event("audit_failed", {
            "document_id": request.document_id,
            "error": str(e)
        }, "audit")
        raise HTTPException(
            status_code=500,
            detail=f"Error auditing contract: {str(e)}"
        )
