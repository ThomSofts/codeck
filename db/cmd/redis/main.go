// codeck-db-redis: plugin de Redis do Codeck (protocolo em internal/proto).
package main

import (
	"codeck/db/internal/docs"
	"codeck/db/internal/redis"
)

func main() { docs.Serve(redis.Driver{}) }
