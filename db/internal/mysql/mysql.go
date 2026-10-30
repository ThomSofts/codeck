// Package mysql: MySQL 5.6+ e MariaDB 10+ (e TiDB), pelo go-sql-driver. Datas chegam como o texto do servidor
// (sem ParseTime): "0000-00-00" de base antiga aparece como está, em vez de quebrar a leitura.
package mysql

import (
	"context"
	"database/sql"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/go-sql-driver/mysql"

	"codeck/db/internal/engine"
)

type Dialect struct{}

func init() { engine.SetMySQL() }

func (Dialect) Engine() string           { return "mysql" }
func (Dialect) Quote(id string) string   { return engine.QuoteWith("`", "`", id) }
func (Dialect) Param(int) string         { return "?" }
func (Dialect) Split() engine.SplitStyle { return engine.SplitSemicolon }
func (Dialect) ReadOnlyTx() bool         { return true }
func (Dialect) Literal(v any) string {
	if s, ok := v.(string); ok { // no MySQL a barra invertida escapa dentro do texto
		return engine.QuoteString(strings.ReplaceAll(s, `\`, `\\`))
	}
	return engine.GenericLiteral(v)
}

func (Dialect) Open(p engine.ConnParams, cap *engine.Capture) (*sql.DB, error) {
	port := p.Port
	if port == 0 {
		port = 3306
	}
	off, err := p.TLS.Off()
	if err != nil {
		return nil, err
	}
	cfg := mysql.NewConfig()
	cfg.User, cfg.Passwd, cfg.Net, cfg.Addr, cfg.DBName = p.User, p.Password, "tcp", fmt.Sprintf("%s:%d", p.Host, port), p.Database
	cfg.Timeout = 15 * time.Second
	cfg.AllowNativePasswords = true
	cfg.ConnectionAttributes = "program_name:Codeck"
	if off {
		cfg.TLSConfig = "false"
	} else {
		cfg.TLS = p.TLS.Config(engine.TLSHost(p), cap)
	}
	conn, err := mysql.NewConnector(cfg)
	if err != nil {
		return nil, fmt.Errorf("configuração inválida: %v", err)
	}
	return sql.OpenDB(conn), nil
}

func (Dialect) Version(ctx context.Context, q engine.Queryer) string {
	v := engine.Scalar(ctx, q, "SELECT VERSION()")
	if strings.Contains(strings.ToLower(v), "mariadb") {
		return "MariaDB " + strings.SplitN(v, "-", 2)[0]
	}
	return "MySQL " + v
}

// EncodeValue: o protocolo de texto manda tudo como bytes; número volta a ser número (decimal fica texto, exato).
func (Dialect) EncodeValue(v any, dbType string) (any, bool) {
	b, ok := v.([]byte)
	if !ok {
		return nil, false
	}
	switch strings.TrimPrefix(dbType, "UNSIGNED ") {
	case "TINYINT", "SMALLINT", "MEDIUMINT", "INT", "INTEGER", "BIGINT", "YEAR":
		if n, err := strconv.ParseInt(string(b), 10, 64); err == nil && n <= 1<<53 && n >= -(1<<53) {
			return n, true
		}
		return string(b), true
	case "FLOAT", "DOUBLE":
		if f, err := strconv.ParseFloat(string(b), 64); err == nil {
			return f, true
		}
	}
	return nil, false
}

func (Dialect) Databases(ctx context.Context, q engine.Queryer) ([]string, error) {
	return engine.Strings(ctx, q, "SHOW DATABASES")
}

func (Dialect) Objects(ctx context.Context, q engine.Queryer) ([]engine.Object, error) {
	rows, err := q.QueryContext(ctx, `
		SELECT TABLE_SCHEMA, TABLE_NAME, IF(TABLE_TYPE = 'VIEW', 'view', 'table') FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()
		UNION ALL
		SELECT ROUTINE_SCHEMA, ROUTINE_NAME, LOWER(ROUTINE_TYPE) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE()
		ORDER BY 2`)
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
		SELECT c.COLUMN_NAME, c.COLUMN_TYPE, c.IS_NULLABLE = 'YES', c.COLUMN_DEFAULT, COALESCE(k.ORDINAL_POSITION, 0), c.EXTRA LIKE '%auto_increment%',
		       c.COLUMN_COMMENT
		  FROM information_schema.COLUMNS c
		  LEFT JOIN information_schema.KEY_COLUMN_USAGE k ON k.TABLE_SCHEMA = c.TABLE_SCHEMA AND k.TABLE_NAME = c.TABLE_NAME
		       AND k.COLUMN_NAME = c.COLUMN_NAME AND k.CONSTRAINT_NAME = 'PRIMARY'
		 WHERE c.TABLE_SCHEMA = ? AND c.TABLE_NAME = ? ORDER BY c.ORDINAL_POSITION`, schema, name)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var c engine.Column
		var def sql.NullString
		if err := rows.Scan(&c.Name, &c.Type, &c.Nullable, &def, &c.PK, &c.Identity, &c.Comment); err != nil {
			rows.Close()
			return nil, err
		}
		if def.Valid {
			c.Default = &def.String
		}
		t.Columns = append(t.Columns, c)
	}
	rows.Close()
	// TABLE_ROWS é estimativa no InnoDB; view tem o comentário "VIEW" e nada de tamanho
	t.Stats(ctx, q, `SELECT IF(TABLE_TYPE = 'VIEW', '', TABLE_COMMENT), TABLE_ROWS, DATA_LENGTH + INDEX_LENGTH
		  FROM information_schema.TABLES WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?`, schema, name)
	rows, err = q.QueryContext(ctx, `
		SELECT CONSTRAINT_NAME, COLUMN_NAME, REFERENCED_TABLE_SCHEMA, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
		  FROM information_schema.KEY_COLUMN_USAGE
		 WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND REFERENCED_TABLE_NAME IS NOT NULL ORDER BY CONSTRAINT_NAME, ORDINAL_POSITION`, schema, name)
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
		SELECT INDEX_NAME, COLUMN_NAME, NON_UNIQUE = 0, INDEX_NAME = 'PRIMARY' FROM information_schema.STATISTICS
		 WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY INDEX_NAME, SEQ_IN_INDEX`, schema, name)
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
