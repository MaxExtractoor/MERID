"""Test fee calculation against Kalshi official formula."""
from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents

# Test cases from Kalshi official documentation
test_cases = [
    # (contracts, price_cents, expected_fee_cents, description)
    (1, 11, 1, "1 contract @ 11¢ should be 1¢"),
    (100, 11, 7, "100 contracts @ 11¢ should be 7¢"),
    (1, 50, 2, "1 contract @ 50¢ should be 2¢"),
    (100, 50, 175, "100 contracts @ 50¢ should be 175¢"),
]

print("Testing Kalshi fee calculation...")
print("=" * 60)

for contracts, price_cents, expected_fee, description in test_cases:
    actual_fee = calculate_kalshi_fee_cents(contracts, price_cents)
    status = "PASS" if actual_fee == expected_fee else "FAIL"
    print(f"{status} {description}")
    print(f"  Expected: {expected_fee}c, Actual: {actual_fee}c")
    if actual_fee != expected_fee:
        # Calculate what the formula should give
        p = price_cents / 100.0
        rate = 0.07 if contracts < 100 else (0.05 if contracts < 1000 else 0.03)
        raw = rate * contracts * p * (1 - p)
        fee_dollars = __import__('math').ceil(raw)
        fee_cents = int(fee_dollars * 100)
        print(f"  Formula check: rate={rate}, P={p}, raw={raw:.6f}, fee_dollars={fee_dollars}, fee_cents={fee_cents}")
    print()

print("=" * 60)
print("Testing the specific case from logs (11c, 1 contract)...")
fee_11c_1contract = calculate_kalshi_fee_cents(1, 11)
print(f"1 contract @ 11c: {fee_11c_1contract}c")
print(f"Expected: 1c (from user analysis)")
print(f"Status: {'PASS' if fee_11c_1contract == 1 else 'FAIL'}")
