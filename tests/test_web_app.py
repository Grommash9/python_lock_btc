#!/usr/bin/env python3
"""
Playwright tests for the Bitcoin Timelock Wallet web application.
"""
import asyncio
import subprocess
import time
from playwright.async_api import async_playwright


async def test_page_loads():
    """Test that the page loads and libraries are initialized."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Capture console messages
        console_messages = []
        page.on("console", lambda msg: console_messages.append(f"{msg.type}: {msg.text}"))

        # Capture errors
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))

        # Navigate to the page
        await page.goto("http://localhost:8080/docs/index.html")

        # Wait for page to load
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)  # Extra time for ES modules to load

        # Check console messages
        print("\n=== Console Messages ===")
        for msg in console_messages:
            print(msg)

        # Check errors
        print("\n=== Page Errors ===")
        for err in errors:
            print(f"ERROR: {err}")

        # Check if libraries are loaded
        tapscript_loaded = await page.evaluate("() => window.tapscript !== undefined")
        secp_loaded = await page.evaluate("() => window.nobleSecp256k1 !== undefined")

        print(f"\n=== Library Status ===")
        print(f"Tapscript loaded: {tapscript_loaded}")
        print(f"Noble-secp256k1 loaded: {secp_loaded}")

        # Check what tapscript exports
        if tapscript_loaded:
            exports = await page.evaluate("""() => {
                const ts = window.tapscript;
                return {
                    keys: Object.keys(ts),
                    Address: typeof ts.Address,
                    Script: typeof ts.Script,
                    Signer: typeof ts.Signer,
                    Tap: typeof ts.Tap,
                    Tx: typeof ts.Tx
                };
            }""")
            print(f"\n=== Tapscript Exports ===")
            print(f"Keys: {exports['keys']}")
            print(f"Address: {exports['Address']}")
            print(f"Script: {exports['Script']}")
            print(f"Signer: {exports['Signer']}")
            print(f"Tap: {exports['Tap']}")
            print(f"Tx: {exports['Tx']}")

        await browser.close()

        return tapscript_loaded and secp_loaded


async def test_generate_address():
    """Test generating a timelocked address."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Capture errors and console
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))

        # Navigate to the page
        await page.goto("http://localhost:8080/docs/index.html")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)

        # Close welcome modal if visible
        modal_visible = await page.is_visible("#welcome-modal.active")
        if modal_visible:
            await page.click(".modal-close-btn")
            await asyncio.sleep(0.5)

        # Select regtest network (now in header)
        await page.select_option("#network-selector", "regtest")
        await asyncio.sleep(2)

        # Debug: Check what Address.p2tr.fromPubKey does
        debug_info = await page.evaluate("""() => {
            const { Address } = window.tapscript;
            // Check what methods exist
            const p2trMethods = Address.p2tr ? Object.keys(Address.p2tr) : [];

            // Test with a dummy key
            const testKey = '50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0';

            // Try different ways to encode
            let results = {};
            try {
                results.default = Address.p2tr.fromPubKey(testKey);
            } catch(e) {
                results.default_error = e.message;
            }
            try {
                results.with_bc = Address.p2tr.fromPubKey(testKey, 'bc');
            } catch(e) {
                results.with_bc_error = e.message;
            }
            try {
                results.with_bcrt = Address.p2tr.fromPubKey(testKey, 'bcrt');
            } catch(e) {
                results.with_bcrt_error = e.message;
            }
            try {
                // Maybe it uses network names instead of HRP?
                results.with_regtest = Address.p2tr.fromPubKey(testKey, 'regtest');
            } catch(e) {
                results.with_regtest_error = e.message;
            }

            return {
                p2trMethods,
                results
            };
        }""")
        print("\n=== Debug: Address.p2tr methods ===")
        print(f"Methods: {debug_info['p2trMethods']}")
        print(f"Results: {debug_info['results']}")

        # Fill in the locktime
        await page.fill("#locktime", "200")

        # Click generate button
        print("\n=== Clicking Generate Button ===")

        # Handle alert dialogs
        dialog_message = None

        async def handle_dialog(dialog):
            nonlocal dialog_message
            dialog_message = dialog.message
            print(f"Dialog: {dialog_message}")
            await dialog.accept()

        page.on("dialog", handle_dialog)

        await page.click("#generate-btn")
        await asyncio.sleep(2)

        if dialog_message:
            print(f"Error dialog: {dialog_message}")
        else:
            # Check if results are shown
            results_visible = await page.is_visible("#create-results")
            print(f"Results visible: {results_visible}")

            if results_visible:
                address = await page.input_value("#result-address")
                descriptor = await page.input_value("#result-descriptor")
                print(f"Address: {address}")
                print(f"Descriptor: {descriptor[:80]}...")

        print("\n=== Page Errors ===")
        for err in errors:
            print(f"ERROR: {err}")

        await browser.close()


async def main():
    print("=" * 60)
    print("Testing Bitcoin Timelock Wallet Web App")
    print("=" * 60)

    # Test 1: Page loads
    print("\n[Test 1] Page Load & Library Check")
    success = await test_page_loads()
    print(f"Result: {'PASS' if success else 'FAIL'}")

    # Test 2: Generate address
    print("\n[Test 2] Generate Address")
    await test_generate_address()


if __name__ == "__main__":
    asyncio.run(main())
