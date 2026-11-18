# 🛡️ PR-Sentinel: Autonomous Incident Triage & Developer Workflow Engine

[![Agentware Track 5](https://img.shields.io/badge/Agentware%20Hackathon-Track%205%3A%20Developer%20Workflow-blue.svg)](#)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](#)
[![Built with Google Gemini](https://img.shields.io/badge/AI-Google%20Gemini%203.8%20Flash-orange.svg)](#)

> **Built for Agentware Hackathon (Track 5: Developer Workflow).**  
> An autonomous, polyglot AI agent for failed-build diagnosis, automated code & security review, multi-language testing, regression guardrails, and human-in-the-loop incident response.

---

## 🧭 Architecture & Core Features

PR-Sentinel replaces brittle automated scripts and manual triage by executing failed builds through a strictly governed **4-Phase Incident Response Lifecycle**:

```
 ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
 │   [PHASE 1]     │  ───> │   [PHASE 2]     │  ───> │   [PHASE 3]     │  ───> │   [PHASE 4]     │
 │ Incident Triage │       │ Root Cause Fix  │       │ Code & Security │       │ PR Artifact &   │
 │ & Baseline Test │       │ & Targeted Diff │       │ Review + Tests  │       │ Human Sign-Off  │
 └─────────────────┘       └─────────────────┘       └─────────────────┘       └─────────────────┘
```

### 1. The 4-Phase Incident Response Pipeline
- **[PHASE 1] Incident Ingestion & Triage**: Automatically scans build logs, detects project config files (`package.json`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, or `pytest`), and captures baseline pass/fail metrics.
- **[PHASE 2] Root Cause Diagnosis & Patching**: Locates faulty code, reads affected files, and drafts precise, surgical fixes.
- **[PHASE 3] Automated Code Review & Regression Testing**:
  - **Pre-Write Security Gate**: Evaluates candidate patches for syntax validity, hardcoded API secrets, unsafe `eval()`/`exec()`, and command injections before writing to disk.
  - **Regression Test Engine**: Runs the project test suite. If existing passing tests fail or syntax errors appear, the agent immediately flags a regression.
- **[PHASE 4] PR Generation & Human Sign-off**: Produces review-ready PR diffs and generates an exhaustive `EXECUTION_REPORT.md` audit artifact once tests pass with zero side-effects.

### 2. Multi-Layer Enterprise Safety & Guardrails
- **Multi-Turn Regression Rollback (`git checkout -- .`)**: If an applied patch breaks previously passing tests, PR-Sentinel automatically rolls back working directory changes, discards the bad diff, and prompts Gemini for an alternative strategy.
- **Circuit Breakers**: Limits regression retry attempts (max 3) and execution steps (max 15) to prevent runaway agent loops.
- **Path Traversal Protection**: Guardrail validates all file access strictly within the workspace root (`_validate_path`).
- **Protected & Sensitive Files Enforcer**: Strictly prevents writing to `.env`, `.git`, lockfiles, or critical runtime entrypoints without approval.
- **Emergency Kill Switch (`STOP.lock`)**: Instantly aborts agent operations via a single red button on the Streamlit dashboard or by touching `STOP.lock`.
- **Human-in-the-Loop Escalation Gateway**: Pauses in an `AWAITING_APPROVAL` state upon 2 consecutive test failures or attempts to alter sensitive files, rendering live git diffs on the console for one-click human approval or rejection.
- **Real-Time Streamlit Operations Console (`dashboard.py`)**: Live streaming audit trail, phase progress, and interactive operator controls.
- **Automated Verification Report (`EXECUTION_REPORT.md`)**: Self-generating Markdown audit report detailing metrics, timeline, and diffs for judges and compliance reviews.

---

## ⚡ Quick Setup Guide (Under 3 Minutes)

### Step 1: Clone Repository & Install Dependencies
```bash
git clone <repo-url>
cd PR-SENTINEL
python -m venv .venv

# On Windows:
.\.venv\Scripts\Activate.ps1
# On macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### Step 2: Configure Environment
Copy the example environment file and add your Google Gemini API key:
```bash
# Windows PowerShell:
Copy-Item .env.example .env

# macOS / Linux:
cp .env.example .env
```
Inside `.env`, configure:
```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-3.8-flash
```
*(Get a free Gemini API key from [Google AI Studio](https://aistudio.google.com/)).*

### Step 3: Launch Operations Console or Run Agent

- **Option A: Live Streamlit Dashboard (Recommended)**:
  ```bash
  streamlit run dashboard.py
  ```
  Open `http://localhost:8501` to view live telemetry, emergency stop controls, and human sign-off prompts.

- **Option B: Run Autonomous Agent via CLI**:
  ```bash
  # Triage the default sample repository:
  python agent.py

  # Or target any external workspace repository:
  python agent.py --path <target_path>
  ```

---

## 🧪 Judge Evaluation Sandbox (`judge_samples/`)

PR-Sentinel includes a pre-configured evaluation suite in the `judge_samples/` directory with 4 isolated scenarios to test every feature of the agent.

> 📖 **Judge Companion Guide**: See [`judge_samples/JUDGE_GUIDE.txt`](./judge_samples/JUDGE_GUIDE.txt) for detailed instructions, expected terminal outputs, and dashboard verification steps.

| Scenario | Workspace Path | Feature Evaluated | What to Expect |
|---|---|---|---|
| **01. Basic Bug** | `./judge_samples/01_basic_bug` | **Autonomous Diagnosis & Patching** | Python calculator bug (`add` returns `a - b`). Ingests, patches `calculator.py`, verifies, and outputs PR report. |
| **02. Polyglot JS** | `./judge_samples/02_polyglot_js` | **Multi-Language Auto-Detection** | Node.js project using native `node --test` runner (zero npm installs). Auto-switches from `pytest` to `npm test`. |
| **03. Regression Trap** | `./judge_samples/03_regression_trap` | **Regression Rollback Guardrail** | Pricing module where regular price passes but discount fails. Naive fixes break regular price, triggering instant `git checkout -- .` rollback. |
| **04. HITL Escalation** | `./judge_samples/04_hitl_escalation` | **Human-in-the-Loop & Security** | Auth module with protected `.env`. Triggers `AWAITING_APPROVAL` banner on Streamlit dashboard for operator sign-off. |

### How to Run Each Test Scenario:

```bash
# Test 1: Basic Python Repair
python agent.py --path ./judge_samples/01_basic_bug

# Test 2: Node.js Multi-Language Auto-Detection
python agent.py --path ./judge_samples/02_polyglot_js

# Test 3: Regression Detection & Automatic Git Rollback
python agent.py --path ./judge_samples/03_regression_trap

# Test 4: Human-in-the-Loop Escalation & Dashboard Review
python agent.py --path ./judge_samples/04_hitl_escalation
```

### Resetting Any Sample Scenario:
Each scenario is initialized as an isolated Git repository. To reset any scenario to its initial failing state for a clean re-run:
```bash
# Example for Scenario 1:
cd judge_samples/01_basic_bug && git checkout -- . && cd ../..

# Example for Scenario 2:
cd judge_samples/02_polyglot_js && git checkout -- . && cd ../..

# Example for Scenario 3:
cd judge_samples/03_regression_trap && git checkout -- . && cd ../..

# Example for Scenario 4:
cd judge_samples/04_hitl_escalation && git checkout -- . && cd ../..
```

---

## 📊 Post-Execution Audit Artifact (`EXECUTION_REPORT.md`)

After every run, PR-Sentinel generates a complete Markdown report ([EXECUTION_REPORT.md](./EXECUTION_REPORT.md)) containing:
1. **Executive Summary**: Resolution status, target repository, steps taken, and runtime duration.
2. **Safety & Guardrail Compliance Matrix**: Audit verification of path traversal protection, sensitive file policies, regression rollbacks, circuit breakers, and emergency controls.
3. **Chronological Audit Timeline**: Step-by-step table of agent reasoning, tool invocations, and tool outputs sourced directly from `audit_trail.jsonl`.
4. **PR Candidate Artifact**: Clean git diff and final test suite verification output.

---

## 📁 Repository Structure

```
PR-SENTINEL/
├── agent.py                  # Core Autonomous Incident Triage Agent loop & Phase Controller
├── dashboard.py              # Streamlit Live Operations & Human Sign-off Console
├── tools.py                  # Polyglot test runners, security review, path traversal & git tools
├── requirements.txt          # Python dependencies (google-genai, streamlit, gitpython, pytest, etc.)
├── .env.example              # Environment template with Gemini model configuration
├── audit_trail.jsonl         # Real-time structured telemetry stream
├── EXECUTION_REPORT.md       # Self-generating post-execution judge audit report
└── judge_samples/            # Isolated test scenarios for Hackathon Judges
    ├── JUDGE_GUIDE.txt       # Step-by-step testing instructions & expected behaviors
    ├── 01_basic_bug/         # Scenario 1: Python math bug
    ├── 02_polyglot_js/       # Scenario 2: Node.js native test project
    ├── 03_regression_trap/   # Scenario 3: Regression trap with git rollback
    └── 04_hitl_escalation/   # Scenario 4: Human-in-the-Loop escalation with .env protection
```
