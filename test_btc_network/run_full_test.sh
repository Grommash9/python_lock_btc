#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================================================"
echo "TAPROOT TIMELOCKED ADDRESS - FULL TEST"
echo "========================================================================"

cd "$(dirname "$0")"

# Step 1: Clean up and start fresh
echo -e "\n${YELLOW}[1/9] Stopping any existing regtest network...${NC}"
docker-compose down -v 2>/dev/null || true
sleep 1

echo -e "\n${YELLOW}[2/9] Starting fresh regtest network...${NC}"
docker-compose up -d
sleep 3

# Verify it's running
BLOCKS=$(./btc.sh getblockcount 2>/dev/null || echo "error")
if [ "$BLOCKS" == "error" ]; then
    echo -e "${RED}ERROR: Failed to connect to bitcoind${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Regtest network running (block $BLOCKS)${NC}"

# Step 2: Create wallet and mine initial blocks
echo -e "\n${YELLOW}[3/9] Creating wallet and mining initial blocks...${NC}"
./btc.sh createwallet "test" > /dev/null 2>&1 || ./btc.sh loadwallet "test" > /dev/null 2>&1
MINER_ADDR=$(./btc.sh -rpcwallet=test getnewaddress)
./btc.sh generatetoaddress 101 "$MINER_ADDR" > /dev/null
BALANCE=$(./btc.sh -rpcwallet=test getbalance)
echo -e "${GREEN}✓ Wallet created, balance: $BALANCE BTC${NC}"

# Step 3: Create timelocked address
echo -e "\n${YELLOW}[4/9] Creating timelocked address (locktime=120)...${NC}"
LOCKTIME=120
OUTPUT=$(cd .. && python create_taproot_locked_address.py --locktime $LOCKTIME --network regtest)
echo "$OUTPUT"

# Parse output
LOCKED_ADDR=$(echo "$OUTPUT" | grep "^Address:" | awk '{print $2}')
DESCRIPTOR=$(echo "$OUTPUT" | grep "^Descriptor:" | sed 's/Descriptor:[[:space:]]*//')
PRIVATE_KEY=$(echo "$OUTPUT" | grep "Private Key (WIF):" | awk '{print $4}')

if [ -z "$LOCKED_ADDR" ] || [ -z "$DESCRIPTOR" ] || [ -z "$PRIVATE_KEY" ]; then
    echo -e "${RED}ERROR: Failed to parse address creation output${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Timelocked address created: $LOCKED_ADDR${NC}"

# Step 4: Fund the locked address
echo -e "\n${YELLOW}[5/9] Funding locked address with 0.2 BTC...${NC}"
FUND_TXID=$(./btc.sh -rpcwallet=test sendtoaddress "$LOCKED_ADDR" 0.2)
./btc.sh generatetoaddress 1 "$MINER_ADDR" > /dev/null
BLOCK_COUNT=$(./btc.sh getblockcount)

# Find the correct vout (sendtoaddress may put our output at vout 0 or 1)
VOUT=$(./btc.sh getrawtransaction "$FUND_TXID" true | jq -r --arg addr "$LOCKED_ADDR" '.vout[] | select(.scriptPubKey.address == $addr) | .n')
if [ -z "$VOUT" ]; then
    echo -e "${RED}ERROR: Could not find vout for locked address${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Funded with TXID: $FUND_TXID (vout: $VOUT)${NC}"
echo -e "${GREEN}✓ Current block: $BLOCK_COUNT (locktime: $LOCKTIME)${NC}"

# Step 5: Get destination address
DEST_ADDR=$(./btc.sh -rpcwallet=test getnewaddress "" bech32m)
echo -e "${GREEN}✓ Destination address: $DEST_ADDR${NC}"

# Step 6: Create spend transaction
echo -e "\n${YELLOW}[6/9] Creating spend transaction...${NC}"
SPEND_OUTPUT=$(cd .. && python spend_taproot_locked_utxo.py \
    --descriptor "$DESCRIPTOR" \
    --private-key "$PRIVATE_KEY" \
    --txid "$FUND_TXID" \
    --vout "$VOUT" \
    --amount 0.2 \
    --destination "$DEST_ADDR" \
    --locktime $LOCKTIME \
    --network regtest 2>&1)

RAW_TX=$(echo "$SPEND_OUTPUT" | grep -A1 "Raw transaction" | tail -1)
SPEND_TXID=$(echo "$SPEND_OUTPUT" | grep "^TXID:" | head -2 | tail -1 | awk '{print $2}')

if [ -z "$RAW_TX" ]; then
    echo -e "${RED}ERROR: Failed to create spend transaction${NC}"
    echo "$SPEND_OUTPUT"
    exit 1
fi
echo -e "${GREEN}✓ Spend transaction created (${#RAW_TX} chars)${NC}"

# Step 7: Try to broadcast BEFORE locktime (should fail)
echo -e "\n${YELLOW}[7/9] Testing broadcast BEFORE locktime (should fail)...${NC}"
BROADCAST_RESULT=$(./btc.sh sendrawtransaction "$RAW_TX" 2>&1 || true)

if echo "$BROADCAST_RESULT" | grep -q "non-final"; then
    echo -e "${GREEN}✓ Correctly rejected with 'non-final' (locktime not reached)${NC}"
else
    echo -e "${RED}ERROR: Expected 'non-final' error but got: $BROADCAST_RESULT${NC}"
    exit 1
fi

# Step 8: Mine to reach locktime
echo -e "\n${YELLOW}[8/9] Mining blocks to reach locktime...${NC}"
BLOCKS_NEEDED=$((LOCKTIME - BLOCK_COUNT + 1))
./btc.sh generatetoaddress $BLOCKS_NEEDED "$MINER_ADDR" > /dev/null
NEW_BLOCK_COUNT=$(./btc.sh getblockcount)
echo -e "${GREEN}✓ Mined $BLOCKS_NEEDED blocks, now at block $NEW_BLOCK_COUNT${NC}"

# Step 9: Broadcast AFTER locktime (should succeed)
echo -e "\n${YELLOW}[9/9] Broadcasting AFTER locktime (should succeed)...${NC}"
BROADCAST_TXID=$(./btc.sh sendrawtransaction "$RAW_TX" 2>&1)

if [ ${#BROADCAST_TXID} -eq 64 ]; then
    echo -e "${GREEN}✓ Transaction broadcast successfully!${NC}"
    echo -e "${GREEN}✓ TXID: $BROADCAST_TXID${NC}"
else
    echo -e "${RED}ERROR: Broadcast failed: $BROADCAST_TXID${NC}"
    exit 1
fi

# Confirm and verify
./btc.sh generatetoaddress 1 "$MINER_ADDR" > /dev/null
UTXO_CHECK=$(./btc.sh gettxout "$BROADCAST_TXID" 0 2>&1)

if echo "$UTXO_CHECK" | grep -q "confirmations"; then
    CONFIRMED_VALUE=$(echo "$UTXO_CHECK" | grep '"value"' | awk -F: '{print $2}' | tr -d ' ,')
    echo -e "${GREEN}✓ Transaction confirmed with value: $CONFIRMED_VALUE BTC${NC}"
else
    echo -e "${RED}ERROR: Could not verify UTXO${NC}"
    exit 1
fi

echo ""
echo "========================================================================"
echo -e "${GREEN}ALL TESTS PASSED!${NC}"
echo "========================================================================"
echo "Summary:"
echo "  - Timelocked address: $LOCKED_ADDR"
echo "  - Funding TXID:       $FUND_TXID"
echo "  - Spend TXID:         $BROADCAST_TXID"
echo "  - Locktime:           $LOCKTIME"
echo "  - Final block:        $(./btc.sh getblockcount)"
echo "========================================================================"
