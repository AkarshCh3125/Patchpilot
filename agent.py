import os
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from google import genai
from google.genai import types
from tools import (
    read_code_file,
    write_code_file,
    run_tests,
    get_git_diff,
    set_workspace,
    rollback_changes,
    is_sensitive_or_unsafe_file,
    check_for_regression,
    review_code_patch,
    WORKSPACE_DIR,
)

load_dotenv()

AUDIT_LOG = "audit_trail.jsonl"
STOP_LOCK = "STOP.lock"
APPROVAL_LOCK = "APPROVAL_REQUIRED.lock"
APPROVAL_STATE_FILE = "APPROVAL_STATE.json"
REPORT_FILE = "EXECUTION_REPORT.md"

MAX_STEPS = 15
MAX_REGRESSION_RETRIES = 3
CONSECUTIVE_TEST_FAILURES_THRESHOLD = 2


def log_audit(step: int, action: str, details: dict, status: str):
    """Appends structured audit records for live monitoring."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "step": step,
        "action": action,
        "details": details,
        "status": status,
    }
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def generate_execution_report(start_time: float, final_status: str, workspace_path: str = ""):
    """Generates a comprehensive markdown report (EXECUTION_REPORT.md) based on audit logs, git diff, and tests."""
    duration = time.time() - start_time
    logs = []
    if os.path.exists(AUDIT_LOG):
        with open(AUDIT_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        logs.append(json.loads(line))
                    except Exception:
                        pass

    # Extract metrics
    total_steps = max([entry.get("step", 0) for entry in logs], default=0)
    escalation_count = 0
    regression_count = 0
    review_rejections = 0
    circuit_breaker_tripped = False
    kill_switch_triggered = False

    for entry in logs:
        action = entry.get("action", "")
        if entry.get("status") == "AWAITING_APPROVAL" or "HUMAN" in action:
            escalation_count += 1
        if action == "REGRESSION_DETECTED":
            regression_count += 1
        if action == "CODE_REVIEW_REJECTED":
            review_rejections += 1
        if action == "CIRCUIT_BREAKER":
            circuit_breaker_tripped = True
        if action == "KILL_SWITCH":
            kill_switch_triggered = True

    git_diff = get_git_diff()
    final_test = run_tests()

    if final_status == "SUCCESS":
        badge = "🟢 **SUCCESS (INCIDENT TRIAGED, PATCH VERIFIED & READY FOR PR)**"
    elif final_status in ("HALTED", "REJECTED"):
        badge = "🔴 **HALTED (EMERGENCY STOP / OPERATOR REJECTED)**"
    elif final_status == "CIRCUIT_BREAKER":
        badge = "🛑 **CIRCUIT BREAKER (MAX RETRIES EXCEEDED)**"
    else:
        badge = f"🟡 **{final_status}**"

    lines = [
        "# 🛡️ PatchPilot: Autonomous Incident Triage & Response Audit Report",
        "",
        f"> **Generated at:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  ",
        f"> **Platform Track:** Agentware Track 5: Autonomous Incident Triage & Developer Workflow Engine",
        "",
        "---",
        "",
        "## 1. Executive Summary & Incident Overview",
        "",
        f"- **Incident Resolution Status:** {badge}",
        f"- **Target Service / Repository:** `{workspace_path or str(WORKSPACE_DIR)}`",
        f"- **Total Remediation Steps:** `{total_steps}`",
        f"- **Incident Response Duration:** `{duration:.2f} seconds`",
        f"- **Security & Quality Rejections Caught:** `{review_rejections}`",
        f"- **Regressions Blocked & Rolled Back:** `{regression_count}`",
        f"- **Human Escalation Events:** `{escalation_count}`",
        f"- **Final Test Suite Outcome:** `{'PASSED ✅' if final_test.get('passed') else 'FAILED ❌'}`",
        "",
        "---",
        "",
        "## 2. Safety & Guardrail Compliance Matrix",
        "",
        "| Incident Guardrail | Operational Standard | Enforcement Status |",
        "|---|---|---|",
        f"| **Automated Code & Security Review** | Pre-write inspection for syntax, credentials, unsafe eval, & injection | `{'ENFORCED 🔍 (' + str(review_rejections) + ' rejected)' if review_rejections > 0 else 'PASSED ✅ (0 security violations)'}` |",
        f"| **Path Traversal Guard** | Access strictly confined to repository root | `COMPLIANT ✅` (Path traversal denied) |",
        f"| **Protected Files Policy** | Modifications to `.env`, `.git`, `main.py` blocked | `ENFORCED ✅` ({'Protected rule intact' if not kill_switch_triggered else 'Halted on violation'}) |",
        f"| **Regression Guardrail** | Discards patches breaking passing tests (git checkout -- .) | `{'ENFORCED 🛡️' if regression_count > 0 else 'MONITORED ✅ (No regressions)'}` |",
        f"| **Circuit Breaker** | Tripped if regression or retry limits (max 3) exceeded | `{'TRIPPED 🛑' if circuit_breaker_tripped else 'MONITORED ✅ (Normal limits)'}` |",
        f"| **Emergency Kill Switch** | Halts immediately upon `STOP.lock` creation | `{'ACTIVATED 🚨' if kill_switch_triggered else 'ACTIVE / STANDBY ✅'}` |",
        f"| **Human-in-the-Loop Gateway** | Pauses on 2 consecutive test fails or sensitive files | `{'TRIGGERED ⚠️' if escalation_count > 0 else 'MONITORED ✅ (No violations)'}` |",
        "",
        "---",
        "",
        "## 3. Step-by-Step Incident Audit Timeline",
        "",
        "| Step | Timestamp (UTC) | Action / Tool | Status | Details / Output Snippet |",
        "|---|---|---|---|---|",
    ]

    for log in logs:
        ts = log.get("timestamp", "").replace("T", " ")[:19]
        st = log.get("step", 0)
        act = log.get("action", "")
        stat = log.get("status", "")
        det = log.get("details", {})
        
        if isinstance(det, dict):
            if "critique" in det:
                snippet = f"Critique: {str(det['critique'])[:80]}".replace("\n", " ").replace("|", "/")
            elif "result" in det:
                snippet = str(det["result"])[:90].replace("\n", " ").replace("|", "/")
            elif "error" in det:
                snippet = f"Error: {str(det['error'])[:80]}".replace("\n", " ").replace("|", "/")
            elif "reason" in det:
                snippet = f"Reason: {str(det['reason'])[:80]}".replace("\n", " ").replace("|", "/")
            elif "text" in det:
                snippet = f"Thought: {str(det['text'])[:80]}...".replace("\n", " ").replace("|", "/")
            elif "args" in det:
                snippet = f"Args: {json.dumps(det['args'])[:80]}".replace("|", "/")
            else:
                snippet = json.dumps(det)[:80].replace("|", "/")
        else:
            snippet = str(det)[:80].replace("|", "/")

        lines.append(f"| `{st}` | {ts} | `{act}` | `{stat}` | {snippet} |")

    lines.extend([
        "",
        "---",
        "",
        "## 4. Proposed Remediation Diff & PR Artifact",
        "",
        "### Applied Git Diff (PR Candidate)",
        "```diff",
        git_diff if git_diff.strip() else "# No uncommitted git diff recorded at report generation time.",
        "```",
        "",
        "### Final Verification Suite Output",
        f"- **Command Run:** `{final_test.get('command', 'test runner')}`",
        f"- **Exit Code:** `{final_test.get('exit_code', 'N/A')}`",
        f"- **Passed:** `{final_test.get('passed', False)}`",
        "```text",
        final_test.get("stdout", "") or final_test.get("stderr", "") or final_test.get("error", "No output captured"),
        "```",
        "",
        "---",
        "*Report autonomously generated by PatchPilot Autonomous Incident Triage & Response Engine.*"
    ])

    report_content = "\n".join(lines)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"\n📊 Incident Resolution & Audit Report generated: {REPORT_FILE}")
    return report_content


def request_human_approval(step: int, reason: str, proposed_patch: str, target_file: str = "") -> bool:
    """Escalates to human operator via APPROVAL_REQUIRED.lock and halts until approved or rejected."""
    diff_content = get_git_diff()
    lock_data = {
        "step": step,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "target_file": target_file,
        "proposed_patch": proposed_patch,
        "git_diff": diff_content,
        "status": "AWAITING_APPROVAL",
    }

    with open(APPROVAL_LOCK, "w", encoding="utf-8") as f:
        json.dump(lock_data, f, indent=2)

    log_audit(step, "HUMAN_ESCALATION_TRIGGERED", lock_data, "AWAITING_APPROVAL")
    print(f"\n⚠️  [PHASE 4: HUMAN SIGN-OFF REQUIRED] Escalation Triggered: {reason}")
    print("⏸️  Incident triage paused in AWAITING_APPROVAL state. Check Streamlit Dashboard to review and sign off/reject.")

    if os.path.exists(APPROVAL_STATE_FILE):
        os.remove(APPROVAL_STATE_FILE)

    while True:
        if os.path.exists(STOP_LOCK):
            print("🚨 Emergency kill switch activated during approval wait.")
            rollback_changes()
            if os.path.exists(APPROVAL_LOCK):
                os.remove(APPROVAL_LOCK)
            return False

        if os.path.exists(APPROVAL_STATE_FILE):
            try:
                with open(APPROVAL_STATE_FILE, "r", encoding="utf-8") as f:
                    decision_data = json.load(f)
                decision = decision_data.get("decision")
                
                os.remove(APPROVAL_STATE_FILE)
                if os.path.exists(APPROVAL_LOCK):
                    os.remove(APPROVAL_LOCK)

                if decision == "APPROVED":
                    print("✅ Human sign-off approved! Resuming autonomous remediation...")
                    log_audit(step, "HUMAN_APPROVAL_GRANTED", {"reason": reason}, "APPROVED")
                    return True
                else:
                    print("❌ Human rejected proposed patch! Triggering emergency stop and rolling back...")
                    rollback_changes()
                    Path(STOP_LOCK).touch()
                    log_audit(step, "HUMAN_APPROVAL_REJECTED", {"reason": reason}, "REJECTED")
                    return False
            except Exception as e:
                print(f"Error reading approval decision: {e}")

        if not os.path.exists(APPROVAL_LOCK):
            print("🔓 Lock file cleared externally. Resuming...")
            log_audit(step, "HUMAN_LOCK_CLEARED_MANUALLY", {"reason": reason}, "APPROVED")
            return True

        time.sleep(1.0)


def send_message_with_retry(chat, message, max_retries=3, base_delay=3.0):
    """Sends a message to the Gemini chat with automatic backoff retry on 503/429 spikes."""
    for attempt in range(max_retries):
        try:
            return chat.send_message(message)
        except Exception as e:
            err_msg = str(e)
            is_transient = any(
                s in err_msg
                for s in ["503", "UNAVAILABLE", "429", "high demand", "capacity"]
            )
            if is_transient and attempt < max_retries - 1:
                wait_time = base_delay * (attempt + 1)
                print(
                    f"⏳ Model demand spike (503/429). Retrying in {wait_time:.0f}s "
                    f"(attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(wait_time)
            else:
                raise


def create_agent_chat(client, model_name: str, tools_list: list):
    """Creates a chat session for PatchPilot."""
    return client.chats.create(
        model=model_name,
        config=types.GenerateContentConfig(
            system_instruction=(
                "You are PatchPilot, an Autonomous Incident Triage & Response developer agent (Agentware Track 5). "
                "Your mission is to autonomously triage failing builds, isolate root causes, draft non-regressive patches, "
                "verify fixes with multi-language test suites, and generate review-ready PR diffs. "
                "Execution Flow:\n"
                "[PHASE 1] Incident Ingestion & Triage: Analyze failing test and build logs.\n"
                "[PHASE 2] Root Cause Diagnosis & Patching: Inspect source files and draft targeted, secure fixes.\n"
                "[PHASE 3] Automated Code Review & Regression Testing: Validate patch against security checks and test suites.\n"
                "[PHASE 4] PR Generation & Sign-off: Ensure all tests pass with zero regressions before concluding.\n"
                "Never touch protected or sensitive files without approval. Strive for zero side-effects."
            ),
            tools=tools_list,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
            temperature=0.1,
        ),
    )


def run_sentinel_agent(workspace_path: str = "./sample_repo"):
    start_time = time.time()
    final_status = "FAILED"
    print("=" * 70)
    print("🛡️  PATCHPILOT: AUTONOMOUS INCIDENT TRIAGE & RESPONSE ENGINE")
    print("    Agentware Track 5: Developer Workflow & Autonomous Remediation")
    print("=" * 70)

    try:
        if os.path.exists(APPROVAL_LOCK):
            os.remove(APPROVAL_LOCK)
        if os.path.exists(APPROVAL_STATE_FILE):
            os.remove(APPROVAL_STATE_FILE)

        try:
            active_workspace = set_workspace(workspace_path)
            print(f"🎯 Target Incident Workspace: {active_workspace}")
        except Exception as e:
            print(f"❌ Error setting workspace: {e}")
            log_audit(
                0,
                "INIT_ERROR",
                {"workspace": workspace_path, "error": str(e)},
                "FAILED",
            )
            final_status = "INIT_FAILED"
            return

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key or api_key == "your_actual_gemini_api_key_here":
            print(
                "⚠️ Please configure a valid GEMINI_API_KEY in your .env file before running."
            )
            log_audit(
                0,
                "INIT_ERROR",
                {"error": "Missing or placeholder GEMINI_API_KEY in .env"},
                "FAILED",
            )
            final_status = "CONFIG_ERROR"
            return

        client = genai.Client(api_key=api_key)

        if os.path.exists(STOP_LOCK):
            os.remove(STOP_LOCK)

        # -------------------------------------------------------------
        # [PHASE 1] Incident Ingestion & Triage
        # -------------------------------------------------------------
        print("\n🔍 [PHASE 1] Incident Ingestion & Triage: Scanning build logs and test suites...")
        initial_test = run_tests()
        baseline_metrics = initial_test.get("metrics", {"passed": 0, "failed": 0, "total": 0})
        baseline_metrics["raw_output"] = (initial_test.get("stdout", "") or "") + "\n" + (initial_test.get("stderr", "") or "")

        print(f"   ↳ Ingested Test Snapshot: {baseline_metrics.get('passed', 0)} passed, {baseline_metrics.get('failed', 0)} failing.")

        if initial_test["passed"]:
            print("✅ [TRIAGE COMPLETE] All tests already passing. No incident remediation required.")
            final_status = "SUCCESS"
            return

        print(f"🚨 [INCIDENT CONFIRMED] Failing test suites identified ({baseline_metrics.get('failed', 0)} failures). Triaging to Phase 2...")
        log_audit(
            0,
            "INCIDENT_INGESTION_CONFIRMED",
            {"workspace": str(active_workspace), "result": initial_test, "baseline_metrics": baseline_metrics},
            "STARTED",
        )

        tools_list = [read_code_file, write_code_file, run_tests, get_git_diff]

        preferred_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        fallback_models = ["gemini-3.5-flash-lite"]
        models_to_try = [preferred_model] + [
            m for m in fallback_models if m != preferred_model
        ]

        for model_name in models_to_try:
            print(f"📡 Dispatching to Triage AI Model: {model_name}...")
            try:
                chat = create_agent_chat(client, model_name, tools_list)
                loop_result = _execute_agent_loop(chat, client, tools_list, model_name, baseline_metrics)
                final_status = loop_result
                if final_status in ("SUCCESS", "HALTED", "CIRCUIT_BREAKER", "REJECTED"):
                    return
            except Exception as e:
                err_str = str(e)
                if (
                    ("503" in err_str or "UNAVAILABLE" in err_str)
                    and model_name != models_to_try[-1]
                ):
                    print(
                        f"⚠️ {model_name} is experiencing high demand (503). "
                        f"Switching to fallback model: {models_to_try[-1]}..."
                    )
                    continue
                else:
                    print(f"⚠️ Error encountered with {model_name}: {err_str}")
                    log_audit(
                        0,
                        "ERROR",
                        {"model": model_name, "error": err_str},
                        "FAILED",
                    )
                    final_status = "FAILED"
                    break
    finally:
        generate_execution_report(start_time, final_status, workspace_path)


def _execute_agent_loop(chat, client, tools_list: list, model_name: str, baseline_metrics: dict) -> str:
    current_message = (
        f"Incident Ingestion Summary: {baseline_metrics.get('failed', 0)} test(s) failing out of {baseline_metrics.get('total', 0)}. "
        f"Proceed through [PHASE 2] Root Cause Diagnosis to identify the faulty code, "
        f"[PHASE 3] Draft fix & verify with run_tests, and [PHASE 4] Confirm zero regressions for PR generation."
    )

    step = 0
    consecutive_test_failures = 0
    regression_retries = 0

    while step < MAX_STEPS:
        step += 1

        if os.path.exists(STOP_LOCK):
            print("🚨 EMERGENCY STOP TRIGGERED VIA KILL SWITCH.")
            log_audit(
                step, "KILL_SWITCH", {"reason": "Manual stop requested"}, "HALTED"
            )
            return "HALTED"

        print(f"\n--- Remediation Step {step}/{MAX_STEPS} ---")

        response = send_message_with_retry(chat, current_message)

        if response.function_calls:
            tool_responses = []
            for function_call in response.function_calls:
                name = function_call.name
                args = function_call.args or {}
                print(f"🔧 Invoking Tool: {name} | Args: {args}")

                # -------------------------------------------------------------
                # [PHASE 2] Root Cause Diagnosis & Code Reading
                # -------------------------------------------------------------
                if name == "read_code_file":
                    print(f"🔬 [PHASE 2] Root Cause Diagnosis: Inspecting {args.get('file_path', '')}...")
                    res = read_code_file(**args)

                # -------------------------------------------------------------
                # [PHASE 3] Automated Code Review & Security Gate
                # -------------------------------------------------------------
                elif name == "write_code_file":
                    target_file = args.get("file_path", "")
                    content = args.get("content", "")

                    is_unsafe, reason = is_sensitive_or_unsafe_file(target_file)
                    if is_unsafe:
                        approved = request_human_approval(
                            step=step,
                            reason=f"Attempted modification to sensitive/restricted file: {reason}",
                            proposed_patch=content,
                            target_file=target_file,
                        )
                        if not approved:
                            return "REJECTED"

                    original_content = ""
                    try:
                        original_content = read_code_file(target_file)
                    except Exception:
                        pass

                    print(f"🛡️  [PHASE 3] Security Gate & Automated Review: Evaluating patch for {target_file}...")
                    review_result = review_code_patch(
                        client=client,
                        model_name=model_name,
                        file_path=target_file,
                        proposed_content=content,
                        original_content=original_content,
                    )

                    review_status = review_result.get("status", "APPROVED")
                    critique = review_result.get("critique", "")
                    issues = review_result.get("issues", [])

                    if review_status == "REJECTED":
                        print(f"❌ [PHASE 3: CODE REVIEW REJECTED] {critique}")
                        log_audit(
                            step,
                            "CODE_REVIEW_REJECTED",
                            {
                                "file_path": target_file,
                                "critique": critique,
                                "issues": issues,
                            },
                            "REJECTED",
                        )
                        res = (
                            f"CODE REVIEW REJECTED: Your proposed patch to '{target_file}' was rejected by the automated "
                            f"security and code review system. Issues detected:\n{critique}\n"
                            f"Please revise your patch to resolve these issues and adhere strictly to security best practices."
                        )
                    else:
                        print(f"✅ [PHASE 3: CODE REVIEW APPROVED] Security & Syntax checks passed.")
                        log_audit(
                            step,
                            "CODE_REVIEW_APPROVED",
                            {"file_path": target_file, "critique": critique},
                            "APPROVED",
                        )
                        print(f"📝 [PHASE 2] Applying remediation patch to {target_file}...")
                        res = write_code_file(**args)

                # -------------------------------------------------------------
                # [PHASE 3 & 4] Regression Testing & PR Readiness
                # -------------------------------------------------------------
                elif name in ("run_tests", "run_pytest"):
                    print("🧪 [PHASE 3] Running Regression & Verification Test Suite...")
                    res = run_tests()
                    
                    is_regression, reg_reason = check_for_regression(baseline_metrics, res)
                    
                    if is_regression:
                        regression_retries += 1
                        print(f"🚨 [PHASE 3 REGRESSION DETECTED] {reg_reason}")
                        print("🔄 Immediately rolling back uncommitted changes via git checkout -- .")
                        rollback_msg = rollback_changes()
                        
                        log_audit(
                            step,
                            "REGRESSION_DETECTED",
                            {
                                "reason": reg_reason,
                                "regression_attempt": regression_retries,
                                "rollback": rollback_msg,
                                "test_output": str(res.get("stdout", ""))[:300],
                            },
                            "ROLLED_BACK",
                        )

                        if regression_retries >= MAX_REGRESSION_RETRIES:
                            print(f"🛑 Circuit Breaker tripped: Maximum regression attempts ({MAX_REGRESSION_RETRIES}) reached.")
                            log_audit(
                                step,
                                "CIRCUIT_BREAKER",
                                {"reason": f"Exceeded max regression retries ({MAX_REGRESSION_RETRIES})", "retries": regression_retries},
                                "HALTED",
                            )
                            return "CIRCUIT_BREAKER"

                        res = {
                            "passed": False,
                            "status": "REGRESSION_DETECTED_AND_ROLLED_BACK",
                            "error": reg_reason,
                            "instruction": (
                                f"CRITICAL REGRESSION: Your previous patch caused regressions or compilation errors ({reg_reason}). "
                                f"Changes were automatically rolled back. "
                                f"Do NOT repeat the previous fix! You must adopt a completely different, safer approach. "
                                f"Regression retry {regression_retries}/{MAX_REGRESSION_RETRIES}."
                            ),
                        }

                    elif res["passed"]:
                        print("\n" + "=" * 70)
                        print("🎉 [PHASE 4] PR GENERATION & VERIFICATION COMPLETE!")
                        print("   ↳ Test suite passed with 0 regressions.")
                        print("   ↳ Clean git diff artifact ready for Pull Request review.")
                        print("=" * 70 + "\n")
                        log_audit(step, "FIX_VERIFIED", res, "SUCCESS")
                        return "SUCCESS"

                    else:
                        consecutive_test_failures += 1
                        print(f"❌ Test failed ({consecutive_test_failures} consecutive failure(s)).")

                        if consecutive_test_failures >= CONSECUTIVE_TEST_FAILURES_THRESHOLD:
                            approved = request_human_approval(
                                step=step,
                                reason=f"Tests failed {consecutive_test_failures} consecutive times. Human intervention required.",
                                proposed_patch=str(res.get("stdout", ""))[:600],
                                target_file="[test_execution]",
                            )
                            if not approved:
                                return "REJECTED"
                            consecutive_test_failures = 0

                elif name == "get_git_diff":
                    res = get_git_diff()
                else:
                    res = f"Unknown tool: {name}"

                log_audit(
                    step,
                    name,
                    {"args": args, "result": str(res)[:200]},
                    "EXECUTED",
                )
                tool_responses.append(
                    types.Part.from_function_response(
                        name=name,
                        response={"result": res},
                    )
                )
            current_message = tool_responses
        else:
            print(f"💬 Triage Agent Analysis: {response.text}")
            log_audit(step, "AGENT_THOUGHT", {"text": response.text}, "THINKING")
            current_message = (
                "Proceed with fixing the bug based on your findings."
            )

        time.sleep(1.5)

    return "MAX_STEPS_REACHED"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="PatchPilot: Autonomous Incident Triage & Response Engine (Agentware Track 5)"
    )
    parser.add_argument(
        "--path",
        default="./sample_repo",
        help="Path to the repository/project workspace to triage and fix (default: ./sample_repo)",
    )
    args = parser.parse_args()
    set_workspace(args.path)
    run_sentinel_agent(args.path)
