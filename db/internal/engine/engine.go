// Package engine: o que todo plugin SQL faz igual — sessões, execução de scripts, leitura de resultados, edições da
// grade em transação. Cada banco entra com um Dialect (como conectar, citar nomes, ler o catálogo).
package engine

import (
	"context"
	"crypto/rand"
	"database/sql"
	"database/sql/driver"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strings"
	"sync"
	"time"

	"codeck/db/internal/proto"
)

// PluginVersion vai no "hello": o backend confere se o plugin instalado é o que acompanha o app.
var PluginVersion = "dev"

type ConnParams struct {
	Host       string            `json:"host"`
	Port       int               `json:"port"`
	Database   string            `json:"database"`
	User       string            `json:"user"`
	Password   string            `json:"password"`
	File       string            `json:"file"` // SQLite
	TLS        TLSParams         `json:"tls"`
	ReadOnly   bool              `json:"readOnly"` // abre o banco só para leitura quando o banco permite (SQLite)
	TimeoutSec int               `json:"timeoutSec"`
	Options    map[string]string `json:"options"`
}

type Object struct {
	Schema string `json:"schema"`
	Name   string `json:"name"`
	Kind   string `json:"kind"` // table | view | procedure | function
}

type Column struct {
	Name     string  `json:"name"`
	Type     string  `json:"type"`
	Nullable bool    `json:"nullable"`
	Default  *string `json:"default"`
	PK       int     `json:"pk"` // posição na chave primária (0 = fora dela)
	Identity bool    `json:"identity"`
}

type ForeignKey struct {
	Name       string   `json:"name"`
	Columns    []string `json:"columns"`
	RefSchema  string   `json:"refSchema"`
	RefTable   string   `json:"refTable"`
	RefColumns []string `json:"refColumns"`
}

type Index struct {
	Name    string   `json:"name"`
	Columns []string `json:"columns"`
	Unique  bool     `json:"unique"`
	Primary bool     `json:"primary"`
}

type TableInfo struct {
	Schema  string       `json:"schema"`
	Name    string       `json:"name"`
	Columns []Column     `json:"columns"`
	FKs     []ForeignKey `json:"fks"`
	Indexes []Index      `json:"indexes"`
}

// Queryer: *sql.Conn, *sql.Tx e *sql.DB.
type Queryer interface {
	QueryContext(ctx context.Context, query string, args ...any) (*sql.Rows, error)
	ExecContext(ctx context.Context, query string, args ...any) (sql.Result, error)
}

type Dialect interface {
	Engine() string
	Open(p ConnParams, cap *Capture) (*sql.DB, error)
	Version(ctx context.Context, q Queryer) string
	Quote(ident string) string
	Param(i int) string // 1, 2, 3… → $1 / ? / @p1
	Split() SplitStyle
	ReadOnlyTx() bool // o banco tem transação somente leitura de verdade (Postgres, MySQL)
	Databases(ctx context.Context, q Queryer) ([]string, error)
	Objects(ctx context.Context, q Queryer) ([]Object, error)
	Table(ctx context.Context, q Queryer, schema, name string) (*TableInfo, error)
	Literal(v any) string // só para mostrar o SQL das edições; a execução usa parâmetros
}

// BatchRunner: o banco executa o lote inteiro e devolve vários resultados e contagens (SQL Server).
type BatchRunner interface {
	RunBatch(ctx context.Context, e *Engine, q Queryer, sql string, max int) ([]Result, error)
}

// ValueEncoder: o banco converte um valor do jeito dele (ex.: uniqueidentifier do SQL Server) antes do padrão.
type ValueEncoder interface {
	EncodeValue(v any, dbType string) (any, bool)
}

type ColumnMeta struct {
	Name string `json:"name"`
	Type string `json:"type"`
}

type Result struct {
	Statement string       `json:"statement"`
	Offset    int          `json:"offset"`
	Columns   []ColumnMeta `json:"columns,omitempty"`
	Rows      [][]any      `json:"rows,omitempty"`
	Affected  *int64       `json:"affected,omitempty"`
	Truncated bool         `json:"truncated,omitempty"`
	Total     *int64       `json:"total,omitempty"` // quando truncado: o total, se deu para contar sem buscar demais
	Messages  []string     `json:"messages,omitempty"`
	Ms        int64        `json:"ms"`
}

type session struct {
	db     *sql.DB
	conn   *sql.Conn
	mu     sync.Mutex // uma consulta por vez na sessão (como uma aba de editor)
	tx     *sql.Tx    // alteração esperando Confirmar/Desfazer
	txID   string
	txStop *time.Timer
}

type Engine struct {
	D        Dialect
	mu       sync.Mutex
	sessions map[string]*session
	running  map[string]context.CancelFunc
	secrets  []string
}

func New(d Dialect) *Engine {
	return &Engine{D: d, sessions: map[string]*session{}, running: map[string]context.CancelFunc{}}
}

func (e *Engine) Serve() { proto.Serve(e.handle, e.scrub) }

func (e *Engine) scrub() []string {
	e.mu.Lock()
	defer e.mu.Unlock()
	return append([]string(nil), e.secrets...)
}

// HeldTxTimeout: uma alteração em produção não fica segurando bloqueios esperando você para sempre.
const HeldTxTimeout = 5 * time.Minute

func (e *Engine) handle(ctx context.Context, method string, raw json.RawMessage) (any, error) {
	switch method {
	case "hello":
		return map[string]any{"protocol": proto.Version, "engine": e.D.Engine(), "version": PluginVersion}, nil
	case "open":
		var p ConnParams
		if err := decode(raw, &p); err != nil {
			return nil, err
		}
		return e.open(ctx, p)
	case "close":
		var p struct{ Session string }
		if err := decode(raw, &p); err != nil {
			return nil, err
		}
		e.close(p.Session)
		return map[string]any{"ok": true}, nil
	case "query":
		var p queryParams
		if err := decode(raw, &p); err != nil {
			return nil, err
		}
		return e.query(ctx, p)
	case "cancel":
		var p struct{ QueryID string }
		if err := decode(raw, &p); err != nil {
			return nil, err
		}
		e.mu.Lock()
		stop := e.running[p.QueryID]
		e.mu.Unlock()
		if stop != nil {
			stop()
		}
		return map[string]any{"ok": stop != nil}, nil
	case "commit", "rollback":
		var p struct{ Session, TxID string }
		if err := decode(raw, &p); err != nil {
			return nil, err
		}
		return e.finishTx(p.Session, p.TxID, method == "commit")
	case "databases", "objects", "table":
		var p struct{ Session, Schema, Name string }
		if err := decode(raw, &p); err != nil {
			return nil, err
		}
		s, err := e.get(p.Session)
		if err != nil {
			return nil, err
		}
		ctx, cancel := context.WithTimeout(ctx, 60*time.Second)
		defer cancel()
		switch method {
		case "databases":
			return e.D.Databases(ctx, s.db)
		case "objects":
			return e.D.Objects(ctx, s.db)
		}
		return e.D.Table(ctx, s.db, p.Schema, p.Name)
	case "analyze":
		var p struct{ SQL string }
		if err := decode(raw, &p); err != nil {
			return nil, err
		}
		return Analyze(p.SQL, e.D.Split()), nil
	case "apply":
		var p applyParams
		if err := decode(raw, &p); err != nil {
			return nil, err
		}
		return e.apply(ctx, p)
	}
	return nil, proto.Fail("unknown-method", "Método desconhecido: %s", method)
}

func decode(raw json.RawMessage, v any) error {
	d := json.NewDecoder(strings.NewReader(string(raw)))
	d.UseNumber()
	if err := d.Decode(v); err != nil {
		return proto.Fail("bad-request", "Parâmetros inválidos: %v", err)
	}
	return nil
}

func newID() string {
	b := make([]byte, 12)
	rand.Read(b)
	return hex.EncodeToString(b)
}

type codeErr struct{ code, msg string }

func (c *codeErr) Error() string { return c.msg }

func asProto(err error) error {
	var c *codeErr
	if errors.As(err, &c) {
		return proto.Fail(c.code, "%s", c.msg)
	}
	return err
}

// ------------------------------------------------------------------ sessões

func (e *Engine) open(ctx context.Context, p ConnParams) (any, error) {
	if p.Password != "" {
		e.mu.Lock()
		e.secrets = append(e.secrets, p.Password)
		e.mu.Unlock()
	}
	timeout := time.Duration(p.TimeoutSec) * time.Second
	if timeout <= 0 {
		timeout = 20 * time.Second
	}
	cap := &Capture{}
	db, err := e.D.Open(p, cap)
	if err != nil {
		return nil, asProto(err)
	}
	db.SetMaxOpenConns(4)
	db.SetConnMaxIdleTime(5 * time.Minute)
	cctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	conn, err := db.Conn(cctx)
	if err == nil {
		err = conn.PingContext(cctx)
	}
	if err != nil {
		db.Close()
		if info := cap.Get(); info != nil && info.Problem != "" {
			msg := map[string]string{
				"unknown": "Certificado do servidor ainda não conferido — confira a impressão digital e fixe",
				"changed": "O certificado do servidor MUDOU desde que foi fixado — pode ser outro servidor no meio do caminho",
				"invalid": "Certificado do servidor não é válido para este host",
			}[info.Problem]
			return nil, &proto.Error{Code: "cert-" + info.Problem, Message: msg, Data: info}
		}
		if le := LegacyCBCError(cap, err, p.TLS); le != nil {
			return nil, le
		}
		if errors.Is(err, context.DeadlineExceeded) {
			return nil, proto.Fail("timeout", "O servidor não respondeu em %s (firewall, VPN desligada ou porta errada?)", timeout)
		}
		return nil, asProto(err)
	}
	s := &session{db: db, conn: conn}
	id := newID()
	e.mu.Lock()
	e.sessions[id] = s
	e.mu.Unlock()
	return map[string]any{"session": id, "server": e.D.Version(cctx, conn), "tls": cap.Get()}, nil
}

// Alguns drivers (MySQL) derrubam a conexão quando uma consulta é cancelada: a sessão pega outra do pool.
func (e *Engine) badConn(s *session) bool {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	return s.conn.PingContext(ctx) != nil
}

func (e *Engine) reconnect(s *session) {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if c, err := s.db.Conn(ctx); err == nil {
		s.conn.Close()
		s.conn = c
	}
}

func (e *Engine) get(id string) (*session, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	s := e.sessions[id]
	if s == nil {
		return nil, proto.Fail("no-session", "Conexão fechada — abra de novo")
	}
	return s, nil
}

func (e *Engine) close(id string) {
	e.mu.Lock()
	s := e.sessions[id]
	delete(e.sessions, id)
	e.mu.Unlock()
	if s == nil {
		return
	}
	if s.tx != nil {
		s.tx.Rollback()
	}
	s.conn.Close()
	s.db.Close()
}

// ------------------------------------------------------------------ consultas

type queryParams struct {
	Session    string
	SQL        string
	QueryID    string
	MaxRows    int
	ReadOnly   bool // roda numa transação desfeita no fim (e somente leitura, quando o banco tem)
	HoldTx     bool // roda numa transação que espera "commit" ou "rollback" (produção: Confirmar/Desfazer)
	TimeoutSec int
}

type QueryError struct {
	Index   int      `json:"index"`
	Offset  int      `json:"offset"`
	Results []Result `json:"results"`
}

func (e *Engine) query(parent context.Context, p queryParams) (any, error) {
	s, err := e.get(p.Session)
	if err != nil {
		return nil, err
	}
	if p.MaxRows <= 0 {
		p.MaxRows = 1000
	}
	ctx, cancel := context.WithCancel(parent)
	if p.TimeoutSec > 0 {
		ctx, cancel = context.WithTimeout(parent, time.Duration(p.TimeoutSec)*time.Second)
	}
	defer cancel()
	if p.QueryID != "" {
		e.mu.Lock()
		e.running[p.QueryID] = cancel
		e.mu.Unlock()
		defer func() { e.mu.Lock(); delete(e.running, p.QueryID); e.mu.Unlock() }()
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.tx != nil {
		return nil, proto.Fail("tx-pending", "Há uma alteração esperando Confirmar ou Desfazer nesta conexão")
	}
	if p.ReadOnly || p.HoldTx {
		for _, a := range Analyze(p.SQL, e.D.Split()) {
			if a.TxControl { // COMMIT/BEGIN no meio sairia da transação que protege (ou espera confirmação)
				return nil, &proto.Error{Code: "tx-control", Message: "Comandos de transação (BEGIN, COMMIT, ROLLBACK…) não rodam aqui: o Codeck já controla a transação desta conexão",
					Data: map[string]any{"offset": a.Offset}}
			}
		}
	}
	var q Queryer = s.conn
	var tx *sql.Tx
	if p.ReadOnly || p.HoldTx {
		// o contexto da transação não é o da consulta: cancelar a consulta não pode desfazer o que espera confirmação
		tx, err = s.conn.BeginTx(context.Background(), &sql.TxOptions{ReadOnly: p.ReadOnly && e.D.ReadOnlyTx()})
		if err != nil {
			return nil, asProto(err)
		}
		q = tx
	}
	started := time.Now()
	results := []Result{}
	for i, st := range Split(p.SQL, e.D.Split()) {
		rs, err := e.run(ctx, q, st, p.MaxRows)
		results = append(results, rs...)
		if err != nil {
			if tx != nil {
				tx.Rollback()
			}
			if errors.Is(err, driver.ErrBadConn) || errors.Is(err, sql.ErrConnDone) {
				e.reconnect(s)
			}
			if ctx.Err() == context.Canceled && parent.Err() == nil {
				err = proto.Fail("canceled", "Consulta cancelada")
			} else if ctx.Err() == context.DeadlineExceeded {
				err = proto.Fail("timeout", "A consulta passou do tempo limite (%ds)", p.TimeoutSec)
			}
			pe := toProto(err)
			pe.Data = QueryError{Index: i, Offset: st.Offset, Results: results}
			return nil, pe
		}
	}
	out := map[string]any{"results": results, "ms": time.Since(started).Milliseconds()}
	switch {
	case p.ReadOnly:
		tx.Rollback()
	case tx == nil && stopped(results) && e.badConn(s):
		e.reconnect(s)
	case p.HoldTx:
		s.tx, s.txID = tx, newID()
		id := s.txID
		s.txStop = time.AfterFunc(HeldTxTimeout, func() { e.finishTx(p.Session, id, false) })
		out["txId"] = id
		out["txExpires"] = time.Now().Add(HeldTxTimeout).UTC().Format(time.RFC3339)
	}
	return out, nil
}

func stopped(rs []Result) bool {
	for _, r := range rs {
		if r.Truncated && r.Total == nil {
			return true
		}
	}
	return false
}

func toProto(err error) *proto.Error {
	var pe *proto.Error
	if errors.As(asProto(err), &pe) {
		return pe
	}
	return &proto.Error{Code: "db", Message: err.Error()}
}

func (e *Engine) finishTx(sessionID, txID string, commit bool) (any, error) {
	s, err := e.get(sessionID)
	if err != nil {
		return nil, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.tx == nil || s.txID != txID {
		return nil, proto.Fail("no-tx", "A alteração já foi desfeita (passou de %s sem confirmar) ou concluída", HeldTxTimeout)
	}
	tx := s.tx
	s.tx, s.txID = nil, ""
	s.txStop.Stop()
	if commit {
		if err := tx.Commit(); err != nil {
			return nil, asProto(err)
		}
	} else {
		tx.Rollback()
	}
	return map[string]any{"ok": true, "committed": commit}, nil
}

var execWords = map[string]bool{"INSERT": true, "UPDATE": true, "DELETE": true, "MERGE": true, "CREATE": true, "ALTER": true, "DROP": true,
	"TRUNCATE": true, "GRANT": true, "REVOKE": true, "SET": true, "BEGIN": true, "COMMIT": true, "ROLLBACK": true, "USE": true,
	"VACUUM": true, "ANALYZE": true, "REINDEX": true, "COMMENT": true, "RENAME": true, "REPLACE": true, "LOCK": true, "UNLOCK": true,
	"START": true, "SAVEPOINT": true, "RELEASE": true, "ATTACH": true, "DETACH": true, "DO": true, "REFRESH": true, "CLUSTER": true}

// FirstWord: a primeira palavra fora de comentários e parênteses.
func FirstWord(s string) string {
	for {
		s = strings.TrimLeft(s, " \t\r\n(")
		switch {
		case strings.HasPrefix(s, "--"):
			if i := strings.IndexByte(s, '\n'); i >= 0 {
				s = s[i+1:]
				continue
			}
			return ""
		case strings.HasPrefix(s, "/*"):
			if i := strings.Index(s, "*/"); i >= 0 {
				s = s[i+2:]
				continue
			}
			return ""
		}
		break
	}
	end := 0
	for end < len(s) && isIdent(s[end]) {
		end++
	}
	return strings.ToUpper(s[:end])
}

func returnsRows(stmt string) bool {
	w := FirstWord(stmt)
	if !execWords[w] {
		return true
	}
	up := strings.ToUpper(stmt)
	return strings.Contains(up, "RETURNING") || strings.Contains(up, "OUTPUT ")
}

func (e *Engine) run(ctx context.Context, q Queryer, st Stmt, max int) ([]Result, error) {
	started := time.Now()
	if br, ok := e.D.(BatchRunner); ok {
		rs, err := br.RunBatch(ctx, e, q, st.SQL, max)
		for i := range rs {
			rs[i].Statement, rs[i].Offset = st.SQL, st.Offset
		}
		if len(rs) > 0 {
			rs[len(rs)-1].Ms = time.Since(started).Milliseconds()
		}
		return rs, err
	}
	if !returnsRows(st.SQL) {
		r, err := q.ExecContext(ctx, st.SQL)
		if err != nil {
			return nil, err
		}
		n, _ := r.RowsAffected()
		return []Result{{Statement: st.SQL, Offset: st.Offset, Affected: &n, Ms: time.Since(started).Milliseconds()}}, nil
	}
	sctx, stop := context.WithCancel(ctx)
	defer stop()
	rows, err := q.QueryContext(sctx, st.SQL)
	if err != nil {
		return nil, err
	}
	var out []Result
	for {
		r, more, err := e.ReadRows(rows, max)
		if err != nil {
			rows.Close()
			return out, err
		}
		r.Statement, r.Offset = st.SQL, st.Offset
		out = append(out, r)
		if more { // resultado enorme: para no servidor em vez de baixar tudo
			stop()
			rows.Close()
			return out, nil
		}
		if !rows.NextResultSet() {
			break
		}
	}
	rows.Close()
	if len(out) > 0 {
		out[len(out)-1].Ms = time.Since(started).Milliseconds()
	}
	return out, rows.Err()
}

// CountLimit: passando de max, continua só contando (sem guardar) até este tanto, para dizer "1.000 de 8.214".
const CountLimit = 50000

// ReadRows lê até max linhas do resultado atual. Mais que isso: Truncated (a tela oferece buscar mais) e, se nem a
// contagem coube em CountLimit, more = true — quem chamou cancela a consulta no servidor.
func (e *Engine) ReadRows(rows *sql.Rows, max int) (Result, bool, error) {
	var r Result
	cts, err := rows.ColumnTypes()
	if err != nil {
		return r, false, err
	}
	types := make([]string, len(cts))
	for i, ct := range cts {
		types[i] = strings.ToUpper(ct.DatabaseTypeName())
		r.Columns = append(r.Columns, ColumnMeta{Name: ct.Name(), Type: types[i]})
	}
	r.Rows = [][]any{}
	vals := make([]any, len(cts))
	ptrs := make([]any, len(cts))
	for i := range vals {
		ptrs[i] = &vals[i]
	}
	for rows.Next() {
		if len(r.Rows) >= max {
			r.Truncated = true
			n := int64(len(r.Rows)) + 1
			for ; n <= int64(max+CountLimit) && rows.Next(); n++ {
			}
			if n > int64(max+CountLimit) {
				return r, true, nil
			}
			r.Total = &n
			return r, false, rows.Err()
		}
		if err := rows.Scan(ptrs...); err != nil {
			return r, false, err
		}
		row := make([]any, len(vals))
		for i, v := range vals {
			row[i] = e.Encode(v, types[i])
		}
		r.Rows = append(r.Rows, row)
	}
	return r, false, rows.Err()
}

const maxBinary = 32 << 10

// Encode deixa o valor pronto para JSON sem perder nada que a tela precise mostrar, copiar ou usar como chave.
func (e *Engine) Encode(v any, dbType string) any {
	if ve, ok := e.D.(ValueEncoder); ok {
		if out, done := ve.EncodeValue(v, dbType); done {
			return out
		}
	}
	switch x := v.(type) {
	case nil:
		return nil
	case []byte:
		if isBinary(dbType) {
			if len(x) > maxBinary {
				return map[string]any{"$bin": len(x)}
			}
			return "0x" + strings.ToUpper(hex.EncodeToString(x))
		}
		return string(x)
	case time.Time:
		return FormatTime(x, dbType)
	case int64:
		if x > 1<<53 || x < -(1<<53) {
			return fmt.Sprint(x) // além do que um número do JavaScript guarda sem arredondar
		}
		return x
	case float64:
		if math.IsNaN(x) || math.IsInf(x, 0) {
			return fmt.Sprint(x)
		}
		return x
	case float32:
		return e.Encode(float64(x), dbType)
	case bool, string:
		return x
	}
	return fmt.Sprint(v)
}

// Scalar: o primeiro valor da primeira linha, como texto ("" se der erro).
func Scalar(ctx context.Context, q Queryer, query string, args ...any) string {
	rows, err := q.QueryContext(ctx, query, args...)
	if err != nil {
		return ""
	}
	defer rows.Close()
	var v sql.NullString
	if rows.Next() && rows.Scan(&v) == nil {
		return v.String
	}
	return ""
}

// Strings: a primeira coluna de todas as linhas.
func Strings(ctx context.Context, q Queryer, query string, args ...any) ([]string, error) {
	rows, err := q.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var s sql.NullString
		if err := rows.Scan(&s); err != nil {
			return nil, err
		}
		out = append(out, s.String)
	}
	return out, rows.Err()
}

func isBinary(t string) bool {
	switch t {
	case "BINARY", "VARBINARY", "IMAGE", "BLOB", "TINYBLOB", "MEDIUMBLOB", "LONGBLOB", "BYTEA", "TIMESTAMP_BINARY", "ROWVERSION", "GEOMETRY":
		return true
	}
	return false
}

func FormatTime(t time.Time, dbType string) string {
	switch {
	case dbType == "DATE":
		return t.Format("2006-01-02")
	case dbType == "TIME" || dbType == "TIMETZ":
		return strings.TrimSuffix(t.Format("15:04:05.999999"), ".")
	case strings.Contains(dbType, "TZ") || dbType == "DATETIMEOFFSET":
		return t.Format("2006-01-02 15:04:05.999999-07:00")
	}
	return t.Format("2006-01-02 15:04:05.999999")
}
