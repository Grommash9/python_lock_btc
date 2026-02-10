#!/usr/bin/env python3
"""Test signing functionality"""
import asyncio
from playwright.async_api import async_playwright

async def test_signing():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto("http://localhost:8080/docs/index.html")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)

        # Check Signer API
        result = await page.evaluate("""() => {
            const { Signer } = window.tapscript;
            return {
                signerKeys: Object.keys(Signer),
                taprootKeys: Signer.taproot ? Object.keys(Signer.taproot) : [],
            };
        }""")
        print(f"Signer keys: {result['signerKeys']}")
        print(f"Taproot keys: {result['taprootKeys']}")

        # Test signing with a dummy key
        result = await page.evaluate("""() => {
            try {
                const { Signer, Tap, Script, Address } = window.tapscript;

                // Generate a test private key
                const privKeyHex = 'a'.repeat(64);  // 32 bytes of 0xaa

                // Create a simple script
                const pubKey = window.nobleSecp256k1.getPublicKey(
                    new Uint8Array(32).fill(0xaa),
                    true
                );
                const pubKeyHex = Array.from(pubKey).map(b => b.toString(16).padStart(2, '0')).join('');

                const script = [pubKeyHex, 'OP_CHECKSIGVERIFY', 100, 'OP_CHECKLOCKTIMEVERIFY'];
                const tapleaf = Tap.encodeScript(script);

                const numsKey = '50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0';
                const [tpubkey, cblock] = Tap.getPubKey(numsKey, { target: tapleaf });

                const address = Address.p2tr.fromPubKey(tpubkey, 'regtest');
                const scriptPubKey = Address.toScriptPubKey(address);

                // Create a dummy transaction
                const txData = {
                    version: 2,
                    locktime: 100,
                    vin: [{
                        txid: 'a'.repeat(64),
                        vout: 0,
                        prevout: {
                            value: 10000,
                            scriptPubKey: scriptPubKey
                        },
                        sequence: 0xfffffffe
                    }],
                    vout: [{
                        value: 9000,
                        scriptPubKey: scriptPubKey
                    }]
                };

                // Try to sign
                const sig = Signer.taproot.sign(privKeyHex, txData, 0, {
                    extension: tapleaf
                });

                return {
                    success: true,
                    sigType: typeof sig,
                    sigKeys: Object.keys(sig || {})
                };
            } catch (e) {
                return {
                    success: false,
                    error: e.message,
                    stack: e.stack
                };
            }
        }""")

        print(f"\nSigning test result: {result}")

        await browser.close()

asyncio.run(test_signing())
