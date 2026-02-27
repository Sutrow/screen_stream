"""
GPT Proxy
=========
Запускайте на Windows рядом с ChatMock.
Добавляет CORS-заголовки чтобы браузер мог обращаться к ChatMock
с внешнего домена (kege-station.store).

Установка:  pip install flask flask-cors requests
Запуск:     python gpt_proxy.py
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

CHATMOCK_URL = "http://127.0.0.1:8000"


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
def completions():
    if request.method == "OPTIONS":
        return "", 204
    try:
        resp = requests.post(
            f"{CHATMOCK_URL}/v1/chat/completions",
            json=request.get_json(),
            headers={"Authorization": "Bearer key"},
            timeout=120
        )
        return jsonify(resp.json()), resp.status_code
    except requests.exceptions.ConnectionError:
        return jsonify({"error": {"message": "ChatMock недоступен. Запустите: python chatmock.py serve"}}), 503
    except Exception as e:
        return jsonify({"error": {"message": str(e)}}), 500


if __name__ == "__main__":
    print("🤖 GPT Proxy запущен на http://127.0.0.1:8001")
    print("   Убедитесь что ChatMock запущен: python chatmock.py serve")
    print("-" * 40)
    app.run(host="127.0.0.1", port=8001)