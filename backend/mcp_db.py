"""Servidor MCP (stdio) dos bancos de dados do Codeck para os agentes de IA.

O agente abre este programa (o Codeck põe na linha de comando dele); cada ferramenta vira um POST no backend local
(CODECK_DB_MCP = http://127.0.0.1:<porta>/dbmcp/<token do projeto>), que decide o que o agente pode ver e pergunta a
você quando precisa. Aqui não há credencial nem acesso direto a banco nenhum. Só a biblioteca padrão do Python.
"""
import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("CODECK_DB_MCP", "")
TOOLS = None


def backend(payload, timeout=35 * 60):   # a aprovação pode esperar até 30 min
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    global TOOLS
    # o MCP fala UTF-8; no Windows o padrão do pipe seria cp1252 (e o -I ignora o PYTHONIOENCODING)
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    if not URL.startswith("http://127.0.0.1:"):
        sys.stderr.write("CODECK_DB_MCP ausente — este servidor só roda aberto pelo Codeck\n")
        return 1
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:   # notificação (initialized, cancelled…)
            continue
        try:
            if method == "initialize":
                ver = (msg.get("params") or {}).get("protocolVersion") or "2025-06-18"
                send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": ver, "capabilities": {"tools": {}},
                      "serverInfo": {"name": "codeck-db", "version": "1"},
                      "instructions": "Bancos de dados do projeto, liberados no Codeck. Comece por list_databases. Alterações e leituras em "
                                      "produção pedem aprovação da pessoa — se ela negar, não insista."}})
            elif method == "ping":
                send({"jsonrpc": "2.0", "id": mid, "result": {}})
            elif method == "tools/list":
                if TOOLS is None:
                    TOOLS = backend({"tool": "__tools__"}, timeout=30).get("result") or []
                send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
            elif method == "tools/call":
                p = msg.get("params") or {}
                r = backend({"tool": p.get("name"), "args": p.get("arguments") or {}})
                text = json.dumps(r.get("result"), ensure_ascii=False, default=str) if r.get("ok") else r.get("error") or "erro"
                send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": not r.get("ok")}})
            else:
                send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"método desconhecido: {method}"}})
        except (urllib.error.URLError, OSError) as e:
            send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": f"Codeck indisponível: {e}"}], "isError": True}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
