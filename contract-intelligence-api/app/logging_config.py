import logging
import logging.handlers
import os
import re
import zipfile
import gzip
import platform
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
import json

PII_PATTERNS = [
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL_REDACTED]'),
    (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE_REDACTED]'),
    (r'\(\d{3}\)\s*\d{3}[-.]?\d{4}', '[PHONE_REDACTED]'),
    (r'\b\d{3}-\d{2}-\d{4}\b', '[SSN_REDACTED]'),
    (r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b', '[CARD_REDACTED]'),
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP_REDACTED]'),
    (r'\b[A-Z][a-z]+ [A-Z][a-z]+\b(?=\s*(,|\.|\s+(hereby|agrees|shall)))', '[NAME_REDACTED]'),
]

class PIIRedactingFormatter(logging.Formatter):
    """Custom formatter that redacts PII from log messages."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def format(self, record):
        msg = super().format(record)
        
        for pattern, replacement in PII_PATTERNS:
            msg = re.sub(pattern, replacement, msg, flags=re.IGNORECASE)
        
        return msg

class CompressingTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """Custom handler that compresses rotated log files using platform-appropriate compression."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.compression_type = self._get_compression_type()
    
    def _get_compression_type(self):
        """Get appropriate compression type based on platform."""
        system = platform.system().lower()
        if system == 'windows':
            return 'zip'
        else:
            return 'gzip'
    
    def doRollover(self):
        """Override to add compression after rotation."""
        super().doRollover()
        
        if self.backupCount > 0:
            rotated_file = self.rotation_filename(self.baseFilename + "." + 
                                                 datetime.now().strftime(self.suffix))
            
            if os.path.exists(rotated_file):
                self._compress_file(rotated_file)
    
    def _compress_file(self, file_path):
        """Compress the rotated log file."""
        try:
            if self.compression_type == 'zip':
                compressed_path = file_path + '.zip'
                with zipfile.ZipFile(compressed_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(file_path, os.path.basename(file_path))
            else:
                compressed_path = file_path + '.gz'
                with open(file_path, 'rb') as f_in:
                    with gzip.open(compressed_path, 'wb') as f_out:
                        f_out.writelines(f_in)
            
            os.remove(file_path)
            
        except Exception as e:
            print(f"Failed to compress log file {file_path}: {e}")

def setup_logging():
    """Set up logging configuration for the application."""
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    logger = logging.getLogger("contract_intelligence")
    logger.setLevel(logging.INFO)
    
    if logger.handlers:
        return logger
    
    formatter = PIIRedactingFormatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    file_handler = CompressingTimedRotatingFileHandler(
        filename=str(log_dir / "contract_intelligence.log"),
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    error_handler = CompressingTimedRotatingFileHandler(
        filename=str(log_dir / "contract_intelligence_errors.log"),
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)
    
    return logger

def get_logger(name: str = None):
    """Get a logger instance with the specified name."""
    if name:
        return logging.getLogger(f"contract_intelligence.{name}")
    return logging.getLogger("contract_intelligence")

def log_event(event_type: str, event_data: Dict[str, Any], logger_name: str = None):
    """
    Log an event with minimal PII exposure.
    
    Args:
        event_type: Type of event (e.g., 'document_ingested', 'extraction_completed')
        event_data: Data to log (will be sanitized)
        logger_name: Optional logger name
    """
    logger = get_logger(logger_name)
    
    sanitized_data = sanitize_event_data(event_data)
    
    logger.info(f"Event: {event_type} | Data: {json.dumps(sanitized_data, default=str)}")

def sanitize_event_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize event data to minimize PII exposure.
    
    Args:
        data: Original event data
        
    Returns:
        Sanitized data with PII removed/hashed
    """
    if not isinstance(data, dict):
        return {"data_type": type(data).__name__}
    
    sanitized = {}
    
    for key, value in data.items():
        key_lower = key.lower()
        
        if any(sensitive in key_lower for sensitive in ['email', 'phone', 'ssn', 'address', 'name']):
            if isinstance(value, str) and value:
                sanitized[key] = f"[REDACTED_{len(value)}_CHARS]"
            else:
                sanitized[key] = "[REDACTED]"
        elif key_lower in ['document_id', 'filename']:
            if isinstance(value, str):
                sanitized[key] = value[:50] + "..." if len(value) > 50 else value
            else:
                sanitized[key] = str(value)
        elif key_lower in ['size_bytes', 'pages', 'timestamp', 'upload_timestamp', 'total_uploaded']:
            sanitized[key] = value
        elif key_lower in ['event_type', 'endpoint', 'method', 'path', 'status', 'extraction_method', 
                          'client_ip', 'status_code', 'process_time_ms', 'question_length', 
                          'answer_length', 'citations_count', 'sources_count', 'file_count',
                          'findings_count', 'parties_found', 'signatories_found', 'fields_extracted',
                          'document_count', 'tokens_streamed', 'successful_uploads', 'webhook_url_domain',
                          'subscribed_webhooks_count', 'gemini_api_configured', 'data_dir', 'pdf_dir', 
                          'extracted_dir', 'url_domain', 'events', 'webhook_id']:
            sanitized[key] = value
        elif isinstance(value, (int, float, bool)):
            sanitized[key] = value
        elif isinstance(value, dict):
            sanitized[key] = sanitize_event_data(value)
        elif isinstance(value, list):
            if value and isinstance(value[0], dict):
                sanitized[key] = [sanitize_event_data(item) for item in value[:5]]
            elif all(isinstance(item, str) for item in value) and key_lower in ['events', 'risk_levels']:
                sanitized[key] = value
            else:
                sanitized[key] = f"[LIST_{len(value)}_ITEMS]"
        elif isinstance(value, str):
            if key_lower in ['error', 'detail']:
                sanitized[key] = value[:200] + "..." if len(value) > 200 else value
            else:
                sanitized_value = value
                for pattern, replacement in PII_PATTERNS:
                    if re.search(pattern, sanitized_value, flags=re.IGNORECASE):
                        sanitized_value = re.sub(pattern, replacement, sanitized_value, flags=re.IGNORECASE)
                
                if len(sanitized_value) > 100:
                    sanitized[key] = sanitized_value[:100] + "..."
                else:
                    sanitized[key] = sanitized_value
        else:
            sanitized[key] = f"[{type(value).__name__.upper()}]"
    
    return sanitized

setup_logging()
