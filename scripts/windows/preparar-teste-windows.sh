#!/usr/bin/env bash
# Monta, no Mac, o pacote para testar os bancos de dados no Windows: dist/codeck-teste-windows.zip com o backend, o
# runner dos testes, as fixtures, os plugins compilados para Windows (.exe) e o testar-bancos.ps1.
# No Windows: extraia, abra o PowerShell na pasta e rode
#   powershell -ExecutionPolicy Bypass -File testar-bancos.ps1
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/dist/codeck-teste-windows"
rm -rf "$OUT" "$OUT.zip"
mkdir -p "$OUT/backend" "$OUT/tests/db" "$OUT/plugins"
cp "$ROOT/backend/server.py" "$ROOT/backend/mcp_db.py" "$OUT/backend/"
rsync -a --exclude __pycache__ "$ROOT/backend/pilot" "$OUT/backend/"
rsync -a --exclude __pycache__ "$ROOT/tests/db/run_tests.py" "$ROOT/tests/db/fixtures" "$OUT/tests/db/"
bash "$ROOT/scripts/build-db-plugins.sh" windows "$OUT/plugins" >/dev/null
cp "$ROOT/scripts/windows/testar-bancos.ps1" "$OUT/"
cat > "$OUT/LEIA-ME.txt" <<'EOF'
Teste dos bancos de dados do Codeck no Windows

1. Extraia esta pasta em qualquer lugar (ex.: Downloads\codeck-teste-windows).
2. Opcional: ligue o Docker Desktop — aí os testes também sobem Postgres, MySQL, MongoDB e Redis de verdade.
3. Abra o PowerShell nesta pasta e rode:
     powershell -ExecutionPolicy Bypass -File testar-bancos.ps1
   (sem Docker: acrescente -SemDocker · sem mexer na área de transferência: -SemAreaDeTransferencia)
4. O relatório fica na Área de trabalho: codeck-teste-bancos.txt — mande para o Claude.

Não mexe nos seus dados do Codeck (%APPDATA%\Codeck): usa uma pasta temporária e apaga as senhas de teste no fim.
EOF
(cd "$ROOT/dist" && zip -qr codeck-teste-windows.zip codeck-teste-windows)
echo "✓ $ROOT/dist/codeck-teste-windows.zip ($(du -h "$ROOT/dist/codeck-teste-windows.zip" | cut -f1))"
