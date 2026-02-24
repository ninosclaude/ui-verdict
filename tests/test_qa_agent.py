"""Tests for QA-Agent package."""

import json
import pytest

from ui_verdict.qa_agent.models import (
    QAReport,
    ACResult,
    Status,
    Severity,
    CheckLevel,
    StepLog,
)
from ui_verdict.qa_agent.report import (
    generate_what_to_fix,
    compute_level_statuses,
    build_report,
)
from ui_verdict.qa_agent.vision import ask_vision_bool
from ui_verdict.qa_agent.checks import (
    check_p01_app_launches,
    check_p02_navigation_exists,
    check_r01_feature_linked,
    check_f01_action_causes_change,
)


class TestModels:
    """Tests for data models."""

    def test_ac_result_to_dict(self):
        """ACResult serializes correctly."""
        result = ACResult(
            ac="App launches",
            check_id="P-01",
            level=CheckLevel.PRE_FLIGHT,
            status=Status.PASS,
            severity=Severity.CRITICAL,
            diagnosis="App running (PID 1234)",
            screenshot="/tmp/test.png",
            details={"pid": 1234},
        )
        data = result.to_dict()

        assert data["ac"] == "App launches"
        assert data["check_id"] == "P-01"
        assert data["level"] == "pre_flight"
        assert data["status"] == "PASS"
        assert data["severity"] == "critical"
        assert data["diagnosis"] == "App running (PID 1234)"
        assert data["screenshot"] == "/tmp/test.png"
        assert data["details"]["pid"] == 1234

    def test_qa_report_to_json(self):
        """QAReport produces valid JSON."""
        report = QAReport(
            run_id="test_123",
            story="Test story",
            overall_status=Status.PASS,
            duration_seconds=5.5,
            acs_passed=3,
            acs_failed=0,
            acs_skipped=1,
            what_to_fix="All checks passed. No fixes needed.",
            levels={"pre_flight": "PASS"},
            acs=[],
            steps=[],
        )

        json_str = report.to_json()
        data = json.loads(json_str)

        assert data["run_id"] == "test_123"
        assert data["story"] == "Test story"
        assert data["overall_status"] == "PASS"
        assert data["duration_seconds"] == 5.5
        assert data["acs_passed"] == 3
        assert data["acs_failed"] == 0
        assert data["acs_skipped"] == 1

    def test_qa_report_summary(self):
        """Summary method produces readable output."""
        report = QAReport(
            run_id="test_123",
            story="Test story",
            overall_status=Status.PASS,
            duration_seconds=3.2,
            acs_passed=5,
            acs_failed=0,
            acs_skipped=1,
            what_to_fix="All checks passed. No fixes needed.",
            levels={"pre_flight": "PASS", "reachability": "PASS"},
            acs=[],
            steps=[],
        )

        summary = report.summary()

        assert "✅" in summary
        assert "PASS" in summary
        assert "3.2s" in summary
        assert "✅5" in summary
        assert "❌0" in summary
        assert "⏭️1" in summary
        assert "pre_flight: PASS" in summary
        assert "reachability: PASS" in summary

    def test_status_enum_values(self):
        """Status enum has expected values."""
        assert Status.PASS.value == "PASS"
        assert Status.FAIL.value == "FAIL"
        assert Status.WARN.value == "WARN"
        assert Status.SKIPPED.value == "SKIPPED"

    def test_step_log_to_dict(self):
        """StepLog serializes correctly."""
        step = StepLog(
            step="App started",
            status="ok",
            details={"pid": 1234},
            screenshot="/tmp/test.png",
        )
        data = step.to_dict()

        assert data["step"] == "App started"
        assert data["status"] == "ok"
        assert data["pid"] == 1234
        assert data["screenshot"] == "/tmp/test.png"


class TestReport:
    """Tests for report generation."""

    def test_generate_what_to_fix_no_failures(self):
        """No failures returns success message."""
        acs = [
            ACResult(
                ac="Test",
                check_id="P-01",
                level=CheckLevel.PRE_FLIGHT,
                status=Status.PASS,
                severity=Severity.CRITICAL,
            )
        ]

        result = generate_what_to_fix(acs)

        assert result == "All checks passed. No fixes needed."

    def test_generate_what_to_fix_preflight_fail(self):
        """Pre-flight failures get critical section."""
        acs = [
            ACResult(
                ac="App launches",
                check_id="P-01",
                level=CheckLevel.PRE_FLIGHT,
                status=Status.FAIL,
                severity=Severity.CRITICAL,
                diagnosis="Binary not found: /bin/app",
            )
        ]

        result = generate_what_to_fix(acs)

        assert "🔴 CRITICAL - App won't start:" in result
        assert "[P-01]" in result
        assert "Binary not found: /bin/app" in result

    def test_generate_what_to_fix_reachability_fail(self):
        """Reachability failures formatted correctly."""
        acs = [
            ACResult(
                ac="Feature linked (settings)",
                check_id="R-01",
                level=CheckLevel.REACHABILITY,
                status=Status.FAIL,
                severity=Severity.CRITICAL,
                diagnosis="No settings button found",
            )
        ]

        result = generate_what_to_fix(acs)

        assert "🔴 CRITICAL - Feature not reachable:" in result
        assert "[R-01]" in result
        assert "Feature linked (settings)" in result
        assert "No settings button found" in result

    def test_generate_what_to_fix_mixed_failures(self):
        """Multiple failure types grouped correctly."""
        acs = [
            ACResult(
                ac="App launches",
                check_id="P-01",
                level=CheckLevel.PRE_FLIGHT,
                status=Status.FAIL,
                severity=Severity.CRITICAL,
                diagnosis="VM not available",
            ),
            ACResult(
                ac="Feature linked",
                check_id="R-01",
                level=CheckLevel.REACHABILITY,
                status=Status.FAIL,
                severity=Severity.CRITICAL,
                diagnosis="Feature not found",
            ),
            ACResult(
                ac="Action works",
                check_id="F-01",
                level=CheckLevel.FUNCTIONAL,
                status=Status.FAIL,
                severity=Severity.CRITICAL,
                diagnosis="No visual change",
                details={"change_ratio": 0.0001},
            ),
        ]

        result = generate_what_to_fix(acs)

        assert "🔴 CRITICAL - App won't start:" in result
        assert "🔴 CRITICAL - Feature not reachable:" in result
        assert "🟠 FUNCTIONAL - Feature broken:" in result
        assert "pixel_diff: 0.0001" in result

    def test_compute_level_statuses_all_pass(self):
        """All pass returns PASS for each level."""
        acs = [
            ACResult(
                ac="Test",
                check_id="P-01",
                level=CheckLevel.PRE_FLIGHT,
                status=Status.PASS,
                severity=Severity.CRITICAL,
            ),
            ACResult(
                ac="Test",
                check_id="R-01",
                level=CheckLevel.REACHABILITY,
                status=Status.PASS,
                severity=Severity.CRITICAL,
            ),
        ]

        levels = compute_level_statuses(acs)

        assert levels["pre_flight"] == "PASS"
        assert levels["reachability"] == "PASS"
        assert levels["functional"] == "SKIPPED"

    def test_compute_level_statuses_with_fails(self):
        """Failures return FAIL status."""
        acs = [
            ACResult(
                ac="Test",
                check_id="P-01",
                level=CheckLevel.PRE_FLIGHT,
                status=Status.FAIL,
                severity=Severity.CRITICAL,
            ),
            ACResult(
                ac="Test",
                check_id="R-01",
                level=CheckLevel.REACHABILITY,
                status=Status.PASS,
                severity=Severity.CRITICAL,
            ),
        ]

        levels = compute_level_statuses(acs)

        assert levels["pre_flight"] == "FAIL"
        assert levels["reachability"] == "PASS"

    def test_compute_level_statuses_with_warns(self):
        """Warnings return warning count."""
        acs = [
            ACResult(
                ac="Test",
                check_id="V-01",
                level=CheckLevel.VISUAL,
                status=Status.WARN,
                severity=Severity.MEDIUM,
            ),
            ACResult(
                ac="Test",
                check_id="V-02",
                level=CheckLevel.VISUAL,
                status=Status.WARN,
                severity=Severity.MEDIUM,
            ),
        ]

        levels = compute_level_statuses(acs)

        assert levels["visual"] == "2 warnings"

    def test_build_report_calculates_counts(self):
        """Report counts passed/failed/skipped correctly."""
        acs = [
            ACResult(
                ac="Test1",
                check_id="P-01",
                level=CheckLevel.PRE_FLIGHT,
                status=Status.PASS,
                severity=Severity.CRITICAL,
            ),
            ACResult(
                ac="Test2",
                check_id="P-02",
                level=CheckLevel.PRE_FLIGHT,
                status=Status.FAIL,
                severity=Severity.CRITICAL,
            ),
            ACResult(
                ac="Test3",
                check_id="P-03",
                level=CheckLevel.PRE_FLIGHT,
                status=Status.SKIPPED,
                severity=Severity.HIGH,
                reason="Pre-flight failed",
            ),
        ]

        report = build_report("run_123", "Test story", acs, [], 5.5)

        assert report.acs_passed == 1
        assert report.acs_failed == 1
        assert report.acs_skipped == 1
        assert report.overall_status == Status.FAIL
        assert report.duration_seconds == 5.5

    def test_build_report_overall_status_warn(self):
        """Report with warnings has WARN status."""
        acs = [
            ACResult(
                ac="Test1",
                check_id="P-01",
                level=CheckLevel.PRE_FLIGHT,
                status=Status.PASS,
                severity=Severity.CRITICAL,
            ),
            ACResult(
                ac="Test2",
                check_id="V-01",
                level=CheckLevel.VISUAL,
                status=Status.WARN,
                severity=Severity.MEDIUM,
            ),
        ]

        report = build_report("run_123", "Test story", acs, [], 3.0)

        assert report.overall_status == Status.WARN


class TestVision:
    """Tests for vision integration."""

    def test_ask_vision_bool_yes_response(self, mocker):
        """YES response parsed as True."""
        mocker.patch(
            "ui_verdict.qa_agent.vision.ask_vision",
            return_value="YES: The button is visible",
        )

        result, explanation = ask_vision_bool(
            "/fake/path.png", "Is the button visible?"
        )

        assert result is True
        assert "YES" in explanation

    def test_ask_vision_bool_no_response(self, mocker):
        """NO response parsed as False."""
        mocker.patch(
            "ui_verdict.qa_agent.vision.ask_vision",
            return_value="NO: Cannot see any button",
        )

        result, explanation = ask_vision_bool(
            "/fake/path.png", "Is the button visible?"
        )

        assert result is False
        assert "NO" in explanation

    def test_ask_vision_bool_case_insensitive(self, mocker):
        """Response parsing is case insensitive."""
        mocker.patch(
            "ui_verdict.qa_agent.vision.ask_vision",
            return_value="yes: found it",
        )

        result, _ = ask_vision_bool("/fake/path.png", "Found?")

        assert result is True

    def test_ask_vision_bool_no_prefix(self, mocker):
        """Response without YES/NO prefix defaults to False."""
        mocker.patch(
            "ui_verdict.qa_agent.vision.ask_vision",
            return_value="Maybe there is a button somewhere",
        )

        result, _ = ask_vision_bool("/fake/path.png", "Is there a button?")

        assert result is False


class TestChecks:
    """Tests for check functions."""

    @pytest.fixture
    def mock_vm(self, mocker):
        """Mock VM operations for successful scenario."""
        mocker.patch("ui_verdict.qa_agent.checks.vm_available", return_value=True)
        mocker.patch("ui_verdict.qa_agent.checks.ensure_display")
        mocker.patch(
            "ui_verdict.qa_agent.checks.check_binary_exists", return_value=True
        )
        mocker.patch(
            "ui_verdict.qa_agent.checks.start_app",
            return_value=(True, 1234, "Running"),
        )
        mocker.patch(
            "ui_verdict.qa_agent.checks.take_screenshot",
            return_value="/tmp/test.png",
        )
        mocker.patch("ui_verdict.qa_agent.checks.run_in_vm", return_value=(0, "ok", ""))

    def test_check_p01_vm_not_available(self, mocker):
        """P-01 fails if VM not available."""
        mocker.patch("ui_verdict.qa_agent.checks.vm_available", return_value=False)

        steps = []
        result = check_p01_app_launches("/bin/app", "app", None, steps)

        assert result.status == Status.FAIL
        assert result.check_id == "P-01"
        assert "VM" in result.diagnosis
        assert len(steps) == 1
        assert steps[0].status == "fail"

    def test_check_p01_app_start_fails(self, mock_vm, mocker):
        """P-01 fails if app doesn't start."""
        mocker.patch(
            "ui_verdict.qa_agent.checks.start_app",
            return_value=(False, None, "Failed to start"),
        )

        steps = []
        result = check_p01_app_launches("/bin/app", "app", None, steps)

        assert result.status == Status.FAIL
        assert result.diagnosis == "Failed to start"

    def test_check_p01_success(self, mock_vm, mocker):
        """P-01 passes when app starts."""
        steps = []
        result = check_p01_app_launches("/bin/app", "app", None, steps)

        assert result.status == Status.PASS
        assert result.check_id == "P-01"
        assert result.details.get("pid") == 1234
        assert result.screenshot == "/tmp/test.png"
        assert "PID 1234" in result.diagnosis

    def test_check_p02_navigation_exists(self, mock_vm, mocker):
        """P-02 passes when UI elements found."""
        mocker.patch(
            "ui_verdict.qa_agent.checks.ask_vision",
            return_value="Found: File menu, Edit button, Save toolbar icon",
        )

        steps = []
        result = check_p02_navigation_exists(steps)

        assert result.status == Status.PASS
        assert result.check_id == "P-02"

    def test_check_p02_no_navigation(self, mock_vm, mocker):
        """P-02 fails when no UI elements found."""
        mocker.patch(
            "ui_verdict.qa_agent.checks.ask_vision",
            return_value="Just a blank window with no interactive elements",
        )

        steps = []
        result = check_p02_navigation_exists(steps)

        assert result.status == Status.FAIL

    def test_check_r01_feature_found(self, mock_vm, mocker):
        """R-01 passes when feature found in UI."""
        mocker.patch(
            "ui_verdict.qa_agent.checks.ask_vision_bool",
            return_value=(True, "YES: Found settings button in top menu"),
        )

        steps = []
        result = check_r01_feature_linked(["settings", "config"], steps)

        assert result.status == Status.PASS
        assert result.check_id == "R-01"
        assert "settings" in result.ac

    def test_check_r01_feature_not_found(self, mock_vm, mocker):
        """R-01 fails when feature not in UI."""
        mocker.patch(
            "ui_verdict.qa_agent.checks.ask_vision_bool",
            return_value=(False, "NO: Cannot find settings anywhere"),
        )

        steps = []
        result = check_r01_feature_linked(["settings"], steps)

        assert result.status == Status.FAIL
        assert "Cannot find settings" in result.diagnosis

    def test_check_f01_action_causes_change(self, mock_vm, mocker):
        """F-01 passes when action changes screen."""
        mocker.patch("ui_verdict.qa_agent.checks.execute_action")
        mocker.patch(
            "ui_verdict.qa_agent.checks.get_pixel_diff",
            return_value={
                "change_ratio": 0.15,
                "changed_pixels": 1000,
                "num_regions": 3,
                "regions": [],
            },
        )

        steps = []
        result = check_f01_action_causes_change("click:100,200", steps)

        assert result.status == Status.PASS
        assert result.check_id == "F-01"
        assert result.details["change_ratio"] == 0.15

    def test_check_f01_no_change(self, mock_vm, mocker):
        """F-01 fails when action doesn't change screen."""
        mocker.patch("ui_verdict.qa_agent.checks.execute_action")
        mocker.patch(
            "ui_verdict.qa_agent.checks.get_pixel_diff",
            return_value={
                "change_ratio": 0.0001,
                "changed_pixels": 5,
                "num_regions": 0,
                "regions": [],
            },
        )

        steps = []
        result = check_f01_action_causes_change("click:100,200", steps)

        assert result.status == Status.FAIL
        assert result.details["change_ratio"] == 0.0001

    def test_check_f01_action_fails(self, mock_vm, mocker):
        """F-01 fails when action execution errors."""
        mocker.patch(
            "ui_verdict.qa_agent.checks.execute_action",
            side_effect=Exception("Action failed"),
        )

        steps = []
        result = check_f01_action_causes_change("click:invalid", steps)

        assert result.status == Status.FAIL
        assert "Action execution failed" in result.diagnosis


class TestServer:
    """Tests for MCP server functions."""

    def test_extract_keywords_german(self):
        """Extracts meaningful keywords from German story."""
        from ui_verdict.qa_agent.server import _extract_keywords

        keywords = _extract_keywords(
            "Als User möchte ich Benachrichtigungen verwalten können"
        )

        assert "benachrichtigungen" in keywords
        assert "verwalten" in keywords
        assert "als" not in keywords
        assert "möchte" not in keywords

    def test_extract_keywords_english(self):
        """Handles English stories too."""
        from ui_verdict.qa_agent.server import _extract_keywords

        keywords = _extract_keywords("As a user I want to manage notifications")

        assert "manage" in keywords
        assert "notifications" in keywords
        assert len(keywords) > 0

    def test_extract_keywords_short_words_filtered(self):
        """Short words are filtered out."""
        from ui_verdict.qa_agent.server import _extract_keywords

        keywords = _extract_keywords("Der UI ist gut")

        assert "der" not in keywords
        assert "ist" not in keywords
        assert "gut" not in keywords

    def test_extract_keywords_max_three(self):
        """Returns max 3 keywords."""
        from ui_verdict.qa_agent.server import _extract_keywords

        keywords = _extract_keywords(
            "User möchte Einstellungen öffnen konfigurieren speichern exportieren"
        )

        assert len(keywords) <= 3

    def test_check_screenshot_returns_json(self, mocker):
        """check_screenshot tool returns valid JSON."""
        mocker.patch(
            "ui_verdict.qa_agent.server.ask_vision_bool",
            return_value=(True, "YES"),
        )
        from ui_verdict.qa_agent.server import check_screenshot

        result = check_screenshot("/tmp/test.png", ["Is the button visible?"])
        data = json.loads(result)

        assert "Is the button visible?" in data
        assert data["Is the button visible?"] is True

    def test_check_screenshot_multiple_checks(self, mocker):
        """check_screenshot handles multiple checks."""
        call_count = [0]

        def mock_ask(path, question):
            call_count[0] += 1
            if call_count[0] == 1:
                return (True, "YES")
            return (False, "NO")

        mocker.patch("ui_verdict.qa_agent.server.ask_vision_bool", side_effect=mock_ask)
        from ui_verdict.qa_agent.server import check_screenshot

        result = check_screenshot(
            "/tmp/test.png", ["Is button visible?", "Is text readable?"]
        )
        data = json.loads(result)

        assert len(data) == 2
        assert data["Is button visible?"] is True
        assert data["Is text readable?"] is False


class TestVisionParsing:
    """Tests for robust YES/NO parsing."""

    def test_parse_yes_no_direct_yes(self):
        from ui_verdict.qa_agent.vision import _parse_yes_no
        assert _parse_yes_no("YES: this is correct") is True
        assert _parse_yes_no("yes, I agree") is True

    def test_parse_yes_no_direct_no(self):
        from ui_verdict.qa_agent.vision import _parse_yes_no
        assert _parse_yes_no("NO: this is wrong") is False
        assert _parse_yes_no("no, I disagree") is False

    def test_parse_yes_no_with_format_prefix(self):
        from ui_verdict.qa_agent.vision import _parse_yes_no
        # Model sometimes repeats the prompt format
        assert _parse_yes_no("Format: YES: this is correct") is True
        assert _parse_yes_no("Format: NO: this is wrong") is False

    def test_parse_yes_no_embedded(self):
        from ui_verdict.qa_agent.vision import _parse_yes_no
        assert _parse_yes_no("I think yes, it looks correct") is True
        assert _parse_yes_no("Looking at this, no it doesn't match") is False

    def test_parse_yes_no_both_present_uses_first(self):
        from ui_verdict.qa_agent.vision import _parse_yes_no
        # When both YES and NO appear, use the first one
        assert _parse_yes_no("Yes, but no issues") is True
        assert _parse_yes_no("No, yes it's fine") is False

    def test_parse_yes_no_indicators(self):
        from ui_verdict.qa_agent.vision import _parse_yes_no
        # Fallback indicators
        assert _parse_yes_no("The element is visible on screen") is True
        assert _parse_yes_no("The element is missing from view") is False
