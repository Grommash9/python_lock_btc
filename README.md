# Bitcoin Taproot Timelock

Lock your Bitcoin until a specific block height. No way to spend early — enforced by the Bitcoin network itself.

## What This Does

Creates a Bitcoin address where funds are **cryptographically locked** until a future block. The lock is enforced by Bitcoin consensus rules, not by trust or willpower.

**Use cases:**
- Forced savings (can't spend impulsively)
- HODL enforcement
- Inheritance planning
- Vesting schedules

## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Create a Locked Address

```bash
python create_taproot_locked_address.py \
  --locktime 950000 \
  --network main \
  --save-backup my_backup.json
```

This creates:
- A `bc1p...` address locked until block 950,000
- A backup file with everything needed to spend later

**Current mainnet block:** ~880,000 (check [mempool.space](https://mempool.space))
**Blocks per year:** ~52,560 (144 blocks/day × 365)

### 3. Send Bitcoin to the Address

Send BTC to the generated address. Note the transaction ID (txid) from your wallet.

### 4. Spend After Locktime

Once the blockchain passes your locktime block:

```bash
python spend_taproot_locked_utxo.py \
  --descriptor "tr(...)"  \
  --private-key "L..." \
  --utxo "abc123...:0:0.1" \
  --destination "bc1p..." \
  --locktime 950000 \
  --network mainnet \
  --broadcast
```

The `--utxo` format is `txid:output_index:amount_in_btc`.

---

## Spending Multiple UTXOs

If you have several locked UTXOs (same address, same locktime), combine them into one transaction to save on fees:

```bash
python spend_taproot_locked_utxo.py \
  --descriptor "tr(...)" \
  --private-key "L..." \
  --utxo "txid1...:0:0.05" \
  --utxo "txid2...:1:0.03" \
  --utxo "txid3...:0:0.02" \
  --destination "bc1p..." \
  --locktime 950000 \
  --fee-rate 10 \
  --network mainnet \
  --broadcast
```

This spends all three UTXOs (0.10 BTC total) in a single transaction. Much cheaper than three separate transactions.

---

## Command Reference

### Creating Addresses

```bash
python create_taproot_locked_address.py \
  --locktime BLOCK_HEIGHT \
  --network [main|regtest|test|signet] \
  --save-backup FILE.json        # Optional: save recovery info
  --private-key HEX              # Optional: use existing key
```

### Spending

```bash
python spend_taproot_locked_utxo.py \
  --descriptor "tr(...)" \
  --private-key "WIF_KEY" \
  --utxo "txid:vout:amount"      # Can repeat for multiple UTXOs
  --destination "bc1p..." \
  --locktime BLOCK_HEIGHT \
  --network [mainnet|testnet|signet|regtest] \
  --fee-rate SATS_PER_VB         # Default: 10
  --broadcast                    # Auto-broadcast via API
  --broadcast-api [mempool|blockstream]
  --psbt                         # Output PSBT for verification
```

**Fee rates** (check [mempool.space/fees](https://mempool.space/fees)):
- Low priority: 5-10 sat/vB
- Medium: 15-30 sat/vB
- High priority: 50+ sat/vB

---

## Security Notes

### How It Works

The address uses a **NUMS point** (Nothing Up My Sleeve) as the internal Taproot key. This makes the key-path spend mathematically impossible — funds can **only** be spent through the script path, which enforces the timelock.

```
tr(NUMS_POINT, and_v(v:pk(YOUR_KEY), after(LOCKTIME)))
```

The timelock is checked by every Bitcoin node. If the blockchain hasn't reached the locktime block, nodes reject the transaction as "non-final".

### What You Need to Save

Keep these safe — you cannot recover funds without them:
- **Descriptor** — identifies the exact script
- **Private key** (WIF format)
- **Locktime value**

The `--save-backup` flag creates an encrypted-ready JSON file with all of this.

### Verify Before Broadcasting (Optional)

For large amounts, generate a PSBT first:

```bash
python spend_taproot_locked_utxo.py ... --psbt
```

Import the PSBT into [Sparrow Wallet](https://sparrowwallet.com/) or similar to verify:
- Input/output amounts
- Destination address
- Fee amount

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `non-final` | Locktime not reached | Wait for more blocks |
| `dust` | Output too small | Send more BTC or lower fee |
| Network error on broadcast | API issue | Try `--broadcast-api blockstream` or manual broadcast |

**Manual broadcast:** Paste the raw transaction at [mempool.space/tx/push](https://mempool.space/tx/push)

---

## Files

| File | Purpose |
|------|---------|
| `create_taproot_locked_address.py` | Generate locked addresses |
| `spend_taproot_locked_utxo.py` | Spend after locktime |
| `test_btc_network/` | Local regtest for testing |
| `requirements.txt` | Dependencies (embit library) |

---

## Testing Locally (Regtest)

For development and testing without real Bitcoin.

### Setup

```bash
# Start local Bitcoin node
cd test_btc_network
docker-compose up -d

# Create wallet and mine initial coins
./btc.sh createwallet "test"
./btc.sh -rpcwallet=test getnewaddress
./btc.sh generatetoaddress 101 <address_from_above>
```

### Test the Full Flow

```bash
# 1. Create address locked at block 120
python create_taproot_locked_address.py --locktime 120 --network regtest

# 2. Fund it (save the txid)
./btc.sh -rpcwallet=test sendtoaddress <locked_address> 0.1
./btc.sh generatetoaddress 1 $(./btc.sh -rpcwallet=test getnewaddress)

# 3. Try to spend (will fail - "non-final")
python spend_taproot_locked_utxo.py \
  --descriptor "tr(...)" \
  --private-key "cXXX..." \
  --utxo "txid:0:0.1" \
  --destination $(./btc.sh -rpcwallet=test getnewaddress "" bech32m) \
  --locktime 120 \
  --network regtest

# Copy the raw tx, then:
./btc.sh sendrawtransaction <raw_tx>
# ERROR: non-final

# 4. Mine to reach locktime
./btc.sh generatetoaddress 20 $(./btc.sh -rpcwallet=test getnewaddress)
./btc.sh getblockcount  # Should be > 120

# 5. Broadcast again (now succeeds)
./btc.sh sendrawtransaction <raw_tx>
./btc.sh generatetoaddress 1 $(./btc.sh -rpcwallet=test getnewaddress)
```

### Cleanup

```bash
cd test_btc_network
docker-compose down     # Stop
docker-compose down -v  # Stop and delete all data
```

---

## Detailed Regtest Walkthrough

<details>
<summary>Click to expand full step-by-step example with actual output</summary>

### 1. Start Bitcoin Regtest

```bash
cd test_btc_network
docker-compose up -d
./btc.sh getblockchaininfo
```

Output:
```json
{
  "chain": "regtest",
  "blocks": 0,
  ...
}
```

### 2. Create Wallet and Mine Coins

```bash
./btc.sh createwallet "test"
./btc.sh -rpcwallet=test getnewaddress
# bcrt1qfhq5gjksvl93m33cstqmee9wa94vcu8vx7ha2u

./btc.sh generatetoaddress 101 bcrt1qfhq5gjksvl93m33cstqmee9wa94vcu8vx7ha2u
./btc.sh -rpcwallet=test getbalance
# 50.00000000
```

### 3. Create Timelocked Address

```bash
python create_taproot_locked_address.py --locktime 120 --network regtest
```

Output:
```
======================================================================
TAPROOT TIMELOCKED ADDRESS CREATED (NUMS-SECURED)
======================================================================
Network:            regtest
Locktime (block):   120
Address:            bcrt1pftke8xlcuv2ul40m45nrk28ak5xtg30g3nq0qtr6kzgfaxgpm7ms4s70eg

--- SECURITY INFO ---
Internal Key:       50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0 (NUMS - unspendable)
Key Path Spend:     IMPOSSIBLE (timelock cannot be bypassed)

--- SAVE THIS INFORMATION ---
Descriptor:         tr(50929b74...,and_v(v:pk(02870eece8...),after(120)))
Private Key (hex):  57dda3e3f5f640396893ac35edbe8e85d1383fc4cfc527f0667353613a6c91f0
Private Key (WIF):  cQXW2RNdhZNPNMR1Dj9x8YzctVXL2hEArXEhsg3jnMf7TFvhw7Fi
======================================================================
```

### 4. Fund the Address

```bash
./btc.sh -rpcwallet=test sendtoaddress bcrt1pftke8xlcuv2ul40m45nrk28ak5xtg30g3nq0qtr6kzgfaxgpm7ms4s70eg 0.2
# c7041b09e125c5436a6bcfe8df4573c6f6b40c435ac05d725e1f5d144738e414

./btc.sh generatetoaddress 1 $(./btc.sh -rpcwallet=test getnewaddress)
./btc.sh getblockcount
# 102
```

### 5. Create Spend Transaction

```bash
./btc.sh -rpcwallet=test getnewaddress "" bech32m
# bcrt1pn09axek9gtthvdg4qgglv2pa8l6dn9uaxykd7shyh0gy02nhm9sslp6ha5

python spend_taproot_locked_utxo.py \
  --descriptor "tr(50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0,and_v(v:pk(02870eece8726f50ad13a2a7247c4081229ac69a47b4a462e2a0f2bb6c7f5e1bdf),after(120)))" \
  --private-key cQXW2RNdhZNPNMR1Dj9x8YzctVXL2hEArXEhsg3jnMf7TFvhw7Fi \
  --utxo "c7041b09e125c5436a6bcfe8df4573c6f6b40c435ac05d725e1f5d144738e414:0:0.2" \
  --destination bcrt1pn09axek9gtthvdg4qgglv2pa8l6dn9uaxykd7shyh0gy02nhm9sslp6ha5 \
  --locktime 120 \
  --network regtest
```

### 6. Try Broadcasting (Fails - Too Early)

```bash
./btc.sh sendrawtransaction 0200000000010114e43847...
```

Output:
```
error code: -26
error message: non-final
```

This is correct! Block height is 102, locktime is 120.

### 7. Mine to Locktime

```bash
./btc.sh generatetoaddress 20 $(./btc.sh -rpcwallet=test getnewaddress)
./btc.sh getblockcount
# 122
```

### 8. Broadcast (Succeeds)

```bash
./btc.sh sendrawtransaction 0200000000010114e43847...
# 6a4e735c0d8149faf5179fb145b5b12e835767fbc2c7f863664ade64a9be73a1
```

### 9. Verify

```bash
./btc.sh generatetoaddress 1 $(./btc.sh -rpcwallet=test getnewaddress)
./btc.sh gettxout 6a4e735c0d8149faf5179fb145b5b12e835767fbc2c7f863664ade64a9be73a1 0
```

Output:
```json
{
  "confirmations": 1,
  "value": 0.19998890,
  "scriptPubKey": {
    "address": "bcrt1pn09axek9gtthvdg4qgglv2pa8l6dn9uaxykd7shyh0gy02nhm9sslp6ha5",
    "type": "witness_v1_taproot"
  }
}
```

Funds arrived! (0.2 BTC - 1110 sats fee = 0.19998890 BTC)

</details>
