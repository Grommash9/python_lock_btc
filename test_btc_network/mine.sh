#!/bin/bash
# Quick mine N blocks
# Usage: ./mine.sh [N]  (default: 1 block)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BTC="$SCRIPT_DIR/btc.sh"

NUM_BLOCKS=${1:-1}
ADDRESS=$($BTC getnewaddress)

echo "Mining $NUM_BLOCKS block(s)..."
$BTC generatetoaddress "$NUM_BLOCKS" "$ADDRESS" > /dev/null

NEW_HEIGHT=$($BTC getblockcount)
echo "Done! Block height: $NEW_HEIGHT"
