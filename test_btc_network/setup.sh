#!/bin/bash
# Initial setup script for the regtest network
# Run this after starting the containers for the first time

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BTC="$SCRIPT_DIR/btc.sh"

echo "Waiting for bitcoind to start..."
sleep 3

echo "Creating wallet 'test'..."
$BTC createwallet "test" || echo "Wallet might already exist"

echo "Generating new address..."
ADDRESS=$($BTC getnewaddress)
echo "Address: $ADDRESS"

echo "Mining 101 blocks (for coinbase maturity)..."
$BTC generatetoaddress 101 "$ADDRESS" > /dev/null

BALANCE=$($BTC getbalance)
echo "Balance: $BALANCE BTC"

BLOCK_HEIGHT=$($BTC getblockcount)
echo "Block height: $BLOCK_HEIGHT"

echo ""
echo "Setup complete! Your regtest network is ready."
echo "Use ./btc.sh <command> to interact with the node."
