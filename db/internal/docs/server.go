package docs

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strings"
	"sync"
	"time"

	"codeck/db/internal/engine"
	"codeck/db/internal/proto"
)

// Output: o que um comando devolve. Docs com os campos na ordem; a primeira coluna é KeyCol (_id, __name__…).
type Output struct {
	Docs      []Obj
	KeyCol    string
	Affected  *int64
	Messages  []string
	Truncated bool
	Total     *int64
}

type Conn interface {
	Close()
	Run(ctx context.Context, c *Call, max int) (*Output, error)
	Databases(ctx context.Context) ([]string, error)
	Objects(ctx context.Context) ([]engine.Object, error)
	Table(ctx context.Context, schema, name string) (*engine.TableInfo, error)
	Apply(ctx context.Context, ch engine.Change) (int64, string, error) // linhas, descrição (prévia)
	Exists(ctx context.Context, ch engine.Change) error                 // o documento da edição ainda existe?
	Describe(ch engine.Change) string
}

type Driver interface {
	Engine() string
	Analyze(c *Call) engine.Analysis
	Open(ctx context.Context, p engine.ConnParams) (Conn, string, *engine.CertInfo, error)
}

type Server struct {
	D        Driver
	mu       sync.Mutex
	sessions map[string]*session
	running  map[string]context.CancelFunc
	secrets  []string
}

type session struct {
	c  Conn
	mu sync.Mutex
}

func Serve(d Driver) {
	s := &Server{D: d, sessions: map[string]*session{}, running: map[string]context.CancelFunc{}}
	proto.Serve(s.handle, func() []string { s.mu.Lock(); defer s.mu.Unlock(); return append([]string(nil), s.secrets...) })
}

func decode(raw json.RawMessage, v any) error {
	d := json.NewDecoder(strings.NewReader(string(raw)))
	d.UseNumber()
	if err := d.Decode(v); err != nil {
		return proto.Fail("bad-request", "Parâmetros inválidos: %v", err)
	}
	return nil
}

func (s *Server) get(id string) (*session, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if x := s.sessions[id]; x != nil {
		return x, nil
	}
	return nil, proto.Fail("no-session", "Conexão fechada — abra de novo")
}

func (s *Server) handle(ctx context.Context, method string, raw json.RawMessage) (any, error) {
	switch method {
	case "hello":
		return map[string]any{"protocol": proto.Version, "engine": s.D.Engine(), "version": engine.PluginVersion, "holdTx": false, "documents": true}, nil
	case "open":
		var p engine.ConnParams
		if err := decode(raw, &p); err != nil {
			return nil, err
		}
		if p.Password != "" {
			s.mu.Lock()
			s.secrets = append(s.secrets, p.Password)
			s.mu.Unlock()
		}
		cctx, cancel := context.WithTimeout(ctx, 30*time.Second)
		defer cancel()
		c, server, cert, err := s.D.Open(cctx, p)
		if err != nil {
			return nil, err
		}
		b := make([]byte, 12)
		rand.Read(b)
		id := hex.EncodeToString(b)
		s.mu.Lock()
		s.sessions[id] = &session{c: c}
		s.mu.Unlock()
		return map[string]any{"session": id, "server": server, "tls": cert}, nil
	case "close":
		var p struct{ Session string }
		decode(raw, &p)
		s.mu.Lock()
		x := s.sessions[p.Session]
		delete(s.sessions, p.Session)
		s.mu.Unlock()
		if x != nil {
			x.c.Close()
		}
		return map[string]any{"ok": true}, nil
	case "cancel":
		var p struct{ QueryID string }
		decode(raw, &p)
		s.mu.Lock()
		stop := s.running[p.QueryID]
		s.mu.Unlock()
		if stop != nil {
			stop()
		}
		return map[string]any{"ok": stop != nil}, nil
	case "analyze":
		var p struct{ SQL string }
		if err := decode(raw, &p); err != nil {
			return nil, err
		}
		return s.analyze(p.SQL)
	case "query":
		var p struct {
			Session, SQL, QueryID string
			MaxRows, TimeoutSec   int
			ReadOnly, HoldTx      bool
		}
		if err := decode(raw, &p); err != nil {
			return nil, err
		}
		return s.query(ctx, p.Session, p.SQL, p.QueryID, p.MaxRows, p.TimeoutSec, p.ReadOnly)
	case "commit", "rollback":
		return nil, proto.Fail("no-tx", "Este banco não segura alterações para confirmar depois")
	case "databases", "objects", "table":
		var p struct{ Session, Schema, Name string }
		decode(raw, &p)
		x, err := s.get(p.Session)
		if err != nil {
			return nil, err
		}
		cctx, cancel := context.WithTimeout(ctx, 60*time.Second)
		defer cancel()
		switch method {
		case "databases":
			return x.c.Databases(cctx)
		case "objects":
			return x.c.Objects(cctx)
		}
		return x.c.Table(cctx, p.Schema, p.Name)
	case "apply":
		var p struct {
			Session string
			Changes []engine.Change
			DryRun  bool
		}
		if err := decode(raw, &p); err != nil {
			return nil, err
		}
		x, err := s.get(p.Session)
		if err != nil {
			return nil, err
		}
		var previews []string
		for _, ch := range p.Changes {
			previews = append(previews, x.c.Describe(ch))
		}
		if p.DryRun {
			return map[string]any{"sql": previews}, nil
		}
		cctx, cancel := context.WithTimeout(ctx, 2*time.Minute)
		defer cancel()
		// sem transação nestes bancos: antes de gravar qualquer coisa, confere que todos os documentos ainda existem
		for i, ch := range p.Changes {
			if ch.Op == "update" || ch.Op == "delete" {
				if err := x.c.Exists(cctx, ch); err != nil {
					return nil, &proto.Error{Code: "row-mismatch", Message: fmt.Sprintf("Edição %d: %v — nada foi aplicado", i+1, err), Data: map[string]any{"index": i}}
				}
			}
		}
		total := int64(0)
		for i, ch := range p.Changes {
			n, _, err := x.c.Apply(cctx, ch)
			if err != nil {
				return nil, &proto.Error{Code: "db", Message: fmt.Sprintf("Edição %d: %v — as %d anteriores já foram aplicadas", i+1, err, i), Data: map[string]any{"index": i}}
			}
			total += n
		}
		return map[string]any{"ok": true, "affected": total, "sql": previews}, nil
	}
	return nil, proto.Fail("unknown-method", "Método desconhecido: %s", method)
}

// parse: o comando lido — ou cru, para bancos de comandos em texto (Redis: GET chave).
func (s *Server) parse(text string, offset int) (*Call, error) {
	if r, ok := s.D.(interface{ Raw() bool }); ok && r.Raw() {
		return &Call{Text: text, Offset: offset}, nil
	}
	return ParseCall(text, offset)
}

func (s *Server) analyze(text string) ([]engine.Analysis, error) {
	out := []engine.Analysis{}
	for _, part := range SplitCalls(text) {
		c, err := s.parse(part.Text, part.Offset)
		if err != nil {
			// comando ilegível: conta como alteração (a regra de produção pergunta) — o erro aparece ao rodar
			out = append(out, engine.Analysis{Offset: part.Offset, First: "?", Write: true})
			continue
		}
		a := s.D.Analyze(c)
		a.Offset = part.Offset
		out = append(out, a)
	}
	return out, nil
}

func (s *Server) query(parent context.Context, sid, text, qid string, max, timeout int, readOnly bool) (any, error) {
	x, err := s.get(sid)
	if err != nil {
		return nil, err
	}
	if max <= 0 {
		max = 1000
	}
	ctx, cancel := context.WithCancel(parent)
	if timeout > 0 {
		ctx, cancel = context.WithTimeout(parent, time.Duration(timeout)*time.Second)
	}
	defer cancel()
	if qid != "" {
		s.mu.Lock()
		s.running[qid] = cancel
		s.mu.Unlock()
		defer func() { s.mu.Lock(); delete(s.running, qid); s.mu.Unlock() }()
	}
	x.mu.Lock()
	defer x.mu.Unlock()
	started := time.Now()
	results := []engine.Result{}
	for i, part := range SplitCalls(text) {
		t0 := time.Now()
		c, err := s.parse(part.Text, part.Offset)
		if err == nil && readOnly && s.D.Analyze(c).Write {
			err = proto.Fail("read-only", "Somente leitura: este comando altera dados")
		}
		var out *Output
		if err == nil {
			out, err = x.c.Run(ctx, c, max)
		}
		if err != nil {
			pe, ok := err.(*proto.Error)
			if !ok {
				pe = &proto.Error{Code: "db", Message: err.Error()}
			}
			if ctx.Err() == context.Canceled && parent.Err() == nil {
				pe = proto.Fail("canceled", "Consulta cancelada")
			}
			pe.Data = engine.QueryError{Index: i, Offset: part.Offset, Results: results}
			return nil, pe
		}
		r := ToResult(out)
		r.Statement, r.Offset, r.Ms = part.Text, part.Offset, time.Since(t0).Milliseconds()
		results = append(results, r)
	}
	return map[string]any{"results": results, "ms": time.Since(started).Milliseconds()}, nil
}

// ToResult transforma documentos em linhas: uma coluna por campo (na ordem em que aparecem), objetos e listas em
// JSON, ObjectId em texto. O tipo da coluna vem do primeiro valor não nulo (MIXED se variar).
func ToResult(o *Output) engine.Result {
	r := engine.Result{Messages: o.Messages, Truncated: o.Truncated, Total: o.Total, Affected: o.Affected}
	if o.Docs == nil {
		return r
	}
	idx := map[string]int{}
	var cols []engine.ColumnMeta
	add := func(k string) {
		if _, ok := idx[k]; !ok && len(cols) < 300 {
			idx[k] = len(cols)
			cols = append(cols, engine.ColumnMeta{Name: k})
		}
	}
	if o.KeyCol != "" {
		add(o.KeyCol)
	}
	for _, d := range o.Docs {
		for _, kv := range d {
			add(kv.K)
		}
	}
	rows := make([][]any, 0, len(o.Docs))
	for _, d := range o.Docs {
		row := make([]any, len(cols))
		for _, kv := range d {
			i, ok := idx[kv.K]
			if !ok {
				continue
			}
			v, t := Cell(kv.V)
			row[i] = v
			if v != nil {
				switch cols[i].Type {
				case "":
					cols[i].Type = t
				case t:
				default:
					cols[i].Type = "MIXED"
				}
			}
		}
		rows = append(rows, row)
	}
	for i := range cols {
		if cols[i].Type == "" {
			cols[i].Type = "NULL"
		}
	}
	r.Columns, r.Rows = cols, rows
	return r
}

// Cell: valor da célula e o tipo da coluna.
func Cell(v any) (any, string) {
	switch x := v.(type) {
	case nil:
		return nil, ""
	case string:
		return x, "STRING"
	case bool:
		return x, "BOOL"
	case int32:
		return int64(x), "INT"
	case int64:
		if x > 1<<53 || x < -(1<<53) {
			return fmt.Sprint(x), "LONG"
		}
		return x, "INT"
	case Long:
		return Cell(int64(x))
	case Int32:
		return int64(x), "INT"
	case float64:
		if math.IsNaN(x) || math.IsInf(x, 0) {
			return fmt.Sprint(x), "DOUBLE"
		}
		return x, "DOUBLE"
	case Decimal:
		return string(x), "DECIMAL"
	case OID:
		return string(x), "OBJECTID"
	case time.Time:
		return x.UTC().Format("2006-01-02 15:04:05.000Z"), "DATE"
	case []byte:
		return "0x" + strings.ToUpper(hex.EncodeToString(x)), "BINARY"
	case Obj, []any, map[string]any:
		return JSON(x), "JSON"
	}
	return fmt.Sprint(v), "STRING"
}

// JSON: objeto ordenado em JSON (ObjectId como {"$oid": …}, datas em ISO).
func JSON(v any) string {
	var b strings.Builder
	writeJSON(&b, v)
	return b.String()
}

func writeJSON(b *strings.Builder, v any) {
	switch x := v.(type) {
	case Obj:
		b.WriteByte('{')
		for i, kv := range x {
			if i > 0 {
				b.WriteByte(',')
			}
			k, _ := json.Marshal(kv.K)
			b.Write(k)
			b.WriteByte(':')
			writeJSON(b, kv.V)
		}
		b.WriteByte('}')
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		o := Obj{}
		for _, k := range keys {
			o = append(o, KV{k, x[k]})
		}
		writeJSON(b, o)
	case []any:
		b.WriteByte('[')
		for i, e := range x {
			if i > 0 {
				b.WriteByte(',')
			}
			writeJSON(b, e)
		}
		b.WriteByte(']')
	case OID:
		fmt.Fprintf(b, `{"$oid":%q}`, string(x))
	case time.Time:
		fmt.Fprintf(b, "%q", x.UTC().Format(time.RFC3339Nano))
	case []byte:
		fmt.Fprintf(b, "%q", "0x"+strings.ToUpper(hex.EncodeToString(x)))
	case Long:
		fmt.Fprint(b, int64(x))
	case Int32:
		fmt.Fprint(b, int32(x))
	case Decimal:
		fmt.Fprintf(b, "%q", string(x))
	case Regex:
		fmt.Fprintf(b, `{"$regex":%q,"$options":%q}`, x.Pattern, x.Flags)
	default:
		out, err := json.Marshal(x)
		if err != nil {
			fmt.Fprintf(b, "%q", fmt.Sprint(x))
			return
		}
		b.Write(out)
	}
}

// Coerce: o texto digitado na grade vira o mesmo tipo que o campo já tinha no documento.
func Coerce(text any, like any) any {
	s, ok := text.(string)
	if !ok {
		if n, ok := text.(json.Number); ok {
			s = n.String()
		} else {
			return text
		}
	}
	switch like.(type) {
	case int32, int64, Long, Int32:
		var n int64
		if _, err := fmt.Sscan(s, &n); err == nil {
			return n
		}
	case float64:
		var f float64
		if _, err := fmt.Sscan(s, &f); err == nil {
			return f
		}
	case bool:
		return s == "true" || s == "1"
	case OID:
		return OID(s)
	case time.Time:
		for _, f := range []string{"2006-01-02 15:04:05.000Z", time.RFC3339Nano, "2006-01-02 15:04:05", "2006-01-02"} {
			if t, err := time.Parse(f, s); err == nil {
				return t
			}
		}
	case Obj, []any, map[string]any:
		if v, err := ParseValue(s); err == nil {
			return v
		}
	case nil:
		if v, err := ParseValue(s); err == nil { // campo novo/nulo: número, true/false, objeto viram o que parecem
			if _, isStr := v.(string); !isStr {
				return v
			}
		}
	}
	return s
}

// ParseValue lê um valor solto ({…}, […], número, "texto", ObjectId(…)).
func ParseValue(s string) (any, error) {
	p := &parser{s: s}
	v, err := p.value()
	if err != nil {
		return nil, err
	}
	p.ws()
	if p.i != len(p.s) {
		return nil, fmt.Errorf("texto sobrando")
	}
	return v, nil
}

// Columns: amostra de documentos → colunas para a "estrutura" (a chave primeiro).
func Columns(docs []Obj, key string) []engine.Column {
	r := ToResult(&Output{Docs: docs, KeyCol: key})
	out := []engine.Column{}
	for _, c := range r.Columns {
		col := engine.Column{Name: c.Name, Type: strings.ToLower(c.Type), Nullable: c.Name != key}
		if c.Name == key {
			col.PK = 1
		}
		out = append(out, col)
	}
	return out
}
