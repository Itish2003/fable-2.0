import re

# Dictionary for known source-universe terms to generic equivalents
TERM_MAPPING = {
    r"\bcursed technique\b": "technique",
    r"\bcursed energy\b": "energy",
    r"\bchakra\b": "energy",
    r"\bparahuman\b": "powered individual",
    r"\bninjutsu\b": "technique",
    r"\bninja\b": "operative",
    r"\bquirk\b": "power"
}

def sanitize_context(text: str) -> str:
    """
    Replaces known source-universe terms with generic equivalents
    to prevent narrative leakage.
    """
    if not text:
        return text
    
    sanitized = text
    for pattern, replacement in TERM_MAPPING.items():
        # Case insensitive replacement
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    return sanitized
