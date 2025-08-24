from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from enum import Enum
from datetime import datetime


class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    upload_timestamp: datetime


class BatchIngestResponse(BaseModel):
    documents: List[DocumentResponse]
    total_uploaded: int


class ExtractRequest(BaseModel):
    document_id: str


class Party(BaseModel):
    name: str
    role: Optional[str] = None


class Signatory(BaseModel):
    name: str
    title: Optional[str] = None
    date: Optional[str] = None


class ExtractResponse(BaseModel):
    document_id: str
    parties: List[Party] = []
    effective_date: Optional[str] = None
    term: Optional[str] = None
    governing_law: Optional[str] = None
    payment_terms: Optional[str] = None
    termination: Optional[str] = None
    auto_renewal: Optional[str] = None
    confidentiality: Optional[str] = None
    indemnity: Optional[str] = None
    liability_cap: Optional[Dict[str, Any]] = None
    signatories: List[Signatory] = []


class Citation(BaseModel):
    document_id: str
    page: int
    start_char: int
    end_char: int
    text: str


class AskRequest(BaseModel):
    question: str
    document_ids: Optional[List[str]] = None


class AskResponse(BaseModel):
    answer: str
    citations: List[Citation] = []


class RiskSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskFinding(BaseModel):
    severity: RiskSeverity
    description: str
    clause_type: str
    evidence: List[Citation]


class AuditResponse(BaseModel):
    document_id: str
    findings: List[RiskFinding] = []


class WebhookConfig(BaseModel):
    url: str
    events: List[str]


class HealthResponse(BaseModel):
    system_status: str
    system_info: Dict[str, Any]
    disk_status: str
    version: str
    timestamp: datetime
