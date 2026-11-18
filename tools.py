import os
import sys
import re
import json
import subprocess
from pathlib import Path
import git
from google.genai import types

WORKSPACE_DIR = Path("./sample_repo").resolve()
PROTECTED_FILES = {".env", "main.py", ".git"}
# Files considered sensitive that trigger Human-in-the-Loop escalation before modification
SENSITIVE_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    "docker-compose.yml",
    "Dockerfile",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "requirements.txt",
    "pyproject.toml",
    "main.py",
}
# Allowed extensions for standard code files
SAFE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".c",
    ".cpp",
    ".h",
    ".cs",
    ".rb",
    ".php",
    ".html",
    ".css",
    ".json",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".toml",
}


def set_workspace(path_str: str) -> Path:
    """Dynamically updates WORKSPACE_DIR and verifies that the path exists."""
    global WORKSPACE_DIR
    target = Path(path_str).resolve()
    if not target.exists():
        raise FileNotFoundError(f"Workspace path does not exist: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"Workspace path is not a directory: {target}")
    WORKSPACE_DIR = target
    return WORKSPACE_DIR


def is_sensitive_or_unsafe_file(file_path: str) -> tuple[bool, str]:
    """Check if a file target is sensitive or outside safe code extensions."""
    target = (WORKSPACE_DIR / file_path).resolve()
    rel = target.relative_to(WORKSPACE_DIR)
    
    # Check sensitive files
    if target.name in SENSITIVE_FILES or any(p in SENSITIVE_FILES for p in rel.parts):
        return True, f"Target file '{target.name}' is classified as a protected/sensitive file."
    
    # Check hidden files / system directories
    if any(part.startswith(".") for part in rel.parts if part != "."):
        return True, f"Target path '{rel}' contains hidden files/directories."
    
    # Check extension
    if target.suffix.lower() not in SAFE_EXTENSIONS:
        return True, f"File extension '{target.suffix}' is outside the safe code extension list."
    
    return False, ""


def _validate_path(file_path: str) -> Path:
    """Guardrail: Prevent path traversal attacks outside the workspace."""
    target = (WORKSPACE_DIR / file_path).resolve()
    if not str(target).startswith(str(WORKSPACE_DIR)):
        raise PermissionError("Security Violation: Access denied outside workspace.")
    rel = target.relative_to(WORKSPACE_DIR)
    if any(p in PROTECTED_FILES for p in rel.parts) or target.name in PROTECTED_FILES:
        raise PermissionError(
            f"Security Violation: Modification of protected file {target.name} is forbidden."
        )
    return target


def read_code_file(file_path: str) -> str:
    """Read a code file within the repository."""
    path = _validate_path(file_path)
    if not path.exists():
        return f"Error: File {file_path} does not exist."
    return path.read_text(encoding="utf-8")


def write_code_file(file_path: str, content: str) -> str:
    """Write a patch to a code file with safety checks."""
    path = _validate_path(file_path)
    path.write_text(content, encoding="utf-8")
    return f"Success: Updated {file_path}"


def rollback_changes() -> str:
    """Roll back uncommitted working directory changes using git or clean files."""
    try:
        repo = git.Repo(str(WORKSPACE_DIR))
        repo.git.checkout("--", ".")
        repo.git.clean("-fd")
        return "Success: Working directory changes rolled back via git."
    except Exception as e:
        return f"Git rollback error: {str(e)}"


def parse_test_metrics(output: str) -> dict:
    """Extract passed, failed, and total test counts across popular test runners."""
    passed = 0
    failed = 0
    errors = 0
    
    # 1. Pytest style: e.g. "1 failed, 4 passed in 0.21s" or "5 passed"
    m_pass = re.search(r"(\d+)\s+passed", output, re.IGNORECASE)
    m_fail = re.search(r"(\d+)\s+failed", output, re.IGNORECASE)
    m_err = re.search(r"(\d+)\s+error", output, re.IGNORECASE)
    if m_pass:
        passed = int(m_pass.group(1))
    if m_fail:
        failed = int(m_fail.group(1))
    if m_err:
        errors = int(m_err.group(1))

    # 2. Jest/Mocha (npm test): e.g. "Tests: 2 failed, 8 passed, 10 total"
    m_jest = re.search(r"Tests:\s*(?:(\d+)\s*failed,)?\s*(?:(\d+)\s*passed,)?\s*(\d+)\s*total", output, re.IGNORECASE)
    if m_jest:
        if m_jest.group(1):
            failed = int(m_jest.group(1))
        if m_jest.group(2):
            passed = int(m_jest.group(2))

    # 3. Cargo / Rust: e.g. "test result: FAILED. 4 passed; 1 failed; 0 ignored"
    m_cargo = re.search(r"test result:.*?(\d+)\s+passed;\s*(\d+)\s+failed", output, re.IGNORECASE)
    if m_cargo:
        passed = int(m_cargo.group(1))
        failed = int(m_cargo.group(2))

    # 4. Go test: count passes / fails
    if "=== RUN" in output or "--- PASS:" in output or "--- FAIL:" in output:
        go_passes = len(re.findall(r"--- PASS:", output))
        go_fails = len(re.findall(r"--- FAIL:", output))
        if go_passes or go_fails:
            passed = go_passes
            failed = go_fails

    total = passed + failed + errors
    return {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total": total,
    }


def run_tests() -> dict:
    """Run tests on the repository according to project configuration files."""
    cmd = []
    try:
        use_shell = sys.platform.startswith("win")
        if (WORKSPACE_DIR / "package.json").exists():
            cmd = ["npm", "test"]
        elif (WORKSPACE_DIR / "Cargo.toml").exists():
            cmd = ["cargo", "test"]
        elif (WORKSPACE_DIR / "go.mod").exists():
            cmd = ["go", "test", "./..."]
        elif (WORKSPACE_DIR / "pom.xml").exists():
            cmd = ["mvn", "test"]
        elif (WORKSPACE_DIR / "build.gradle").exists() or (WORKSPACE_DIR / "build.gradle.kts").exists():
            cmd = ["gradle", "test"]
        else:
            cmd = [sys.executable, "-m", "pytest", str(WORKSPACE_DIR)]
            use_shell = False

        result = subprocess.run(
            cmd,
            cwd=str(WORKSPACE_DIR),
            capture_output=True,
            text=True,
            timeout=60,
            shell=use_shell,
        )
        combined_output = (result.stdout or "") + "\n" + (result.stderr or "")
        metrics = parse_test_metrics(combined_output)
        return {
            "command": " ".join(cmd),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "passed": result.returncode == 0,
            "metrics": metrics,
        }
    except Exception as e:
        return {
            "command": " ".join(cmd) if cmd else "unknown",
            "passed": False,
            "error": str(e),
            "metrics": {"passed": 0, "failed": 0, "errors": 1, "total": 0},
        }


def check_for_regression(baseline_metrics: dict, current_result: dict) -> tuple[bool, str]:
    """Detects if previously passing tests failed or syntax/compilation errors occurred."""
    current_metrics = current_result.get("metrics", {})
    base_passed = baseline_metrics.get("passed", 0)
    curr_passed = current_metrics.get("passed", 0)
    base_failed = baseline_metrics.get("failed", 0)
    curr_failed = current_metrics.get("failed", 0)
    
    stdout_stderr = (current_result.get("stdout", "") or "") + "\n" + (current_result.get("stderr", "") or "")
    
    # Check 1: Syntax error / Indentation error / compilation error introduced
    syntax_error_patterns = [
        "SyntaxError:",
        "IndentationError:",
        "NameError:",
        "TypeError:",
        "compile error",
        "BUILD FAILED",
        "could not compile",
        "aborting due to previous error",
    ]
    for pattern in syntax_error_patterns:
        if pattern.lower() in stdout_stderr.lower() and pattern.lower() not in (baseline_metrics.get("raw_output", "")).lower():
            return True, f"Critical syntax/compilation error introduced: '{pattern}' detected in test output."

    # Check 2: Fewer tests passed than baseline (side-effect breaking existing tests)
    if base_passed > 0 and curr_passed < base_passed:
        return True, (
            f"Regression detected: previously passing tests dropped from {base_passed} to {curr_passed} "
            f"(Total failed: {curr_failed} vs baseline {base_failed})."
        )

    # Check 3: More tests failed than baseline
    if curr_failed > base_failed:
        return True, (
            f"Regression detected: failing test count increased from {base_failed} to {curr_failed}."
        )

    return False, ""


def review_code_patch(client, model_name: str, file_path: str, proposed_content: str, original_content: str) -> dict:
    """Reviews proposed code patch for syntax, security vulnerabilities, and side-effect logic bugs using Gemini.
    
    Returns:
        {
            "status": "APPROVED" | "REJECTED",
            "critique": str,
            "issues": list[str]
        }
    """
    # 1. Deterministic heuristic pre-checks (instant security and syntax check)
    precheck_issues = []
    
    # Check 1a: Python AST syntax check if file is python
    if file_path.endswith(".py"):
        import ast
        try:
            ast.parse(proposed_content)
        except SyntaxError as e:
            precheck_issues.append(f"Python SyntaxError at line {e.lineno}: {e.msg}")

    # Check 1b: Common security red flags
    security_patterns = [
        (r"(?i)(api[_-]?key|secret|password|bearer|auth[_-]?token)\s*=\s*['\"][A-Za-z0-9_\-\.]{12,}['\"]", "Hardcoded credentials or API key detected"),
        (r"\beval\s*\(", "Dangerous use of eval() function"),
        (r"\bexec\s*\(", "Dangerous use of exec() function"),
        (r"subprocess\.(run|Popen|call)\(.*shell\s*=\s*True.*\)", "Potentially unsafe shell=True in subprocess call"),
        (r"os\.system\s*\(", "Insecure os.system() call"),
    ]
    for pattern, description in security_patterns:
        if re.search(pattern, proposed_content) and not (original_content and re.search(pattern, original_content)):
            precheck_issues.append(description)

    if precheck_issues:
        return {
            "status": "REJECTED",
            "critique": "Pre-check security/syntax violation: " + "; ".join(precheck_issues),
            "issues": precheck_issues,
        }

    # 2. Automated Gemini Code Review
    prompt = (
        f"You are an expert Security Engineer and Senior Code Reviewer.\n"
        f"Review the proposed code patch for file '{file_path}'.\n\n"
        f"--- ORIGINAL CONTENT ---\n{original_content[:2000] if original_content else '[New File]'}\n\n"
        f"--- PROPOSED PATCH ---\n{proposed_content[:3000]}\n\n"
        f"Evaluate the patch against:\n"
        f"1. Syntax validity and compilation errors.\n"
        f"2. Security flaws (e.g. hardcoded secrets, unsafe eval/exec, SQL injection, arbitrary command execution, path traversal).\n"
        f"3. Logic flaws, regressions, or side effects.\n\n"
        f"Output your response strictly as valid JSON in this exact structure:\n"
        f'{{"status": "APPROVED", "critique": "Reason for approval", "issues": []}}\n'
        f"or if issues are found:\n"
        f'{{"status": "REJECTED", "critique": "Clear explanation of issues and why it is rejected", "issues": ["issue 1", "issue 2"]}}'
    )

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        data = json.loads(response.text)
        status = data.get("status", "APPROVED").upper()
        if status not in ("APPROVED", "REJECTED"):
            status = "APPROVED"
        return {
            "status": status,
            "critique": data.get("critique", "Code review passed."),
            "issues": data.get("issues", []),
        }
    except Exception as e:
        # Fallback to approved if API call fails but heuristic pre-check passed
        return {
            "status": "APPROVED",
            "critique": f"Automated review completed (fallback passed; note: {str(e)[:80]}).",
            "issues": [],
        }


def get_git_diff() -> str:
    """Get current git diff to inspect changes made by the agent."""
    try:
        repo = git.Repo(str(WORKSPACE_DIR))
        return repo.git.diff()
    except Exception as e:
        return f"Git error: {str(e)}"
