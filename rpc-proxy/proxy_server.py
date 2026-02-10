#!/usr/bin/env python3
"""
Simple Flask RPC proxy for Bitcoin regtest.
Bridges web app to local bitcoind for UTXO fetching and transaction broadcasting.

Usage:
    pip install -r requirements.txt
    python proxy_server.py

Runs on localhost:5000 with CORS enabled.
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import requests
import json

app = Flask(__name__)
CORS(app)

# Bitcoin Core RPC configuration (matches docker-compose.yml)
RPC_URL = "http://localhost:18443"
RPC_USER = "bitcoin"
RPC_PASS = "bitcoin123"


def rpc_call(method: str, params: list = None) -> dict:
    """Make RPC call to bitcoind"""
    payload = {
        "jsonrpc": "2.0",
        "id": "proxy",
        "method": method,
        "params": params or []
    }
    try:
        response = requests.post(
            RPC_URL,
            auth=(RPC_USER, RPC_PASS),
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        return response.json()
    except requests.exceptions.ConnectionError:
        return {"error": {"message": "Cannot connect to bitcoind. Is regtest running?"}}
    except Exception as e:
        return {"error": {"message": str(e)}}


@app.route('/rpc', methods=['POST'])
def rpc_proxy():
    """Forward arbitrary RPC calls to bitcoind"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    method = data.get('method')
    params = data.get('params', [])

    if not method:
        return jsonify({"error": "Missing 'method' field"}), 400

    result = rpc_call(method, params)
    return jsonify(result)


@app.route('/utxos/<address>', methods=['GET'])
def get_utxos(address: str):
    """
    Get UTXOs for address using scantxoutset.
    Returns format compatible with mempool.space API.
    """
    result = rpc_call('scantxoutset', ['start', [f'addr({address})']])

    if 'error' in result and result['error']:
        return jsonify({'error': result['error'].get('message', str(result['error']))}), 400

    utxos = []
    result_data = result.get('result', {})

    for unspent in result_data.get('unspents', []):
        utxos.append({
            'txid': unspent['txid'],
            'vout': unspent['vout'],
            'value': int(float(unspent['amount']) * 100_000_000),  # BTC to sats
            'status': {'confirmed': True}
        })

    return jsonify(utxos)


@app.route('/block/height', methods=['GET'])
def get_block_height():
    """Get current block height"""
    result = rpc_call('getblockcount')

    if 'error' in result and result['error']:
        return jsonify({'error': result['error'].get('message', str(result['error']))}), 400

    return jsonify({'height': result.get('result', 0)})


@app.route('/block/info', methods=['GET'])
def get_block_info():
    """Get full blockchain info"""
    result = rpc_call('getblockchaininfo')

    if 'error' in result and result['error']:
        return jsonify({'error': result['error'].get('message', str(result['error']))}), 400

    info = result.get('result', {})
    return jsonify({
        'height': info.get('blocks', 0),
        'chain': info.get('chain', 'unknown'),
        'bestblockhash': info.get('bestblockhash', ''),
        'difficulty': info.get('difficulty', 0),
        'mediantime': info.get('mediantime', 0)
    })


@app.route('/tx', methods=['POST'])
def broadcast_tx():
    """Broadcast raw transaction"""
    tx_hex = request.get_data(as_text=True)

    if not tx_hex:
        return jsonify({'error': 'Missing transaction hex'}), 400

    # Strip any whitespace/newlines
    tx_hex = tx_hex.strip()

    result = rpc_call('sendrawtransaction', [tx_hex])

    if 'error' in result and result['error']:
        error_msg = result['error'].get('message', str(result['error']))
        return jsonify({'error': error_msg}), 400

    # Return just the txid as plain text (compatible with mempool.space)
    txid = result.get('result', '')
    return Response(txid, mimetype='text/plain')


@app.route('/tx/<txid>', methods=['GET'])
def get_transaction(txid: str):
    """Get transaction details"""
    result = rpc_call('getrawtransaction', [txid, True])

    if 'error' in result and result['error']:
        return jsonify({'error': result['error'].get('message', str(result['error']))}), 400

    return jsonify(result.get('result', {}))


@app.route('/fees/recommended', methods=['GET'])
def get_fees():
    """Return mock fee recommendations for regtest (always 1 sat/vB is fine)"""
    return jsonify({
        'fastestFee': 1,
        'halfHourFee': 1,
        'hourFee': 1,
        'economyFee': 1,
        'minimumFee': 1
    })


@app.route('/address/<address>', methods=['GET'])
def get_address_info(address: str):
    """Get address info including balance"""
    # Use scantxoutset to get balance
    result = rpc_call('scantxoutset', ['start', [f'addr({address})']])

    if 'error' in result and result['error']:
        return jsonify({'error': result['error'].get('message', str(result['error']))}), 400

    result_data = result.get('result', {})
    total_sats = int(float(result_data.get('total_amount', 0)) * 100_000_000)

    return jsonify({
        'address': address,
        'chain_stats': {
            'funded_txo_count': len(result_data.get('unspents', [])),
            'funded_txo_sum': total_sats,
            'spent_txo_count': 0,  # Can't determine from scantxoutset
            'spent_txo_sum': 0
        }
    })


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    result = rpc_call('getblockcount')

    if 'error' in result and result['error']:
        return jsonify({
            'status': 'error',
            'bitcoind': False,
            'error': result['error'].get('message', str(result['error']))
        }), 503

    return jsonify({
        'status': 'ok',
        'bitcoind': True,
        'block_height': result.get('result', 0)
    })


if __name__ == '__main__':
    print("=" * 60)
    print("Bitcoin Regtest RPC Proxy")
    print("=" * 60)
    print(f"RPC URL: {RPC_URL}")
    print(f"RPC User: {RPC_USER}")
    print("=" * 60)
    print("Endpoints:")
    print("  GET  /health          - Health check")
    print("  GET  /block/height    - Current block height")
    print("  GET  /block/info      - Full blockchain info")
    print("  GET  /utxos/:address  - Get UTXOs for address")
    print("  GET  /address/:addr   - Get address info")
    print("  GET  /tx/:txid        - Get transaction details")
    print("  POST /tx              - Broadcast raw transaction")
    print("  GET  /fees/recommended - Fee recommendations")
    print("  POST /rpc             - Forward any RPC call")
    print("=" * 60)
    print("Starting server on http://localhost:5001")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5001, debug=True)
