#!/usr/bin/env python3
"""
Create a timelocked Taproot (P2TR) address using CHECKLOCKTIMEVERIFY.

Uses the embit library for proper BIP340/341/342 implementation.
The generated address can only be spent after the specified block height.

SECURITY: Uses a NUMS (Nothing Up My Sleeve) point as the internal key,
making Key Path spending impossible. Funds can ONLY be spent via Script Path
after the timelock expires. This provides cryptographically enforced timelocks.
"""

import argparse
import json
import secrets
import sys
from datetime import datetime
from pathlib import Path

from embit import bech32
from embit.descriptor import Descriptor
from embit.ec import PrivateKey, PublicKey
from embit.networks import NETWORKS


# NUMS point (Nothing Up My Sleeve) - an unspendable internal key
# This is the x-coordinate of a point where nobody knows the discrete log.
# Derived as: lift_x(SHA256(SHA256("TapTweak")||SHA256("TapTweak")||encode(G)))
# Using the standard from BIP-0341 recommendation for provably unspendable keys.
# This specific point is SHA256(generator_point_G_compressed) = H
NUMS_KEY_HEX = "50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0"


def create_taproot_locked_address(
    locktime: int,
    network: str = "regtest",
    private_key_hex: str | None = None,
) -> dict:
    """
    Create a Taproot address with CLTV timelock using embit.

    Uses miniscript: and_v(v:pk(key),after(locktime))
    This requires both a valid signature AND the timelock to have passed.

    SECURITY: The internal key is a NUMS point (unspendable), forcing all spends
    to go through the Script Path where the timelock is enforced. This prevents
    the owner from bypassing the timelock via Key Path spending.
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
    # tr(NUMS_KEY, and_v(v:pk(key), after(locktime)))
    # NUMS_KEY is unspendable, forcing Script Path spend with timelock enforcement
    desc_str = f"tr({NUMS_KEY_HEX},and_v(v:pk({pubkey_hex}),after({locktime})))"

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
        "internal_key": NUMS_KEY_HEX,
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

    parser.add_argument(
        "--save-backup",
        type=str,
        metavar="FILE",
        help="Save backup to JSON file (e.g., --save-backup backup.json). Contains all info needed to spend.",
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
    print("TAPROOT TIMELOCKED ADDRESS CREATED (NUMS-SECURED)")
    print("=" * 70)
    print(f"Network:            {result['network']}")
    print(f"Locktime (block):   {result['locktime']}")
    print(f"Address:            {result['address']}")
    print()
    print("--- SECURITY INFO ---")
    print(f"Internal Key:       {result['internal_key']} (NUMS - unspendable)")
    print("Key Path Spend:     IMPOSSIBLE (timelock cannot be bypassed)")
    print()
    print("--- SAVE THIS INFORMATION ---")
    print(f"Descriptor:         {result['descriptor']}")
    print(f"Private Key (hex):  {result['private_key_hex']}")
    print(f"Private Key (WIF):  {result['private_key_wif']}")
    print(f"Public Key:         {result['public_key_hex']}")
    print("=" * 70)
    print()
    print(f"Send BTC to: {result['address']}")
    print(f"Funds spendable after block {result['locktime']} (ENFORCED - no bypass possible)")

    # Save backup if requested
    if args.save_backup:
        backup_data = {
            "created_at": datetime.utcnow().isoformat() + "Z",
            "warning": "KEEP THIS FILE SECURE - contains private key!",
            "network": result["network"],
            "address": result["address"],
            "locktime": result["locktime"],
            "descriptor": result["descriptor"],
            "private_key_wif": result["private_key_wif"],
            "private_key_hex": result["private_key_hex"],
            "public_key_hex": result["public_key_hex"],
            "internal_key": result["internal_key"],
        }

        backup_path = Path(args.save_backup)
        backup_path.write_text(json.dumps(backup_data, indent=2))
        print()
        print(f"Backup saved to: {backup_path.absolute()}")
        print("WARNING: This file contains your private key. Store it securely!")


if __name__ == "__main__":
    main()
