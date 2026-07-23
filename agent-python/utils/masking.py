import re
from typing import Any, Dict

def redact_pii(text: str) -> str:
    """
    Redact Personally Identifiable Information (PII) from text.
    """
    if not text or not isinstance(text, str):
        return text

    # Redact Emails
    text = re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[REDACTED_EMAIL]', text)
    
    # Redact Phone Numbers (simple pattern)
    text = re.sub(r'\+?\d{10,14}', '[REDACTED_PHONE]', text)
    
    # Redact potential Social Security Numbers / IDs
    text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[REDACTED_SSN]', text)
    
    # Redact IP addresses
    text = re.sub(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', '[REDACTED_IP]', text)

    return text

def sanitize_alert_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively iterate through the alert payload and redact PII from string fields.
    """
    sanitized = {}
    for key, value in payload.items():
        if isinstance(value, str):
            sanitized[key] = redact_pii(value)
        elif isinstance(value, dict):
            sanitized[key] = sanitize_alert_payload(value)
        elif isinstance(value, list):
            sanitized[key] = [
                redact_pii(item) if isinstance(item, str) 
                else sanitize_alert_payload(item) if isinstance(item, dict) 
                else item 
                for item in value
            ]
        else:
            sanitized[key] = value
            
    return sanitized
