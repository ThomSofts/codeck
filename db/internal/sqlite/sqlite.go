// Package sqlite: arquivos SQLite (inclusive o banco de apps Flutter: sqflite, drift, floor), pelo modernc — Go
// puro, sem C. O arquivo abre com espera de 5 s quando outro processo (o app) está escrevendo.
package sqlite

import (
	"context"
	"database/sql"
	"fmt"
	"net/url"
	"os"

	_ "modernc.org/sqlite"

	"codeck/db/internal/engine"
)

type Dialect struct{}

func (Dialect) Engine() string           { return "sqlite" }
func (Dialect) Quote(id string) string   { return engine.QuoteWith(`"`, `"`, id) }
func (Dialect) Param(int) string         { return "?" }
func (Dialect) Split() engine.SplitStyle { return engine.SplitSemicolon }
func (Dialect) ReadOnlyTx() bool         { return false }
func (Dialect) Literal(v any) string {
	if b, ok := v.(bool); ok {
		return map[bool]string{true: "1", false: "0"}[b]
	}
	return engine.GenericLiteral(v)
}

func (Dialect) Open(p engine.ConnParams, _ *engine.Capture) (*sql.DB, error) {
	if p.File == "" {
		return nil, fmt.Errorf("arquivo do banco não informado")
	}
	if st, err := os.Stat(p.File); err != nil || st.IsDir() {
		return nil, fmt.Errorf("arquivo não encontrado: %s", p.File) // não cria banco vazio por engano
	}
	q := url.Values{}
	q.Add("_pragma", "busy_timeout(5000)")
	if p.ReadOnly {
		q.Set("mode", "ro")
	}
	return sql.Open("sqlite", "file:"+(&url.URL{Path: p.File}).EscapedPath()+"?"+q.Encode())
}

func (Dialect) Version(ctx context.Context, q engine.Queryer) string {
	return "SQLite " + engine.Scalar(ctx, q, "SELECT sqlite_version()")
}

func (Dialect) Databases(ctx context.Context, q engine.Queryer) ([]string, error) {
	return engine.Strings(ctx, q, "SELECT name FROM pragma_database_list ORDER BY seq")
}

func (Dialect) Objects(ctx context.Context, q engine.Queryer) ([]engine.Object, error) {
	rows, err := q.QueryContext(ctx, `SELECT 'main', name, type FROM sqlite_master
		WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name`)
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
	if schema == "" {
		schema = "main"
	}
	t := &engine.TableInfo{Schema: schema, Name: name, Columns: []engine.Column{}, FKs: []engine.ForeignKey{}, Indexes: []engine.Index{}}
	rows, err := q.QueryContext(ctx, `SELECT name, type, "notnull", dflt_value, pk FROM pragma_table_info(?, ?)`, name, schema)
	if err != nil {
		return nil, err
	}
	pks := 0
	for rows.Next() {
		var c engine.Column
		var notnull bool
		var def sql.NullString
		if err := rows.Scan(&c.Name, &c.Type, &notnull, &def, &c.PK); err != nil {
			rows.Close()
			return nil, err
		}
		c.Nullable = !notnull && c.PK == 0
		if def.Valid {
			c.Default = &def.String
		}
		if c.PK > 0 {
			pks++
		}
		t.Columns = append(t.Columns, c)
	}
	rows.Close()
	for i := range t.Columns { // INTEGER PRIMARY KEY sozinha é o rowid: o SQLite numera
		if pks == 1 && t.Columns[i].PK == 1 && (t.Columns[i].Type == "INTEGER" || t.Columns[i].Type == "integer") {
			t.Columns[i].Identity = true
		}
	}
	rows, err = q.QueryContext(ctx, `SELECT id, "table", "from", COALESCE("to", '') FROM pragma_foreign_key_list(?, ?) ORDER BY id, seq`, name, schema)
	if err != nil {
		return nil, err
	}
	lastID := -1
	for rows.Next() {
		var id int
		var rt, col, rc string
		if err := rows.Scan(&id, &rt, &col, &rc); err != nil {
			rows.Close()
			return nil, err
		}
		if id == lastID {
			k := len(t.FKs) - 1
			t.FKs[k].Columns = append(t.FKs[k].Columns, col)
			t.FKs[k].RefColumns = append(t.FKs[k].RefColumns, rc)
		} else {
			t.FKs = append(t.FKs, engine.ForeignKey{Name: fmt.Sprintf("fk_%d", id), Columns: []string{col}, RefSchema: schema, RefTable: rt, RefColumns: []string{rc}})
		}
		lastID = id
	}
	rows.Close()
	rows, err = q.QueryContext(ctx, `SELECT il.name, ii.name, il."unique", il.origin = 'pk'
		FROM pragma_index_list(?, ?) il JOIN pragma_index_info(il.name) ii ORDER BY il.name, ii.seqno`, name, schema)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var ix engine.Index
		var col sql.NullString
		if err := rows.Scan(&ix.Name, &col, &ix.Unique, &ix.Primary); err != nil {
			return nil, err
		}
		if k := len(t.Indexes); k > 0 && t.Indexes[k-1].Name == ix.Name {
			t.Indexes[k-1].Columns = append(t.Indexes[k-1].Columns, col.String)
		} else {
			ix.Columns = []string{col.String}
			t.Indexes = append(t.Indexes, ix)
		}
	}
	return t, rows.Err()
}
