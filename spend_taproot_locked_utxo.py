#!/usr/bin/env python3
"""
Spend a timelocked Taproot (P2TR) UTXO after the locktime has passed.

Uses the embit library for Taproot key path signing.
Can broadcast via public APIs (mempool.space, blockstream.info) - no Bitcoin node required.
"""

import argparse
import hashlib
import sys
import urllib.request
import urllib.error
from decimal import Decimal

from embit.descriptor import Descriptor
from embit.psbt import PSBT
from embit.transaction import Transaction, TransactionInput, TransactionOutput, SIGHASH
from embit.script import Script, Witness
from embit.ec import PrivateKey
from embit.networks import NETWORKS


COIN = 100_000_000

# Estimated vsize for P2TR key path spend (1 input, 1 output)
# Base: 4 (version) + 1 (input count) + 41 (input) + 1 (output count) + 43 (P2TR output) + 4 (locktime) = 94
# Witness: 1 (items) + 1 (sig len) + 64 (schnorr sig) = 66
# Weight = 94 * 3 + (94 + 2 + 66) = 444, vsize = ceil(444/4) = 111
VSIZE_1IN_1OUT_P2TR = 111

# Broadcast API endpoints
BROADCAST_APIS = {
    "mempool": {
        "mainnet": "https://mempool.space/api/tx",
        "testnet": "https://mempool.space/testnet/api/tx",
        "signet": "https://mempool.space/signet/api/tx",
    },
    "blockstream": {
        "mainnet": "https://blockstream.info/api/tx",
        "testnet": "https://blockstream.info/testnet/api/tx",
    },
}


def btc_to_sat(btc: Decimal) -> int:
    return int(btc * COIN)


def sat_to_btc(sat: int) -> Decimal:
    return Decimal(sat) / COIN


def broadcast_transaction(tx_hex: str, network: str = "mainnet", api: str = "mempool") -> str:
    """
    Broadcast a raw transaction via public API.

    Returns the txid on success.
    """
    if api not in BROADCAST_APIS:
        raise ValueError(f"Unknown API: {api}. Available: {list(BROADCAST_APIS.keys())}")

    api_urls = BROADCAST_APIS[api]
    if network not in api_urls:
        raise ValueError(f"Network '{network}' not supported by {api}. Available: {list(api_urls.keys())}")

    url = api_urls[network]

    # POST the raw transaction hex
    req = urllib.request.Request(
        url,
        data=tx_hex.encode('utf-8'),
        headers={'Content-Type': 'text/plain'},
        method='POST'
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            txid = response.read().decode('utf-8').strip()
            return txid
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else str(e)
        raise RuntimeError(f"Broadcast failed ({e.code}): {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")


def create_and_sign_spend_tx(
    descriptor: str,
    private_key_wif: str,
    txid: str,
    vout: int,
    amount_sat: int,
    destination: str,
    fee_rate: int,
    locktime: int,
    network: str = "regtest",
) -> tuple[str, str, int]:
    """
    Create and sign a spend transaction for a timelocked Taproot UTXO.

    Uses embit for Taproot KEY PATH signing - no Bitcoin Core needed.

    The timelock is enforced via the transaction's nLockTime field - the network
    will reject the transaction as "non-final" until the locktime block is reached.

    Args:
        fee_rate: Fee rate in sat/vB

    Returns (raw_tx_hex, txid, fee_sat).
    """
    fee_sat = fee_rate * VSIZE_1IN_1OUT_P2TR
    output_amount_sat = amount_sat - fee_sat
    if output_amount_sat <= 0:
        raise ValueError(f"Fee too high ({fee_sat} sats) - output amount would be negative")

    # Parse descriptor
    d = Descriptor.from_string(descriptor)
    if not d.is_taproot:
        raise ValueError("Descriptor is not a Taproot descriptor")

    # Get network config
    net = NETWORKS.get(network)
    if not net:
        # Map common names
        net_map = {"mainnet": "main", "main": "main", "testnet": "test", "regtest": "regtest", "signet": "signet"}
        net = NETWORKS.get(net_map.get(network, network))
    if not net:
        raise ValueError(f"Unknown network: {network}")

    # Parse private key
    privkey = PrivateKey.from_wif(private_key_wif)
    pubkey = privkey.get_public_key()

    # Get the taptree and compute merkle root for the tweak
    taptree = d.taptree
    if not taptree:
        raise ValueError("Descriptor has no taptree (script)")

    merkle_root = taptree.tweak()

    # Compute the tweaked private key for key path spending
    # This is: tweaked_privkey = privkey + tagged_hash("TapTweak", pubkey || merkle_root)
    tweaked_privkey = privkey.taproot_tweak(merkle_root)

    # Parse previous txid (embit handles byte order internally)
    prev_txid = bytes.fromhex(txid)

    # Create the spending transaction
    # nLockTime = locktime enforces the timelock at the network level
    # nSequence = 0xFFFFFFFE enables nLockTime (must be < 0xFFFFFFFF)
    tx = Transaction(
        version=2,
        locktime=locktime,
        vin=[TransactionInput(prev_txid, vout, sequence=0xFFFFFFFE)],
        vout=[TransactionOutput(output_amount_sat, Script.from_address(destination))]
    )

    # Create PSBT to compute the sighash
    psbt = PSBT(tx)
    inp = psbt.inputs[0]
    inp.witness_utxo = TransactionOutput(amount_sat, d.script_pubkey())

    # Compute the sighash for taproot key path spending
    sighash = psbt.sighash(0, sighash=SIGHASH.DEFAULT)

    # Sign with the tweaked private key using Schnorr signature
    sig = tweaked_privkey.schnorr_sign(sighash)

    # Key path witness: just the 64-byte Schnorr signature
    # (No script or control block needed for key path spending)
    witness = Witness([sig.serialize()])
    tx.vin[0].witness = witness

    # Serialize the final transaction
    raw_tx = tx.serialize().hex()

    # Compute txid (double SHA256 of non-witness serialization, byte-reversed)
    tx_no_witness = Transaction(
        version=tx.version,
        locktime=tx.locktime,
        vin=[TransactionInput(tx.vin[0].txid, tx.vin[0].vout, sequence=tx.vin[0].sequence)],
        vout=tx.vout
    )
    tx_bytes = tx_no_witness.serialize()
    new_txid = hashlib.sha256(hashlib.sha256(tx_bytes).digest()).digest()[::-1].hex()

    return raw_tx, new_txid, fee_sat


def main():
    parser = argparse.ArgumentParser(
        description="Spend a timelocked Taproot UTXO",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create transaction (without broadcasting)
  python spend_taproot_locked_utxo.py \\
    --descriptor 'tr(03...,and_v(v:pk(03...),after(250)))' \\
    --private-key cVVY... \\
    --txid abc123... --vout 0 \\
    --amount 0.5 \\
    --destination bc1p... \\
    --locktime 250 \\
    --fee-rate 10

  # Create and broadcast to mainnet via mempool.space
  python spend_taproot_locked_utxo.py \\
    --descriptor 'tr(03...,and_v(v:pk(03...),after(935000)))' \\
    --private-key L... \\
    --txid abc123... --vout 0 \\
    --amount 0.1 \\
    --destination bc1p... \\
    --locktime 935000 \\
    --fee-rate 20 \\
    --network mainnet \\
    --broadcast

The descriptor and private key come from create_taproot_locked_address.py output.
Fee rate: check https://mempool.space/fees for current rates.
        """,
    )

    parser.add_argument("--descriptor", required=True, help="Output descriptor from address creation")
    parser.add_argument("--private-key", required=True, help="Private key (WIF format)")
    parser.add_argument("--txid", required=True, help="TXID of the UTXO to spend")
    parser.add_argument("--vout", type=int, required=True, help="Output index (usually 0)")
    parser.add_argument("--amount", type=Decimal, required=True, help="Amount in BTC")
    parser.add_argument("--destination", required=True, help="Destination address")
    parser.add_argument("--locktime", type=int, required=True, help="Locktime (block height)")
    parser.add_argument("--fee-rate", type=int, default=10, help="Fee rate in sat/vB (default: 10)")
    parser.add_argument("--network", default="regtest", choices=["mainnet", "testnet", "signet", "regtest"],
                        help="Network (default: regtest)")
    parser.add_argument("--broadcast", action="store_true", help="Broadcast via mempool.space API")
    parser.add_argument("--broadcast-api", default="mempool", choices=["mempool", "blockstream"],
                        help="Broadcast API to use (default: mempool)")

    args = parser.parse_args()

    print("=" * 70)
    print("SPENDING TIMELOCKED TAPROOT UTXO")
    print("=" * 70)
    print(f"TXID:        {args.txid}")
    print(f"Vout:        {args.vout}")
    print(f"Amount:      {args.amount} BTC")
    print(f"Fee rate:    {args.fee_rate} sat/vB")
    print(f"Destination: {args.destination}")
    print(f"Locktime:    {args.locktime}")
    print(f"Network:     {args.network}")
    print()

    try:
        # Map network names for embit
        embit_network = {
            "mainnet": "main",
            "testnet": "test",
            "signet": "signet",
            "regtest": "regtest"
        }.get(args.network, args.network)

        raw_tx, new_txid, fee_sat = create_and_sign_spend_tx(
            descriptor=args.descriptor,
            private_key_wif=args.private_key,
            txid=args.txid,
            vout=args.vout,
            amount_sat=btc_to_sat(args.amount),
            destination=args.destination,
            fee_rate=args.fee_rate,
            locktime=args.locktime,
            network=embit_network,
        )

        print(f"Transaction created!")
        print(f"TXID: {new_txid}")
        print(f"Fee:  {fee_sat} sats ({args.fee_rate} sat/vB × {VSIZE_1IN_1OUT_P2TR} vB)")
        print()
        print(f"Raw transaction ({len(raw_tx)//2} bytes):")
        print(raw_tx)
        print()

        if args.broadcast:
            if args.network == "regtest":
                print("ERROR: Cannot broadcast regtest transactions to public APIs.")
                print("Use bitcoin-cli sendrawtransaction for regtest.")
                sys.exit(1)

            print(f"Broadcasting via {args.broadcast_api}...")
            broadcast_txid = broadcast_transaction(raw_tx, args.network, args.broadcast_api)
            print(f"SUCCESS! Broadcast TXID: {broadcast_txid}")
        else:
            print("=" * 70)
            print("BROADCAST OPTIONS")
            print("=" * 70)

            if args.network == "regtest":
                print("For regtest, use bitcoin-cli:")
                print(f"  bitcoin-cli sendrawtransaction {raw_tx[:50]}...")
            else:
                # Show curl commands for manual broadcast
                print("Option 1: Use --broadcast flag to auto-broadcast via mempool.space")
                print()
                print("Option 2: Manual broadcast via curl:")
                print()

                if args.network == "mainnet":
                    print("  # mempool.space (recommended)")
                    print(f"  curl -X POST -d '{raw_tx}' https://mempool.space/api/tx")
                    print()
                    print("  # blockstream.info")
                    print(f"  curl -X POST -d '{raw_tx}' https://blockstream.info/api/tx")
                elif args.network == "testnet":
                    print("  # mempool.space testnet")
                    print(f"  curl -X POST -d '{raw_tx}' https://mempool.space/testnet/api/tx")
                elif args.network == "signet":
                    print("  # mempool.space signet")
                    print(f"  curl -X POST -d '{raw_tx}' https://mempool.space/signet/api/tx")

                print()
                print("Option 3: Paste the raw transaction at:")
                if args.network == "mainnet":
                    print("  https://mempool.space/tx/push")
                elif args.network == "testnet":
                    print("  https://mempool.space/testnet/tx/push")
                elif args.network == "signet":
                    print("  https://mempool.space/signet/tx/push")

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        if "non-final" in str(e).lower() or "locktime" in str(e).lower():
            print("\nThe locktime has not been reached yet.")
            print("Wait for the blockchain to reach the required block height.")
        sys.exit(1)

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
