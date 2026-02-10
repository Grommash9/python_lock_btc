#!/usr/bin/env python3
"""
Spend a timelocked Taproot (P2TR) UTXO after the locktime has passed.

Uses the embit library for Taproot SCRIPT PATH signing (not key path).
Since the internal key is a NUMS point (unspendable), funds can ONLY be spent
via Script Path, which enforces the timelock condition.

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
from embit.misc import secp256k1


COIN = 100_000_000

# secp256k1 curve order
SECP256K1_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def calculate_vsize(tx: Transaction) -> int:
    """
    Calculate the virtual size (vsize) of a transaction.

    vsize = (weight + 3) / 4, where:
    - weight = base_size * 3 + total_size
    - base_size = size without witness data
    - total_size = size with witness data
    """
    # Serialize with witness
    tx_with_witness = tx.serialize()
    total_size = len(tx_with_witness)

    # Serialize without witness (create a copy without witness)
    tx_no_witness = Transaction(
        version=tx.version,
        locktime=tx.locktime,
        vin=[TransactionInput(inp.txid, inp.vout, sequence=inp.sequence) for inp in tx.vin],
        vout=tx.vout
    )
    base_size = len(tx_no_witness.serialize())

    # Calculate weight and vsize
    weight = base_size * 3 + total_size
    vsize = (weight + 3) // 4

    return vsize


def parse_utxo(utxo_str: str) -> tuple[str, int, int]:
    """
    Parse UTXO string in format 'txid:vout:amount_sats' or 'txid:vout:amount_btc'.

    Returns (txid, vout, amount_in_sats).
    """
    parts = utxo_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid UTXO format: {utxo_str}. Expected 'txid:vout:amount'")

    txid = parts[0]
    if len(txid) != 64:
        raise ValueError(f"Invalid txid length: {txid}")

    vout = int(parts[1])

    # Parse amount - if it contains a decimal point, treat as BTC
    amount_str = parts[2]
    if '.' in amount_str:
        amount_sat = int(Decimal(amount_str) * COIN)
    else:
        amount_sat = int(amount_str)

    return txid, vout, amount_sat

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
    utxos: list[tuple[str, int, int]],  # List of (txid, vout, amount_sat)
    destination: str,
    fee_rate: int,
    locktime: int,
    network: str = "regtest",
) -> tuple[str, str, int, int]:
    """
    Create and sign a spend transaction for one or more timelocked Taproot UTXOs.

    Uses embit for Taproot SCRIPT PATH signing - required because the internal
    key is a NUMS point (unspendable). This ensures the timelock is enforced
    by the Bitcoin consensus rules, not just by voluntary nLockTime setting.

    The witness stack for Script Path spend contains:
    1. Signature (satisfies pk(key) condition)
    2. The leaf script (and_v(v:pk(key), after(locktime)))
    3. Control block (proves script is in the taptree)

    Args:
        descriptor: Taproot descriptor for the locked address
        private_key_wif: Private key in WIF format
        utxos: List of (txid, vout, amount_sat) tuples to spend
        destination: Destination address
        fee_rate: Fee rate in sat/vB
        locktime: Block height for timelock
        network: Bitcoin network

    Returns (raw_tx_hex, txid, fee_sat, vsize).
    """
    # Parse descriptor
    d = Descriptor.from_string(descriptor)
    if not d.is_taproot:
        raise ValueError("Descriptor is not a Taproot descriptor")

    # Get network config
    net = NETWORKS.get(network)
    if not net:
        net_map = {"mainnet": "main", "main": "main", "testnet": "test", "regtest": "regtest", "signet": "signet"}
        net = NETWORKS.get(net_map.get(network, network))
    if not net:
        raise ValueError(f"Unknown network: {network}")

    # Parse private key - we use the UNTWEAKED key for script path signing
    privkey = PrivateKey.from_wif(private_key_wif)
    pubkey = privkey.get_public_key()

    # Get the taptree
    taptree = d.taptree
    if not taptree:
        raise ValueError("Descriptor has no taptree (script)")

    # Get internal key from descriptor (should be NUMS point)
    internal_key = d.key

    # Get the leaf from taptree - for single leaf, taptree.tree is the TapLeaf
    tap_leaf = taptree.tree

    # Get the compiled script bytes from the miniscript
    script_bytes = tap_leaf.miniscript.compile()
    leaf_script = Script(script_bytes)

    # Leaf version for tapscript
    LEAF_VERSION = 0xc0

    # Get the x-only internal pubkey (32 bytes)
    internal_pubkey_bytes = internal_key.sec()
    if len(internal_pubkey_bytes) == 33:
        internal_pubkey_x = internal_pubkey_bytes[1:]  # Strip the prefix byte
    else:
        internal_pubkey_x = internal_pubkey_bytes

    # Compute the tweaked output key to determine parity
    merkle_root = taptree.tweak()
    tweaked_output_key = internal_key.taproot_tweak(merkle_root)

    # Get the parity bit from the tweaked output key
    _, parity_bit = secp256k1.xonly_pubkey_from_pubkey(tweaked_output_key._point)
    parity_bit = 1 if parity_bit else 0

    # Build control block: (leaf_version | parity_bit) || internal_key_x || merkle_path
    control_byte = LEAF_VERSION | parity_bit
    control_block = bytes([control_byte]) + internal_pubkey_x

    # Prepare signing key (handle odd y-coordinate)
    pubkey_bytes = pubkey.sec()
    if pubkey_bytes[0] == 0x03:  # Odd y-coordinate
        negated_secret = SECP256K1_ORDER - int.from_bytes(privkey.secret, 'big')
        signing_key = PrivateKey(negated_secret.to_bytes(32, 'big'))
    else:
        signing_key = privkey

    # Calculate total input amount
    total_input_sat = sum(amount for _, _, amount in utxos)

    # Create inputs for all UTXOs
    tx_inputs = []
    for txid, vout, _ in utxos:
        prev_txid = bytes.fromhex(txid)
        tx_inputs.append(TransactionInput(prev_txid, vout, sequence=0xFFFFFFFE))

    # --- Two-pass approach for accurate fee calculation ---
    # Pass 1: Create transaction with estimated output, sign it to get actual size
    estimated_fee = fee_rate * (68 + 58 * len(utxos))  # Rough estimate
    estimated_output = total_input_sat - estimated_fee

    tx = Transaction(
        version=2,
        locktime=locktime,
        vin=tx_inputs,
        vout=[TransactionOutput(estimated_output, Script.from_address(destination))]
    )

    # Sign all inputs to measure actual witness size
    script_pubkey = d.script_pubkey()
    script_pubkeys = [script_pubkey] * len(utxos)
    values = [amount for _, _, amount in utxos]

    for i in range(len(utxos)):
        sighash = tx.sighash_taproot(
            input_index=i,
            script_pubkeys=script_pubkeys,
            values=values,
            sighash=SIGHASH.DEFAULT,
            ext_flag=1,
            script=leaf_script,
            leaf_version=LEAF_VERSION,
        )
        sig = signing_key.schnorr_sign(sighash)
        witness = Witness([sig.serialize(), script_bytes, control_block])
        tx.vin[i].witness = witness

    # Calculate actual vsize
    actual_vsize = calculate_vsize(tx)
    actual_fee = fee_rate * actual_vsize

    # Pass 2: Rebuild transaction with correct output amount
    output_amount_sat = total_input_sat - actual_fee
    if output_amount_sat <= 0:
        raise ValueError(f"Fee too high ({actual_fee} sats for {actual_vsize} vB) - output would be negative. "
                         f"Total input: {total_input_sat} sats")

    # Dust threshold check (P2TR dust is 330 sats)
    if output_amount_sat < 330:
        raise ValueError(f"Output amount ({output_amount_sat} sats) is below dust threshold (330 sats)")

    # Recreate inputs (need fresh ones for new transaction)
    tx_inputs = []
    for txid, vout, _ in utxos:
        prev_txid = bytes.fromhex(txid)
        tx_inputs.append(TransactionInput(prev_txid, vout, sequence=0xFFFFFFFE))

    tx = Transaction(
        version=2,
        locktime=locktime,
        vin=tx_inputs,
        vout=[TransactionOutput(output_amount_sat, Script.from_address(destination))]
    )

    # Sign all inputs again with correct output
    for i in range(len(utxos)):
        sighash = tx.sighash_taproot(
            input_index=i,
            script_pubkeys=script_pubkeys,
            values=values,
            sighash=SIGHASH.DEFAULT,
            ext_flag=1,
            script=leaf_script,
            leaf_version=LEAF_VERSION,
        )
        sig = signing_key.schnorr_sign(sighash)
        witness = Witness([sig.serialize(), script_bytes, control_block])
        tx.vin[i].witness = witness

    # Serialize the final transaction
    raw_tx = tx.serialize().hex()

    # Compute txid
    tx_no_witness = Transaction(
        version=tx.version,
        locktime=tx.locktime,
        vin=[TransactionInput(inp.txid, inp.vout, sequence=inp.sequence) for inp in tx.vin],
        vout=tx.vout
    )
    tx_bytes = tx_no_witness.serialize()
    new_txid = hashlib.sha256(hashlib.sha256(tx_bytes).digest()).digest()[::-1].hex()

    return raw_tx, new_txid, actual_fee, actual_vsize


def create_unsigned_psbt(
    descriptor: str,
    utxos: list[tuple[str, int, int]],  # List of (txid, vout, amount_sat)
    destination: str,
    fee_rate: int,
    locktime: int,
    network: str = "regtest",
) -> str:
    """
    Create an unsigned PSBT for verification in external wallets (e.g., Sparrow, Specter).

    This allows users to inspect the transaction details before signing,
    providing an additional layer of security for high-value transactions.

    Returns the PSBT in base64 format.
    """
    # Parse descriptor
    d = Descriptor.from_string(descriptor)
    if not d.is_taproot:
        raise ValueError("Descriptor is not a Taproot descriptor")

    # Get network config
    net = NETWORKS.get(network)
    if not net:
        net_map = {"mainnet": "main", "main": "main", "testnet": "test", "regtest": "regtest", "signet": "signet"}
        net = NETWORKS.get(net_map.get(network, network))
    if not net:
        raise ValueError(f"Unknown network: {network}")

    # Calculate total input and estimate fee
    total_input_sat = sum(amount for _, _, amount in utxos)
    estimated_vsize = 68 + 58 * len(utxos)  # Base + per-input witness
    fee_sat = fee_rate * estimated_vsize
    output_amount_sat = total_input_sat - fee_sat

    if output_amount_sat <= 0:
        raise ValueError(f"Fee too high ({fee_sat} sats) - output amount would be negative")

    # Create inputs
    tx_inputs = []
    for txid, vout, _ in utxos:
        prev_txid = bytes.fromhex(txid)
        tx_inputs.append(TransactionInput(prev_txid, vout, sequence=0xFFFFFFFE))

    # Create the unsigned transaction
    tx = Transaction(
        version=2,
        locktime=locktime,
        vin=tx_inputs,
        vout=[TransactionOutput(output_amount_sat, Script.from_address(destination))]
    )

    # Create PSBT from the unsigned transaction
    psbt = PSBT(tx)

    # Get script pubkey and internal key info
    script_pubkey = d.script_pubkey()
    internal_key = d.key
    internal_pubkey_bytes = internal_key.sec()
    if len(internal_pubkey_bytes) == 33:
        internal_pubkey_x = internal_pubkey_bytes[1:]
    else:
        internal_pubkey_x = internal_pubkey_bytes

    # Get tap leaf script info
    taptree = d.taptree
    tap_leaf = taptree.tree if taptree else None
    script_bytes = tap_leaf.miniscript.compile() if tap_leaf else None
    leaf_version = 0xc0

    # Add info for each input
    for i, (_, _, amount_sat) in enumerate(utxos):
        psbt.inputs[i].witness_utxo = TransactionOutput(amount_sat, script_pubkey)
        psbt.inputs[i].tap_internal_key = internal_pubkey_x
        if script_bytes:
            psbt.inputs[i].tap_leaf_scripts = {
                (internal_pubkey_x, bytes([leaf_version]) + script_bytes): bytes([leaf_version])
            }

    return psbt.to_base64()


def encode_compact_size(n: int) -> bytes:
    """Encode an integer as Bitcoin's compact size (varint)."""
    if n < 0xfd:
        return bytes([n])
    elif n <= 0xffff:
        return bytes([0xfd]) + n.to_bytes(2, 'little')
    elif n <= 0xffffffff:
        return bytes([0xfe]) + n.to_bytes(4, 'little')
    else:
        return bytes([0xff]) + n.to_bytes(8, 'little')


def main():
    parser = argparse.ArgumentParser(
        description="Spend timelocked Taproot UTXOs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Spend single UTXO (legacy format)
  python spend_taproot_locked_utxo.py \\
    --descriptor 'tr(50929b...,and_v(v:pk(03...),after(250)))' \\
    --private-key cVVY... \\
    --txid abc123... --vout 0 --amount 0.5 \\
    --destination bc1p... \\
    --locktime 250

  # Spend multiple UTXOs in one transaction (saves fees!)
  python spend_taproot_locked_utxo.py \\
    --descriptor 'tr(50929b...,and_v(v:pk(03...),after(935000)))' \\
    --private-key L... \\
    --utxo 'abc123...:0:0.1' \\
    --utxo 'def456...:1:0.05' \\
    --utxo 'ghi789...:0:0.02' \\
    --destination bc1p... \\
    --locktime 935000 \\
    --fee-rate 20 \\
    --network mainnet

  UTXO format: 'txid:vout:amount' (amount in BTC or sats)

The descriptor and private key come from create_taproot_locked_address.py output.
Fee rate: check https://mempool.space/fees for current rates.
Fee is calculated based on ACTUAL transaction size (not estimated).
        """,
    )

    parser.add_argument("--descriptor", required=True, help="Output descriptor from address creation")
    parser.add_argument("--private-key", required=True, help="Private key (WIF format)")

    # Multiple UTXO support
    parser.add_argument("--utxo", action="append", dest="utxos", metavar="TXID:VOUT:AMOUNT",
                        help="UTXO to spend (format: 'txid:vout:amount'). Can be specified multiple times.")

    # Legacy single-UTXO arguments (for backwards compatibility)
    parser.add_argument("--txid", help="TXID of the UTXO to spend (legacy, use --utxo instead)")
    parser.add_argument("--vout", type=int, help="Output index (legacy, use --utxo instead)")
    parser.add_argument("--amount", type=Decimal, help="Amount in BTC (legacy, use --utxo instead)")

    parser.add_argument("--destination", required=True, help="Destination address")
    parser.add_argument("--locktime", type=int, required=True, help="Locktime (block height)")
    parser.add_argument("--fee-rate", type=int, default=10, help="Fee rate in sat/vB (default: 10)")
    parser.add_argument("--network", default="regtest", choices=["mainnet", "testnet", "signet", "regtest"],
                        help="Network (default: regtest)")
    parser.add_argument("--broadcast", action="store_true", help="Broadcast via mempool.space API")
    parser.add_argument("--broadcast-api", default="mempool", choices=["mempool", "blockstream"],
                        help="Broadcast API to use (default: mempool)")
    parser.add_argument("--psbt", action="store_true",
                        help="Output unsigned PSBT for verification in external wallets (Sparrow, Specter, etc.)")

    args = parser.parse_args()

    # Build UTXO list from arguments
    utxos = []

    if args.utxos:
        # New format: --utxo txid:vout:amount
        for utxo_str in args.utxos:
            utxos.append(parse_utxo(utxo_str))
    elif args.txid and args.vout is not None and args.amount:
        # Legacy format: --txid --vout --amount
        utxos.append((args.txid, args.vout, btc_to_sat(args.amount)))
    else:
        parser.error("Either --utxo or (--txid, --vout, --amount) is required")

    # Calculate totals
    total_input_sat = sum(amount for _, _, amount in utxos)

    print("=" * 70)
    print("SPENDING TIMELOCKED TAPROOT UTXO" + ("S" if len(utxos) > 1 else ""))
    print("=" * 70)
    print(f"Inputs:      {len(utxos)} UTXO(s)")
    for i, (txid, vout, amount) in enumerate(utxos):
        print(f"  [{i+1}] {txid[:16]}...:{vout} = {sat_to_btc(amount)} BTC")
    print(f"Total:       {sat_to_btc(total_input_sat)} BTC ({total_input_sat} sats)")
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

        raw_tx, new_txid, fee_sat, vsize = create_and_sign_spend_tx(
            descriptor=args.descriptor,
            private_key_wif=args.private_key,
            utxos=utxos,
            destination=args.destination,
            fee_rate=args.fee_rate,
            locktime=args.locktime,
            network=embit_network,
        )

        output_sat = total_input_sat - fee_sat
        print(f"Transaction created (Script Path spend)!")
        print(f"TXID:   {new_txid}")
        print(f"Size:   {vsize} vB (actual, not estimated)")
        print(f"Fee:    {fee_sat} sats ({args.fee_rate} sat/vB × {vsize} vB)")
        print(f"Output: {sat_to_btc(output_sat)} BTC ({output_sat} sats)")
        print()
        print(f"Raw transaction ({len(raw_tx)//2} bytes):")
        print(raw_tx)
        print()

        # Output PSBT if requested
        if args.psbt:
            print("=" * 70)
            print("PSBT (for verification in external wallets)")
            print("=" * 70)
            psbt_base64 = create_unsigned_psbt(
                descriptor=args.descriptor,
                utxos=utxos,
                destination=args.destination,
                fee_rate=args.fee_rate,
                locktime=args.locktime,
                network=embit_network,
            )
            print(psbt_base64)
            print()
            print("Import this PSBT into Sparrow, Specter, or another wallet to verify:")
            print("  - Input amount(s) and source(s)")
            print("  - Output destination and amount")
            print("  - Fee amount")
            print("  - Timelock conditions")
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
