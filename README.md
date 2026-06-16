# Motor Insurance Policy Comparison Tool

A local web application that extracts data from up to 5 motor insurance policy PDFs and generates a styled side-by-side comparison Excel sheet — **no API keys, no internet connection required**.

---

## Features

- Upload up to 5 motor insurance PDFs (quotes or renewal notices)
- Automatically detects insurer, vehicle details, IDV, premium, and 15+ add-ons
- Generates a formatted Excel comparison chart matching industry-standard templates
- Supports major Indian insurers: TATA AIG, ICICI Lombard, Bajaj Allianz, Zuno, HDFC ERGO, and more
- Debug mode to inspect raw extracted text and KV pairs for any PDF
- Drag-and-drop file upload UI

---

## Supported Add-Ons

| Add-On | Add-On |
|--------|--------|
| Nil Depreciation | NCB Protection |
| Engine Protection | IMT 23 |
| Consumables Cover | IMT 25 (CNG/LPG) |
| Road Side Assistance | Passenger PA Cover |
| Return To Invoice | Tyre Protection |
| Emergency Transport & Hotel | Key Replacement |
| Personal Belongings Cover | Emergency Medical Expenses |
| Legal Liability to Paid Driver | Personal Accident (Owner Driver) |

---

## Requirements

- Python 3.10+
- pip

### Python Dependencies

```
flask>=3.0
pdfplumber>=0.11
pymupdf>=1.24
openpyxl>=3.1
```

---

## Installation

```bash
# Clone or download the project
cd acha_agent

# Install dependencies
pip install -r requirements.txt
```

---

## Usage

### Start the server

```bash
python app.py
```

Then open your browser at: **http://localhost:5000**

### Using the web UI

1. Drag and drop up to 5 policy PDFs onto the upload area, or click to browse
2. Click **Analyze & Generate Comparison**
3. Download the generated Excel file when processing is complete

### Debug a single PDF

Click **Debug PDF** after selecting a file to inspect:
- Raw extracted text (PyMuPDF and pdfplumber)
- Detected KV field pairs
- Table data
- Full parsed result

This is useful for diagnosing why a specific field or add-on wasn't detected correctly.

---

## How It Works

### Text Extraction

Uses two extraction engines and picks the richer result:

- **PyMuPDF (`fitz`)** — word-position-based line reconstruction; preserves column separation (used for all per-line parsing)
- **pdfplumber** — layout-mode text extraction; captures more text in complex layouts (used for keyword search)

### Field Detection

- **Insurer** — matched against a catalogue of 20 Indian insurers using regex patterns
- **IDV** — searches for "Total IDV", "Insured Declared Value", minimum threshold of ₹50,000 to avoid false matches
- **Premium** — targets "Total Premium Payable" / "Final Premium" (GST-inclusive totals)
- **Registration, Expiry Date** — pattern matched from KV pairs and line context
- **Insured Name** — KV lookup with 15+ field label variants; falls back to "Dear Mr./Mrs." salutation; insurer names are automatically filtered out

### Add-On Detection (3-pass system)

1. **Pass 1** — keyword presence in the isolated add-on section using a domain-expert canonical term list (200+ terms across 15 core add-ons)
2. **Pass 2** — table rows with explicit Yes/No cells
3. **Pass 3** — line-by-line Yes/No scanning

Negation markers (`not opted`, `not covered`, `excluded`, `N/A`) suppress false positives with a 50-character context window.

### Excel Output

Generated with `openpyxl`, styled to match the reference template:
- Dark blue header (`#002060`)
- Green add-on labels (`#3A7D22`)
- Yes/No values color-coded green/red
- Dynamic columns for each insurer
- Extended add-on rows appear only when detected in at least one policy

---

## Known Limitations

- **Scanned / image-only PDFs** are not supported (text extraction requires a text layer)
- **Bundled add-ons** (e.g., ICICI Lombard's RSA and Tyre bundled inside "Smart Saver Plus") cannot be detected because they are not listed as individual line items in the PDF
- **Name extraction** may return N/A for PDFs that don't include a clearly labeled insured/customer name field

---

## Project Structure

```
acha_agent/
├── app.py              # Flask routes and Excel generation
├── extractor.py        # PDF extraction and add-on detection logic
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html      # Web UI
├── uploads/            # Temporary PDF storage (auto-cleaned)
└── outputs/            # Generated Excel files
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Upload UI |
| `POST` | `/analyze` | Process PDFs, returns download link |
| `POST` | `/debug` | Inspect raw extraction data for one PDF |
| `GET` | `/download/<filename>` | Download generated Excel |
