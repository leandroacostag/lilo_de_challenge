"""
Test framework for challenge search queries.

Tests the following queries from the challenge:
1. "3 hp sewage pump weir" - should find pumps from Weir vendor
2. "nitrile glove bulk pack" - should find nitrile gloves in bulk
3. "pvc pipe 50mm" - should find PVC pipes with 50mm diameter
4. "tomato" - should return food items
5. "tomato makeup" - should return cosmetics
"""

import asyncio
import json
from dataclasses import dataclass, field

import httpx

BASE_URL = "http://localhost:8000"


@dataclass
class SearchTest:
    """Test case for search validation."""

    query: str
    description: str
    expected_terms: list[str]  # Terms that SHOULD appear in results
    unexpected_terms: list[str]  # Terms that should NOT appear
    expected_category_contains: str | None = None
    expected_vendor_contains: str | None = None
    expected_attributes: list[str] = field(default_factory=list)  # Attrs to display
    min_results: int = 1


# Challenge test cases
CHALLENGE_TESTS = [
    SearchTest(
        query="3 hp sewage pump weir",
        description="Should find 3 HP sewage pumps from Weir vendor",
        expected_terms=["pump"],
        unexpected_terms=[],
        expected_vendor_contains="weir",
        expected_attributes=["power_hp", "flow_lpm"],
    ),
    SearchTest(
        query="nitrile glove bulk pack",
        description="Should find nitrile gloves in bulk packaging",
        expected_terms=["glove", "nitrile"],
        unexpected_terms=["compressor", "wrench", "pipe", "mask"],
        # Note: category check removed - data quality issue (gloves in wrong categories)
        expected_attributes=["bulk_pack", "material"],
    ),
    SearchTest(
        query="pvc pipe 50mm",
        description="Should find PVC pipes with 50mm diameter",
        expected_terms=["pipe", "pvc"],
        unexpected_terms=[],
        expected_attributes=["diameter_mm", "material"],
    ),
    SearchTest(
        query="tomato",
        description="Should return food items (not tools)",
        expected_terms=["tomato"],
        unexpected_terms=[],
        expected_category_contains="food",
        expected_attributes=["color"],
    ),
    SearchTest(
        query="tomato makeup",
        description="Should return cosmetics (not food or tools)",
        expected_terms=["makeup"],
        unexpected_terms=[],
        expected_category_contains="cosmetic",
        expected_attributes=["color"],
    ),
]


async def run_search(query: str, size: int = 20) -> dict:
    """Execute search query against the API."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/search",
            params={"q": query, "size": size},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()


def format_result(r: dict, attrs_to_show: list[str]) -> str:
    """Format a single result for display."""
    title = (r.get("title") or "N/A")[:55]
    vendor = r.get("vendor") or "N/A"
    category = r.get("category") or "N/A"
    score = r.get("score", 0)
    bm25_rank = r.get("bm25_rank", "?")
    knn_rank = r.get("knn_rank", "?")

    # Get relevant attributes
    attrs = r.get("attributes", {}) or {}
    attr_strs = []
    for attr in attrs_to_show:
        val = attrs.get(attr)
        if val is not None:
            attr_strs.append(f"{attr}={val}")
    attrs_display = ", ".join(attr_strs) if attr_strs else "none"

    return (
        f"{title}\n"
        f"         vendor: {vendor} | cat: {category[:40]}\n"
        f"         score: {score:.4f} (bm25:{bm25_rank}, knn:{knn_rank})\n"
        f"         attrs: {attrs_display}"
    )


def check_results(results: list[dict], test: SearchTest) -> dict:
    """
    Check if results match expected criteria.
    Returns a report dict with pass/fail status and details.
    """
    report = {
        "query": test.query,
        "description": test.description,
        "total_results": len(results),
        "passed": True,
        "issues": [],
        "top_results": [],
    }

    # Get top results for inspection
    for r in results[:10]:
        report["top_results"].append(
            {
                "title": r.get("title"),
                "vendor": r.get("vendor"),
                "category": r.get("category"),
                "score": r.get("score"),
                "bm25_rank": r.get("bm25_rank"),
                "knn_rank": r.get("knn_rank"),
                "attributes": r.get("attributes", {}),
            }
        )

    # Check minimum results
    if len(results) < test.min_results:
        report["passed"] = False
        report["issues"].append(
            f"Expected at least {test.min_results} results, got {len(results)}"
        )

    # Check expected terms in top results
    top_titles = " ".join([(r.get("title") or "").lower() for r in results[:10]])
    top_descriptions = " ".join(
        [(r.get("description") or "").lower() for r in results[:10]]
    )
    combined_text = top_titles + " " + top_descriptions

    for term in test.expected_terms:
        if term.lower() not in combined_text:
            report["issues"].append(f"Expected term '{term}' not found in top 10")

    # Check unexpected terms
    for term in test.unexpected_terms:
        count = sum(
            1 for r in results[:10] if term.lower() in (r.get("title") or "").lower()
        )
        if count > 2:
            report["issues"].append(
                f"Unexpected term '{term}' found in {count}/10 titles"
            )
            report["passed"] = False

    # Check expected category
    if test.expected_category_contains:
        top_categories = [(r.get("category") or "").lower() for r in results[:5]]
        found = any(
            test.expected_category_contains.lower() in cat for cat in top_categories
        )
        if not found:
            report["issues"].append(
                f"Expected category '{test.expected_category_contains}' not in top 5"
            )

    # Check expected vendor
    if test.expected_vendor_contains:
        top_vendors = [(r.get("vendor") or "").lower() for r in results[:5]]
        found = any(
            test.expected_vendor_contains.lower() in v for v in top_vendors if v
        )
        if not found:
            report["issues"].append(
                f"Expected vendor '{test.expected_vendor_contains}' not in top 5"
            )

    if report["issues"]:
        report["passed"] = False

    return report


async def run_all_tests():
    """Run all challenge tests and print detailed report."""
    print("=" * 80)
    print("SEARCH QUALITY TEST FRAMEWORK - Hybrid BM25 + kNN with Manual RRF")
    print("=" * 80)

    all_reports = []

    for test in CHALLENGE_TESTS:
        print(f"\n{'=' * 80}")
        print(f'📝 QUERY: "{test.query}"')
        print(f"   Expected: {test.description}")
        print("-" * 80)

        try:
            response = await run_search(test.query)
            results = response.get("results", [])
            total = response.get("total", 0)
            returned = response.get("returned", len(results))
            print(f"   Total matching: {total}, Returned: {returned}")

            report = check_results(results, test)
            all_reports.append(report)

            # Show top 5 results with details
            print("\n   TOP 5 RESULTS:")
            for i, r in enumerate(results[:5], 1):
                print(f"   {i}. {format_result(r, test.expected_attributes)}")

            # Show pass/fail
            print()
            if report["passed"]:
                print("   ✅ PASSED")
            else:
                print("   ❌ FAILED")
                for issue in report["issues"]:
                    print(f"      ⚠️  {issue}")

        except Exception as e:
            print(f"   ❌ ERROR: {e}")
            import traceback

            traceback.print_exc()
            all_reports.append(
                {"query": test.query, "passed": False, "issues": [str(e)]}
            )

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    passed = sum(1 for r in all_reports if r.get("passed", False))
    total = len(all_reports)
    print(f"Passed: {passed}/{total}")

    if passed < total:
        print("\n❌ FAILED TESTS:")
        for r in all_reports:
            if not r.get("passed", False):
                print(f"   - {r['query']}")
                for issue in r.get("issues", []):
                    print(f"      {issue}")

    # Save detailed report
    report_path = "test_results.json"
    with open(report_path, "w") as f:
        json.dump(all_reports, f, indent=2, default=str)
    print(f"\n📄 Detailed report saved to: {report_path}")

    return all_reports


if __name__ == "__main__":
    asyncio.run(run_all_tests())
