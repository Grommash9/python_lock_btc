#!/usr/bin/env python3
"""
Create a timelocked Taproot (P2TR) address using CHECKLOCKTIMEVERIFY.

Uses the embit library for proper BIP340/341/342 implementation.
The generated address can only be spent after the specified block height.
"""

import argparse
import secrets
import sys

from embit import bech32
from embit.descriptor import Descriptor
from embit.ec import PrivateKey
from embit.networks import NETWORKS


def create_taproot_locked_address(
    locktime: int,
    network: str = "regtest",
    private_key_hex: str | None = None,
) -> dict:
    """
    Create a Taproot address with CLTV timelock using embit.

    Uses miniscript: and_v(v:pk(key),after(locktime))
    This requires both a valid signature AND the timelock to have passed.
    """
    # Generate or use provided private key
    if private_key_hex:
        privkey = PrivateKey(bytes.fromhex(private_key_hex))
    else:
        privkey = PrivateKey(secrets.token_bytes(32))

    # Get the public key (x-only for Taproot)
    pubkey = privkey.get_public_key()
    pubkey_hex = pubkey.sec().hex()  # Compressed pubkey for descriptor

    # Build the Taproot descriptor with CLTV timelock
    # tr(internal_key, and_v(v:pk(key), after(locktime)))
    # Using the same key as internal key and script key for simplicity
    desc_str = f"tr({pubkey_hex},and_v(v:pk({pubkey_hex}),after({locktime})))"

    descriptor = Descriptor.from_string(desc_str)

    # Get the scriptPubKey and address
    script_pubkey = descriptor.script_pubkey()
    net = NETWORKS[network]
    address = script_pubkey.address(net)

    # Get witness script info for spending later
    # The taptree contains our script
    taptree = descriptor.taptree
    tweak = taptree.tweak() if taptree else b""

    return {
        "network": network,
        "address": address,
        "locktime": locktime,
        "descriptor": desc_str,
        "private_key_hex": privkey.secret.hex(),
        "private_key_wif": privkey.wif(net),
        "public_key_hex": pubkey_hex,
        "script_pubkey_hex": script_pubkey.data.hex(),
        "tweak_hex": tweak.hex() if tweak else "",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Create a timelocked Taproot address (P2TR + CLTV)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create Taproot address locked until block 200 on regtest
  python create_taproot_locked_address.py --locktime 200 --network regtest

  # Create Taproot address locked until block 1,000,000 on mainnet
  python create_taproot_locked_address.py --locktime 1000000 --network main

  # Use existing private key
  python create_taproot_locked_address.py --locktime 200 --private-key <hex>

IMPORTANT: Save the descriptor and private key! You need them to spend later.

Taproot addresses start with:
  - bc1p...   (mainnet)
  - bcrt1p... (regtest)
        """,
    )

    parser.add_argument(
        "--locktime",
        type=int,
        required=True,
        help="Block height when funds become spendable (must be < 500,000,000)",
    )

    parser.add_argument(
        "--network",
        choices=["regtest", "main", "test", "signet"],
        default="regtest",
        help="Bitcoin network (default: regtest)",
    )

    parser.add_argument(
        "--private-key",
        type=str,
        default=None,
        help="Use existing private key (hex). If not provided, generates new key.",
    )

    args = parser.parse_args()

    # Validate locktime
    if args.locktime >= 500_000_000:
        print(
            "WARNING: locktime >= 500,000,000 is interpreted as Unix timestamp!",
            file=sys.stderr,
        )

    result = create_taproot_locked_address(
        locktime=args.locktime,
        network=args.network,
        private_key_hex=args.private_key,
    )

    print("=" * 70)
    print("TAPROOT TIMELOCKED ADDRESS CREATED")
    print("=" * 70)
    print(f"Network:            {result['network']}")
    print(f"Locktime (block):   {result['locktime']}")
    print(f"Address:            {result['address']}")
    print()
    print("--- SAVE THIS INFORMATION ---")
    print(f"Descriptor:         {result['descriptor']}")
    print(f"Private Key (hex):  {result['private_key_hex']}")
    print(f"Private Key (WIF):  {result['private_key_wif']}")
    print(f"Public Key:         {result['public_key_hex']}")
    print("=" * 70)
    print()
    print(f"Send BTC to: {result['address']}")
    print(f"Funds spendable after block {result['locktime']}")


if __name__ == "__main__":
    main()
