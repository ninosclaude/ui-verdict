#!/usr/bin/env python3
"""
ui-verdict CLI - Visual UI Testing

Usage:
    ui-verdict check URL [--baseline NAME] [--platform web|desktop]
    ui-verdict baseline create NAME URL [--platform web|desktop]
    ui-verdict baseline compare NAME [--url URL] [--platform web|desktop]
    ui-verdict baseline list
    ui-verdict baseline update NAME [--url URL] [--platform web|desktop]
"""

import argparse
import json
import sys
from typing import NoReturn


def cmd_check(args) -> int:
    """Run QA check on URL."""
    from .qa_agent.server import run

    result_json = run(
        story=f"Visual check of {args.url}",
        binary=args.url,
        app_name="check",
        acs=args.acs.split(",") if args.acs else None,
        platform=args.platform,
        baseline_mode=args.baseline is not None,
        baseline_name=args.baseline,
        skip_levels=["edge_cases"] if not args.full else [],
    )

    result = json.loads(result_json)

    # Print summary
    status = result["overall_status"]
    passed = result["acs_passed"]
    failed = result["acs_failed"]
    duration = result["duration_seconds"]

    if status == "PASS":
        print(f"✅ PASS | {passed} checks passed | {duration:.1f}s")
        return 0
    if status == "WARN":
        warn_count = len([a for a in result["acs"] if a["status"] == "WARN"])
        print(f"⚠️  WARN | {passed} passed, {warn_count} warnings | {duration:.1f}s")
        return 0

    print(f"❌ FAIL | {passed} passed, {failed} failed | {duration:.1f}s")
    print("\nWhat to fix:")
    print(result.get("what_to_fix", "No details"))
    return 1


def cmd_baseline_create(args) -> int:
    """Create visual baseline."""
    from .qa_agent.server import baseline_create

    result_json = baseline_create(
        name=args.name,
        url=args.url,
        platform=args.platform,
    )
    result = json.loads(result_json)

    if result.get("success"):
        print(f"✅ Created baseline '{args.name}'")
        print(f"   Screenshot: {result['screenshot']}")
        return 0

    print(f"❌ Failed: {result.get('error')}")
    return 1


def cmd_baseline_compare(args) -> int:
    """Compare against baseline."""
    from .qa_agent.server import baseline_compare

    result_json = baseline_compare(
        name=args.name,
        url=args.url,
        platform=args.platform,
    )
    result = json.loads(result_json)

    if not result.get("success"):
        print(f"❌ Failed: {result.get('error')}")
        return 1

    compare = result["result"]
    verdict = compare["verdict"]
    ratio = compare["change_ratio"]

    if verdict == "no_change":
        print(f"✅ NO CHANGE | {ratio * 100:.2f}% diff")
        return 0
    if verdict == "intentional":
        print(f"⚠️  INTENTIONAL CHANGE | {ratio * 100:.2f}% diff")
        print(f"   {compare.get('ai_explanation', 'No explanation')}")
        return 0
    if verdict == "regression":
        print(f"❌ REGRESSION | {ratio * 100:.2f}% diff")
        print(f"   {compare.get('ai_explanation', 'No explanation')}")
        return 1

    print(f"⚠️  UNKNOWN | {compare.get('ai_explanation', 'No baseline?')}")
    return 1


def cmd_baseline_list(args) -> int:
    """List all baselines."""
    from .qa_agent.server import baseline_list

    result_json = baseline_list()
    result = json.loads(result_json)

    if result["count"] == 0:
        print("No baselines found.")
        return 0

    print(f"Found {result['count']} baseline(s):\n")
    for b in result["baselines"]:
        print(f"  • {b['name']}")
        print(f"    URL: {b['url']}")
        print(f"    Viewport: {b['viewport'][0]}x{b['viewport'][1]}")
        print(f"    Updated: {b['updated_at'][:19]}")
        print()

    return 0


def cmd_baseline_update(args) -> int:
    """Update baseline."""
    from .qa_agent.server import baseline_update

    result_json = baseline_update(
        name=args.name,
        url=args.url,
        platform=args.platform,
    )
    result = json.loads(result_json)

    if result.get("success"):
        print(f"✅ Updated baseline '{args.name}'")
        return 0

    print(f"❌ Failed: {result.get('error')}")
    return 1


def main() -> NoReturn:
    parser = argparse.ArgumentParser(
        description="ui-verdict - Visual UI Testing CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # check command
    check_parser = subparsers.add_parser("check", help="Run QA check on URL")
    check_parser.add_argument("url", help="URL to check")
    check_parser.add_argument("--baseline", "-b", help="Compare against named baseline")
    check_parser.add_argument("--acs", help="Comma-separated acceptance criteria")
    check_parser.add_argument(
        "--platform", "-p", choices=["web", "desktop"], default="web"
    )
    check_parser.add_argument(
        "--full", action="store_true", help="Run all checks including edge cases"
    )
    check_parser.set_defaults(func=cmd_check)

    # baseline subcommand
    baseline_parser = subparsers.add_parser("baseline", help="Manage visual baselines")
    baseline_subparsers = baseline_parser.add_subparsers(dest="baseline_command")

    # baseline create
    create_parser = baseline_subparsers.add_parser("create", help="Create new baseline")
    create_parser.add_argument("name", help="Baseline name")
    create_parser.add_argument("url", help="URL to capture")
    create_parser.add_argument(
        "--platform", "-p", choices=["web", "desktop"], default="web"
    )
    create_parser.set_defaults(func=cmd_baseline_create)

    # baseline compare
    compare_parser = baseline_subparsers.add_parser(
        "compare", help="Compare against baseline"
    )
    compare_parser.add_argument("name", help="Baseline name")
    compare_parser.add_argument(
        "--url", help="URL to compare (uses stored URL if not provided)"
    )
    compare_parser.add_argument(
        "--platform", "-p", choices=["web", "desktop"], default="web"
    )
    compare_parser.set_defaults(func=cmd_baseline_compare)

    # baseline list
    list_parser = baseline_subparsers.add_parser("list", help="List all baselines")
    list_parser.set_defaults(func=cmd_baseline_list)

    # baseline update
    update_parser = baseline_subparsers.add_parser(
        "update", help="Update existing baseline"
    )
    update_parser.add_argument("name", help="Baseline name to update")
    update_parser.add_argument("--url", help="URL (uses stored URL if not provided)")
    update_parser.add_argument(
        "--platform", "-p", choices=["web", "desktop"], default="web"
    )
    update_parser.set_defaults(func=cmd_baseline_update)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "baseline" and not hasattr(args, "func"):
        baseline_parser.print_help()
        sys.exit(1)

    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
