"""
PDF extraction — no external API.
Add-on detection uses canonical term lists provided by domain expert.
"""

import re
from collections import defaultdict
import pdfplumber
import fitz  # PyMuPDF


# ─── insurer catalogue ────────────────────────────────────────────────────────

KNOWN_INSURERS = [
    ("TATA AIG",            [r"tata\s*aig"]),
    ("HDFC ERGO",           [r"hdfc\s*ergo"]),
    ("ICICI Lombard",       [r"icici\s*lombard", r"icici\s+general"]),
    ("SBI General",         [r"sbi\s+gen(?:eral)?"]),
    ("Bajaj Allianz",       [r"bajaj\s*allianz", r"bajaj\s+general"]),
    ("New India Assurance", [r"new\s+india"]),
    ("National Insurance",  [r"national\s+insurance"]),
    ("Oriental Insurance",  [r"oriental\s+insurance"]),
    ("Royal Sundaram",      [r"royal\s+sundaram"]),
    ("IFFCO Tokio",         [r"iffco.{0,4}tokio"]),
    ("Future Generali",     [r"future\s+generali"]),
    ("Go Digit",            [r"go\s*digit", r"\bdigit\s+insurance\b"]),
    ("Chola MS",            [r"chola(?:mandalam)?\s*ms", r"cholamandalam", r"\bchola\b"]),
    ("Magma HDI",           [r"magma\s*hdi", r"\bmagma\b"]),
    ("Shriram",             [r"shriram\s+gen(?:eral)?"]),
    ("Universal Sompo",     [r"universal\s+sompo"]),
    ("Zuno",                [r"\bzuno\b"]),
    ("Acko",                [r"\backo\b"]),
    ("Navi",                [r"navi\s+gen(?:eral)?"]),
    ("IndusInd",            [r"indusind", r"reliance\s+gen(?:eral)?"]),
]


# ─── canonical add-on term map ────────────────────────────────────────────────
# Plain-English phrases → compiled to word-boundary regex at runtime.
# Broad matching within add-on sections; false-positive guard via negation list.

ADDON_TERMS: dict[str, list[str]] = {

    # ── core add-ons (always shown) ───────────────────────────────────────────

    "Nil Depreciation": [
        # specific compound phrases first
        "zero dep shield", "zero dep plus", "unlimited zero dep",
        "depreciation reimbursement", "depreciation waiver", "dep protection",
        "dep waiver", "dep shield", "depreciation cover", "depreciation protect",
        "zero depreciation", "nil depreciation", "nil dep", "zero dep",
        "bumper to bumper", "bumper 2 bumper",
        "zero wear and tear",
        "acc dep waiver", "accessory depreciation waiver",
        "zero dep claim", "zero depreciation claim", "depreciation claim",
        "100% depreciation cover", "full invoice value of parts",
        "no depreciation cover", "complete cover plus",        # ICICI / generic marketing names
        "total protect cover",
        # catch-all: any mention of depreciation in add-on context
        "depreciation",
    ],

    "Engine Protection": [
        "engine secure", "engine protector", "engine protect",
        "engine guard", "engine gaurd",                         # SBI spells it both ways
        "engine care", "engine cover",
        "engine and gearbox", "engine and gear box protect", "engine and gear box",
        "engine and gear-box protect", "engine & gear box protector",
        "engine & gearbox protect", "engine gearbox protect",
        "gear box protect", "engine damage",
        "hydrostatic lock", "water ingress cover", "engine ingress",
        "consequential engine damage", "engine restore",
        "undercarriage damage cover", "engine internal parts cover",
        "engine protect plus",                                  # ICICI
        "engine secure cover",                                  # TATA AIG
    ],

    "Consumables Cover": [
        "consumable expenses protect", "consumables protection",
        "cover for consumables", "cost of consumable items",     # HDFC ERGO
        "consumable replacement", "consumable expenses",
        "consumables add on", "consumables",
        "consumable cover", "consumables protect",
        "nuts bolts", "oil grease", "engine oil cover",
        "fluid replacement", "lubricant cover",
    ],

    "Road Side Assistance": [
        "24x7 spot assistance", "spot assistance", "on spot assistance",
        "road side assistance", "roadside assistance", "road assist",
        "basic road assistance", "basic road assist",            # SBI phrasing
        "car breakdown assistance", "car breakdown cover",       # GoDigit phrasing
        "emergency road service", "breakdown assistance", "breakdown assist",
        "breakdown rescue", "towing assistance", "towing service",
        "on call assistance", "flat tyre support", "battery jumpstart",
        "fuel delivery", "emergency mobility", "on road assistance",
        "breakdown support", "emergency assistance cover",       # HDFC ERGO
        # generic RSA abbreviation — word-bounded so doesn't match "persona"
        "rsa",
    ],

    "Return To Invoice": [
        # Keep specific to avoid matching stray "invoice" mentions
        "return to invoice",
        "invoice protection", "invoice return cover",
        "invoice value guarantee", "invoice shield", "invoice gap cover",
        "invoice price protection", "full invoice cover",
        "new vehicle replacement cover", "replacement cost cover",
        "purchase price protection", "vehicle replacement value plus",  # Royal Sundaram
        "rpi",                                                   # Iffco Tokio abbreviation
        "rti cover", "rti",
    ],

    "Tyre Protection": [
        "tyre secure", "tyre protect", "tyre protection",
        "tyre damage cover", "tyre cover", "tyre care",
        "tire protect", "tire cover",
        "rim protector", "rim damage cover",
        "alloy wheel cover", "tyre burst",
        "tyre secure cover",                                     # TATA AIG
    ],

    "Emergency Transport & Hotel": [
        "emergency transport and hotel", "transport and hotel",
        "emergency hotel expenses", "alternate accommodation",
        "emergency travel assistance", "hotel stay expenses",
        "hotel expenses", "emergency transport",
        "higher protection and removal costs",                   # HDFC ERGO
        "removal of debris", "debris removal cover",
    ],

    "Personal Belongings Cover": [
        "personal baggage cover", "personal belongings protect",
        "personal belongings cover", "personal effects cover",
        "personal items cover", "loss of personal belongings",
        "loss of personal", "belongings cover",
        "laptop cover", "mobile cover", "baggage cover",
        "item protection", "cabin contents",
        "loss of baggage cover", "personal baggage",
    ],

    "Key Replacement": [
        "keys and locks replacement cover", "key and locks protect",
        "key and lock protect", "keys and locks protect",
        "lock and key replacement", "key replacement",
        "key protect", "key loss cover", "key care",
        "key replacement cover",
        "smart key cover", "smart key protection",
        "key loss assistance", "lost key cover", "key fob cover",
        "key and lock cover", "lockset replacement",
    ],

    "Emergency Medical Expenses": [
        "emergency medical expenses", "medical expense cover",
        "hospitalisation expense", "hospital cash",
        "ambulance charges", "accidental hospitalisation",
        "emergency medical",
    ],

    "Legal Liability to Paid Driver": [
        # Bajaj: "LL To Person For Operation/Maintenance" / "Legal Liability To Person"
        "ll to person for operation",
        "ll to person",
        "legal liability to person for operation",
        "legal liability to person",
        "legal liability to paid drivers",
        "legal liability to paid driver",
        "legal liability to paid",
        "liability to paid driver",
        "paid driver cover",
        "paid driver liability",
        "cover for paid driver",
        "ll to paid driver",
        # ICICI page 2: just "Paid Driver" listed as add-on line item
        "paid driver",
    ],

    "Personal Accident (Owner Driver)": [
        # Most specific first
        "compulsory pa cover for owner driver",
        "compulsory pa for owner driver",
        "compulsory pa cover owner driver",
        "compulsory pa owner driver",
        "compulsory pa for owner",
        "compulsory pa",                      # Bajaj/TATA AIG: "Compulsory PA for owner driver"
        "compulsory personal accident cover",
        "cpa cover",
        "pa cover for owner driver",
        "pa cover owner driver",
        "pa cover owner",                     # ICICI: "PA Cover - Owner Driver"
        "pa owner driver",
        "pa to owner driver",
        "pa to owner",
        "owner driver pa cover",
        "owner driver personal accident",
        "personal accident owner driver",
        "personal accident for owner",
        "pa benefit owner",
        "pa owner",                           # Zuno: "PA Owner Driver"
    ],

    "IMT 23": [
        "imt 23", "imt23",
        "repair of glass rubber plastic",
        "repair of glass.*plastic",
        "repair of glass fibre plastic rubber parts",
        "glass fibre plastic rubber cover",
        "lamps tyres tubes",
        "fitments cover",
    ],

    "NCB Protection": [
        # removed bare "ncb" — it matches "NCB Discount" causing false positives
        "ncb protect", "ncb protector", "ncb protection",
        "no claim bonus protection", "no claim bonus protect",
        "ncb saver", "bonus protection", "bonus protect",
        "bonus retention", "claim shield", "ncb guard",
        "bonus lock", "ncb protector cover",
    ],

    "IMT 25 (CNG/LPG)": [
        "imt 25", "imt25", "cng kit", "lpg kit",
        "cng/lpg", "cng lpg", "bi-fuel kit", "cng cover",
    ],

    # ── extended add-ons (shown if found in any policy) ───────────────────────

    "Passenger PA Cover": [
        "passenger pa", "passenger personal accident",
        "occupant cover", "pa for occupants",
        "co-passenger cover", "co passenger cover",
        "unnamed passenger cover", "named passenger cover",
        "occupant injury cover", "family passenger cover",
        "additional personal accident",                          # HDFC ERGO
        "enhanced pa cover",                                      # IMT 47 marketing name
        "accident shield",                                        # Go Digit PA top-up bundle
    ],

    "Glass Cover": [
        "windshield cover", "glass damage cover", "glass protection",
        "glass secure", "glass rubber plastic",
        "windscreen protection", "mirror cover",
        "window glass cover", "sunroof cover", "glass cover",
        "windscreen cover", "windshield protect",
    ],

    "Daily Allowance": [
        "daily cash allowance", "daily allowance",
        "alternate transport", "travel assistance",
        "taxi reimbursement", "emergency taxi",
        "daily commute allowance",
        "daily conveyance benefit", "conveyance benefit",        # Go Digit
        "garage cash",                                            # ICICI Lombard
        "loss of use", "down time protection",                   # HDFC ERGO
        "daily cash benefit",
    ],

    "Car Replacement": [
        "replacement vehicle", "courtesy car",
        "substitute vehicle", "car replacement",
        "hire car cover",                                         # TATA AIG
        "vehicle replacement advantage",                          # Go Digit top-up cover
        "standby vehicle",
    ],

    "Electrical Accessories": [
        "electrical accessories cover", "electronic accessories cover",
        "music system cover", "audio system cover",
        "electronic device cover",
    ],

    "Non-Electrical Accessories": [
        "non-electrical accessories", "non electrical accessories",
    ],

    "EV Battery Protection": [
        "ev battery cover", "battery secure", "battery protection",
        "charger cover", "charging equipment cover",
        "ev secure", "battery replacement cover", "cable cover",
        "hybrid electric car shield", "ev shield",               # Royal Sundaram / Go Digit
        "electric surge secure",                                  # TATA AIG (EV add-on)
        "battery degradation cover", "drive motor cover",
        "ev roadside assistance", "charging point cover",
    ],

    "Loan Protection": [
        "emi protection", "loan shield", "emi secure",
        "instalment protection", "loan cover",
        "finance protection", "loan guard", "emi protector",      # HDFC ERGO
    ],

    "Smart Assistance": [
        "il smart assist", "smart assist", "smart saver plus",
        "smart save pro",                                        # Royal Sundaram
    ],

    "IMT 47": [
        "imt 47", "imt47", "enhanced pa cover",
    ],

    "Voluntary Deductible": [
        "voluntary deductible",                                   # HDFC ERGO / Royal Sundaram
        "voluntary excess",
    ],

    "Pay As You Drive": [
        "pay as you drive", "payd cover", "limit sure-pay as you drive",
        "kilometer based cover", "usage based cover",
    ],
}

# Which add-ons always appear in the Excel (core set from template)
CORE_ADDONS = [
    "Return To Invoice",
    "Nil Depreciation",
    "Consumables Cover",
    "Engine Protection",
    "Road Side Assistance",
    "Tyre Protection",
    "Emergency Transport & Hotel",
    "Personal Belongings Cover",
    "Key Replacement",
    "Emergency Medical Expenses",
    "Legal Liability to Paid Driver",
    "Personal Accident (Owner Driver)",
    "IMT 23",
    "NCB Protection",
    "IMT 25 (CNG/LPG)",
]

EXTENDED_ADDONS = [k for k in ADDON_TERMS if k not in CORE_ADDONS]

# Negation markers
_NEGATION = re.compile(
    r"\b(?:not\s+(?:opted|covered|included|applicable|availed|selected|offered)"
    r"|opted\s*:\s*no|included\s*:\s*no|covered\s*:\s*no"
    r"|excluded|declined|rejected|not\s+available)\b",
    re.IGNORECASE,
)
_YES_RE = re.compile(
    r"\b(?:yes|included|opted|covered|available|selected|applicable|availed)\b|[✓✔☑]",
    re.IGNORECASE,
)
_NO_RE = re.compile(
    # "no\b(?!\s*[.\d])" — excludes "No. 1" (number) and "No." abbreviation
    r"(?:\bno\b(?!\s*[.\d])|not\s+included|not\s+opted|not\s+covered|\bnil\b|\bexcluded\b|\bn/a\b|\bna\b|not\s+applicable)|[✗✘☐]",
    re.IGNORECASE,
)


def _terms_to_pattern(terms: list[str]) -> re.Pattern:
    """
    Convert plain-English terms to a single regex.
    Each term gets word-boundaries so 'rti' never matches inside 'Vertical'.
    """
    parts = []
    for t in terms:
        # escape then loosen spaces/hyphens, and wrap in word boundaries
        escaped = re.escape(t.strip())
        escaped = re.sub(r"\\ ", r"[\\s\\-­]*", escaped)  # allow soft-hyphens too
        # wrap in word boundary only if term starts/ends with word chars
        left  = r"\b" if re.match(r"\w", t[0])  else ""
        right = r"\b" if re.match(r"\w", t[-1]) else ""
        parts.append(left + escaped + right)
    parts.sort(key=len, reverse=True)  # longest/most-specific first
    return re.compile(r"(?:" + "|".join(parts) + r")", re.IGNORECASE)


# Pre-compile at import time
_ADDON_COMPILED: dict[str, re.Pattern] = {
    name: _terms_to_pattern(terms) for name, terms in ADDON_TERMS.items()
}

# Add-ons that should also be searched in the FULL text (not just add-on section)
# because they appear in the Liability / TP section of premium breakdowns
_FULLTEXT_ADDONS = {
    "Legal Liability to Paid Driver",
    "Personal Accident (Owner Driver)",
}

# Signal words for unknown add-on detection
_ADDON_SIGNAL = re.compile(
    r"\b(?:protect(?:ion)?|secure|shield|cover(?:age)?|care|assist(?:ance)?"
    r"|guard|saver|benefit|replacement)\b",
    re.IGNORECASE,
)


# ─── OCR fallback ─────────────────────────────────────────────────────────────
# Tesseract must be installed separately (see README). On Windows the default
# install path is detected automatically; set TESSERACT_CMD env var to override.

import os as _os
import io as _io

def _find_tesseract() -> str | None:
    """Return the tesseract executable path, or None if not found."""
    env = _os.environ.get("TESSERACT_CMD")
    if env:
        return env
    # Common Windows install location
    win_default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if _os.path.isfile(win_default):
        return win_default
    return None  # rely on PATH


_TESSERACT_CMD = _find_tesseract()


def _ocr_pdf(path: str) -> tuple[str, list[str]]:
    """
    Render each page at 300 DPI with PyMuPDF and run Tesseract OCR on it.
    Returns (full_text, lines) in the same shape as _pymupdf_lines.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return "", []

    if _TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD

    doc = fitz.open(path)
    page_texts: list[str] = []
    all_lines:  list[str] = []

    for page in doc:
        # 300 DPI gives good accuracy without being too slow
        mat = fitz.Matrix(300 / 72, 300 / 72)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        img = Image.open(_io.BytesIO(pix.tobytes("png")))
        raw = pytesseract.image_to_string(img, lang="eng",
                                          config="--oem 3 --psm 6")
        text = _normalize_text(raw)
        page_texts.append(text)
        all_lines.extend(ln.strip() for ln in text.splitlines() if ln.strip())

    doc.close()
    return "\n".join(page_texts), all_lines


def _text_is_sparse(text: str, lines: list[str], num_pages: int) -> bool:
    """True when the PDF yielded so little text it's likely image-based."""
    if not text.strip():
        return True
    # Fewer than 15 meaningful words per page → treat as image-only
    word_count = len(re.findall(r"\b[a-zA-Z]{3,}\b", text))
    return word_count < max(15, num_pages * 15)


# ─── PDF text extraction ──────────────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    """Remove soft hyphens and normalize non-breaking spaces."""
    text = text.replace("­", "")   # soft hyphen
    text = text.replace(" ", " ")  # non-breaking space
    text = text.replace("\xa0", " ")
    return text


def _pymupdf_lines(path: str) -> tuple[str, list[str]]:
    doc = fitz.open(path)
    all_lines: list[str] = []
    full_pages: list[str] = []

    for page in doc:
        words = page.get_text("words")
        if not words:
            full_pages.append(_normalize_text(page.get_text("text")))
            continue

        line_map: dict[tuple, list] = defaultdict(list)
        for w in words:
            x0, y0, x1, y1, text_w, bn, ln, wn = w
            line_map[(bn, ln, round(y0))].append((x0, text_w))

        page_lines = []
        for key in sorted(line_map.keys()):
            parts = sorted(line_map[key], key=lambda p: p[0])
            line = " ".join(p[1] for p in parts).strip()
            if line:
                page_lines.append(_normalize_text(line))

        all_lines.extend(page_lines)
        full_pages.append(_normalize_text(page.get_text("text")))

    doc.close()
    return "\n".join(full_pages), all_lines


def _plumber_tables(path: str) -> list[list[str]]:
    rows = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if row:
                        rows.append([_normalize_text(str(c or "")).strip() for c in row])
    return rows


def _plumber_text(path: str) -> str:
    parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text(layout=True, x_tolerance=3, y_tolerance=3)
            if t:
                parts.append(_normalize_text(t))
    return "\n".join(parts)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())

def _parse_number(s: str) -> float | None:
    raw = re.sub(r"[^\d.]", "", s)
    try:
        v = float(raw)
        return v if v > 0 else None
    except ValueError:
        return None


_MONTH_MAP = {
    'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
    'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
    'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12',
}
_MONTH_PAT = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May"
    r"|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?"
    r"|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
_DATE_NUMERIC  = re.compile(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\b")
_DATE_WORD_MDY = re.compile(rf"\b({_MONTH_PAT})\s+(\d{{1,2}})[,\s]+(\d{{4}})\b", re.I)
_DATE_WORD_DMY = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_PAT})[,.\s]+(\d{{4}})\b", re.I)


def _parse_date_str(s: str) -> str | None:
    """Return the first date found in *s* as DD/MM/YYYY, or None."""
    m = _DATE_NUMERIC.search(s)
    if m:
        d, mo, y = m.groups()
        y = "20" + y if len(y) == 2 else y
        return f"{d.zfill(2)}/{mo.zfill(2)}/{y}"
    m = _DATE_WORD_MDY.search(s)
    if m:
        month, d, y = m.groups()
        mo = _MONTH_MAP.get(month[:3].lower(), "??")
        return f"{d.zfill(2)}/{mo}/{y}"
    m = _DATE_WORD_DMY.search(s)
    if m:
        d, month, y = m.groups()
        mo = _MONTH_MAP.get(month[:3].lower(), "??")
        return f"{d.zfill(2)}/{mo}/{y}"
    return None


# ─── KV dict from lines ───────────────────────────────────────────────────────

def _build_kv(lines: list[str]) -> dict[str, str]:
    kv: dict[str, str] = {}
    n = len(lines)
    for i, line in enumerate(lines):
        # TATA AIG 3-line pattern: "Label\n:\nValue" — must be checked FIRST
        # because a bare ":" also satisfies '":" in line' below
        if line.strip() == ":":
            if i > 0 and i + 1 < n:
                label = _norm(lines[i - 1].strip())
                value = _clean(lines[i + 1])
                if label and value and len(label) < 80:
                    kv[label] = value
        elif ":" in line:
            parts = line.split(":", 1)
            label = _norm(parts[0].strip())
            value = _clean(parts[1].strip())
            if label and len(label) < 80:
                if value:
                    kv[label] = value
                elif i + 1 < n:
                    # Value on next line (e.g. "Client Name:\n Vijaykumar Bandi")
                    nv = _clean(lines[i + 1])
                    if nv and ":" not in lines[i + 1]:
                        kv[label] = nv
        else:
            m = re.match(r"^(.+?)\s{3,}(.+)$", line)
            if m:
                label = _norm(m.group(1).strip())
                value = _clean(m.group(2).strip())
                if label and value:
                    kv[label] = value
    return kv


def _kv_lookup(kv: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        # exact match
        if key in kv:
            return kv[key]
        # substring match only for labels ≥5 chars (avoids "a"⊂"clientname" false hits)
        for k, v in kv.items():
            if len(k) >= 5 and len(key) >= 5:
                if key in k or k in key:
                    return v
    return None


# ─── field extractors ─────────────────────────────────────────────────────────

def _detect_insurer(text: str) -> str:
    t = text.lower()
    for name, patterns in KNOWN_INSURERS:
        if any(re.search(p, t) for p in patterns):
            return name
    return "N/A"


def _detect_plan_coverage(text: str) -> str:
    t = text.lower()
    if re.search(r"\bcomprehensive\b|\bpackage\s+policy\b|\bod\s*\+\s*tp\b", t):
        return "Comprehensive (Own Damage + Third Party Liability)"
    if re.search(
        r"(?:four|two|two)\s+wheeler\s+package|private\s+car\s+package"
        r"|motor\s+package|bundled\s+policy",
        t,
    ):
        return "Comprehensive (Own Damage + Third Party Liability)"
    if re.search(r"own\s+damage\s+only|standalone\s+od|\bsaod\b", t):
        return "Own Damage Only"
    if re.search(r"third\s+party\s+only|tp\s+only|\bliability\s+only\b", t):
        return "Third Party Only"
    return "N/A"


_VEH_REG = re.compile(r"\b([A-Z]{2}[\s\-]?\d{2}[\s\-]?[A-Z]{1,3}[\s\-]?\d{1,4})\b")
_CIN     = re.compile(r"\b[A-Z]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b")


def _find_registration(full_text: str, kv: dict[str, str]) -> str:
    val = _kv_lookup(kv,
        "vehicleregistrationno", "vehicleregno", "registrationno",
        "vehicleno", "regnno", "regnumber", "vehicleregistrationnumber",
        "registrationmark",
    )
    if val:
        val = _CIN.sub("", val).strip()
        m = _VEH_REG.search(val)
        if m:
            return _clean(m.group(1))

    for line in full_text.splitlines():
        if _CIN.search(line):
            continue
        m = _VEH_REG.search(line)
        if m:
            return _clean(m.group(1))
    return "N/A"


def _find_expiry(full_text: str, kv: dict[str, str], lines: list[str]) -> str:
    # Policy end dates searched before quote-validity dates to avoid returning
    # the quote's validity window instead of the actual policy end date.
    val = _kv_lookup(kv,
        "policyexpirydate", "expirydate", "policyexpiringdate",
        "policyenddate", "dateofexpiry", "policyto",
        "equotevalidupto", "renewaldate",
        "quotevalidtill", "validupto", "validtill", "validuntil",
    )
    if val:
        d = _parse_date_str(val)
        if d:
            return d

    for line in lines:
        if re.search(r"policy\s+period|period\s+of\s+insurance|validity|expires", line, re.I):
            d = _parse_date_str(line)
            if d:
                return d
            # fall through to window search below

    for i, line in enumerate(lines):
        if re.search(r"expir|valid\s+(?:till|upto|until)|end\s+date|policy\s+end", line, re.I):
            snippet = " ".join(lines[i:i+3])
            d = _parse_date_str(snippet)
            if d:
                return d
    return "N/A"


def _find_amount(
    lines: list[str],
    table_rows: list[list[str]],
    primary_patterns: list[str],
    fallback_patterns: list[str],
    min_value: float = 100.0,
    search_window: int = 4,
) -> float | None:
    NUMBER_RE = re.compile(r"[\d,]+(?:\.\d{1,2})?")
    CURRENCY  = re.compile(r"(?:rs\.?|inr|₹)\s*", re.I)

    def _nums(text: str) -> list[float]:
        text = CURRENCY.sub("", text)
        out = []
        for n in NUMBER_RE.findall(text):
            v = _parse_number(n)
            if v and v >= min_value:
                out.append(v)
        return out

    for pat_list in [primary_patterns, fallback_patterns]:
        for pat in pat_list:
            compiled = re.compile(pat, re.I)
            for i, line in enumerate(lines):
                if compiled.search(line):
                    # wider window for multi-column table layouts
                    snippet = " ".join(lines[i:i+search_window])
                    nums = _nums(snippet)
                    if nums:
                        return nums[0]
            for row in table_rows:
                for ci, cell in enumerate(row):
                    if compiled.search(cell):
                        rest = " ".join(row[ci+1:])
                        nums = _nums(rest)
                        if nums:
                            return nums[0]
    return None


# ─── add-on section isolation ─────────────────────────────────────────────────

_SECTION_START = re.compile(
    r"(?:"
    # Standard headers
    r"add[\s\-]*on[s]?\s*(?:opted|covered|selected|availed|details?|list|schedule|covers?|premium)?|"
    r"optional\s+(?:covers?|benefits?)|"
    r"endorsement\s+(?:details?|schedule)|"
    r"selected\s+add[\s\-]*on[s]?|"
    r"additional\s+(?:covers?|benefits?)|"
    # TATA AIG: "Section - I ADD ON COVERS(C)"
    r"section\s*[-–]\s*i\s+add|"
    r"add\s*on\s*covers?\s*\(?[a-z]\)?|"
    # ICICI: "Own Damage- Add-on Covers"  (soft hyphens already removed)
    r"own\s+damage\s*.*\s*add\s*on|"
    r"third\s+party\s*.*\s*add\s*on|"
    # Bajaj: "Add-on Description"
    r"add[\s\-]*on\s+description|"
    # Zuno: "Add ons" as section header
    r"^add\s+ons?\s*$"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

_SECTION_END = re.compile(
    r"(?:terms\s+and\s+conditions|signature|declaration|claim\s+procedure|"
    r"policy\s+wording|general\s+exclusion|important\s+notice|"
    r"important\s+note|note\s*:|disclaimer)",
    re.IGNORECASE,
)


def _isolate_addon_section(full_text: str) -> str:
    m = _SECTION_START.search(full_text)
    if not m:
        return ""
    end_m = _SECTION_END.search(full_text, m.end())
    end = end_m.start() if end_m else min(m.start() + 5000, len(full_text))
    return full_text[m.start():end]


# ─── Bajaj plan-name → add-on mapping ────────────────────────────────────────
# Bajaj bundles add-ons into named packages. When a Plan Name is present we can
# infer the exact add-on set without relying on keyword scanning (which would
# fire on the full package catalogue printed in every Bajaj quote).
# List is sorted longest-first so "daw+" is always tested before "daw".

_BAJAJ_PLAN_ADDONS: list[tuple[str, list[str]]] = sorted([
    ("eco assure repair protection", [
        "Road Side Assistance", "Engine Protection", "EV Battery Protection",
        "Consumables Cover", "Key Replacement", "Personal Belongings Cover",
    ]),
    ("drive assure drivesmart prestige", [
        "Road Side Assistance", "Nil Depreciation", "Engine Protection",
        "Daily Allowance", "Passenger PA Cover",
        "Key Replacement", "Personal Belongings Cover", "Consumables Cover",
    ]),
    ("drive assure drivesmart premium", [
        "Road Side Assistance", "Nil Depreciation", "Engine Protection",
        "Passenger PA Cover", "Key Replacement", "Personal Belongings Cover",
    ]),
    ("drive assure drivesmart classic", [
        "Road Side Assistance", "Passenger PA Cover",
        "Key Replacement", "Personal Belongings Cover",
    ]),
    ("drive assure economy plus", [
        "Road Side Assistance", "Nil Depreciation", "Engine Protection",
        "Key Replacement", "Personal Belongings Cover",
    ]),
    ("drive assure welcome plus", [
        "Road Side Assistance", "Nil Depreciation",
        "Key Replacement", "Personal Belongings Cover",
    ]),
    ("drive assure prime plus", [
        "Road Side Assistance", "Key Replacement", "Personal Belongings Cover",
    ]),
    ("drive assure economy", [
        "Road Side Assistance", "Nil Depreciation", "Engine Protection",
    ]),
    ("drive assure welcome", [
        "Road Side Assistance", "Nil Depreciation",
    ]),
    ("dae+", [
        "Road Side Assistance", "Nil Depreciation", "Engine Protection",
        "Key Replacement", "Personal Belongings Cover",
    ]),
    ("daw+", [
        "Road Side Assistance", "Nil Depreciation",
        "Key Replacement", "Personal Belongings Cover",
    ]),
    ("dae", ["Road Side Assistance", "Nil Depreciation", "Engine Protection"]),
    ("daw", ["Road Side Assistance", "Nil Depreciation"]),
], key=lambda x: len(x[0]), reverse=True)

# Top-up cover text fragment → canonical add-on key
_BAJAJ_TOPUP_MAP: list[tuple[str, str]] = [
    ("consumable",          "Consumables Cover"),
    ("vehicle replacement", "Car Replacement"),
    ("conveyance",          "Daily Allowance"),
    ("accident shield",     "Passenger PA Cover"),
    ("depreciation",        "Nil Depreciation"),
    ("engine",              "Engine Protection"),
    ("tyre",                "Tyre Protection"),
    ("ncb",                 "NCB Protection"),
    ("return to invoice",   "Return To Invoice"),
    ("rpi",                 "Return To Invoice"),
    ("key",                 "Key Replacement"),
]

_BAJAJ_TOPUP_LINE = re.compile(
    r"top[\s\-]*up\s+cover\s*\d*\s*[:.]?\s*(.+)", re.IGNORECASE
)


def _apply_bajaj_plan_addons(plan_name: str, full_text: str, addons: dict[str, str]) -> None:
    """Set add-ons to Yes based on Bajaj plan name + any selected top-up covers."""
    plan_lower = plan_name.lower().strip()

    for key, addon_list in _BAJAJ_PLAN_ADDONS:
        if key in plan_lower:
            for addon in addon_list:
                addons[addon] = "Yes"
            break

    # Parse individually numbered top-up cover lines
    for line in full_text.splitlines():
        m = _BAJAJ_TOPUP_LINE.match(line.strip())
        if not m:
            continue
        cover_text = m.group(1).lower()
        for fragment, addon in _BAJAJ_TOPUP_MAP:
            if fragment in cover_text:
                addons[addon] = "Yes"
                break


# ─── add-on detection ─────────────────────────────────────────────────────────

def _detect_addons(
    full_text: str,
    lines: list[str],
    table_rows: list[list[str]],
) -> tuple[dict[str, str], list[str]]:

    results: dict[str, str] = {name: "No" for name in ADDON_TERMS}
    extras:  list[str] = []

    addon_section = _isolate_addon_section(full_text)
    search_text   = addon_section if addon_section else full_text

    def _negated(m: re.Match, text: str) -> bool:
        # 50-char window avoids false negation from unrelated "Not Applicable"
        # text that appears in adjacent columns/fields (e.g. Hypothecation details)
        ctx = text[max(0, m.start()-40): min(len(text), m.end()+50)]
        return bool(_NEGATION.search(ctx))

    # ── Pass 1: keyword presence in add-on section ────────────────────────────
    for name, pattern in _ADDON_COMPILED.items():
        # PA and Legal Liability appear in Liability section → always search full text
        scope = full_text if name in _FULLTEXT_ADDONS else search_text
        m = pattern.search(scope)
        if m and not _negated(m, scope):
            results[name] = "Yes"

    # ── Pass 2: table rows with explicit Yes/No ───────────────────────────────
    all_rows = list(table_rows)
    for line in lines:
        if "|" in line:
            all_rows.append([c.strip() for c in line.split("|") if c.strip()])

    for row in all_rows:
        row_joined = " ".join(row)
        for name, pattern in _ADDON_COMPILED.items():
            if pattern.search(row_joined):
                for ci, cell in enumerate(row):
                    if pattern.search(cell):
                        rest = " ".join(row[ci+1:])
                        if _YES_RE.search(rest):
                            results[name] = "Yes"
                        elif _NO_RE.search(rest):
                            results[name] = "No"
                        break

    # ── Pass 3: line-by-line explicit Yes/No ──────────────────────────────────
    for line in lines:
        for name, pattern in _ADDON_COMPILED.items():
            m = pattern.search(line)
            if m:
                after = line[m.end():]
                if _YES_RE.search(after):
                    results[name] = "Yes"
                elif _NO_RE.search(after):
                    results[name] = "No"

    # ── Pass 4: unknown add-on candidates ────────────────────────────────────
    section_lines = (addon_section or full_text).splitlines()
    for line in section_lines:
        line_s = line.strip()
        if not line_s or len(line_s) < 4 or len(line_s) > 80:
            continue
        matched_known = any(p.search(line_s) for p in _ADDON_COMPILED.values())
        if matched_known:
            continue
        if _ADDON_SIGNAL.search(line_s):
            clean = re.sub(r"^[\s\d\.\-\*\•]+", "", line_s).strip()
            if clean and clean not in extras:
                extras.append(clean)

    return results, extras


# ─── public entry point ───────────────────────────────────────────────────────

def extract_policy_data(path: str) -> dict:
    full_text_py, lines_py = _pymupdf_lines(path)
    plumber = _plumber_text(path)

    # Full text: use whichever is richer (pdfplumber captures layout text better)
    full_text = plumber if len(plumber) > len(full_text_py) else full_text_py

    # Lines: ALWAYS use PyMuPDF — pdfplumber layout mode merges table columns
    # onto one line, causing false Yes/No matches and wrong KV field values.
    lines = lines_py if lines_py else [l for l in plumber.splitlines() if l.strip()]

    # ── OCR fallback for image-based PDFs ────────────────────────────────────
    doc_tmp = fitz.open(path)
    num_pages = doc_tmp.page_count
    doc_tmp.close()

    if _text_is_sparse(full_text, lines, num_pages):
        ocr_text, ocr_lines = _ocr_pdf(path)
        if ocr_text.strip():
            full_text = ocr_text
            lines     = ocr_lines

    if not full_text.strip():
        raise ValueError("No text extracted — PDF may be scanned/image-only and Tesseract is not installed.")

    table_rows = _plumber_tables(path)
    kv = _build_kv(lines)
    for row in table_rows:
        # Process every adjacent pair of columns so 4-column layouts
        # (col0=key, col1=val, col2=key, col3=val) are fully captured.
        for j in range(0, len(row) - 1, 2):
            label = _norm(row[j].rstrip(":"))
            value = _clean(row[j + 1])
            if label and value:
                kv.setdefault(label, value)

    # ── header fields ─────────────────────────────────────────────────────────
    vehicle_model = _kv_lookup(kv,
        "manufacturemodel",                              # ICICI: "Manufacture Model"
        "makemodel", "makemodelvariant", "vehiclemodel", "makeofvehicle",
        "vehiclemakemodel", "modeldescription", "vehicledescription",
        "carmake", "carmodel", "make", "model", "vehicle",
    ) or "N/A"
    vehicle_model = re.sub(r"^[^\w]+", "", vehicle_model)

    insured_name = _kv_lookup(kv,
        "clientname", "nameofinsured", "insuredname",
        "policyholder", "proposer", "proposername",
        "nameofpolicyholder", "customersname", "customername",
        "nameoftheinsured", "namedinsured", "policyownername",
        "dearmr", "deardr", "dearms",
        # ICICI / Bajaj / Zuno field variants
        "nameofproposer", "proposedinsured", "applicantname",
        "policyholderName", "insuredfirstname", "customersfullname",
    ) or "N/A"

    if insured_name and insured_name != "N/A":
        # Strip trailing noise: dates, known label keywords after the name
        insured_name = re.sub(
            r"\s+\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}.*", "", insured_name
        )
        insured_name = re.sub(
            r"\s+(?:quote|issuance|policy|date|valid|expires|period|number|no\.?).*",
            "", insured_name, flags=re.I,
        )
        # If the "name" value is actually the insurer name, discard it
        if _detect_insurer(insured_name) != "N/A":
            insured_name = "N/A"
        # Trim to 60 chars at word boundary
        elif len(insured_name) > 60:
            insured_name = insured_name[:60].rsplit(" ", 1)[0]

    # Regex fallback: "Dear Mr./Mrs. Name," or similar greeting in document
    if insured_name == "N/A":
        m_name = re.search(
            r"\bDear\s+(?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3})",
            full_text,
        )
        if m_name:
            insured_name = _clean(m_name.group(1))

    registration_number = _find_registration(full_text, kv)
    expiry_date         = _find_expiry(full_text, kv, lines)
    insurer             = _detect_insurer(full_text)
    plan_coverage       = _detect_plan_coverage(full_text)

    # ── IDV — require large value (car IDVs are typically > 1 lakh) ──────────
    # Wide window (10 lines) handles multi-column tables where IDV header and
    # value land on separate lines (TATA AIG layout).
    idv = _find_amount(lines, table_rows,
        primary_patterns=[
            r"total\s+idv\b",
            r"insured\s+declared\s+value\s*\(?idv\)?",
            r"\bidv\s+of\s+vehicle\b",
            r"\bidv\b",
        ],
        fallback_patterns=[r"sum\s+insured\b", r"declared\s+value\b"],
        min_value=50000,
        search_window=10,   # look further ahead for table-format PDFs
    )

    # ── Premium — prefer the RSA-inclusive final total (Tata AIG pattern) ───────
    # Tata AIG PDFs show "TOTAL PREMIUM ₹X" then "Final Premium With Road Side
    # Assistance ₹Y". We want Y (the actual amount paid), so check the most
    # specific/final phrase first before falling back to bare "total premium".
    premium = _find_amount(lines, table_rows,
        primary_patterns=[
            r"final\s+premium\s+with\s+road\s+side\s+assistance",  # Tata AIG
            r"total\s+premium\s+payable",
            r"final\s+premium\b",
            r"amount\s+payable\b",
            r"total\s+premium\b",
        ],
        fallback_patterns=[
            r"net\s+premium\s+payable",
            r"total\s+amount\s+(?:due|payable)",
            r"(?:gross|net)\s+premium(?!\s+payable)",
        ],
        min_value=1000,
    )

    addons, extras = _detect_addons(full_text, lines, table_rows)

    # ── Bajaj plan-based add-on resolution ───────────────────────────────────
    # Bajaj quotes print every available package in the add-on section, so the
    # keyword scanner marks everything as Yes. We override that completely:
    # reset to No, then re-derive from Plan Name + top-up cover lines only.
    if insurer == "Bajaj Allianz":
        plan_name = _kv_lookup(kv, "planname", "plan") or ""
        plan_name_clean = re.sub(r"[^a-z0-9\s]", "", plan_name.lower()).strip()
        for k in addons:
            addons[k] = "No"
        if plan_name_clean:
            _apply_bajaj_plan_addons(plan_name, full_text, addons)

    return {
        "product":               "Motor Insurance",
        "vehicle_model":         _clean(vehicle_model),
        "policy_expiring_date":  _clean(expiry_date),
        "insured_name":          _clean(insured_name),
        "registration_number":   _clean(registration_number),
        "insurer":               insurer,
        "policy_type":           "Motor Insurance",
        "plan_coverage":         plan_coverage,
        "idv":                   idv,
        "total_premium":         premium,
        "addons":                addons,
        "extras":                extras,
    }