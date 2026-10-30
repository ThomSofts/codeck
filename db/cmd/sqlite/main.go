// codeck-db-sqlite: plugin do Codeck (protocolo em internal/proto).
package main

import (
	"codeck/db/internal/engine"
	"codeck/db/internal/sqlite"
)

func main() { engine.New(sqlite.Dialect{}).Serve() }
