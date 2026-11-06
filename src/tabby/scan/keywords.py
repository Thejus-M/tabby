"""Label vocabulary for Indian restaurant bills."""

import re
from difflib import SequenceMatcher

HEADER_WORDS = {
    "item", "items", "particulars", "description", "dish", "qty", "quantity", "qt", "rate", "price",
    "amt", "amount", "value", "total", "sl", "sno", "s.no", "hsn",
}  # fmt: skip
_HEADER_KEY = {"qty", "quantity", "rate", "price", "amt", "amount"}

SUBTOTAL = re.compile(
    r"\b(sub\s*-?\s*total|taxable\s*(value|amount)|food\s*total|bar\s*total|item\s*total|gross)\b", re.I
)
GRAND = re.compile(
    r"\b(grand\s*total|net\s*(payable|amount|amt|total)|total\s*(payable|due|amount|bill)|bill\s*amount"
    r"|amount\s*(payable|due)|to\s*pay|payable)\b",
    re.I,
)
TOTAL_ONLY = re.compile(r"^\s*total\b(?!\s*(qty|items?|quantity))", re.I)
COUNT_LINE = re.compile(r"\b(total\s*(qty|items?|quantity)|no\.?\s*of\s*items|items?\s*:|qty\s*:)", re.I)
PAYMENT = re.compile(r"\b(cash|card|upi|paytm|gpay|phonepe|tender(ed)?|change|paid|balance|visa|master|settle)\b", re.I)
EXTRA_CHARGE = re.compile(r"\b(packing|packaging|container|delivery|tip|surcharge|cover\s*charge|cess)\b", re.I)
META = re.compile(
    r"\b(gstin|gst\s*no|fssai|cin|pan|tin|ph(one)?|tel|mob(ile)?|contact|e-?mail|bill\s*(no|#)|invoice|kot|"
    r"table|tbl|pax|steward|waiter|captain|cashier|server|date|time|order|token|counter|dine\s*in|"
    r"take\s*away|duplicate|original|thank|visit)\b|www\.|\.com\b",
    re.I,
)
GSTIN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b")
ADDRESS = re.compile(
    r"\b(road|rd|street|st|nagar|layout|floor|near|opp|sector|block|lane|marg|main|cross|colony|complex|mall|"
    r"plaza|phase|stage|pin|india|bangalore|bengaluru|mumbai|delhi|hyderabad|chennai|pune|kolkata)\b|\b\d{6}\b",
    re.I,
)
DATE_TIME = re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|\b\d{1,2}:\d{2}\b")
SEPARATOR = re.compile(r"^[-=_*.~\s]{4,}$")

_ALCOHOL = re.compile(
    r"\b(beers?|lager|ale|ipa|stout|draught|draft|pints?|pitcher|tower|bucket|shots?|pegs?|whisk(e)?y|scotch|"
    r"bourbon|vodka|rum|gin|tequila|wine|sangria|champagne|prosecco|brandy|cognac|liqueur|cider|breezer|"
    r"cocktail|martini|margarita|mojito|daiquiri|negroni|liit|long\s*island|cosmopolitan|jager(meister)?|"
    r"kingfisher|kf|budweiser|heineken|corona|hoegaarden|tuborg|carlsberg|bira|simba|kati\s*patang|"
    r"old\s*monk|bacardi|smirnoff|absolut|magic\s*moments|jack\s*daniel'?s?|johnnie\s*walker|black\s*label|"
    r"red\s*label|teacher'?s|blenders?\s*pride|royal\s*stag|100\s*pipers|chivas|glenfiddich|jameson|sula)\b",
    re.I,
)
_VOLUME = re.compile(r"\b(30|60|90|180|330|500|650|750)\s*ml\b|\b(large|small)\s*peg\b", re.I)
_NOT_ALCOHOL = re.compile(
    r"\b(virgin|mocktail|non[-\s]?alcoholic|zero\s*proof|ginger\s*ale|root\s*beer|rumali|prawn\s*cocktail|"
    r"fruit\s*cocktail|shrimp\s*cocktail|water|soda|juice|coke|pepsi|sprite|lassi|milk\s*shake|shake)\b",
    re.I,
)


def clean_label(text: str) -> str:
    """Undo digit-for-letter misreads inside words and drop dots between letters ('C.G.5.T' -> 'CGST')."""
    out = []
    for word in text.split():
        letters = sum(ch.isalpha() for ch in word)
        if letters and letters >= (len(word) - word.count(".")) / 2 and not word.endswith("%"):
            word = re.sub(r"(?<=[A-Za-z.])5(?=[A-Za-z.]|$)", "S", word)
            word = re.sub(r"(?<=[A-Za-z])0(?=[A-Za-z]|$)", "O", word)
            word = re.sub(r"(?<=[A-Za-z])\.(?=[A-Za-z])", "", word)
        out.append(word)
    return " ".join(out).strip(" .:-*")


def _close(word: str, vocab: set[str]) -> str | None:
    w = word.lower().strip(".:")
    if w in vocab:
        return w
    for v in vocab:
        if len(w) >= 3 and SequenceMatcher(None, w, v).ratio() >= 0.8:
            return v
    return None


def is_header(text: str) -> bool:
    words = [_close(w, HEADER_WORDS) for w in text.split()]
    hits = {w for w in words if w}
    return len(hits) >= 2 and bool(hits & _HEADER_KEY)


def is_alcohol(name: str) -> bool:
    n = clean_label(name)
    return not _NOT_ALCOHOL.search(n) and bool(_ALCOHOL.search(n) or _VOLUME.search(n))
