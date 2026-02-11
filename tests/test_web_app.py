#!/usr/bin/env python3
"""
Playwright tests for the Bitcoin Vault web application.
Updated for the new modern crypto design.
"""
import asyncio
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

        # Close welcome modal if visible (click outside or on button)
        modal_visible = await page.is_visible("#welcome-modal.active")
        if modal_visible:
            # New design: click the button inside modal
            await page.click(".modal-close")
            await asyncio.sleep(0.5)
            print("[OK] Closed welcome modal")

        # Select regtest network (in header)
        await page.select_option("#network-selector", "regtest")
        await asyncio.sleep(2)

        # Debug: Check what Address.p2tr.fromPubKey does
        debug_info = await page.evaluate("""() => {
            const { Address } = window.tapscript;
            const p2trMethods = Address.p2tr ? Object.keys(Address.p2tr) : [];
            const testKey = '50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0';
            let results = {};
            try {
                results.default = Address.p2tr.fromPubKey(testKey);
            } catch(e) {
                results.default_error = e.message;
            }
            try {
                results.with_regtest = Address.p2tr.fromPubKey(testKey, 'regtest');
            } catch(e) {
                results.with_regtest_error = e.message;
            }
            return { p2trMethods, results };
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


async def test_welcome_modal():
    """Test the welcome modal functionality."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Clear localStorage to ensure modal shows
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto("http://localhost:8080/docs/index.html")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)

        # Check modal is visible
        modal_visible = await page.is_visible("#welcome-modal.active")
        print(f"Modal visible on first visit: {modal_visible}")

        if modal_visible:
            # Check title
            title = await page.text_content(".modal-title")
            print(f"Modal title: {title}")
            assert "Bitcoin Vault" in title, "Modal title should contain 'Bitcoin Vault'"

            # Check subtitle
            subtitle = await page.text_content(".modal-subtitle")
            print(f"Modal subtitle: {subtitle}")

            # Check that the modal has educational content
            modal_content = await page.text_content(".modal")
            assert "How It Works" in modal_content, "Modal should have 'How It Works' section"
            assert "Your Security" in modal_content, "Modal should have 'Your Security' section"
            assert "network itself" in modal_content.lower() or "trustless" in modal_content.lower(), \
                "Modal should mention trustless/network security"

            # Test clicking outside to close
            await page.click("#welcome-modal", position={"x": 10, "y": 10})
            await asyncio.sleep(0.5)

            modal_visible_after = await page.is_visible("#welcome-modal.active")
            print(f"Modal closed by clicking outside: {not modal_visible_after}")

        await browser.close()
        print("[PASS] Welcome modal test")


async def test_glassmorphism_design():
    """Test that the new glassmorphism design elements are present."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto("http://localhost:8080/docs/index.html")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)

        # Close modal if visible
        modal_visible = await page.is_visible("#welcome-modal.active")
        if modal_visible:
            await page.click(".modal-close")
            await asyncio.sleep(0.5)

        # Check for glass-card class on sections
        glass_cards = await page.query_selector_all(".glass-card")
        print(f"Glass cards found: {len(glass_cards)}")
        assert len(glass_cards) >= 2, "Should have at least 2 glass cards"

        # Check for gradient background
        body_style = await page.evaluate("""() => {
            const style = window.getComputedStyle(document.body);
            return {
                background: style.background,
                backgroundImage: style.backgroundImage
            };
        }""")
        print(f"Body background: {body_style}")
        assert "gradient" in body_style["backgroundImage"].lower(), "Body should have gradient background"

        # Check for info tooltips
        info_triggers = await page.query_selector_all(".info-trigger")
        print(f"Info triggers (tooltips) found: {len(info_triggers)}")
        assert len(info_triggers) >= 5, "Should have multiple info tooltips"

        # Check for section numbers (1, 2)
        section_numbers = await page.query_selector_all(".section-number")
        print(f"Section numbers found: {len(section_numbers)}")
        assert len(section_numbers) >= 2, "Should have section numbers"

        await browser.close()
        print("[PASS] Glassmorphism design test")


async def main():
    print("=" * 60)
    print("Testing Bitcoin Vault Web App")
    print("=" * 60)

    # Test 1: Page loads
    print("\n[Test 1] Page Load & Library Check")
    success = await test_page_loads()
    print(f"Result: {'PASS' if success else 'FAIL'}")

    # Test 2: Generate address
    print("\n[Test 2] Generate Address")
    await test_generate_address()

    # Test 3: Welcome modal
    print("\n[Test 3] Welcome Modal")
    await test_welcome_modal()

    # Test 4: Design elements
    print("\n[Test 4] Glassmorphism Design")
    await test_glassmorphism_design()


if __name__ == "__main__":
    asyncio.run(main())
