#!/bin/bash
# Helper script to run bitcoin-cli commands against the regtest node

docker exec btc-regtest bitcoin-cli -regtest -rpcuser=bitcoin -rpcpassword=bitcoin123 "$@"
