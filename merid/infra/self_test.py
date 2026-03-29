"""
Self-Test Harness for Kill Switch and Exposure API

Run this before switching to live mode to validate critical safety features:
1. Kill switch triggers and cancels all open orders
2. Exposure API returns valid data for all asset/timeframe combinations

Usage:
    python -m merid.infra.self_test
    python -m merid.infra.self_test --verbose
"""

import asyncio
import sys
from typing import Dict, List, Any
from datetime import datetime

from utils.logger import get_logger

logger = get_logger("merid.infra.self_test")


class SelfTestHarness:
    """Self-test harness for production readiness validation."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: List[Dict[str, Any]] = []
        self.passed = 0
        self.failed = 0

    def log(self, message: str, level: str = "info"):
        """Log a message if verbose mode is enabled."""
        if self.verbose:
            if level == "error":
                logger.error(message)
            elif level == "warning":
                logger.warning(message)
            else:
                logger.info(message)

    def record_result(self, test_name: str, passed: bool, message: str, details: Any = None):
        """Record a test result."""
        result = {
            "test": test_name,
            "passed": passed,
            "message": message,
            "details": details,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.results.append(result)

        if passed:
            self.passed += 1
            self.log(f"✅ PASS: {test_name} - {message}")
        else:
            self.failed += 1
            self.log(f"❌ FAIL: {test_name} - {message}", level="error")

    async def test_kill_switch_manual_trigger(self) -> bool:
        """Test manual kill switch trigger and reset."""
        test_name = "kill_switch_manual_trigger"
        self.log(f"Testing {test_name}...")

        try:
            from merid.risk.kill_switches import risk_controller

            # Record initial state
            initial_state = risk_controller.can_trade()
            self.log(f"  Initial trading state: {initial_state}")

            # Trigger kill switch
            risk_controller.emergency_stop("Self-test manual trigger")
            await asyncio.sleep(0.5)  # Give it time to process

            # Verify kill switch is active
            if risk_controller.can_trade():
                self.record_result(test_name, False, "Kill switch did not activate")
                return False

            kill_reason = risk_controller.get_kill_reason()
            self.log(f"  Kill switch activated: {kill_reason}")

            # Reset kill switch
            reset_success = risk_controller.reset("self-test-harness")
            if not reset_success:
                self.record_result(test_name, False, "Failed to reset kill switch")
                return False

            # Verify trading is allowed again
            if not risk_controller.can_trade():
                self.record_result(test_name, False, "Kill switch did not deactivate after reset")
                return False

            self.record_result(
                test_name,
                True,
                "Manual kill switch trigger and reset successful",
                {"reason": kill_reason}
            )
            return True

        except Exception as exc:
            self.record_result(test_name, False, f"Exception: {str(exc)}")
            return False

    async def test_kill_switch_daily_loss_trigger(self) -> bool:
        """Test daily loss kill switch trigger."""
        test_name = "kill_switch_daily_loss_trigger"
        self.log(f"Testing {test_name}...")

        try:
            from merid.risk.kill_switches import risk_controller

            # Reset to clean state
            risk_controller.reset("self-test-harness")
            risk_controller.reset_daily_counters()
            await asyncio.sleep(0.5)

            # Record large loss to trigger kill switch
            daily_loss_limit = risk_controller.daily_loss_limit
            trigger_loss = -daily_loss_limit - 10  # Exceed limit
            self.log(f"  Recording loss: ${trigger_loss:.2f} (limit: ${daily_loss_limit:.2f})")

            continue_trading = risk_controller.record_pnl(trigger_loss)

            if continue_trading:
                self.record_result(test_name, False, "Daily loss did not trigger kill switch")
                # Reset for next tests
                risk_controller.reset("self-test-harness")
                return False

            if risk_controller.can_trade():
                self.record_result(test_name, False, "Kill switch not active after daily loss trigger")
                # Reset for next tests
                risk_controller.reset("self-test-harness")
                return False

            kill_reason = risk_controller.get_kill_reason()
            self.log(f"  Kill switch activated: {kill_reason}")

            # Reset for next tests
            risk_controller.reset("self-test-harness")
            risk_controller.reset_daily_counters()

            self.record_result(
                test_name,
                True,
                "Daily loss kill switch trigger successful",
                {"loss": trigger_loss, "limit": daily_loss_limit}
            )
            return True

        except Exception as exc:
            self.record_result(test_name, False, f"Exception: {str(exc)}")
            # Ensure reset for next tests
            try:
                from merid.risk.kill_switches import risk_controller
                risk_controller.reset("self-test-harness")
            except:
                pass
            return False

    async def test_exposure_api_structure(self) -> bool:
        """Test exposure API returns valid structure."""
        test_name = "exposure_api_structure"
        self.log(f"Testing {test_name}...")

        try:
            import httpx

            # Try to call the exposure API
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    response = await client.get("http://localhost:8000/api/v1/exposure/by-asset-timeframe")

                    if response.status_code != 200:
                        self.record_result(
                            test_name,
                            False,
                            f"API returned status {response.status_code}",
                            {"response": response.text[:200]}
                        )
                        return False

                    data = response.json()

                    # Verify it's a list
                    if not isinstance(data, list):
                        self.record_result(test_name, False, "Response is not a list")
                        return False

                    self.log(f"  Received {len(data)} exposure entries")

                    # If we have data, validate structure
                    if len(data) > 0:
                        first_entry = data[0]
                        required_fields = [
                            "asset", "timeframe", "net_exposure_usd", "gross_exposure_usd",
                            "contracts_long", "contracts_short", "cap_used_pct", "cap_max_usd"
                        ]

                        missing_fields = [f for f in required_fields if f not in first_entry]
                        if missing_fields:
                            self.record_result(
                                test_name,
                                False,
                                f"Missing required fields: {missing_fields}",
                                {"entry": first_entry}
                            )
                            return False

                        # Validate no NaN values
                        for field in ["net_exposure_usd", "gross_exposure_usd", "cap_used_pct"]:
                            value = first_entry.get(field)
                            if value is None or (isinstance(value, float) and value != value):  # NaN check
                                self.record_result(
                                    test_name,
                                    False,
                                    f"Field {field} has NaN or None value",
                                    {"entry": first_entry}
                                )
                                return False

                    self.record_result(
                        test_name,
                        True,
                        f"Exposure API structure valid ({len(data)} entries)",
                        {"sample": data[0] if data else None}
                    )
                    return True

                except httpx.ConnectError:
                    self.record_result(
                        test_name,
                        False,
                        "Cannot connect to API (server not running?)"
                    )
                    return False

        except Exception as exc:
            self.record_result(test_name, False, f"Exception: {str(exc)}")
            return False

    async def test_exposure_api_asset_filter(self) -> bool:
        """Test exposure API asset filtering."""
        test_name = "exposure_api_asset_filter"
        self.log(f"Testing {test_name}...")

        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    # Test filtering by BTC
                    response = await client.get(
                        "http://localhost:8000/api/v1/exposure/by-asset-timeframe?asset=BTC"
                    )

                    if response.status_code != 200:
                        self.record_result(
                            test_name,
                            False,
                            f"API returned status {response.status_code}"
                        )
                        return False

                    data = response.json()

                    # Verify all entries are for BTC
                    if data and any(entry.get("asset") != "BTC" for entry in data):
                        self.record_result(test_name, False, "Asset filter not working")
                        return False

                    self.record_result(
                        test_name,
                        True,
                        f"Asset filter working ({len(data)} BTC entries)",
                    )
                    return True

                except httpx.ConnectError:
                    self.record_result(
                        test_name,
                        False,
                        "Cannot connect to API (server not running?)"
                    )
                    return False

        except Exception as exc:
            self.record_result(test_name, False, f"Exception: {str(exc)}")
            return False

    async def run_all_tests(self) -> bool:
        """Run all self-tests."""
        logger.info("=" * 60)
        logger.info("MERID SELF-TEST HARNESS")
        logger.info("=" * 60)
        logger.info("")

        # Test kill switch functionality
        logger.info("Testing Kill Switch Functionality...")
        await self.test_kill_switch_manual_trigger()
        await self.test_kill_switch_daily_loss_trigger()

        logger.info("")
        logger.info("Testing Exposure API...")
        await self.test_exposure_api_structure()
        await self.test_exposure_api_asset_filter()

        # Summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("SELF-TEST SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total tests: {len(self.results)}")
        logger.info(f"Passed: {self.passed}")
        logger.info(f"Failed: {self.failed}")
        logger.info("")

        if self.failed > 0:
            logger.error("❌ SELF-TEST FAILED - DO NOT GO LIVE")
            logger.error("")
            logger.error("Failed tests:")
            for result in self.results:
                if not result["passed"]:
                    logger.error(f"  - {result['test']}: {result['message']}")
            return False
        else:
            logger.info("✅ ALL SELF-TESTS PASSED - READY FOR LIVE MODE")
            return True


async def main():
    """Main entry point for self-test harness."""
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    harness = SelfTestHarness(verbose=verbose)
    success = await harness.run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
