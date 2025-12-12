"""
Test script for Task 4 - User-Level Customization and Boosting.

Demonstrates how the search results change based on user purchase history.

Two personas:
1. user_135 - Industrial Worker: Buys pumps, pipes, compressors, masks
2. user_017 - Diverse Buyer: Buys wrenches, makeup, gloves, pipes

The same query should return different rankings based on the user's history.
"""

import asyncio

import httpx

BASE_URL = "http://localhost:8000"

# User personas based on actual order history
PERSONAS = {
    "user_135": {
        "name": "Industrial Worker",
        "description": "Buys industrial equipment: pumps, pipes, compressors, masks",
        "top_purchases": [
            ("Respirator Mask abrasive bulk pack", 49),
            ("Air Compressor kit", 45),
            ("Industrial Lubricant 3 hp", 23),
            ("PVC Pipe waterproof", 14),
            ("Water Pump", 7),
        ],
    },
    "user_017": {
        "name": "Diverse Buyer",
        "description": "Buys variety: wrenches, makeup, gloves, pipes",
        "top_purchases": [
            ("Adjustable Wrench color blue", 73),
            ("tomato coloured makeup", 53),
            ("Power Cord", 50),
            ("PVC Pipe PVC industrial", 50),
            ("Nitrile Gloves industrial grade", 50),
        ],
    },
}

# Test queries that should show different results based on user
TEST_QUERIES = [
    "pipe",          # Both users buy pipes - check ordering
    "pump",          # user_135 buys pumps, user_017 doesn't
    "gloves",        # user_017 buys gloves, user_135 buys masks
    "makeup",        # user_017 buys makeup, user_135 doesn't
    "industrial",    # Both have industrial purchases
]


async def search(query: str, user_id: str | None = None, size: int = 5) -> dict:
    """Execute search query with optional user_id."""
    async with httpx.AsyncClient() as client:
        params = {"q": query, "size": size}
        if user_id:
            params["user_id"] = user_id
        response = await client.get(f"{BASE_URL}/search", params=params, timeout=30.0)
        response.raise_for_status()
        return response.json()


def format_result(r: dict) -> str:
    """Format a single result for display."""
    title = (r.get("title") or "N/A")[:50]
    score = r.get("score", 0)
    
    # Check if user boosted
    user_boost = r.get("user_boost")
    user_orders = r.get("user_orders")
    
    if user_boost and user_boost > 1.0:
        return f"{title}  [score: {score:.4f}, BOOSTED {user_boost}x, {user_orders} orders]"
    return f"{title}  [score: {score:.4f}]"


async def run_comparison():
    """Run comparison tests for both personas."""
    print("=" * 90)
    print("TASK 4: USER-LEVEL CUSTOMIZATION AND BOOSTING")
    print("=" * 90)
    
    # Print persona info
    for user_id, info in PERSONAS.items():
        print(f"\n📋 {user_id} - {info['name']}")
        print(f"   {info['description']}")
        print("   Top purchases:")
        for product, qty in info["top_purchases"][:3]:
            print(f"      - {product[:45]}: {qty} items")
    
    print("\n" + "=" * 90)
    print("SEARCH COMPARISON")
    print("=" * 90)
    
    for query in TEST_QUERIES:
        print(f"\n{'='*90}")
        print(f"🔍 QUERY: \"{query}\"")
        print("-" * 90)
        
        # Search without user (baseline)
        print("\n📊 NO USER (baseline):")
        try:
            result = await search(query, user_id=None)
            for i, r in enumerate(result["results"][:3], 1):
                print(f"   {i}. {format_result(r)}")
        except Exception as e:
            print(f"   ERROR: {e}")
        
        # Search for each persona
        for user_id, info in PERSONAS.items():
            print(f"\n👤 {user_id} ({info['name']}):")
            try:
                result = await search(query, user_id=user_id)
                for i, r in enumerate(result["results"][:3], 1):
                    print(f"   {i}. {format_result(r)}")
            except Exception as e:
                print(f"   ERROR: {e}")
    
    print("\n" + "=" * 90)
    print("ANALYSIS")
    print("=" * 90)
    print("""
The boosting logic applies multipliers based on order quantity:
  - 1-5 orders:   1.2x boost
  - 6-20 orders:  1.5x boost  
  - 21-50 orders: 2.0x boost
  - 50+ orders:   2.5x boost

Products the user has ordered before get boosted in search results,
with higher boosts for products they order frequently.
""")


if __name__ == "__main__":
    asyncio.run(run_comparison())

