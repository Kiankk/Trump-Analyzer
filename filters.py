# filters.py
"""
NLP Filter Matrix for the Financial Squawk Box.
Designed to identify headlines that MOVE FUTURES MARKETS.

Two-tier approach:
  1. Source-aware routing: FinancialJuice headlines are always market-relevant
     (they are pre-curated by professional analysts) — pass them all through.
  2. For general RSS/web sources: strict regex filters to cut noise.

Categories are ranked by typical futures impact severity.
"""
import re

# ═══════════════════════════════════════════════════════════════
#  TIER 1: HIGH-IMPACT — Direct futures movers
# ═══════════════════════════════════════════════════════════════

FILTER_MATRIX = {
    # ─── Fed & Central Banks ────────────────────────────────────
    # These move ES, NQ, bonds instantly
    "FED_SPEAK": re.compile(
        r'\b('
        r'powell|waller|bowman|barr|jefferson|cook|kugler|goolsbee|'  # Fed governors
        r'williams|daly|bostic|mester|kashkari|harker|barkin|collins|'  # Regional Feds
        r'lagarde|bailey|ueda|kuroda|'  # ECB, BOE, BOJ
        r'fed\s*chair|fed\s*gov|fed\'?s\s+\w+'  # "Fed's Powell", "Fed Chair"
        r')\b',
        re.IGNORECASE
    ),

    "MACRO_DATA": re.compile(
        r'\b('
        r'fomc|rate\s*(cut|hike|hold|decision|pause|unchanged)|'
        r'cpi|ppi|pce|core\s+inflation|'
        r'non.?farm|nfp|payrolls|unemployment\s+rate|jobless\s+claims|'
        r'gdp\s+(growth|q[1-4]|report|data|contracted|expanded)|'
        r'retail\s+sales|consumer\s+confidence|ism\s+(manufacturing|services)|'
        r'housing\s+starts|building\s+permits|durable\s+goods|'
        r'trade\s+balance|current\s+account|'
        r'basis\s+points?|bps|dot\s+plot|'
        r'inflation\s+(expectations?|data|report|surged?|eased?|rose|fell)|'
        r'rate\s+expectations?|fed\s+funds|'
        r'quantitative\s+(easing|tightening)|'
        r'yield\s+curve|inverted|2.?year|10.?year|treasury\s+yield'
        r')\b',
        re.IGNORECASE
    ),

    # ─── Trump / Executive Policy ───────────────────────────────
    # Direct market movers: tariffs, sanctions, trade wars
    "TRUMP_POLICY": re.compile(
        r'\b('
        r'trump|potus'
        r')\b'
        r'.*\b('
        r'tariff|sanction|trade\s+war|executive\s+order|'
        r'ban|restrict|reciprocal|deal|negotiate|'
        r'china|eu|mexico|canada|'
        r'oil|iran|israel|russia|ukraine|nato'
        r')\b',
        re.IGNORECASE
    ),

    # ─── Geopolitical Escalation (Futures-Moving Only) ──────────
    # Only catches events that actually move oil/gold/bonds
    "GEO_RISK": re.compile(
        r'\b('
        r'strait\s+of\s+hormuz|blockade|shipping\s+lane|red\s+sea|'
        r'ceasefire\s+(deal|agreement|broken|collapsed)|'
        r'nuclear\s+(test|launch|threat|weapon)|'
        r'airstrike|missile\s+(launch|strike|attack)|ballistic|'
        r'invasion|ground\s+(offensive|troops|invasion)|'
        r'war\s+(declared|escalat|expands?)|'
        r'houthis?.*attack|irgc.*attack|'
        r'oil\s+(tanker|pipeline|facility)\s*(attack|struck|hit)|'
        r'emergency\s+un\s+session|'
        r'nato\s+article\s+5|'
        r'sanctions?\s+(imposed|expanded|new|additional)'
        r')\b',
        re.IGNORECASE
    ),

    # ─── Energy & Commodities ───────────────────────────────────
    "COMMODITIES": re.compile(
        r'\b('
        r'opec\+?\s*(cut|hike|meeting|output|decision|agree)|'
        r'brent\s+crude|wti\s+crude|'
        r'oil\s+price\s*(surge|crash|spike|jump|plunge|soar|drop)|'
        r'crude\s+(surge|crash|spike|jump|drop|plunge|soar|above|below|near|nears?|hits?)|'
        r'strategic\s+petroleum\s+reserve|spr\s+release|'
        r'gold\s+price|gold\s+(surge|rally|hits?|near|above|below)|'
        r'natural\s+gas\s+(price|surge|spike|drop)|'
        r'copper\s+(surge|drop|price)|'
        r'barrel|per\s+barrel|\$/barrel|'
        r'supply\s+(disruption|shortage|shock|glut)|'
        r'lng\s+(export|import|shipment)'
        r')\b',
        re.IGNORECASE
    ),

    # ─── Earnings & Corporate ───────────────────────────────────
    "EARNINGS": re.compile(
        r'\b('
        r'(beats?|miss(es)?|exceeds?|tops?)\s+(estimates?|expectations?|consensus)|'
        r'earnings\s+(surprise|beat|miss|report|season)|'
        r'revenue\s+(beat|miss|growth|decline)|'
        r'guidance\s+(raised?|lowered?|cut|boost)|'
        r'profit\s+warn(ing)?|'
        r'eps\s+(beat|miss|\$)|'
        r'quarterly\s+results?|'
        r'(dow|s&p|nasdaq|spy|qqq|nvda|aapl|msft|tsla|amzn|goog|meta)\s+(surge|crash|drop|rally|jump|plunge)'
        r')\b',
        re.IGNORECASE
    ),

    # ─── Market Sentiment / Flow ────────────────────────────────
    "MARKET_FLOW": re.compile(
        r'\b('
        r'(traders?|market)\s*(pric(e|ing)\s+(in|out)|erase|bet|expect|see)|'
        r'risk\s+(on|off|appetite|aversion)|'
        r'flight\s+to\s+(safety|quality)|'
        r'margin\s+call|liquidat|'
        r'circuit\s+breaker|trading\s+halt|'
        r'flash\s+crash|sell.?off|selloff|melt.?up|'
        r'capitulat|panic\s+(sell|buy)|'
        r'short\s+squeeze|gamma\s+squeeze|'
        r'vix\s+(spike|surge|above|below)|'
        r'all.time\s+(high|low)|record\s+(high|low|close)'
        r')\b',
        re.IGNORECASE
    ),

    # ─── SEC Filings ────────────────────────────────────────────
    "SEC_FILING": re.compile(
        r'\b('
        r'8-K|10-K|10-Q|S-1|13F|'
        r'insider\s+(buy|sell|trade|purchas)|'
        r'sec\s+(filing|investigat|charg|probe)|'
        r'material\s+event|disclosure'
        r')\b',
        re.IGNORECASE
    ),
}

# Category display groups (for UI ordering)
CATEGORY_PRIORITY = {
    'FED_SPEAK': 3,      # Critical — moves everything
    'MACRO_DATA': 3,     # Critical — moves everything
    'TRUMP_POLICY': 3,   # Critical
    'GEO_RISK': 2,       # High — moves oil, gold, bonds
    'COMMODITIES': 2,    # High
    'MARKET_FLOW': 2,    # High
    'EARNINGS': 1,       # Medium
    'SEC_FILING': 1,     # Medium
}


# ═══════════════════════════════════════════════════════════════
#  Sentiment Keywords — focused on futures impact
# ═══════════════════════════════════════════════════════════════

BULLISH_WORDS = {
    'rally', 'surge', 'gain', 'rise', 'soar', 'jump', 'boom', 'beat',
    'exceeded', 'strong', 'growth', 'positive', 'record high', 'upbeat',
    'bullish', 'upgrade', 'outperform', 'recovery', 'rebound',
    'dovish', 'stimulus', 'easing', 'rate cut', 'breakout',
    'all-time high', 'optimistic', 'robust', 'resilient', 'expansion',
    'ceasefire', 'deal', 'agreement', 'resolved', 'de-escalation'
}

BEARISH_WORDS = {
    'crash', 'plunge', 'drop', 'fall', 'sink', 'tumble', 'bust', 'miss',
    'weak', 'decline', 'negative', 'record low', 'recession', 'default',
    'crisis', 'bearish', 'downgrade', 'underperform', 'loss', 'layoff',
    'sell-off', 'selloff', 'hawkish', 'tightening', 'contraction',
    'collapse', 'warning', 'slump', 'breakdown', 'escalation',
    'invasion', 'attack', 'sanction', 'embargo', 'blockade',
    'inflation higher', 'rate hike', 'stagflation', 'tariff'
}


# ═══════════════════════════════════════════════════════════════
#  Ticker Extraction
# ═══════════════════════════════════════════════════════════════

TICKER_PATTERN = re.compile(r'\$([A-Z]{1,5})\b')

def extract_tickers(text: str) -> list:
    """Extract $TICKER symbols from text."""
    return TICKER_PATTERN.findall(text)


# ═══════════════════════════════════════════════════════════════
#  Sentiment Scoring
# ═══════════════════════════════════════════════════════════════

def score_sentiment(text: str) -> str:
    """Score sentiment as BULLISH, BEARISH, or NEUTRAL."""
    text_lower = text.lower()
    bull = sum(1 for w in BULLISH_WORDS if w in text_lower)
    bear = sum(1 for w in BEARISH_WORDS if w in text_lower)
    if bull > bear:
        return 'BULLISH'
    elif bear > bull:
        return 'BEARISH'
    return 'NEUTRAL'


# ═══════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════

def analyze_text(text: str) -> str:
    """Legacy API: returns category name or None. Used by main.py."""
    if not text:
        return None
    for category_name, regex_pattern in FILTER_MATRIX.items():
        if regex_pattern.search(text):
            return category_name
    return None


def analyze_headline(text: str, source: str = '') -> tuple:
    """
    Full analysis: returns (category, sentiment, priority) tuple.
    
    For FinancialJuice: ALL headlines pass through (pre-curated by analysts).
    For general RSS:    Only headlines matching the filter matrix pass.
    """
    if not text:
        return None, 'NEUTRAL', 0

    # ─── FinancialJuice special handling ─────────────────────
    # FJ headlines are pre-curated by professional analysts.
    # They are ALWAYS market-relevant. Categorize them but don't filter.
    is_finjuice = (source == 'FIN_JUICE')

    # Try to categorize via regex
    matched_category = None
    for category_name, regex_pattern in FILTER_MATRIX.items():
        if regex_pattern.search(text):
            matched_category = category_name
            break

    if matched_category:
        sentiment = score_sentiment(text)
        priority = CATEGORY_PRIORITY.get(matched_category, 1)
        return matched_category, sentiment, priority

    # If no regex match but it's FinancialJuice → still show it
    if is_finjuice:
        sentiment = score_sentiment(text)
        return 'BREAKING', sentiment, 2

    # General RSS with no match → filtered out
    return None, 'NEUTRAL', 0