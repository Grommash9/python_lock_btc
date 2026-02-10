#!/usr/bin/env python3
"""
Full end-to-end Playwright tests for the Bitcoin Timelock Wallet.
Tests the complete flow: create address, fund, fail before lock, succeed after lock.
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


async def test_full_flow():
    """Test the complete timelock wallet flow."""
    print("=" * 70)
    print("FULL END-TO-END TEST: Bitcoin Timelock Wallet")
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
            await page.click(".modal-close-btn")
            await asyncio.sleep(0.5)
            print("[OK] Closed welcome modal")

        # Step 2: Select regtest network (now in header)
        print("\n[Step 2] Selecting regtest network...")
        await page.select_option("#network-selector", "regtest")
        await asyncio.sleep(2)  # Wait for connection

        # Verify connection
        status_text = await page.text_content("#status-text")
        print(f"[OK] Network status: {status_text}")

        # Step 3: Calculate locktime (current + 5 blocks)
        current_height = get_block_height()
        locktime = current_height + 5
        print(f"\n[Step 3] Setting locktime to {locktime} (current: {current_height}, +5 blocks)")
        await page.fill("#locktime", str(locktime))
        await asyncio.sleep(0.5)

        # Step 4: Generate address
        print("\n[Step 4] Generating timelocked address...")
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

        print(f"[OK] Address: {address}")
        print(f"[OK] Descriptor: {descriptor[:60]}...")

        # Step 5: Fund the address
        print("\n[Step 5] Funding address with 0.1 BTC...")
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

        # Step 6: Manually set up spend section (no more "Use in Spend Section" button)
        print("\n[Step 6] Setting up spend transaction...")

        # Fill in spend section fields from the create results
        await page.fill("#spend-descriptor", descriptor)
        await page.fill("#spend-privkey", privkey_wif)
        await page.fill("#utxo-address", address)

        # Get a destination address
        dest_address = btc_rpc("getnewaddress", [])
        await page.fill("#destination", dest_address)
        print(f"[OK] Destination: {dest_address}")

        # Fetch UTXOs
        print("\n[Step 7] Fetching UTXOs...")
        await page.click('button:has-text("Fetch")')
        await asyncio.sleep(2)

        utxo_count = await page.text_content("#utxo-count")
        total_sats = await page.text_content("#total-sats")
        print(f"[OK] Found {utxo_count} UTXO(s), total: {total_sats} sats")

        if utxo_count == "0":
            print("[FAIL] No UTXOs found")
            await browser.close()
            return False

        # Step 8: Create transaction
        print("\n[Step 8] Creating spend transaction...")
        dialog_messages.clear()
        await page.click("#create-tx-btn")
        await asyncio.sleep(3)

        if dialog_messages:
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
        print(f"[OK] Transaction created: {tx_vsize} vB, {tx_fee} sat fee")
        print(f"[OK] Raw TX: {raw_tx[:60]}...")

        # Step 9: Try to broadcast BEFORE locktime (should fail)
        print(f"\n[Step 9] Trying to broadcast BEFORE locktime (block {get_block_height()} < {locktime})...")
        txid, error = broadcast_tx(raw_tx)
        if txid:
            print(f"[FAIL] Transaction was accepted! Should have been rejected. TXID: {txid}")
            await browser.close()
            return False
        if "non-final" in str(error).lower():
            print(f"[OK] Correctly rejected with: {error.strip()}")
        else:
            print(f"[WARN] Rejected but with unexpected error: {error}")

        # Step 10: Mine blocks to reach locktime
        current = get_block_height()
        blocks_needed = locktime - current + 1
        print(f"\n[Step 10] Mining {blocks_needed} blocks to reach locktime...")
        new_height = mine_blocks(blocks_needed)
        print(f"[OK] New height: {new_height} (locktime was {locktime})")

        # Step 11: Broadcast AFTER locktime (should succeed)
        print(f"\n[Step 11] Broadcasting AFTER locktime...")
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


async def main():
    success = await test_full_flow()
    exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
