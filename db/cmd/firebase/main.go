// codeck-db-firebase: plugin de Firebase (Firestore e Realtime Database) do Codeck (protocolo em internal/proto).
package main

import (
	"codeck/db/internal/docs"
	"codeck/db/internal/firebase"
)

func main() { docs.Serve(firebase.Driver{}) }
