// codeck-db-mongodb: plugin de MongoDB do Codeck (protocolo em internal/proto).
package main

import (
	"codeck/db/internal/docs"
	"codeck/db/internal/mongo"
)

func main() { docs.Serve(mongo.Driver{}) }
