// codeck-db-mysql: plugin do Codeck (protocolo em internal/proto).
package main

import (
	"codeck/db/internal/engine"
	"codeck/db/internal/mysql"
)

func main() { engine.New(mysql.Dialect{}).Serve() }
