// codeck-db-postgres: plugin do Codeck (protocolo em internal/proto).
package main

import (
	"codeck/db/internal/engine"
	"codeck/db/internal/postgres"
)

func main() { engine.New(postgres.Dialect{}).Serve() }
