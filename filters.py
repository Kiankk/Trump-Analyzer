# filters.py
import re

# Institutional Regex Matrix
FILTER_MATRIX = {
    "TRUMP_POLICY": re.compile(r'\b(trump|potus|47)\b.*\b(tariff|sanction|executive order|veto|pardon|sign|china|mexico|nato)\b', re.IGNORECASE),
    "FED_MACRO": re.compile(r'\b(fomc|powell|yellen|cpi|ppi|nfp|inflation|basis points?|bps|rate (cut|hike|decision))\b', re.IGNORECASE),
    "GEO_ESCALATION": re.compile(r'\b(nuclear|airstrike|ballistic|mobilization|strait of hormuz|blockade|brics|embargo)\b', re.IGNORECASE),
    "COMMODITIES": re.compile(r'\b(opec\+?|brent crude|wti|strategic petroleum reserve|spr|gold|lng|supply chain)\b', re.IGNORECASE)
}

def analyze_text(text: str) -> str:
    """Scans text against the matrix. Returns the category name or None."""
    if not text:
        return None
        
    text_lower = text.lower()
    for category_name, regex_pattern in FILTER_MATRIX.items():
        if regex_pattern.search(text_lower):
            return category_name
    return None