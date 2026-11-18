import streamlit as st
import os
import json
from pathlib import Path

st.set_page_config(page_title="PatchPilot Operations Console | Incident Triage", layout="wide")

AUDIT_LOG = "audit_trail.jsonl"
STOP_LOCK = "STOP.lock"
APPROVAL_LOCK = "APPROVAL_REQUIRED.lock"
APPROVAL_STATE_FILE = "APPROVAL_STATE.json"

st.title("🛡️ PatchPilot: Autonomous Incident Triage & Developer Workflow Engine")
st.markdown(
    "**Agentware Track 5 Platform:** End-to-end autonomous incident ingestion, root-cause diagnosis, "
    "automated code & security review, regression verification, and PR-ready change sign-off."
)

# ---------------------------------------------------------
# Human-in-the-Loop Escalation Banner (Top Priority Alert)
# ---------------------------------------------------------
if os.path.exists(APPROVAL_LOCK):
    try:
        with open(APPROVAL_LOCK, "r", encoding="utf-8") as f:
            approval_info = json.load(f)
    except Exception as e:
        approval_info = {"reason": "Approval required", "error": str(e)}

    st.error("### ⚠️ [PHASE 4] HUMAN SIGN-OFF REQUIRED (Incident Triage Paused)")
    st.warning(
        f"**Incident Escalation Reason:** {approval_info.get('reason', 'Intervention required')}\n\n"
        f"**Target Service / File:** `{approval_info.get('target_file', 'N/A')}` | "
        f"**Remediation Step:** `{approval_info.get('step', '?')}`"
    )

    col_diff, col_patch = st.columns(2)
    with col_diff:
        st.markdown("#### 🔍 Candidate PR Git Diff")
        git_diff_text = approval_info.get("git_diff", "")
        if git_diff_text.strip():
            st.code(git_diff_text, language="diff")
        else:
            st.info("No uncommitted git diff detected.")

    with col_patch:
        st.markdown("#### 📝 Proposed Patch / Diagnostic Output")
        patch_text = approval_info.get("proposed_patch", "")
        st.code(patch_text, language="python" if approval_info.get("target_file", "").endswith(".py") else "text")

    col_btn_approve, col_btn_reject, col_btn_spacer = st.columns([2, 2, 4])
    with col_btn_approve:
        if st.button("✅ Approve Patch & Continue", type="primary", use_container_width=True):
            with open(APPROVAL_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({"decision": "APPROVED"}, f)
            if os.path.exists(APPROVAL_LOCK):
                os.remove(APPROVAL_LOCK)
            st.success("Remediation patch approved! Autonomous triage resumed.")
            st.rerun()

    with col_btn_reject:
        if st.button("❌ Reject & Halt", type="secondary", use_container_width=True):
            with open(APPROVAL_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({"decision": "REJECTED"}, f)
            Path(STOP_LOCK).touch()
            if os.path.exists(APPROVAL_LOCK):
                os.remove(APPROVAL_LOCK)
            st.error("Remediation patch rejected! Changes rolled back and incident halted.")
            st.rerun()

    st.divider()

# ---------------------------------------------------------
# Standard Safety & Audit Trail Controls
# ---------------------------------------------------------
col1, col2 = st.columns([2, 1])

with col2:
    st.subheader("🚨 Incident Guardrails & Safety Control")
    if os.path.exists(STOP_LOCK):
        st.error("Incident Status: HALTED (Emergency Kill Switch Active)")
        if st.button("Reset / Clear Kill Switch"):
            os.remove(STOP_LOCK)
            st.success("Kill switch cleared. Ready for restart.")
            st.rerun()
    elif os.path.exists(APPROVAL_LOCK):
        st.warning("Incident Status: ⏸️ PAUSED ([PHASE 4] Awaiting Human Sign-off)")
    else:
        st.success("Incident Status: ACTIVE / MONITORING")
        if st.button("🔴 EMERGENCY STOP (Kill Switch)", type="primary"):
            Path(STOP_LOCK).touch()
            st.error("Kill Switch Activated! Incident response halted immediately.")
            st.rerun()

    st.markdown("---")
    st.markdown("#### 🧭 Incident Response Phases")
    st.markdown("""
    - **[PHASE 1] Incident Ingestion & Triage:** Scanning build logs & failing test suites.
    - **[PHASE 2] Root Cause Diagnosis & Patching:** Locating bugs & drafting targeted fixes.
    - **[PHASE 3] Code Review & Regression Testing:** Automated security check & verification.
    - **[PHASE 4] PR Generation & Human Sign-off:** Clean diff artifact ready for Pull Request.
    """)

with col1:
    st.subheader("📜 Live Incident Audit Trail & Telemetry")
    if os.path.exists(AUDIT_LOG):
        with open(AUDIT_LOG, "r", encoding="utf-8") as f:
            lines = f.readlines()

        logs = [json.loads(line) for line in lines[::-1]]

        for log in logs:
            if log["status"] == "SUCCESS":
                status_color = "green"
            elif log["status"] in ["HALTED", "FAILED", "REJECTED"]:
                status_color = "red"
            elif log["status"] in ["AWAITING_APPROVAL"]:
                status_color = "orange"
            else:
                status_color = "blue"

            st.markdown(
                f"**Step {log['step']}** | `{log['action']}` | Status: :{status_color}[{log['status']}]"
            )
            st.json(log["details"], expanded=False)
            st.divider()
    else:
        st.info(
            "No active incident audit telemetry found. Run `python agent.py` to trigger triage."
        )

if st.button("🔄 Refresh Telemetry"):
    st.rerun()
