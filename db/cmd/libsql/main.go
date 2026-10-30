//go:debug x509negativeserial=1

// codeck-db-libsql: plugin de libSQL/Turso do Codeck (protocolo em internal/proto).
//
// O go:debug acima: servidores com certificado próprio (todo SQL Server antigo, muitos MySQL/PostgreSQL) às vezes o
// geram com número de série negativo, que o Go recusa desde a 1.23 — antes de o Codeck conferir a impressão digital
// fixada. A confiança vem do certificado fixado ou da cadeia verificada, não do número de série.
package main

import (
	"codeck/db/internal/engine"
	"codeck/db/internal/libsql"
)

func main() { engine.New(libsql.Dialect{}).Serve() }
