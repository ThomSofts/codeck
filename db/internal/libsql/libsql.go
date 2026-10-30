// Package libsql: libSQL/Turso (SQLite na rede). Mesmo SQL e catálogo do SQLite; a conexão é a URL do banco
// (libsql://nome-org.turso.io) com o token de acesso no lugar da senha. HTTPS com o certificado verificado pelo sistema.
package libsql

import (
	"context"
	"database/sql"
	"fmt"
	"strings"

	"github.com/tursodatabase/libsql-client-go/libsql"

	"codeck/db/internal/engine"
	"codeck/db/internal/sqlite"
)

type Dialect struct{ sqlite.Dialect }

func (Dialect) Engine() string { return "libsql" }

func (Dialect) Open(p engine.ConnParams, _ *engine.Capture) (*sql.DB, error) {
	u := strings.TrimSpace(p.Host)
	off, err := p.TLS.Off()
	if err != nil {
		return nil, err
	}
	if !strings.HasPrefix(u, "libsql://") && !strings.HasPrefix(u, "https://") && !(off && strings.HasPrefix(u, "http://")) {
		return nil, fmt.Errorf("use a URL do banco (libsql://… ou https://…)")
	}
	opts := []libsql.Option{libsql.WithTls(!off)}
	if p.Password != "" {
		opts = append(opts, libsql.WithAuthToken(p.Password))
	}
	c, err := libsql.NewConnector(u, opts...)
	if err != nil {
		return nil, err
	}
	return sql.OpenDB(c), nil
}

func (Dialect) Version(ctx context.Context, q engine.Queryer) string {
	return "libSQL " + engine.Scalar(ctx, q, "SELECT sqlite_version()")
}
