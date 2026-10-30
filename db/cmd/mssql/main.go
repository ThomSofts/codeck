// codeck-db-mssql: plugin de SQL Server do Codeck (protocolo em internal/proto).
package main

import (
	"codeck/db/internal/engine"
	"codeck/db/internal/mssql"
)

func main() { engine.New(mssql.Dialect{}).Serve() }
