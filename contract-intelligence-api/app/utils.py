import requests
import os
import sys
import json
import uuid
import PyPDF2
import pdfplumber
import re
import spacy
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

DATA_DIR = Path(__file__).parent / "data"
PDF_DIR = DATA_DIR / "pdfs"
EXTRACTED_DIR = DATA_DIR / "extracted"

PDF_DIR.mkdir(parents=True, exist_ok=True)
EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    import subprocess
    subprocess.run([sys.executable, "-m", "spacy", "download", "en_core_web_sm"])
    nlp = spacy.load("en_core_web_sm")


def generate_document_id() -> str:
    """Generate a unique document ID."""
    return str(uuid.uuid4())


def save_pdf(file_content: bytes, filename: str, document_id: str) -> str:
    """Save uploaded PDF to disk."""
    file_path = PDF_DIR / f"{document_id}.pdf"
    with open(file_path, "wb") as f:
        f.write(file_content)
    return str(file_path)


def extract_text_from_pdf(pdf_path: str) -> Dict[int, str]:
    """Extract text from PDF, organized by page number."""
    text_by_page = {}
    
    with open(pdf_path, "rb") as file:
        pdf_reader = PyPDF2.PdfReader(file)
        for i, page in enumerate(pdf_reader.pages):
            text = page.extract_text()
            if text:
                text_by_page[i+1] = text
    
    if not any(text_by_page.values()):
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    text_by_page[i+1] = text
    
    return text_by_page


def save_extracted_text(document_id: str, text_by_page: Dict[int, str], metadata: Dict[str, Any]) -> str:
    """Save extracted text and metadata to disk."""
    data = {
        "document_id": document_id,
        "text_by_page": text_by_page,
        "metadata": metadata
    }
    
    file_path = EXTRACTED_DIR / f"{document_id}.json"
    with open(file_path, "w") as f:
        json.dump(data, f, default=str)
    
    return str(file_path)


def load_document(document_id: str) -> Dict[str, Any]:
    """Load document text and metadata from disk."""
    file_path = EXTRACTED_DIR / f"{document_id}.json"
    if not file_path.exists():
        raise FileNotFoundError(f"Document {document_id} not found")
    
    with open(file_path, "r") as f:
        return json.load(f)

def extract_fields_with_llm(text: str, llm_url: str = "http://localhost:11434/api/generate", model: str = "phi3") -> dict:
    """
    Use a local LLM (e.g., Ollama) to extract structured contract fields from text.
    Returns a dict with keys: parties, effective_date, term, governing_law, payment_terms, termination, auto_renewal, confidentiality, indemnity, liability_cap, signatories
    """
    prompt = f'''You are a contract analysis expert. Extract the following fields from the contract text and return ONLY a valid JSON object with no additional text or explanation.

Required JSON structure:
{{
  "parties": [{{ "name": "Party Name", "role": "Party Role" }}],
  "effective_date": "date string or null",
  "term": "term string or null", 
  "governing_law": "law string or null",
  "payment_terms": "payment terms string or null",
  "termination": "termination clause or null",
  "auto_renewal": "auto renewal clause or null",
  "confidentiality": "confidentiality clause or null",
  "indemnity": "indemnity clause or null",
  "liability_cap": {{ "amount": "number or unlimited", "currency": "USD/EUR/etc or null" }},
  "signatories": [{{ "name": "Signatory Name", "title": "Title or null" }}]
}}

Contract text:
{text}

Return ONLY the JSON object:'''
    
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "top_p": 0.9
        }
    }
    
    
    try:
        response = requests.post(llm_url, json=payload, timeout=120)
        response.raise_for_status()
        
        result = response.json()
        content = result.get("response", "").strip()
        
        import json as _json
        
        start = content.find('{')
        end = content.rfind('}') + 1
        
        if start != -1 and end > start:
            json_str = content[start:end]
            try:
                parsed = _json.loads(json_str)
                if isinstance(parsed, dict):
                    return parsed
            except _json.JSONDecodeError:
                pass
        
        print(f"LLM returned non-JSON response: {content[:200]}...")
        return {}
        
    except Exception as e:
        print(f"LLM extraction failed: {e}")
        return {}

def find_parties(text: str) -> List[Dict[str, str]]:
    """Extract party information from contract text."""
    parties = []
    
    party_patterns = [
        r"This\s+agreement\s+is\s+between\s+(.*?)\s+and\s+(.*?)[\.,]",
        r"This\s+agreement\s+is\s+made\s+by\s+and\s+between\s+(.*?)\s+and\s+(.*?)[\.,]",
        r"(.*?)\s+\((?:\"|\")?(Buyer|Client|Customer|Licensee|Vendor|Seller|Provider|Company|Contractor)(?:\"|\")?[\),]",
        r"(.*?)\s+\((?:\"|\")?(the\s+)?([A-Z][a-z]+)(?:\"|\")?[\),]"
    ]
    
    for pattern in party_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE | re.DOTALL)
        for match in matches:
            if match.lastindex == 2:  
                name1 = match.group(1)
                name2 = match.group(2)
                if name1 and name2:
                    parties.append({"name": name1.strip(), "role": "Party"})
                    parties.append({"name": name2.strip(), "role": "Party"})
            elif match.lastindex >= 2:
                name = match.group(1)
                role = match.group(2)
                if name and role:
                    name = name.strip()
                    role = role.strip()
                    if len(name) > 3 and len(role) > 0:
                        parties.append({"name": name, "role": role})
    
    unique_parties = []
    seen_names = set()
    for party in parties:
        if party["name"] not in seen_names:
            seen_names.add(party["name"])
            unique_parties.append(party)
    
    return unique_parties


def find_dates(text: str) -> List[str]:
    """Extract dates from contract text."""
    date_patterns = [
        r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{2,4})\b",
        r"\b([A-Z][a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,\s+(\d{4})\b",
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Z][a-z]+),?\s+(\d{4})\b",
        r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)?\s+day\s+of\s+([A-Z][a-z]+),?\s+(\d{4})\b"
    ]
    
    dates = []
    for pattern in date_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            dates.append(match.group(0))
    
    return dates


def find_effective_date(text: str) -> Optional[str]:
    """Find the effective date in contract text."""
    effective_patterns = [
        r"effective\s+(?:as\s+of\s+|date[:\s]+)([A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}|\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        r"agreement\s+date[:\s]+([A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}|\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        r"dated\s+(?:as\s+of\s+)?([A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}|\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        r"commenc(?:es|ing)\s+on\s+([A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}|\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})"
    ]
    
    for pattern in effective_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    effective_pos = text.lower().find("effective")
    if effective_pos != -1:
        window_text = text[effective_pos:effective_pos + 200]
        dates = find_dates(window_text)
        if dates:
            return dates[0]
    
    return None


def find_term(text: str) -> Optional[str]:
    """Find the term duration in contract text."""
    term_patterns = [
        r"(?:for\s+a\s+|for\s+an\s+|the\s+|initial\s+)?term\s+(?:of|is|shall\s+be)\s+(\d+)\s+(year|month|day)s?",
        r"shall\s+(?:remain\s+in|be\s+in|continue\s+in)\s+(?:full\s+force\s+and\s+effect\s+|effect\s+|force\s+)?for\s+(?:a\s+period\s+of\s+)?(\d+)\s+(year|month|day)s?",
        r"continue\s+for\s+a\s+period\s+of\s+(\d+)\s+(year|month|day)s?",
        r"agreement\s+(?:shall|will)\s+(?:be\s+valid|remain\s+in\s+force)\s+for\s+(\d+)\s+(year|month|day)s?"
    ]
    
    for pattern in term_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            duration = match.group(1)
            unit = match.group(2)
            return f"{duration} {unit}{'s' if int(duration) > 1 and not unit.endswith('s') else ''}"
    
    return None


def find_governing_law(text: str) -> Optional[str]:
    """Find the governing law in contract text."""
    law_patterns = [
        r"govern(?:ed|ing)\s+(?:by\s+)?(?:the\s+)?laws\s+of\s+(?:the\s+)?([A-Za-z\s]+)(?:,|\.|\s|$)",
        r"jurisdiction\s+of\s+(?:the\s+)?([A-Za-z\s]+)(?:,|\.|\s|$)",
        r"(?:exclusive\s+)?venue\s+(?:shall\s+be|will\s+be|in)\s+(?:the\s+)?([A-Za-z\s]+)(?:,|\.|\s|$)"
    ]
    
    for pattern in law_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            law = match.group(1).strip()
            for suffix in [" courts", " court", " state", " only"]:
                if law.lower().endswith(suffix):
                    law = law[:-len(suffix)]
            return law.strip()
    
    return None


def find_payment_terms(text: str) -> Optional[str]:
    """Find payment terms in contract text."""
    payment_window = 5000
    
    payment_sections = []
    payment_keywords = ["payment", "fee", "compensation", "price", "cost", "invoice"]
    
    for keyword in payment_keywords:
        pos = text.lower().find(keyword)
        if pos != -1:
            start_pos = max(0, pos - payment_window // 2)
            end_pos = min(len(text), pos + payment_window // 2)
            payment_sections.append(text[start_pos:end_pos])
    
    if not payment_sections:
        return None
    
    payment_text = " ".join(payment_sections)
    
    payment_patterns = [
        r"(?:payment|invoice)\s+(?:shall\s+be|is|are)\s+due\s+(?:and\s+payable\s+)?within\s+(\d+)\s+(?:calendar\s+|business\s+)?days",
        r"(?:payment|invoice)\s+terms\s+(?:are|shall\s+be)\s+(\d+)\s+(?:calendar\s+|business\s+)?days",
        r"(?:payment|invoice)\s+(?:shall\s+be|is|are)\s+due\s+(?:and\s+payable\s+)?(\d+)\s+(?:calendar\s+|business\s+)?days",
        r"net\s+(\d+)(?:\s+days)?"
    ]
    
    for pattern in payment_patterns:
        match = re.search(pattern, payment_text, re.IGNORECASE)
        if match:
            days = match.group(1)
            return f"Net {days} days"
    
    doc = nlp(payment_text[:1000])
    
    payment_sentences = []
    for sent in doc.sents:
        sent_text = sent.text.lower()
        if any(keyword in sent_text for keyword in payment_keywords):
            payment_sentences.append(sent.text)
    
    if payment_sentences:
        return payment_sentences[0][:250] + "..."
    
    return None


def find_signatories(text: str) -> List[Dict[str, str]]:
    """Find signatories in contract text."""
    signatories = []
    
    signature_patterns = [
        r"(?:Signed|Signature):\s*(.*?)(?:\n|$)",
        r"(?:Name|Print\s+Name):\s*(.*?)(?:\n|$)",
        r"(?:Title):\s*(.*?)(?:\n|$)",
        r"By:\s*(.*?)(?:\n|$)",
        r"(?:[A-Z][a-zA-Z\s]+):\s*\n\s*_+\s*\n\s*(?:Name|By)?:\s*(.*?)(?:\n|$)",
        r"(?:[A-Z][a-zA-Z\s]+):\s*\n\s*_+\s*\n\s*(?:Title):\s*(.*?)(?:\n|$)"
    ]
    
    names = []
    titles = []
    
    for pattern in signature_patterns:
        matches = re.finditer(pattern, text)
        for match in matches:
            content = match.group(1).strip()
            if "name" in pattern.lower() or "by" in pattern.lower():
                names.append(content)
            elif "title" in pattern.lower():
                titles.append(content)
    
    for i, name in enumerate(names):
        signatory = {"name": name}
        if i < len(titles):
            signatory["title"] = titles[i]
        signatories.append(signatory)
    
    return signatories


def find_liability_cap(text: str) -> Optional[Dict[str, Any]]:
    """Find liability cap information in contract text."""
    amount_patterns = [
        r"liability\s+(?:shall\s+|will\s+)?(?:be\s+|not\s+exceed\s+|limited\s+to\s+|exceed\s+|in\s+excess\s+of\s+)(?:a\s+total\s+of\s+)?(?:USD|US\$|\$|€|EUR|GBP|£)?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:USD|US\$|\$|€|EUR|GBP|£)?(?:\s+(?:US\s+)?dollars|(?:US\s+)?dollars|\s+euros|\s+pounds)?",
        r"liability\s+(?:shall\s+|will\s+)?(?:be\s+|not\s+exceed\s+|limited\s+to\s+|exceed\s+|in\s+excess\s+of\s+)(?:a\s+total\s+of\s+)?(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:USD|US\$|\$|€|EUR|GBP|£|(?:US\s+)?dollars|euros|pounds)",
        r"limitation\s+of\s+liability\s*[:\.\s]+(?:.*?)(?:USD|US\$|\$|€|EUR|GBP|£)?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:USD|US\$|\$|€|EUR|GBP|£)?(?:\s+(?:US\s+)?dollars|(?:US\s+)?dollars|\s+euros|\s+pounds)?",
        r"maximum\s+(?:aggregate\s+)?liability\s+(?:.*?)(?:USD|US\$|\$|€|EUR|GBP|£)?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:USD|US\$|\$|€|EUR|GBP|£)?(?:\s+(?:US\s+)?dollars|(?:US\s+)?dollars|\s+euros|\s+pounds)?"
    ]
    
    currency_map = {
        "$": "USD",
        "USD": "USD",
        "US$": "USD",
        "dollars": "USD",
        "US dollars": "USD",
        "€": "EUR",
        "EUR": "EUR",
        "euros": "EUR",
        "£": "GBP",
        "GBP": "GBP",
        "pounds": "GBP"
    }
    
    for pattern in amount_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(1).replace(",", "")
            amount = float(amount_str)
            
            currency = "USD"
            match_text = match.group(0).lower()
            
            for curr_symbol, curr_code in currency_map.items():
                if curr_symbol.lower() in match_text:
                    currency = curr_code
                    break
            
            return {
                "amount": amount,
                "currency": currency
            }
    
    unlimited_patterns = [
        r"unlimited\s+liability",
        r"without\s+limitation\s+of\s+liability",
        r"no\s+(?:cap|limitation|limit)\s+(?:on|of|to)\s+liability"
    ]
    
    for pattern in unlimited_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return {
                "amount": "unlimited",
                "currency": None
            }
    
    return None
