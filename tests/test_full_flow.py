#!/usr/bin/env python3
"""
Full end-to-end Playwright tests for the Bitcoin Vault.
Tests the complete flow: create address, fund, fail before lock, succeed after lock.
Updated for the new modern crypto design.
"""
import asyncio
import requests
import time
from playwright.async_api import async_playwright

# RPC Proxy URL
PROXY_URL = "http://localhost:5001"
WEB_APP_URL = "http://localhost:8080/docs/index.html"


def btc_rpc(method, params=None):
    """Make RPC call via proxy"""
    response = requests.post(
        f"{PROXY_URL}/rpc",
        json={"method": method, "params": params or []}
    )
    result = response.json()
    if "error" in result and result["error"]:
        raise Exception(f"RPC Error: {result['error']}")
    return result.get("result")


def get_block_height():
    """Get current block height"""
    response = requests.get(f"{PROXY_URL}/block/height")
    return response.json().get("height", 0)


def mine_blocks(n):
    """Mine n blocks"""
    address = btc_rpc("getnewaddress", [])
    btc_rpc("generatetoaddress", [n, address])
    return get_block_height()


def send_to_address(address, amount):
    """Send BTC to address"""
    return btc_rpc("sendtoaddress", [address, amount])


def broadcast_tx(tx_hex):
    """Broadcast raw transaction"""
    response = requests.post(
        f"{PROXY_URL}/tx",
        data=tx_hex,
        headers={"Content-Type": "text/plain"}
    )
    if response.status_code != 200:
        return None, response.text
    return response.text, None


async def test_early_withdrawal_error():
    """Test that the web app shows proper error for early withdrawal attempts."""
    print("=" * 70)
    print("TEST: Early Withdrawal Error Detection")
    print("=" * 70)

    # Check proxy is running
    try:
        height = get_block_height()
        print(f"\n[Setup] Connected to regtest. Current block: {height}")
    except Exception as e:
        print(f"\n[FAIL] Cannot connect to proxy: {e}")
        return False

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Handle dialogs - capture the error message
        dialog_messages = []

        async def handle_dialog(dialog):
            dialog_messages.append(dialog.message)
            print(f"[Dialog] {dialog.message[:100]}...")
            await dialog.accept()

        page.on("dialog", handle_dialog)

        # Navigate to the page
        print("\n[Step 1] Loading web app...")
        await page.goto(WEB_APP_URL)
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)

        # Close welcome modal if visible
        modal_visible = await page.is_visible("#welcome-modal.active")
        if modal_visible:
            await page.click(".modal-close")
            await asyncio.sleep(0.5)
            print("[OK] Closed welcome modal")

        # Select regtest network
        print("\n[Step 2] Selecting regtest network...")
        await page.select_option("#network-selector", "regtest")
        await asyncio.sleep(2)

        # Create a vault with locktime far in the future
        current_height = get_block_height()
        locktime = current_height + 100  # 100 blocks in the future
        print(f"\n[Step 3] Creating vault with locktime {locktime} (current: {current_height})")
        await page.fill("#locktime", str(locktime))
        await page.click("#generate-btn")
        await asyncio.sleep(2)

        # Get generated data
        address = await page.input_value("#result-address")
        descriptor = await page.input_value("#result-descriptor")
        privkey_wif = await page.input_value("#result-privkey-wif")
        print(f"[OK] Vault address: {address}")

        # Fund the address
        print("\n[Step 4] Funding vault with 0.1 BTC...")
        txid = send_to_address(address, 0.1)
        mine_blocks(1)
        print(f"[OK] Funded: {txid}")

        # Set up withdrawal
        print("\n[Step 5] Setting up early withdrawal attempt...")
        await page.fill("#spend-descriptor", descriptor)
        await page.fill("#spend-privkey", privkey_wif)
        await page.fill("#utxo-address", address)

        dest_address = btc_rpc("getnewaddress", [])
        await page.fill("#destination", dest_address)

        # Fetch UTXOs - updated button text
        await page.click('button:has-text("Find Funds")')
        await asyncio.sleep(2)

        utxo_count = await page.text_content("#utxo-count")
        print(f"[OK] Found {utxo_count} UTXO(s)")

        # Try to create transaction - should show error about funds being locked
        print("\n[Step 6] Attempting early withdrawal (should fail)...")
        dialog_messages.clear()
        await page.click("#create-tx-btn")
        await asyncio.sleep(2)

        # Check for error dialog
        if dialog_messages:
            error_msg = dialog_messages[-1]
            print(f"[OK] Got error dialog")

            # Verify the error message contains the expected information
            checks = [
                ("Funds are still locked" in error_msg, "Should mention 'Funds are still locked'"),
                ("Current block" in error_msg, "Should show current block"),
                ("Unlock block" in error_msg, "Should show unlock block"),
                ("Blocks remaining" in error_msg, "Should show blocks remaining"),
                ("Estimated wait" in error_msg, "Should show estimated wait time"),
            ]

            all_passed = True
            for check, msg in checks:
                status = "PASS" if check else "FAIL"
                print(f"  [{status}] {msg}")
                if not check:
                    all_passed = False

            # Check time formatting includes larger units for 100 blocks
            # 100 blocks * 10 min = 1000 min = ~16.6 hours
            if "hour" in error_msg.lower():
                print(f"  [PASS] Time estimate includes hours")
            else:
                print(f"  [WARN] Time estimate may not show hours for 100 blocks")

            if all_passed:
                print("\n[PASS] Early withdrawal error test passed!")
            else:
                print("\n[FAIL] Some checks failed")
                print(f"Full error message:\n{error_msg}")
                await browser.close()
                return False
        else:
            print("[FAIL] No error dialog shown - transaction was created when it shouldn't have been")
            await browser.close()
            return False

        await browser.close()
        return True


async def test_full_flow():
    """Test the complete timelock wallet flow."""
    print("=" * 70)
    print("FULL END-TO-END TEST: Bitcoin Vault")
    print("=" * 70)

    # Check proxy is running
    try:
        height = get_block_height()
        print(f"\n[Setup] Connected to regtest. Current block: {height}")
    except Exception as e:
        print(f"\n[FAIL] Cannot connect to proxy: {e}")
        print("Make sure the RPC proxy is running: python rpc-proxy/proxy_server.py")
        return False

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Capture errors
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))

        # Handle dialogs
        dialog_messages = []

        async def handle_dialog(dialog):
            dialog_messages.append(dialog.message)
            await dialog.accept()

        page.on("dialog", handle_dialog)

        # Navigate to the page
        print("\n[Step 1] Loading web app...")
        await page.goto(WEB_APP_URL)
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)

        # Check libraries loaded
        tapscript_loaded = await page.evaluate("() => window.tapscript !== undefined")
        secp_loaded = await page.evaluate("() => window.nobleSecp256k1 !== undefined")
        if not tapscript_loaded or not secp_loaded:
            print(f"[FAIL] Libraries not loaded. Tapscript: {tapscript_loaded}, Secp: {secp_loaded}")
            await browser.close()
            return False
        print("[OK] Libraries loaded")

        # Close welcome modal if visible
        modal_visible = await page.is_visible("#welcome-modal.active")
        if modal_visible:
            await page.click(".modal-close")
            await asyncio.sleep(0.5)
            print("[OK] Closed welcome modal")

        # Step 2: Select regtest network (in header)
        print("\n[Step 2] Selecting regtest network...")
        await page.select_option("#network-selector", "regtest")
        await asyncio.sleep(2)  # Wait for connection

        # Verify connection by checking block height is shown
        block_display = await page.text_content("#header-block-height")
        print(f"[OK] Network connected, block: {block_display}")

        # Step 3: Calculate locktime (current + 5 blocks)
        current_height = get_block_height()
        locktime = current_height + 5
        print(f"\n[Step 3] Setting locktime to {locktime} (current: {current_height}, +5 blocks)")
        await page.fill("#locktime", str(locktime))
        await asyncio.sleep(0.5)

        # Step 4: Generate address
        print("\n[Step 4] Creating vault address...")
        await page.click("#generate-btn")
        await asyncio.sleep(2)

        if dialog_messages:
            print(f"[FAIL] Error dialog: {dialog_messages[-1]}")
            await browser.close()
            return False

        # Get generated data
        address = await page.input_value("#result-address")
        descriptor = await page.input_value("#result-descriptor")
        privkey_wif = await page.input_value("#result-privkey-wif")

        if not address.startswith("bcrt1p"):
            print(f"[FAIL] Address has wrong prefix: {address}")
            await browser.close()
            return False

        print(f"[OK] Vault Address: {address}")
        print(f"[OK] Vault Blueprint: {descriptor[:60]}...")

        # Check for the Network-Enforced Lock info box
        info_box = await page.is_visible(".alert-info")
        if info_box:
            info_text = await page.text_content(".alert-info")
            if "Network-Enforced" in info_text:
                print("[OK] Network-enforced lock info box displayed")

        # Step 5: Fund the address
        print("\n[Step 5] Funding vault with 0.1 BTC...")
        try:
            txid = send_to_address(address, 0.1)
            print(f"[OK] Funding TX: {txid}")
        except Exception as e:
            print(f"[FAIL] Could not fund address: {e}")
            await browser.close()
            return False

        # Mine 1 block to confirm
        mine_blocks(1)
        print(f"[OK] Mined 1 block. Height: {get_block_height()}")

        # Step 6: Set up spend section
        print("\n[Step 6] Setting up withdrawal...")
        await page.fill("#spend-descriptor", descriptor)
        await page.fill("#spend-privkey", privkey_wif)
        await page.fill("#utxo-address", address)

        # Get a destination address
        dest_address = btc_rpc("getnewaddress", [])
        await page.fill("#destination", dest_address)
        print(f"[OK] Destination: {dest_address}")

        # Fetch UTXOs - button text updated to "Find Funds"
        print("\n[Step 7] Finding funds...")
        await page.click('button:has-text("Find Funds")')
        await asyncio.sleep(2)

        utxo_count = await page.text_content("#utxo-count")
        total_sats = await page.text_content("#total-sats")
        print(f"[OK] Found {utxo_count} digital bill(s), total: {total_sats} sats")

        if utxo_count == "0":
            print("[FAIL] No funds found")
            await browser.close()
            return False

        # Step 8: Create transaction
        print("\n[Step 8] Preparing withdrawal...")
        dialog_messages.clear()
        await page.click("#create-tx-btn")
        await asyncio.sleep(3)

        if dialog_messages:
            # Check if this is a "funds still locked" error (which is expected behavior)
            if "still locked" in dialog_messages[-1].lower():
                print(f"[INFO] Got expected 'funds locked' error (current block < locktime)")
                # Mine blocks to reach locktime
                current = get_block_height()
                blocks_needed = locktime - current + 1
                print(f"[Step 8b] Mining {blocks_needed} blocks to reach locktime...")
                mine_blocks(blocks_needed)
                new_height = get_block_height()
                print(f"[OK] New height: {new_height}")

                # Wait for the web app to update its cached block height
                # The app polls every second, so wait a bit
                await asyncio.sleep(3)

                # Verify the page has the updated height
                page_height = await page.text_content("#header-block-height")
                print(f"[OK] Page block height updated to: {page_height}")

                # Retry creating transaction
                dialog_messages.clear()
                await page.click("#create-tx-btn")
                await asyncio.sleep(3)

                if dialog_messages:
                    print(f"[FAIL] Error creating TX: {dialog_messages[-1]}")
                    await browser.close()
                    return False
            else:
                print(f"[FAIL] Error creating TX: {dialog_messages[-1]}")
                await browser.close()
                return False

        # Get raw transaction
        raw_tx = await page.input_value("#result-rawtx")
        if not raw_tx:
            print("[FAIL] No raw transaction generated")
            await browser.close()
            return False

        tx_vsize = await page.text_content("#result-vsize")
        tx_fee = await page.text_content("#result-fee")
        output_amount = await page.text_content("#result-output")
        print(f"[OK] Transaction prepared: {tx_vsize} vB, {tx_fee} sat fee, {output_amount} sats output")

        # Step 9: Ensure we're past locktime
        current = get_block_height()
        if current < locktime:
            blocks_needed = locktime - current + 1
            print(f"\n[Step 9] Mining {blocks_needed} blocks to reach locktime...")
            mine_blocks(blocks_needed)
            print(f"[OK] Height: {get_block_height()} (locktime was {locktime})")

        # Step 10: Broadcast using slide-to-confirm
        print(f"\n[Step 10] Broadcasting transaction...")

        # The new UI uses slide-to-confirm, but we can also broadcast via API for testing
        txid, error = broadcast_tx(raw_tx)
        if error:
            print(f"[FAIL] Transaction rejected: {error}")
            await browser.close()
            return False

        print(f"[OK] Transaction broadcast! TXID: {txid}")

        # Mine 1 more block to confirm
        mine_blocks(1)
        print(f"[OK] Mined confirmation block. Final height: {get_block_height()}")

        await browser.close()

        print("\n" + "=" * 70)
        print("ALL TESTS PASSED!")
        print("=" * 70)
        return True


async def test_time_formatting():
    """Test that time estimates include years, months, days, hours."""
    print("=" * 70)
    print("TEST: Time Formatting in Error Messages")
    print("=" * 70)

    try:
        height = get_block_height()
        print(f"\n[Setup] Current block: {height}")
    except Exception as e:
        print(f"\n[FAIL] Cannot connect to proxy: {e}")
        return False

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        dialog_messages = []

        async def handle_dialog(dialog):
            dialog_messages.append(dialog.message)
            await dialog.accept()

        page.on("dialog", handle_dialog)

        await page.goto(WEB_APP_URL)
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)

        # Close modal
        modal_visible = await page.is_visible("#welcome-modal.active")
        if modal_visible:
            await page.click(".modal-close")
            await asyncio.sleep(0.5)

        await page.select_option("#network-selector", "regtest")
        await asyncio.sleep(2)

        # Create vault with locktime ~1 year in future
        # 1 year = 365 * 24 * 6 blocks = 52,560 blocks (at 10 min/block)
        current_height = get_block_height()
        locktime = current_height + 60000  # ~1.14 years
        print(f"\n[Test] Creating vault with locktime {locktime} ({60000} blocks ahead)")
        await page.fill("#locktime", str(locktime))
        await page.click("#generate-btn")
        await asyncio.sleep(2)

        address = await page.input_value("#result-address")
        descriptor = await page.input_value("#result-descriptor")
        privkey_wif = await page.input_value("#result-privkey-wif")

        # Fund minimally
        send_to_address(address, 0.001)
        mine_blocks(1)

        # Set up withdrawal
        await page.fill("#spend-descriptor", descriptor)
        await page.fill("#spend-privkey", privkey_wif)
        await page.fill("#utxo-address", address)
        await page.fill("#destination", btc_rpc("getnewaddress", []))

        await page.click('button:has-text("Find Funds")')
        await asyncio.sleep(2)

        # Try to withdraw
        dialog_messages.clear()
        await page.click("#create-tx-btn")
        await asyncio.sleep(2)

        if dialog_messages:
            error_msg = dialog_messages[-1]
            print(f"\n[OK] Got error message")

            # Check for year/month formatting
            has_year = "year" in error_msg.lower()
            has_month = "month" in error_msg.lower()

            print(f"  Contains 'year': {has_year}")
            print(f"  Contains 'month': {has_month}")

            if has_year:
                print("[PASS] Time formatting includes years!")
            else:
                print("[WARN] Time formatting might not include years for this block count")
                print(f"Error message: {error_msg}")

            await browser.close()
            return has_year
        else:
            print("[FAIL] No error dialog shown")
            await browser.close()
            return False


async def main():
    results = {}

    # Test 1: Early withdrawal error
    print("\n" + "=" * 70)
    print("RUNNING TEST 1: Early Withdrawal Error Detection")
    print("=" * 70)
    results["early_withdrawal"] = await test_early_withdrawal_error()

    # Test 2: Time formatting
    print("\n" + "=" * 70)
    print("RUNNING TEST 2: Time Formatting")
    print("=" * 70)
    results["time_formatting"] = await test_time_formatting()

    # Test 3: Full flow
    print("\n" + "=" * 70)
    print("RUNNING TEST 3: Full Flow")
    print("=" * 70)
    results["full_flow"] = await test_full_flow()

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    all_passed = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("=" * 70)
    if all_passed:
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED")
    print("=" * 70)

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
