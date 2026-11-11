# SOP Copilot

A small question-answering tool for shop-floor supervisors. It searches the supplied plant SOP and manual PDFs and answers only from the retrieved document evidence, showing the document, revision, page, section and scope behind the answer. If the supplied documents do not support an answer, it says so instead of guessing.

Built for the BiztelAI Junior Software Engineer (Full Stack / AI) assignment.

## Problem

A manufacturing plant has hundreds of SOPs, manuals and procedures as PDFs. Supervisors need quick, trustworthy answers during a shift, often from a phone or tablet.

The main risks this project addresses are:

- answers that sound correct but are not supported by the documents;
- answers taken from an outdated document revision;
- important safety steps being lost in a short summary;
- questions that the supplied documents simply cannot answer.

The user reasoning and journey are documented in `THINKING.md`.

## Features

- Answers grounded in retrieved PDF text.
- Source cards showing document number, title, revision, effective date, page, section and scope.
- Revision-aware retrieval: only the newest supplied revision is used as current evidence.
- Older revisions can be identified and reported without being used as current evidence.
- Not-found gate before the LLM call.
- Safety handling for lockout/isolation and stored-energy procedures.
- Generated-answer checks requiring evidence citations.
- Numeric output checks to reduce unsupported values.
- Evidence-only fallback when an LLM is unavailable.
- Provider-agnostic LLM integration.
- Mobile-friendly UI.
- Accessible from another device on the same Wi-Fi.
- FastAPI backend with a simple HTML/CSS/JavaScript frontend.

## Architecture

```text
Supplied PDFs
     |
     v
  ingest.py
     |
     v
Document chunks + metadata
     |
     v
retrieval.py
TF-IDF retrieval over current revisions
     |
     +--> vague question ----> needs detail
     |
     +--> insufficient evidence ----> not found
     |
     v
   copilot.py
     |
     v
 prompt.py ----> optional LLM ----> llm.py
     |
     v
Citation / number / safety checks
     |
     v
FastAPI JSON response
     |
     v
Mobile-friendly web UI
```

## Project structure

| File / folder | Responsibility |
|---|---|
| `app/ingest.py` | Extracts PDF text into chunks with document metadata |
| `app/retrieval.py` | TF-IDF retrieval, tokenisation, revision handling, gates and ranking |
| `app/copilot.py` | Main copilot pipeline and output checks |
| `app/prompt.py` | Evidence-based LLM prompt |
| `app/llm.py` | LLM provider integration |
| `app/main.py` | FastAPI routes |
| `app/schemas.py` | Request/response validation |
| `static/` | HTML, CSS and JavaScript UI |
| `data/` | Supplied PDF documents |
| `tests/` | Automated test suite |
| `scripts/` | Retrieval sweep and question-running utilities |
| `THINKING.md` | User understanding, journey, AI critique and reflection |

## Technology stack

- Python
- FastAPI
- pypdf
- scikit-learn TF-IDF retrieval
- HTML / CSS / JavaScript
- pytest
- Optional LLM provider through an OpenAI-compatible interface
- Gemini tested as the real LLM provider

## Setup

### Requirements

Python 3.10 or newer.

The project was developed and tested in the submitted environment using Python 3.14.4.

### Windows PowerShell

```powershell
cd sop-copilot
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

Alternatively, the virtual-environment Python executable can be used directly without activation:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Configuration

The `.env` file is used for optional LLM configuration.

Example:

```env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_api_key_here
LLM_MODEL=your_model_name
LLM_BASE_URL=your_provider_endpoint
```

For evidence-only operation:

```env
LLM_PROVIDER=none
LLM_API_KEY=
LLM_MODEL=
LLM_BASE_URL=
```

For the real integration test, Gemini was configured through its OpenAI-compatible endpoint.

**Never commit `.env` or an API key to GitHub.**

## Run locally

Start the server:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

On Windows, when using the project virtual environment directly:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open:

```text
http://localhost:8000
```

The PDFs are loaded when the application starts.

Health endpoint:

```text
http://localhost:8000/api/health
```

FastAPI documentation:

```text
http://localhost:8000/docs
```

## Phone / same-Wi-Fi access

The application was tested successfully from a real phone on the same Wi-Fi network as the development laptop.

1. Start the server using `--host 0.0.0.0`.
2. Find the laptop's IPv4 address using:

```powershell
ipconfig
```

3. Find the IPv4 address under the Wi-Fi adapter.
4. On the phone, connected to the same Wi-Fi, open:

```text
http://<LAPTOP-IP>:8000
```

Example used during testing:

```text
http://10.55.181.172:8000
```

The phone successfully loaded the application and received a generated, cited answer for the coolant question.

If Windows Firewall asks for permission, allow Python on the Private network.

## How retrieval works

### 1. PDF ingestion

The supplied PDFs are converted into document chunks containing metadata such as:

- document number;
- title;
- revision;
- effective date;
- page;
- section;
- scope;
- safety flag;
- current/superseded status.

### 2. TF-IDF retrieval

Questions are matched against the current document chunks using TF-IDF similarity.

The tokenizer preserves important plant codes such as:

```text
AL-104
BH-220
```

It also normalises common variations such as:

```text
AL104
AL 104
```

to the same code.

A small synonym table handles tested wording variations such as:

```text
mix / mixture / percentage / percent / ratio
```

for the document term `concentration`.

### 3. Evidence gate

The system checks whether there is enough document evidence before calling the LLM.

If the evidence is insufficient, the system returns a not-found response instead of asking the LLM to guess.

### 4. LLM answer generation

When an LLM is configured, the top retrieved evidence blocks are provided to the model.

The model must:

- answer only from the supplied evidence;
- use evidence citation markers;
- avoid unsupported facts;
- return `NOT_FOUND` when the evidence does not support an answer.

### 5. Output validation

Generated answers are checked before being displayed.

The application verifies that:

- citations refer to supplied evidence blocks;
- numerical values in the answer occur in the supporting evidence;
- malformed or unsupported generated output is rejected.

If validation fails, the application falls back to the retrieved evidence.

## Revision handling

The supplied inspection procedure contains multiple revisions.

The application:

- stores revisions separately;
- treats the highest revision supplied for a document number as the newest supplied revision;
- does not merge old and new revisions;
- uses only current chunks as answer evidence;
- can report when an older revision also matched;
- uses the document's own supersession information where available.

The application deliberately says **"newest supplied"** rather than claiming to know the absolute latest QMS revision.

This is important because the controlled documents state that printed copies are uncontrolled and that the QMS should be consulted for the latest version.

## Safety handling

Safety-related evidence, including lockout/isolation procedures, is specially flagged.

For safety questions, the UI:

- displays a safety caution;
- expands the relevant safety evidence;
- provides related safety passages when applicable;
- prevents the LLM from inventing additional safety instructions.

The copilot is intended to help locate and understand the supplied SOP. It does not replace the controlled safety procedure.

## Not-found behaviour

For questions that are not supported by the supplied documents, the application returns a message such as:

> I couldn't find enough supporting information for this question in the provided documents. Please check the QMS or the controlled manual, or contact the responsible team.

The system does not claim that the requested information does not exist everywhere. It only states that sufficient supporting information was not found in the supplied documents.

Examples that correctly return `not_found` include:

- maximum spindle speed of the TX-200;
- canteen menu;
- weather;
- TX-300 information;
- hydraulic pump supplier;
- coolant price.

## Real LLM integration test

The application was tested with a real Gemini model through the OpenAI-compatible Gemini endpoint.

Example question:

```text
What is the recommended coolant concentration for the TX-200 CNC turning centre?
```

The application generated an evidence-cited answer identifying:

```text
6 - 8 %
```

and attached the relevant source evidence.

A LOTO question was also tested successfully. The generated response correctly explained that an authorised person removes their own lock and that the documented absent-owner procedure requires the Production Manager and Safety Officer to authorise the removal.

The application also correctly rejected the unsupported question:

```text
What is the maximum spindle speed of the TX-200?
```

with a `not_found` response.

## Sample questions

### 1. Coolant concentration

**Question**

```text
What is the recommended coolant concentration for the TX-200 CNC turning centre?
```

**Expected evidence**

```text
Coolant concentration 6 - 8 %
```

The real Gemini test produced a cited answer based on the TX-200 manual.

### 2. AL-104 alarm

**Question**

```text
The machine is showing alarm AL-104. What does it mean and what should the operator do?
```

The retrieved evidence identifies the alarm as low way-lube oil level and provides the documented operator action.

### 3. LOTO lock removal

**Question**

```text
Who is allowed to remove a lockout lock from a machine?
```

The real LLM test returned a cited answer based on the LOTO procedure, including the documented absent-owner process.

### 4. BH-220 tolerance

**Question**

```text
What is the outer diameter tolerance for the BH-220 bearing housing?
```

The current inspection revision provides:

```text
90.000 +/- 0.050 mm
```

### 5. Spindle runout

**Question**

```text
How often should spindle runout be checked, and who does it?
```

The retrieved maintenance procedure identifies the monthly check and the responsible maintenance role.

## Original questions

The project also includes five original questions designed before the final testing:

| # | Question | Result |
|---|---|---|
| A1 | What is the chuck mounting bolt torque? | Answerable from the maintenance manual |
| A2 | How quickly must SQE be notified? | Answerable from the inspection procedure |
| A3 | What happens if the required MTC is missing? | Answerable from the inspection procedure |
| A4 | For a 200-piece lot, how many samples are required? | Revision-aware; Rev 04 gives 13 samples |
| A5 | What is the maximum spindle speed of the TX-200? | Not found |

For A4, the system uses the current supplied Rev 04 sampling plan rather than the superseded Rev 03 rule.

## Testing

Run the full automated test suite:

```bash
python -m pytest -q
```

Retrieval threshold sweep:

```bash
python scripts/sweep.py
```

Run the sample/original/extra question groups:

```bash
python scripts/run_questions.py --group sample --group original --group extra
```

### Final test result

Last full test run:

```text
186 passed
0 failed
0 xfail
0 xpass
```

Additional checks included:

- PDF ingestion and metadata;
- revision marking;
- retrieval and ranking;
- `AL104` vs `AL-104`;
- answerable and unanswerable question gates;
- coolant wording variations;
- hydraulic-pump unknown-word cases;
- revision notes;
- prevention of superseded evidence reaching the LLM;
- citation accuracy;
- safety flags;
- successful and failed LLM responses;
- malformed LLM output;
- request validation;
- API error handling.

The live server was also tested on `0.0.0.0:8000`, including the health endpoint, web page and API through the laptop's LAN address.

## API

### `POST /api/ask`

Request:

```json
{
  "question": "What is the recommended coolant concentration for the TX-200?"
}
```

The response includes fields such as:

```text
status
answer
message
sources[]
revision_note
safety_note
llm_used
llm_error
highlights
```

### `GET /api/health`

Reports application health, loaded documents/revisions and LLM configuration status.

### `GET /`

Returns the web application.

### FastAPI documentation

```text
/docs
```

## Security

- API keys belong only in `.env` or environment variables.
- `.env` must never be committed.
- Generated `results/` output is git-ignored.
- `.venv/` and Python cache files are git-ignored.
- The application uses plain HTTP and has no authentication, so it should only be run on a trusted local network.
- If a hosted LLM is used, retrieved SOP passages and the question are sent to that provider. Sensitive documents should not be sent to an external provider unless the organisation permits it.
- The browser uses `textContent` when rendering returned text to avoid HTML injection from document or model content.

## Known limitations

- Retrieval currently uses TF-IDF rather than embeddings or a neural reranker.
- Synonyms are maintained through a small hand-written list, so unsupported wording can still produce a false not-found result.
- The retrieval thresholds were tuned against a small labelled question set, so the reported test results are a sanity check rather than a production accuracy measurement.
- Generic machine wording can sometimes rank a purpose/introduction section above the exact table containing the answer.
- Tables are represented as chunks rather than individual rows.
- "Current" means the highest revision supplied with the assignment; the application does not have access to the plant's live QMS.
- Machine applicability is currently based on textual matching rather than a structured machine-to-scope mapping.
- Scanned PDFs would require OCR; the supplied PDFs are text PDFs.
- No authentication or HTTPS is implemented.
- English is currently supported.
- There is no document upload/re-ingestion workflow.

## Future improvements

Possible production improvements include:

- semantic embeddings and/or a reranker for larger document collections;
- better table and row-level retrieval;
- structured machine applicability matching;
- a controlled document source connected to the plant QMS;
- document upload and re-ingestion;
- clarification dialogue for ambiguous questions;
- audit logging of questions and answers;
- user feedback such as thumbs-up/down;
- local LLM deployment for environments where documents cannot leave the premises;
- Docker-based deployment;
- multilingual support such as Tamil and Hindi.

## AI usage

Claude was used during development to help plan, implement, test and critique parts of the project.

The user journey was written before the AI critique. The actual AI critique and reflection are documented in `THINKING.md`.

AI assistance was also used for implementation and debugging, while the supplied PDF evidence was checked against the source documents for the project tests.

The project does not treat an LLM as the source of truth: document retrieval and validation happen around the LLM, and unsupported answers are rejected or returned as not found.

## Assignment deliverables

The repository contains:

- application source code;
- supplied PDF documents;
- tests;
- scripts;
- `README.md`;
- `THINKING.md`;
- `.env.example`.

Before pushing to GitHub, verify that the repository does **not** contain:

```text
.env
API keys
.venv/
__pycache__/
.pytest_cache/
generated private results
```
