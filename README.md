# Bitcoin Taproot Timelocked Address

Create Bitcoin addresses where funds can only be spent after a specific block height using Taproot (P2TR) and CHECKLOCKTIMEVERIFY (CLTV).

## Overview

This project demonstrates:
- Creating Taproot addresses with timelock conditions using miniscript
- Spending from timelocked UTXOs after the locktime passes
- Broadcasting via public APIs (mempool.space, blockstream.info) - no Bitcoin node required for mainnet
- Testing on a local Bitcoin regtest network

## Prerequisites

- Python 3.10+
- Docker and Docker Compose (for regtest testing only)

## Setup

### Install Python Dependencies

```bash
pip install -r requirements.txt
```

This installs the [embit](https://github.com/diybitcoinhardware/embit) library for Taproot/miniscript support.

---

## Using on Mainnet (Production)

**No Bitcoin node required!** The scripts use the embit library for signing and public APIs for broadcasting.

### Step 1: Create a Timelocked Address

Choose a future block height for the locktime. Current mainnet block height is ~883,000 (February 2025).

```bash
# Lock until block 935,000 (~1 year from now)
# ~144 blocks per day × 365 days ≈ 52,560 blocks

python create_taproot_locked_address.py --locktime 935000 --network main
```

Output:
```
======================================================================
TAPROOT TIMELOCKED ADDRESS CREATED
======================================================================
Network:            main
Locktime (block):   935000
Address:            bc1p...

--- SAVE THIS INFORMATION ---
Descriptor:         tr(02...,and_v(v:pk(02...),after(935000)))
Private Key (hex):  <hex>
Private Key (WIF):  L... or K...
Public Key:         02...
======================================================================

Send BTC to: bc1p...
Funds spendable after block 935000
```

### Step 2: Securely Store Recovery Info

**CRITICAL:** Before sending any funds, securely backup:
- Descriptor (needed to identify the script)
- Private Key (WIF format)
- Locktime value

Storage options:
- Encrypted file (GPG, Veracrypt)
- Hardware wallet seed backup location
- Paper backup in secure location

### Step 3: Fund the Address

Send BTC to the `bc1p...` address using any wallet. Verify the address multiple times before sending.

After sending, note the:
- **TXID** - Transaction ID of your funding transaction
- **vout** - Output index (usually 0, check on a block explorer)
- **Amount** - Exact amount sent

### Step 4: Wait for Locktime

Monitor the blockchain at [mempool.space](https://mempool.space) until it reaches your locktime block.

### Step 5: Spend After Locktime

Once the blockchain has passed your locktime block:

```bash
# Without auto-broadcast (shows raw transaction and broadcast options)
python spend_taproot_locked_utxo.py \
  --descriptor "tr(02...,and_v(v:pk(02...),after(935000)))" \
  --private-key L... \
  --txid <funding-txid> \
  --vout 0 \
  --amount 0.1 \
  --destination <your-destination-bc1p-address> \
  --locktime 935000 \
  --network mainnet
```

Output:
```
======================================================================
SPENDING TIMELOCKED TAPROOT UTXO
======================================================================
TXID:        <funding-txid>
Vout:        0
Amount:      0.1 BTC
Fee:         0.0001 BTC
Destination: bc1p...
Locktime:    935000
Network:     mainnet

Transaction created!
TXID: abc123...

Raw transaction (234 bytes):
020000000001...

======================================================================
BROADCAST OPTIONS
======================================================================
Option 1: Use --broadcast flag to auto-broadcast via mempool.space

Option 2: Manual broadcast via curl:

  # mempool.space (recommended)
  curl -X POST -d '020000...' https://mempool.space/api/tx

  # blockstream.info
  curl -X POST -d '020000...' https://blockstream.info/api/tx

Option 3: Paste the raw transaction at:
  https://mempool.space/tx/push

======================================================================
```

### Auto-Broadcast via API

Add `--broadcast` to automatically broadcast via mempool.space:

```bash
python spend_taproot_locked_utxo.py \
  --descriptor "tr(02...,and_v(v:pk(02...),after(935000)))" \
  --private-key L... \
  --txid <funding-txid> \
  --vout 0 \
  --amount 0.1 \
  --destination <your-destination-address> \
  --locktime 935000 \
  --network mainnet \
  --broadcast
```

Use `--broadcast-api blockstream` to use blockstream.info instead.

### Fee Estimation

Check current fee rates at [mempool.space/fees](https://mempool.space/fees) and adjust with `--fee`:

```bash
--fee 0.00005   # 5,000 sats (low priority)
--fee 0.0001    # 10,000 sats (default)
--fee 0.0002    # 20,000 sats (high priority)
```

---

## Testing on Regtest (Local Development)

### 1. Start the Bitcoin Regtest Network

```bash
cd test_btc_network
docker-compose up -d
```

Verify it's running:

```bash
./btc.sh getblockchaininfo
```

Output:
```json
{
  "chain": "regtest",
  "blocks": 0,
  "headers": 0,
  ...
}
```

### 2. Create a Wallet and Mine Initial Blocks

```bash
./btc.sh createwallet "test"
```

Output:
```json
{
  "name": "test"
}
```

Get a new address and mine 101 blocks to have spendable coins:

```bash
./btc.sh -rpcwallet=test getnewaddress
# bcrt1qfhq5gjksvl93m33cstqmee9wa94vcu8vx7ha2u

./btc.sh generatetoaddress 101 bcrt1qfhq5gjksvl93m33cstqmee9wa94vcu8vx7ha2u
```

Check balance:

```bash
./btc.sh -rpcwallet=test getbalance
# 50.00000000
```

### 3. Create a Timelocked Address

```bash
python create_taproot_locked_address.py --locktime 120 --network regtest
```

Output:
```
======================================================================
TAPROOT TIMELOCKED ADDRESS CREATED
======================================================================
Network:            regtest
Locktime (block):   120
Address:            bcrt1pftke8xlcuv2ul40m45nrk28ak5xtg30g3nq0qtr6kzgfaxgpm7ms4s70eg

--- SAVE THIS INFORMATION ---
Descriptor:         tr(02870eece8726f50ad13a2a7247c4081229ac69a47b4a462e2a0f2bb6c7f5e1bdf,and_v(v:pk(02870eece8726f50ad13a2a7247c4081229ac69a47b4a462e2a0f2bb6c7f5e1bdf),after(120)))
Private Key (hex):  57dda3e3f5f640396893ac35edbe8e85d1383fc4cfc527f0667353613a6c91f0
Private Key (WIF):  cQXW2RNdhZNPNMR1Dj9x8YzctVXL2hEArXEhsg3jnMf7TFvhw7Fi
Public Key:         02870eece8726f50ad13a2a7247c4081229ac69a47b4a462e2a0f2bb6c7f5e1bdf
======================================================================

Send BTC to: bcrt1pftke8xlcuv2ul40m45nrk28ak5xtg30g3nq0qtr6kzgfaxgpm7ms4s70eg
Funds spendable after block 120
```

**Save** the descriptor and private key (WIF) - you'll need these to spend!

### 4. Fund the Locked Address

```bash
./btc.sh -rpcwallet=test sendtoaddress bcrt1pftke8xlcuv2ul40m45nrk28ak5xtg30g3nq0qtr6kzgfaxgpm7ms4s70eg 0.2
# c7041b09e125c5436a6bcfe8df4573c6f6b40c435ac05d725e1f5d144738e414
```

Mine a block to confirm:

```bash
./btc.sh generatetoaddress 1 $(./btc.sh -rpcwallet=test getnewaddress)
./btc.sh getblockcount
# 102
```

### 5. Try to Spend Before Locktime (Should Fail)

Get a destination address:
```bash
./btc.sh -rpcwallet=test getnewaddress "" bech32m
# bcrt1pn09axek9gtthvdg4qgglv2pa8l6dn9uaxykd7shyh0gy02nhm9sslp6ha5
```

Create the spend transaction:
```bash
python spend_taproot_locked_utxo.py \
  --descriptor "tr(02870eece8726f50ad13a2a7247c4081229ac69a47b4a462e2a0f2bb6c7f5e1bdf,and_v(v:pk(02870eece8726f50ad13a2a7247c4081229ac69a47b4a462e2a0f2bb6c7f5e1bdf),after(120)))" \
  --private-key cQXW2RNdhZNPNMR1Dj9x8YzctVXL2hEArXEhsg3jnMf7TFvhw7Fi \
  --txid c7041b09e125c5436a6bcfe8df4573c6f6b40c435ac05d725e1f5d144738e414 \
  --vout 0 \
  --amount 0.2 \
  --destination bcrt1pn09axek9gtthvdg4qgglv2pa8l6dn9uaxykd7shyh0gy02nhm9sslp6ha5 \
  --locktime 120 \
  --network regtest
```

Output:
```
======================================================================
SPENDING TIMELOCKED TAPROOT UTXO
======================================================================
TXID:        c7041b09e125c5436a6bcfe8df4573c6f6b40c435ac05d725e1f5d144738e414
Vout:        0
Amount:      0.2 BTC
Fee:         0.0001 BTC
Destination: bcrt1pn09axek9gtthvdg4qgglv2pa8l6dn9uaxykd7shyh0gy02nhm9sslp6ha5
Locktime:    120
Network:     regtest

Transaction created!
TXID: 6a4e735c0d8149faf5179fb145b5b12e835767fbc2c7f863664ade64a9be73a1

Raw transaction (162 bytes):
0200000000010114e43847145d1f5e725dc05a430cb4f6c67345dfe8cf6b6a43c525e1091b04c70000000000feffffff01f0053101000000002251209bcbd366c542d77635150211f6283d3ff4d9979d312cdf42e4bbd047aa77d961014093a92a92ad70e425a8d62620b20f350288cef8533ecacee0c433ee1322d8b3794358957ccd17c1d9464d761a8d3a71f9748900b41954a074fbec4c7930a399ca78000000

======================================================================
BROADCAST OPTIONS
======================================================================
For regtest, use bitcoin-cli:
  bitcoin-cli sendrawtransaction 0200000000010114e43847145d1f5e725dc05a430cb4...

======================================================================
```

Try to broadcast - **this will fail** because we're at block 102 and locktime is 120:

```bash
./btc.sh sendrawtransaction 0200000000010114e43847145d1f5e725dc05a430cb4f6c67345dfe8cf6b6a43c525e1091b04c70000000000feffffff01f0053101000000002251209bcbd366c542d77635150211f6283d3ff4d9979d312cdf42e4bbd047aa77d961014093a92a92ad70e425a8d62620b20f350288cef8533ecacee0c433ee1322d8b3794358957ccd17c1d9464d761a8d3a71f9748900b41954a074fbec4c7930a399ca78000000
```

Output:
```
error code: -26
error message:
non-final
```

**This is expected!** The transaction has `nLockTime=120` but we're only at block 102.

### 6. Mine Blocks to Reach Locktime

```bash
./btc.sh generatetoaddress 20 $(./btc.sh -rpcwallet=test getnewaddress)
./btc.sh getblockcount
# 122
```

### 7. Spend After Locktime

Now broadcast the same raw transaction (no need to recreate it):

```bash
./btc.sh sendrawtransaction 0200000000010114e43847145d1f5e725dc05a430cb4f6c67345dfe8cf6b6a43c525e1091b04c70000000000feffffff01f0053101000000002251209bcbd366c542d77635150211f6283d3ff4d9979d312cdf42e4bbd047aa77d961014093a92a92ad70e425a8d62620b20f350288cef8533ecacee0c433ee1322d8b3794358957ccd17c1d9464d761a8d3a71f9748900b41954a074fbec4c7930a399ca78000000
# 6a4e735c0d8149faf5179fb145b5b12e835767fbc2c7f863664ade64a9be73a1
```

**Success!** The transaction was accepted and is now in the mempool.

### 8. Verify

Mine a block to confirm and verify the UTXO exists:

```bash
./btc.sh generatetoaddress 1 $(./btc.sh -rpcwallet=test getnewaddress)
./btc.sh gettxout 6a4e735c0d8149faf5179fb145b5b12e835767fbc2c7f863664ade64a9be73a1 0
```

Output:
```json
{
  "bestblock": "5f219c5d7e18658c636189fbe66850e84e7e26d5cc452ae06daa25a8f6ad89a3",
  "confirmations": 1,
  "value": 0.19990000,
  "scriptPubKey": {
    "asm": "1 9bcbd366c542d77635150211f6283d3ff4d9979d312cdf42e4bbd047aa77d961",
    "desc": "rawtr(9bcbd366c542d77635150211f6283d3ff4d9979d312cdf42e4bbd047aa77d961)#q2ud38tc",
    "hex": "51209bcbd366c542d77635150211f6283d3ff4d9979d312cdf42e4bbd047aa77d961",
    "address": "bcrt1pn09axek9gtthvdg4qgglv2pa8l6dn9uaxykd7shyh0gy02nhm9sslp6ha5",
    "type": "witness_v1_taproot"
  },
  "coinbase": false
}
```

The funds (0.19990000 BTC = 0.2 - 0.0001 fee) are now at the destination address!

---

## How It Works

### Taproot Descriptor

The address uses a miniscript descriptor:
```
tr(pubkey, and_v(v:pk(pubkey), after(locktime)))
```

- `tr(...)` - Taproot output
- `and_v(...)` - Requires ALL conditions to be true
- `v:pk(pubkey)` - Valid signature from the public key
- `after(locktime)` - Block height must be >= locktime

### Spending Mechanism

1. Transaction's `nLockTime` is set to the locktime value
2. Input's `nSequence` is set to `0xFFFFFFFE` (enables locktime)
3. Network validates:
   - Current block height >= nLockTime
   - Valid Schnorr signature via Taproot key path spend

The spend script uses **key path spending** with a tweaked private key. The timelock is enforced at the network level through `nLockTime` - the network rejects the transaction with "non-final" until the locktime block is reached.

### Security

- Uses [embit](https://github.com/diybitcoinhardware/embit) for Taproot signing (same library used by hardware wallets)
- No custom cryptographic implementations
- Signing happens locally - private keys never leave your machine
- Broadcasting via HTTPS to trusted public APIs

---

## Use Cases

- **Forced savings** - Can't spend impulsively
- **Inheritance planning** - Funds unlock at future date
- **Vesting schedules** - Time-release payments
- **HODL enforcement** - Commit to holding

---

## Files

| File | Description |
|------|-------------|
| `create_taproot_locked_address.py` | Generate timelocked Taproot addresses |
| `spend_taproot_locked_utxo.py` | Spend from timelocked UTXOs (sign locally, broadcast via API) |
| `test_btc_network/` | Docker setup for local regtest testing |
| `requirements.txt` | Python dependencies (embit) |

---

## Troubleshooting

### "non-final" error when broadcasting
The locktime hasn't been reached. Wait for the blockchain to reach the required block height.

### "Wallet not found" (regtest)
```bash
./test_btc_network/btc.sh loadwallet "test"
```

### "No such container" (regtest)
```bash
cd test_btc_network && docker-compose up -d
```

### Broadcast fails with network error
Try a different API:
```bash
--broadcast-api blockstream
```

Or manually broadcast at https://mempool.space/tx/push

---

## Cleanup (Regtest)

Stop the network:
```bash
cd test_btc_network && docker-compose down
```

Remove all data:
```bash
cd test_btc_network && docker-compose down -v
```
