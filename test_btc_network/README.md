# Bitcoin Regtest Network

Local Bitcoin regtest network for testing timelock transactions and other Bitcoin scripts.

## Why Regtest?

- **Instant blocks**: Mine blocks on demand, no waiting
- **Free coins**: Generate as many test bitcoins as you need
- **Full control**: Reset, fast-forward, or manipulate the chain as needed
- **No external dependencies**: Works offline, no faucets required

## Quick Start

### 1. Start the network

```bash
docker-compose up -d
```

### 2. Create a wallet and generate coins

```bash
# Create a wallet
./btc.sh createwallet "test"

# Generate an address
./btc.sh getnewaddress

# Mine 101 blocks to that address (need 100 confirmations for coinbase maturity)
./btc.sh generatetoaddress 101 <your_address>

# Check balance
./btc.sh getbalance
```

### 3. Common commands

```bash
# Check blockchain info
./btc.sh getblockchaininfo

# Get current block height
./btc.sh getblockcount

# Mine N blocks (useful for testing timelocks!)
./btc.sh generatetoaddress <N> <address>

# Send raw transaction
./btc.sh sendrawtransaction <hex>

# Decode raw transaction
./btc.sh decoderawtransaction <hex>

# Get transaction details
./btc.sh getrawtransaction <txid> true

# List unspent outputs
./btc.sh listunspent
```

## Testing Timelocks

For testing CLTV (CheckLockTimeVerify) scripts:

1. Create your locked address and send coins to it
2. Try to spend before the locktime - should fail with "non-final" error
3. Mine blocks until you reach the target block height:
   ```bash
   # Check current height
   ./btc.sh getblockcount

   # Mine blocks to reach target
   ./btc.sh generatetoaddress 10 $(./btc.sh getnewaddress)
   ```
4. Now spend - should succeed!

## RPC Connection Details

For your Python scripts:

```python
# Connection settings for regtest
RPC_USER = "bitcoin"
RPC_PASSWORD = "bitcoin123"
RPC_HOST = "127.0.0.1"
RPC_PORT = 18443
```

Example with `python-bitcoinlib`:

```python
from bitcoin.rpc import RawProxy

proxy = RawProxy(
    service_url="http://bitcoin:bitcoin123@127.0.0.1:18443"
)

# Get blockchain info
info = proxy.getblockchaininfo()
print(f"Chain: {info['chain']}, Blocks: {info['blocks']}")
```

## Useful Tips

### Reset the chain
```bash
docker-compose down -v
docker-compose up -d
```

### View logs
```bash
docker-compose logs -f
```

### Stop the network
```bash
docker-compose down
```

### Direct bitcoin-cli access
```bash
docker exec -it btc-regtest bitcoin-cli -regtest -rpcuser=bitcoin -rpcpassword=bitcoin123 <command>
```

## Network Parameters

| Parameter | Value |
|-----------|-------|
| Network | regtest |
| RPC Port | 18443 |
| P2P Port | 18444 |
| Default fee | 0.0001 BTC |
| Address prefix | bcrt1... (bech32) |
