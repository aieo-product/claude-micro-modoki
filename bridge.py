from threading import Thread
import json
import traceback
from flask import Flask, jsonify, request
from websockets.sync.server import serve as websocket_serve
from websockets.sync.server import ServerConnection

bridge_addr = '0.0.0.0'
bridge_port = 35703

app = Flask(__name__)

client = None
last_message = None

def websocket_cb(conn:ServerConnection):
    global last_message, client
    print(conn)
    print(conn.recv())
    client = conn
    while True:
        msg = conn.recv()
        last_message = msg

ws = websocket_serve(websocket_cb, bridge_addr, bridge_port + 1)

def websocket_main():
    ws.serve_forever()

thread_websocket = Thread(group=None, target=websocket_main)
thread_websocket.start()


@app.route("/decision", methods=["POST"])
def route_decision():
    global client, last_message
    if client is not None:
        client.send(json.dumps(request.json))
        while True:
            if last_message is not None:
                print(last_message)
                msg = json.loads(last_message)
                last_message = None
                return jsonify({
                    "result": msg["result"]
                })

    return jsonify({"result": "fallback"})


app.run(bridge_addr, bridge_port)

ws.shutdown()
thread_websocket.join()
