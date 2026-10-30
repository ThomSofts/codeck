// Package mssql: SQL Server (2008 em diante), pelo go-mssqldb. Lote dividido por "GO", como no SSMS; cada lote
// devolve todos os resultados e contagens. Servidor antigo: TLS 1.0 + certificado fixado (TLSParams.Legacy/Pin).
package mssql

import (
	"context"
	"database/sql"
	"encoding/hex"
	"fmt"
	"net/url"
	"strconv"
	"strings"

	"github.com/golang-sql/sqlexp"
	mssql "github.com/microsoft/go-mssqldb"
	"github.com/microsoft/go-mssqldb/msdsn"

	"codeck/db/internal/engine"
)

type Dialect struct{}

func (Dialect) Engine() string           { return "sqlserver" }
func (Dialect) Quote(id string) string   { return engine.QuoteWith("[", "]", id) }
func (Dialect) Param(i int) string       { return "@p" + strconv.Itoa(i) }
func (Dialect) Split() engine.SplitStyle { return engine.SplitGo }
func (Dialect) ReadOnlyTx() bool         { return false } // sem transação somente leitura: a transação é desfeita no fim
func (Dialect) Literal(v any) string {
	switch x := v.(type) {
	case string:
		return "N" + engine.QuoteString(x)
	case bool:
		if x {
			return "1"
		}
		return "0"
	}
	return engine.GenericLiteral(v)
}

func (Dialect) Open(p engine.ConnParams, cap *engine.Capture) (*sql.DB, error) {
	port := p.Port
	if port == 0 {
		port = 1433
	}
	q := url.Values{}
	q.Set("database", p.Database)
	q.Set("app name", "Codeck")
	q.Set("dial timeout", "15")
	off, err := p.TLS.Off()
	if err != nil {
		return nil, err
	}
	if off {
		q.Set("encrypt", "disable")
	} else {
		q.Set("encrypt", "true")
	}
	u := &url.URL{Scheme: "sqlserver", User: url.UserPassword(p.User, p.Password), Host: fmt.Sprintf("%s:%d", p.Host, port), RawQuery: q.Encode()}
	cfg, err := msdsn.Parse(u.String())
	if err != nil {
		return nil, fmt.Errorf("endereço inválido: %v", strings.ReplaceAll(err.Error(), p.Password, "•••"))
	}
	if !off {
		cfg.Encryption = msdsn.EncryptionRequired // tudo cifrado, não só o login
		cfg.TLSConfig = p.TLS.Config(engine.TLSHost(p), cap)
	}
	return sql.OpenDB(mssql.NewConnectorConfig(cfg)), nil
}

func (Dialect) Version(ctx context.Context, q engine.Queryer) string {
	v := engine.Scalar(ctx, q, "SELECT @@VERSION")
	return strings.TrimSpace(strings.SplitN(v, "\n", 2)[0])
}

// RunBatch lê as mensagens do lote na ordem em que o servidor manda: resultados, contagens ("N linhas afetadas"),
// PRINT/avisos e erros — um lote com SELECT, UPDATE e SELECT devolve as três coisas, como no SSMS.
func (Dialect) RunBatch(ctx context.Context, e *engine.Engine, q engine.Queryer, text string, max int) ([]engine.Result, error) {
	sctx, stop := context.WithCancel(ctx)
	defer stop()
	ret := &sqlexp.ReturnMessage{}
	rows, err := q.QueryContext(sctx, text, ret)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []engine.Result
	var notes []string
	var firstErr error
	lastWasRows := false
	for active := true; active; {
		switch m := ret.Message(sctx).(type) {
		case sqlexp.MsgNotice:
			notes = append(notes, m.Message.String())
		case sqlexp.MsgNext:
			r, more, err := e.ReadRows(rows, max)
			if err != nil {
				return out, err
			}
			out = append(out, r)
			lastWasRows = true
			if more {
				out[len(out)-1].Messages = append(notes, "Resultado grande demais: o resto do lote foi interrompido")
				stop()
				return out, nil
			}
		case sqlexp.MsgRowsAffected:
			if lastWasRows { // é a contagem do SELECT que acabou de ser lido
				lastWasRows = false
				continue
			}
			n := m.Count
			out = append(out, engine.Result{Affected: &n})
		case sqlexp.MsgNextResultSet:
			lastWasRows = false
			active = rows.NextResultSet()
		case sqlexp.MsgError:
			if firstErr == nil {
				firstErr = m.Error
			}
		}
	}
	if len(notes) > 0 {
		if len(out) == 0 {
			out = append(out, engine.Result{})
		}
		out[len(out)-1].Messages = append(out[len(out)-1].Messages, notes...)
	}
	return out, firstErr
}

func (Dialect) EncodeValue(v any, dbType string) (any, bool) {
	b, ok := v.([]byte)
	if !ok {
		return nil, false
	}
	switch dbType {
	case "UNIQUEIDENTIFIER":
		var u mssql.UniqueIdentifier
		if u.Scan(b) == nil {
			return u.String(), true
		}
	case "TIMESTAMP", "ROWVERSION": // rowversion, não data
		return "0x" + strings.ToUpper(hex.EncodeToString(b)), true
	}
	return nil, false
}

func (Dialect) Databases(ctx context.Context, q engine.Queryer) ([]string, error) {
	return engine.Strings(ctx, q, "SELECT name FROM sys.databases WHERE HAS_DBACCESS(name) = 1 AND state = 0 ORDER BY name")
}

func (Dialect) Objects(ctx context.Context, q engine.Queryer) ([]engine.Object, error) {
	rows, err := q.QueryContext(ctx, `SELECT s.name, o.name, RTRIM(o.type) FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id
		WHERE o.type IN ('U','V','P','FN','IF','TF') AND o.is_ms_shipped = 0 ORDER BY s.name, o.name`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	kinds := map[string]string{"U": "table", "V": "view", "P": "procedure", "FN": "function", "IF": "function", "TF": "function"}
	out := []engine.Object{}
	for rows.Next() {
		var o engine.Object
		var t string
		if err := rows.Scan(&o.Schema, &o.Name, &t); err != nil {
			return nil, err
		}
		o.Kind = kinds[t]
		out = append(out, o)
	}
	return out, rows.Err()
}

func (d Dialect) Table(ctx context.Context, q engine.Queryer, schema, name string) (*engine.TableInfo, error) {
	obj := d.Quote(schema) + "." + d.Quote(name)
	t := &engine.TableInfo{Schema: schema, Name: name, Columns: []engine.Column{}, FKs: []engine.ForeignKey{}, Indexes: []engine.Index{}}
	rows, err := q.QueryContext(ctx, `SELECT c.name, TYPE_NAME(c.user_type_id), c.max_length, c.precision, c.scale, c.is_nullable, c.is_identity,
		dc.definition, ISNULL((SELECT ic.key_ordinal FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
		  WHERE i.object_id = c.object_id AND i.is_primary_key = 1 AND ic.column_id = c.column_id), 0)
		FROM sys.columns c LEFT JOIN sys.default_constraints dc ON dc.object_id = c.default_object_id
		WHERE c.object_id = OBJECT_ID(@p1) ORDER BY c.column_id`, obj)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var c engine.Column
		var typ string
		var maxLen, prec, scale, pk int
		var def sql.NullString
		if err := rows.Scan(&c.Name, &typ, &maxLen, &prec, &scale, &c.Nullable, &c.Identity, &def, &pk); err != nil {
			rows.Close()
			return nil, err
		}
		c.Type, c.PK = typeName(typ, maxLen, prec, scale), pk
		if def.Valid {
			c.Default = &def.String
		}
		t.Columns = append(t.Columns, c)
	}
	rows.Close()
	rows, err = q.QueryContext(ctx, `SELECT fk.name, pc.name, rs.name, rt.name, rc.name FROM sys.foreign_keys fk
		JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
		JOIN sys.columns pc ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id
		JOIN sys.tables rt ON rt.object_id = fkc.referenced_object_id JOIN sys.schemas rs ON rs.schema_id = rt.schema_id
		JOIN sys.columns rc ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id
		WHERE fk.parent_object_id = OBJECT_ID(@p1) ORDER BY fk.name, fkc.constraint_column_id`, obj)
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
	rows, err = q.QueryContext(ctx, `SELECT i.name, c.name, i.is_unique, i.is_primary_key FROM sys.indexes i
		JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
		JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
		WHERE i.object_id = OBJECT_ID(@p1) AND ic.is_included_column = 0 AND i.name IS NOT NULL ORDER BY i.name, ic.key_ordinal`, obj)
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

func typeName(t string, maxLen, prec, scale int) string {
	switch t {
	case "varchar", "char", "varbinary", "binary":
		if maxLen < 0 {
			return t + "(max)"
		}
		return fmt.Sprintf("%s(%d)", t, maxLen)
	case "nvarchar", "nchar":
		if maxLen < 0 {
			return t + "(max)"
		}
		return fmt.Sprintf("%s(%d)", t, maxLen/2)
	case "decimal", "numeric":
		return fmt.Sprintf("%s(%d,%d)", t, prec, scale)
	case "datetime2", "datetimeoffset", "time":
		return fmt.Sprintf("%s(%d)", t, scale)
	}
	return t
}
