// Package postgres: PostgreSQL 10+ (e o que fala o protocolo dele: Supabase, Neon, CockroachDB…), pelo pgx.
package postgres

import (
	"context"
	"database/sql"
	"fmt"
	"net/url"
	"strconv"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/stdlib"

	"codeck/db/internal/engine"
)

type Dialect struct{}

func (Dialect) Engine() string           { return "postgres" }
func (Dialect) Quote(id string) string   { return engine.QuoteWith(`"`, `"`, id) }
func (Dialect) Param(i int) string       { return "$" + strconv.Itoa(i) }
func (Dialect) Split() engine.SplitStyle { return engine.SplitSemicolon }
func (Dialect) ReadOnlyTx() bool         { return true }
func (Dialect) Literal(v any) string     { return engine.GenericLiteral(v) }

func (Dialect) Open(p engine.ConnParams, cap *engine.Capture) (*sql.DB, error) {
	port := p.Port
	if port == 0 {
		port = 5432
	}
	off, err := p.TLS.Off()
	if err != nil {
		return nil, err
	}
	q := url.Values{}
	q.Set("application_name", "Codeck")
	q.Set("connect_timeout", "15")
	q.Set("sslmode", map[bool]string{true: "disable", false: "require"}[off])
	u := &url.URL{Scheme: "postgres", User: url.UserPassword(p.User, p.Password), Host: fmt.Sprintf("%s:%d", p.Host, port), Path: "/" + p.Database, RawQuery: q.Encode()}
	cfg, err := pgx.ParseConfig(u.String())
	if err != nil {
		return nil, fmt.Errorf("endereço inválido")
	}
	if !off {
		cfg.TLSConfig = p.TLS.Config(engine.TLSHost(p), cap)
	}
	cfg.Fallbacks = nil // nada de "tenta sem TLS se falhar"
	return stdlib.OpenDB(*cfg), nil
}

func (Dialect) Version(ctx context.Context, q engine.Queryer) string {
	return "PostgreSQL " + engine.Scalar(ctx, q, "SHOW server_version")
}

func (Dialect) Databases(ctx context.Context, q engine.Queryer) ([]string, error) {
	return engine.Strings(ctx, q, `SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate
		AND has_database_privilege(datname, 'CONNECT') ORDER BY 1`)
}

const userSchemas = `NOT IN ('pg_catalog', 'information_schema') AND %s NOT LIKE 'pg_toast%%' AND %s NOT LIKE 'pg_temp%%'`

func (Dialect) Objects(ctx context.Context, q engine.Queryer) ([]engine.Object, error) {
	rows, err := q.QueryContext(ctx, fmt.Sprintf(`
		SELECT n.nspname, c.relname, CASE WHEN c.relkind IN ('v', 'm') THEN 'view' ELSE 'table' END
		  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
		 WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f') AND n.nspname `+userSchemas+`
		UNION ALL
		SELECT n.nspname, p.proname, CASE p.prokind WHEN 'p' THEN 'procedure' ELSE 'function' END
		  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
		 WHERE p.prokind IN ('f', 'p') AND n.nspname `+userSchemas+`
		 ORDER BY 1, 2`, "n.nspname", "n.nspname", "n.nspname", "n.nspname"))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []engine.Object{}
	for rows.Next() {
		var o engine.Object
		if err := rows.Scan(&o.Schema, &o.Name, &o.Kind); err != nil {
			return nil, err
		}
		out = append(out, o)
	}
	return out, rows.Err()
}

func (Dialect) Table(ctx context.Context, q engine.Queryer, schema, name string) (*engine.TableInfo, error) {
	t := &engine.TableInfo{Schema: schema, Name: name, Columns: []engine.Column{}, FKs: []engine.ForeignKey{}, Indexes: []engine.Index{}}
	rows, err := q.QueryContext(ctx, `
		SELECT a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull, pg_get_expr(d.adbin, d.adrelid),
		       COALESCE((SELECT k.ord FROM unnest(i.indkey::int2[]) WITH ORDINALITY AS k(attnum, ord) WHERE k.attnum = a.attnum), 0)::int,
		       a.attidentity <> '' OR COALESCE(pg_get_expr(d.adbin, d.adrelid), '') LIKE 'nextval(%'
		  FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
		  LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
		  LEFT JOIN pg_index i ON i.indrelid = c.oid AND i.indisprimary
		 WHERE n.nspname = $1 AND c.relname = $2 AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum`, schema, name)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var c engine.Column
		var def sql.NullString
		if err := rows.Scan(&c.Name, &c.Type, &c.Nullable, &def, &c.PK, &c.Identity); err != nil {
			rows.Close()
			return nil, err
		}
		if def.Valid {
			c.Default = &def.String
		}
		t.Columns = append(t.Columns, c)
	}
	rows.Close()
	rows, err = q.QueryContext(ctx, `
		SELECT con.conname, a.attname, rn.nspname, rc.relname, ra.attname
		  FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
		  JOIN pg_class rc ON rc.oid = con.confrelid JOIN pg_namespace rn ON rn.oid = rc.relnamespace
		 CROSS JOIN LATERAL unnest(con.conkey, con.confkey) WITH ORDINALITY AS k(attnum, refnum, ord)
		  JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
		  JOIN pg_attribute ra ON ra.attrelid = con.confrelid AND ra.attnum = k.refnum
		 WHERE con.contype = 'f' AND n.nspname = $1 AND c.relname = $2 ORDER BY con.conname, k.ord`, schema, name)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var n, col, rs, rt, rc string
		if err := rows.Scan(&n, &col, &rs, &rt, &rc); err != nil {
			rows.Close()
			return nil, err
		}
		if k := len(t.FKs); k > 0 && t.FKs[k-1].Name == n {
			t.FKs[k-1].Columns = append(t.FKs[k-1].Columns, col)
			t.FKs[k-1].RefColumns = append(t.FKs[k-1].RefColumns, rc)
		} else {
			t.FKs = append(t.FKs, engine.ForeignKey{Name: n, Columns: []string{col}, RefSchema: rs, RefTable: rt, RefColumns: []string{rc}})
		}
	}
	rows.Close()
	rows, err = q.QueryContext(ctx, `
		SELECT ic.relname, a.attname, i.indisunique, i.indisprimary
		  FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid JOIN pg_namespace n ON n.oid = c.relnamespace
		  JOIN pg_class ic ON ic.oid = i.indexrelid
		 CROSS JOIN LATERAL unnest(i.indkey::int2[]) WITH ORDINALITY AS k(attnum, ord)
		  JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
		 WHERE n.nspname = $1 AND c.relname = $2 ORDER BY ic.relname, k.ord`, schema, name)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var ix engine.Index
		var col string
		if err := rows.Scan(&ix.Name, &col, &ix.Unique, &ix.Primary); err != nil {
			return nil, err
		}
		if k := len(t.Indexes); k > 0 && t.Indexes[k-1].Name == ix.Name {
			t.Indexes[k-1].Columns = append(t.Indexes[k-1].Columns, col)
		} else {
			ix.Columns = []string{col}
			t.Indexes = append(t.Indexes, ix)
		}
	}
	return t, rows.Err()
}
