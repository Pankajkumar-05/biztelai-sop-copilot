# THINKING

## 1. Understand the user

The primary user is a shop-floor supervisor working in a manufacturing
plant. The goal is to get a quick, trustworthy answer from the supplied
SOPs and manuals without manually searching multiple PDFs.

Likely questions include: - What does alarm AL-104 mean and what should
the operator do? - What coolant concentration is recommended for the
TX-200? - Who can remove a lockout lock? - What is the tolerance for the
BH-220 outer diameter? - How many samples are required for a particular
lot size?

Likely frustrations include long PDFs, information spread across
documents, conflicting revisions, safety steps being lost in short
answers, unsupported questions, and the need for a simple phone
interface.

I did not interview a real supervisor. Therefore gloves, noise, Wi-Fi
reliability, device ownership, and exact role responsibilities are
assumptions that should be validated with real users.

My product need is a source-grounded copilot that gives a concise
answer, shows the supporting document/revision information, and clearly
says when it cannot find enough supporting information.

## 2. User journey

### Step 1: Incident or question

During an active shift, a supervisor encounters a machine alarm,
maintenance question, inspection requirement, or safety question.

### Step 2: Ask the copilot

The supervisor opens the mobile browser and asks a natural-language
question such as:

> "What does alarm AL-104 mean and what should the operator do?"

The expected answer should come from the supplied plant documents rather
than general AI knowledge.

### Step 3: Retrieve and answer

The system searches the supplied SOPs and manuals and considers
document, revision, page, section, and machine scope. The answer should
be concise while the supporting evidence remains visible.

### Step 4: Verify and act

The supervisor can verify the supporting evidence, especially for
safety-related questions. The copilot assists with finding information
but does not replace approved procedures or safety responsibilities.

### Step 5: Handle revisions

The supplied Incoming Material Inspection procedure has Rev 03 and Rev
04 with different sampling requirements. The prototype treats the
highest supplied revision as the newest supplied revision and does not
claim it is necessarily the latest QMS revision.

### Step 6: Complete the task

The desired experience is: ask a question, receive a concise answer, see
the source, know when information is unavailable, and continue the task.

### Failure modes

-   Unsupported question: return a controlled not-found response instead
    of guessing.
-   Vague question: ask for more detail.
-   Conflicting revisions: handle revisions in application logic.
-   Safety-critical question: show supporting safety evidence and
    caution.
-   LLM/network failure: still show retrieved passages.
-   Difficult PDFs: the supplied PDFs are text PDFs; general OCR is a
    future concern.

## 3. AI challenge

After writing the journey, I asked Claude to act as a skeptical
shop-floor supervisor, product manager, and AI/LLM engineer.

### Skeptical supervisor

> "Most touchscreens don't register thick gloves, so 'large, simple
> controls' doesn't solve it."

This made me reconsider the unverified glove assumption.

> "The journey never says the copilot must tell me which machine or
> document the answer applies to."

I agreed that machine and document scope are important.

> ""Not found" is a dead end. What do I do next: call maintenance, check
> the QMS, ask a colleague?"

This changed the not-found design to include a useful next step.

### Skeptical product manager

> ""Latest" is not the same as "applicable.""

This is important because a newer supplied revision does not prove which
revision applied to a historical lot.

The critique also questioned whether the supervisor should always be the
primary user because the documents contain different roles. I agree this
should be validated with the customer.

### Skeptical AI/LLM engineer

> ""The system should not invent an answer" is a wish, not a design."

I agreed. I therefore implemented retrieval gates, revision handling,
citation checks, numerical evidence checks, and fallback evidence when
the LLM fails.

The critique also distinguished vague questions from genuinely
unsupported questions, which influenced the application's separate
handling.

### What I agreed with

I agreed that assumptions should be separated from facts,
machine/document scope should be visible, "latest" should not be
confused with "applicable", not-found should provide a next step, safety
should be supported by application behaviour, evidence should remain
available when the LLM fails, and the LLM provider should be
replaceable.

### What I would not blindly accept

I would not automatically treat every critique point as a requirement.
For example, voice input may not be appropriate in a noisy plant and
should be validated with users. I also think a supervisor is a
reasonable primary user for this prototype because the assignment
specifically describes supervisors as the target.

### Changes caused by the critique

-   Source cards show document, revision, page, section and scope.
-   Safety evidence is always visible and receives special handling.
-   Not-found responses provide a next step.
-   The application says "newest supplied revision".
-   AL104/AL-104 formatting is normalised.
-   LLM failure falls back to retrieved evidence.
-   Voice/OCR/offline remain future improvements.

## 4. The improvement I added, and why I chose it

### Revision-aware retrieval

I chose revision-aware retrieval because the supplied documents contain
a concrete conflict: QC-SOP-014 Rev 03 and Rev 04.

Rev 03 says five samples are taken for every lot, while Rev 04
introduces a lot-size-dependent sampling table. A normal retrieval
system could retrieve both and give conflicting information.

The application therefore: 1. extracts document number and revision; 2.
stores revision, effective date, page and section with each chunk; 3.
marks the highest supplied revision as newest supplied; 4. marks older
revisions as superseded; 5. uses only current chunks as current
evidence; 6. detects older revisions separately for a revision note; 7.
does not claim the newest supplied revision is the actual QMS version.

For a 200-piece lot, the application retrieves Rev 04, where the 91--500
range requires 13 samples.

## 5. Final reflection

### Biggest challenge

The biggest technical challenge was making "not found" trustworthy. A
similarity threshold alone was not enough, so I added coverage of
meaningful question words and an unknown-word rule.

I also learned that wording matters. The documents use "concentration",
while a user may ask for "coolant mix percentage", so I added a small
controlled synonym mapping.

The synonym list and tuning set are small, so these results should not
be treated as production accuracy.

### Building challenges

I had to handle codes such as AL-104 and BH-220, different document
revisions, and LLM output validation. Generated answers must cite
retrieved evidence and numerical claims must be supported by that
evidence.

When the LLM is unavailable, the application falls back to retrieved
passages.

### Deployment and phone testing

I ran FastAPI with `--host 0.0.0.0 --port 8000` and accessed it from a
real phone on the same Wi-Fi using the laptop's local IP address. I
successfully asked a TX-200 coolant question and received the generated
answer and supporting sources.

### What I would build next

I would test a larger labelled question set, add clarifying dialogue,
improve table retrieval, consider embeddings or a re-ranker at larger
scale, add a source of truth for revisions, add audit logging and
feedback, support a local model for on-premises deployments, test with
real supervisors/operators, and add language support if required.

### What I am unsure about

I am unsure how well the retrieval thresholds and synonym rules will
generalise to unseen documents and questions, and how often a real LLM
might incorrectly return NOT_FOUND when the answer exists.

### What I would ask the customer

1.  Who is the main user: supervisor, operator, QC, or maintenance?
2.  What is the source of truth for the current SOP revision?
3.  Can SOP content be sent to a hosted LLM, or must it run on-premises?
4.  Which machines and processes should each document apply to?
5.  Which languages do users need?
6.  What evidence must be displayed for safety-critical answers?
7.  How should historical questions be handled when procedures change?

### Overall learning

An AI copilot for manufacturing should not be judged only by whether it
generates a good-looking answer. It must retrieve the right information,
identify the right revision, expose evidence, avoid guessing, handle
AI-service failure, and be usable safely in the real environment.

For this prototype I focused on these controls rather than unnecessary
infrastructure. The result is a small FastAPI application that retrieves
information from the supplied PDFs, generates source-grounded Gemini
answers when configured, falls back to evidence when the LLM is
unavailable, handles revision conflicts, rejects unsupported questions,
and runs from a phone on the same Wi-Fi.

## AI usage

I used Claude and other AI assistance during development to help plan,
implement, debug, and test the project. I also used Claude to critique
the user journey after writing my own first draft.

I verified document facts used by the application against the supplied
PDFs and tested the application with automated tests and real user
questions.

I understand the main modules and design decisions and can explain the
retrieval, revision handling, LLM integration, citation checks, and
not-found behaviour.
