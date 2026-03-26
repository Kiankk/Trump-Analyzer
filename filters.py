# filters.py
import re

# Upgraded Institutional Regex Matrix for Geopolitics & Macro
FILTER_MATRIX = {
    # Catches Trump alongside major geopolitical actors or actions
    "TRUMP_POLICY": re.compile(r'\b(trump|potus|47)\b.*\b(tariff|sanction|pardon|veto|china|mexico|nato|iran|russia|ukraine|israel|putin)\b', re.IGNORECASE),
    
    # Standard Fed & Macro events
    "FED_MACRO": re.compile(r'\b(fomc|powell|yellen|cpi|ppi|nfp|inflation|basis points?|bps|rate (cut|hike|decision))\b', re.IGNORECASE),
    
    # Expanded to include major regional conflicts and military actions
    "GEO_ESCALATION": re.compile(r'\b(nuclear|airstrike|ballistic|mobilization|strait of hormuz|blockade|brics|embargo|idf|houthis|irgc|hezbollah|nato|escalation)\b', re.IGNORECASE),
    
    # Expanded for energy markets
    "COMMODITIES": re.compile(r'\b(opec\+?|brent crude|wti|strategic petroleum reserve|spr|gold|lng|supply chain|barrel)\b', re.IGNORECASE)
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