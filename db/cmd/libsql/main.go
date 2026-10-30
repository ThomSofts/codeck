// codeck-db-libsql: plugin de libSQL/Turso do Codeck (protocolo em internal/proto).
package main

import (
	"codeck/db/internal/engine"
	"codeck/db/internal/libsql"
)

func main() { engine.New(libsql.Dialect{}).Serve() }
