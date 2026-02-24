"""Tests for verify module."""

import json
import pytest

from ui_verdict.verify import (
    ACResult,
    VerifyResult,
    ActionAC,
    classify_acs,
    build_verification_prompt,
    _parse_response,
    GENERIC_LOCATIONS,
)


class TestACResult:
    """Tests for ACResult dataclass."""

    def test_pass_result(self):
        """Test PASS result with location."""
        result = ACResult(
            ac="Button is visible",
            status="PASS",
            location="top-right corner, blue button",
            description="48px button with white text",
        )
        assert result.ac == "Button is visible"
        assert result.status == "PASS"
        assert result.location == "top-right corner, blue button"
        assert result.description == "48px button with white text"
        assert result.reason is None
        assert result.suggestion is None

    def test_fail_result(self):
        """Test FAIL result with reason and suggestion."""
        result = ACResult(
            ac="Button is visible",
            status="FAIL",
            reason="No button found on page",
            suggestion="Add a button element with proper styling",
        )
        assert result.ac == "Button is visible"
        assert result.status == "FAIL"
        assert result.reason == "No button found on page"
        assert result.suggestion == "Add a button element with proper styling"
        assert result.location is None
        assert result.description is None


class TestVerifyResult:
    """Tests for VerifyResult dataclass."""

    def test_all_passed_true(self):
        """Test all_passed when no failures."""
        result = VerifyResult(
            passed=[
                ACResult(ac="AC1", status="PASS", location="top-left"),
                ACResult(ac="AC2", status="PASS", location="bottom-right"),
            ],
            failed=[],
        )
        assert result.all_passed is True

    def test_all_passed_false(self):
        """Test all_passed when there are failures."""
        result = VerifyResult(
            passed=[ACResult(ac="AC1", status="PASS", location="top-left")],
            failed=[
                ACResult(
                    ac="AC2",
                    status="FAIL",
                    reason="Not found",
                    suggestion="Add element",
                )
            ],
        )
        assert result.all_passed is False

    def test_all_passed_no_acs(self):
        """Test all_passed when no ACs at all."""
        result = VerifyResult(passed=[], failed=[])
        assert result.all_passed is True

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = VerifyResult(
            passed=[
                ACResult(ac="AC1", status="PASS", location="top-left"),
                ACResult(
                    ac="AC2",
                    status="PASS",
                    location="center",
                    description="big button",
                ),
            ],
            failed=[
                ACResult(
                    ac="AC3",
                    status="FAIL",
                    reason="Not found",
                    suggestion="Add it",
                )
            ],
            screenshot="/tmp/screenshot.png",
            duration_seconds=1.5,
        )

        d = result.to_dict()

        assert d["all_passed"] is False
        assert len(d["passed"]) == 2
        assert d["passed"][0] == {"ac": "AC1", "location": "top-left"}
        assert d["passed"][1] == {"ac": "AC2", "location": "center"}
        assert len(d["failed"]) == 1
        assert d["failed"][0] == {
            "ac": "AC3",
            "reason": "Not found",
            "suggestion": "Add it",
        }
        assert d["screenshot"] == "/tmp/screenshot.png"
        assert d["duration_seconds"] == 1.5

    def test_to_dict_empty(self):
        """Test to_dict with no ACs."""
        result = VerifyResult()
        d = result.to_dict()

        assert d["all_passed"] is True
        assert d["passed"] == []
        assert d["failed"] == []
        assert d["screenshot"] is None
        assert d["duration_seconds"] == 0.0


class TestClassifyAcs:
    """Tests for classify_acs function."""

    def test_all_static(self):
        """Test classification when all ACs are static."""
        acs = [
            "Login button is visible",
            "Email input field exists",
            "Header displays company logo",
        ]
        static, actions = classify_acs(acs)

        assert len(static) == 3
        assert len(actions) == 0
        assert static == acs

    def test_all_actions(self):
        """Test classification when all ACs are action-based."""
        acs = [
            "Clicking submit shows loading spinner",
            "After entering test@example.com in email field, button enables",
            "Hovering over help icon reveals tooltip",
        ]
        static, actions = classify_acs(acs)

        assert len(static) == 0
        assert len(actions) == 3

    def test_mixed_acs(self):
        """Test classification with mixed static and action ACs."""
        acs = [
            "Login button is visible",
            "Clicking login shows dashboard",
            "Email input exists",
        ]
        static, actions = classify_acs(acs)

        assert len(static) == 2
        assert len(actions) == 1
        assert static == ["Login button is visible", "Email input exists"]

    def test_click_pattern(self):
        """Test click pattern parsing."""
        acs = ["Clicking submit shows loading spinner"]
        static, actions = classify_acs(acs)

        assert len(actions) == 1
        action = actions[0]
        assert action.ac == "Clicking submit shows loading spinner"
        assert action.action_type == "click"
        assert action.target == "submit"
        assert action.expected == "loading spinner"
        assert action.fill_value == ""

    def test_click_pattern_case_insensitive(self):
        """Test that click pattern is case insensitive."""
        acs = ["CLICKING SUBMIT SHOWS SPINNER"]
        static, actions = classify_acs(acs)

        assert len(actions) == 1
        assert actions[0].action_type == "click"

    def test_fill_pattern(self):
        """Test fill pattern parsing."""
        acs = ["After entering test@example.com in email field, submit button enables"]
        static, actions = classify_acs(acs)

        assert len(actions) == 1
        action = actions[0]
        assert action.action_type == "fill"
        assert action.fill_value == "test@example.com"
        assert action.target == "email field"
        assert action.expected == "submit button enables"

    def test_fill_pattern_with_quotes(self):
        """Test fill pattern with quoted value."""
        acs = [
            "After entering 'password123' in password field, strength indicator shows"
        ]
        static, actions = classify_acs(acs)

        assert len(actions) == 1
        action = actions[0]
        assert action.fill_value == "password123"

    def test_hover_pattern(self):
        """Test hover pattern parsing."""
        acs = ["Hovering over help icon reveals tooltip"]
        static, actions = classify_acs(acs)

        assert len(actions) == 1
        action = actions[0]
        assert action.action_type == "hover"
        assert action.target == "help icon"
        assert action.expected == "tooltip"
        assert action.fill_value == ""

    def test_empty_list(self):
        """Test with empty AC list."""
        static, actions = classify_acs([])
        assert static == []
        assert actions == []

    def test_complex_descriptions(self):
        """Test ACs with complex descriptions."""
        acs = [
            "Clicking the blue 'Sign Up' button shows registration form",
            "After entering admin@company.com in the email input field, validation message appears",
        ]
        static, actions = classify_acs(acs)

        assert len(actions) == 2
        assert actions[0].target == "the blue 'Sign Up' button"
        assert actions[1].fill_value == "admin@company.com"


class TestBuildVerificationPrompt:
    """Tests for build_verification_prompt function."""

    def test_single_ac_no_actions(self):
        """Test prompt with single AC and no actions."""
        prompt = build_verification_prompt(
            ["Button is visible"], has_before_after=False
        )

        assert "1. Button is visible" in prompt
        assert "PASS" in prompt
        assert "FAIL" in prompt
        assert "location" in prompt
        assert "suggestion" in prompt
        assert "Image 1 (BEFORE)" not in prompt
        assert "Image 2 (AFTER)" not in prompt

    def test_multiple_acs(self):
        """Test prompt with multiple ACs."""
        acs = [
            "Login button exists",
            "Email field is visible",
            "Logo is displayed",
        ]
        prompt = build_verification_prompt(acs, has_before_after=False)

        assert "1. Login button exists" in prompt
        assert "2. Email field is visible" in prompt
        assert "3. Logo is displayed" in prompt

    def test_with_before_after_context(self):
        """Test prompt includes before/after context."""
        prompt = build_verification_prompt(
            ["Clicking X shows Y"], has_before_after=True
        )

        assert "Image 1 (BEFORE)" in prompt
        assert "Image 2 (AFTER)" in prompt
        assert "Initial page state" in prompt
        assert "State after user actions" in prompt

    def test_grounding_requirements(self):
        """Test prompt includes grounding requirements."""
        prompt = build_verification_prompt(
            ["Button is visible"], has_before_after=False
        )

        assert "SPECIFIC location" in prompt
        assert 'not "visible" or "on the page"' in prompt
        assert "actionable suggestion" in prompt

    def test_json_format_example(self):
        """Test prompt includes JSON format examples."""
        prompt = build_verification_prompt(
            ["Button is visible"], has_before_after=False
        )

        assert '"index"' in prompt
        assert '"status"' in prompt
        assert '"location"' in prompt
        assert '"reason"' in prompt
        assert '"suggestion"' in prompt


class TestParseResponse:
    """Tests for _parse_response function."""

    def test_valid_pass_response(self):
        """Test parsing valid PASS response."""
        response = json.dumps(
            [
                {
                    "index": 1,
                    "status": "PASS",
                    "location": "top-right corner, blue button",
                    "description": "48px button with white text",
                }
            ]
        )
        acs = ["Submit button is visible"]

        results = _parse_response(response, acs)

        assert len(results) == 1
        assert results[0].ac == "Submit button is visible"
        assert results[0].status == "PASS"
        assert results[0].location == "top-right corner, blue button"
        assert results[0].description == "48px button with white text"

    def test_valid_fail_response(self):
        """Test parsing valid FAIL response."""
        response = json.dumps(
            [
                {
                    "index": 1,
                    "status": "FAIL",
                    "reason": "No submit button found on page",
                    "suggestion": "Add a button element with text 'Submit'",
                }
            ]
        )
        acs = ["Submit button is visible"]

        results = _parse_response(response, acs)

        assert len(results) == 1
        assert results[0].status == "FAIL"
        assert results[0].reason == "No submit button found on page"
        assert results[0].suggestion == "Add a button element with text 'Submit'"

    def test_multiple_results(self):
        """Test parsing multiple AC results."""
        response = json.dumps(
            [
                {"index": 1, "status": "PASS", "location": "top-left"},
                {
                    "index": 2,
                    "status": "FAIL",
                    "reason": "Not found",
                    "suggestion": "Add it",
                },
                {"index": 3, "status": "PASS", "location": "bottom-right"},
            ]
        )
        acs = ["AC1", "AC2", "AC3"]

        results = _parse_response(response, acs)

        assert len(results) == 3
        assert results[0].status == "PASS"
        assert results[1].status == "FAIL"
        assert results[2].status == "PASS"

    def test_json_with_markdown_wrapper(self):
        """Test parsing JSON wrapped in markdown code blocks."""
        response = """Here are the results:
```json
[
    {"index": 1, "status": "PASS", "location": "top-left"}
]
```
"""
        acs = ["Button is visible"]

        results = _parse_response(response, acs)

        assert len(results) == 1
        assert results[0].status == "PASS"

    def test_json_with_extra_text(self):
        """Test parsing JSON with surrounding text."""
        response = """Based on the screenshot, I verified the criteria:

[
    {"index": 1, "status": "PASS", "location": "center of page"}
]

Hope this helps!"""
        acs = ["Element exists"]

        results = _parse_response(response, acs)

        assert len(results) == 1
        assert results[0].status == "PASS"

    def test_generic_location_rejected(self):
        """Test that generic locations are rejected."""
        for generic_location in GENERIC_LOCATIONS:
            response = json.dumps(
                [{"index": 1, "status": "PASS", "location": generic_location}]
            )
            acs = ["Button is visible"]

            results = _parse_response(response, acs)

            assert len(results) == 1
            assert results[0].status == "FAIL"
            assert "could not provide specific location" in results[0].reason

    def test_empty_location_rejected(self):
        """Test that empty location is rejected."""
        response = json.dumps([{"index": 1, "status": "PASS", "location": ""}])
        acs = ["Button is visible"]

        results = _parse_response(response, acs)

        assert len(results) == 1
        assert results[0].status == "FAIL"

    def test_whitespace_location_rejected(self):
        """Test that whitespace-only location is rejected."""
        response = json.dumps([{"index": 1, "status": "PASS", "location": "   "}])
        acs = ["Button is visible"]

        results = _parse_response(response, acs)

        assert len(results) == 1
        assert results[0].status == "FAIL"

    def test_case_insensitive_generic_location(self):
        """Test that generic location check is case insensitive."""
        response = json.dumps([{"index": 1, "status": "PASS", "location": "VISIBLE"}])
        acs = ["Button is visible"]

        results = _parse_response(response, acs)

        assert results[0].status == "FAIL"

    def test_invalid_json(self):
        """Test handling of invalid JSON."""
        response = "This is not JSON at all"
        acs = ["AC1", "AC2"]

        results = _parse_response(response, acs)

        assert len(results) == 2
        assert all(r.status == "FAIL" for r in results)
        assert all("could not parse model response" in r.reason for r in results)

    def test_malformed_json(self):
        """Test handling of malformed JSON."""
        response = "[{index: 1, status: 'PASS'}]"  # Missing quotes
        acs = ["Button is visible"]

        results = _parse_response(response, acs)

        assert len(results) == 1
        assert results[0].status == "FAIL"

    def test_no_json_array(self):
        """Test handling when no JSON array is found."""
        response = '{"not": "an array"}'
        acs = ["Button is visible"]

        results = _parse_response(response, acs)

        assert len(results) == 1
        assert results[0].status == "FAIL"

    def test_missing_ac_in_response(self):
        """Test that missing ACs are marked as FAIL."""
        response = json.dumps(
            [
                {"index": 1, "status": "PASS", "location": "top-left"},
                # Index 2 is missing
                {"index": 3, "status": "PASS", "location": "bottom-right"},
            ]
        )
        acs = ["AC1", "AC2", "AC3"]

        results = _parse_response(response, acs)

        assert len(results) == 3
        # Find the AC2 result
        ac2_result = next(r for r in results if r.ac == "AC2")
        assert ac2_result.status == "FAIL"
        assert "Not verified by model" in ac2_result.reason

    def test_out_of_range_index(self):
        """Test handling of out-of-range index."""
        response = json.dumps(
            [
                {"index": 1, "status": "PASS", "location": "top-left"},
                {
                    "index": 99,
                    "status": "PASS",
                    "location": "somewhere",
                },  # Out of range
            ]
        )
        acs = ["AC1"]

        results = _parse_response(response, acs)

        # Should only have 1 result (index 99 is ignored)
        assert len(results) == 1
        assert results[0].ac == "AC1"

    def test_negative_index(self):
        """Test handling of negative index."""
        response = json.dumps(
            [
                {"index": -1, "status": "PASS", "location": "top-left"},
                {"index": 1, "status": "PASS", "location": "center"},
            ]
        )
        acs = ["AC1"]

        results = _parse_response(response, acs)

        assert len(results) == 1
        assert results[0].ac == "AC1"

    def test_default_status_to_fail(self):
        """Test that missing status defaults to FAIL."""
        response = json.dumps([{"index": 1}])  # No status field
        acs = ["Button is visible"]

        results = _parse_response(response, acs)

        assert results[0].status == "FAIL"

    def test_lowercase_status(self):
        """Test that lowercase status is uppercased."""
        response = json.dumps([{"index": 1, "status": "pass", "location": "top-left"}])
        acs = ["Button is visible"]

        results = _parse_response(response, acs)

        assert results[0].status == "PASS"

    def test_fail_with_defaults(self):
        """Test FAIL result with missing reason/suggestion gets defaults."""
        response = json.dumps([{"index": 1, "status": "FAIL"}])
        acs = ["Button is visible"]

        results = _parse_response(response, acs)

        assert results[0].status == "FAIL"
        assert results[0].reason == "Criterion not met"
        assert results[0].suggestion == "Review the UI implementation"


class TestVerifyAcsAsync:
    """Tests for verify_acs_async function - edge cases only."""

    @pytest.mark.asyncio
    async def test_no_url(self):
        """Test that empty URL returns all failures."""
        from ui_verdict.verify import verify_acs_async

        result = await verify_acs_async(url="", acs=["AC1", "AC2"])

        assert result.all_passed is False
        assert len(result.failed) == 2
        assert all("No URL provided" in r.reason for r in result.failed)
        assert result.duration_seconds == 0.0

    @pytest.mark.asyncio
    async def test_no_acs(self):
        """Test that empty ACs list returns empty result."""
        from ui_verdict.verify import verify_acs_async

        result = await verify_acs_async(url="http://example.com", acs=[])

        assert result.all_passed is True
        assert len(result.passed) == 0
        assert len(result.failed) == 0
        assert result.duration_seconds == 0.0

    @pytest.mark.asyncio
    async def test_none_url(self):
        """Test that None URL is handled as empty."""
        from ui_verdict.verify import verify_acs_async

        result = await verify_acs_async(url=None, acs=["AC1"])

        assert result.all_passed is False
        assert len(result.failed) == 1
        assert "No URL provided" in result.failed[0].reason


class TestGenericLocations:
    """Tests for GENERIC_LOCATIONS constant."""

    def test_generic_locations_lowercase(self):
        """Test that all generic locations are lowercase."""
        assert all(loc == loc.lower() for loc in GENERIC_LOCATIONS)

    def test_common_generics_included(self):
        """Test that common generic phrases are included."""
        assert "visible" in GENERIC_LOCATIONS
        assert "on the page" in GENERIC_LOCATIONS
        assert "displayed" in GENERIC_LOCATIONS
