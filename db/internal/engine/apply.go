package engine

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"

	"codeck/db/internal/proto"
)

// Change é uma edição da grade. Key identifica a linha pelos valores ORIGINAIS da chave primária (ou única).
type Change struct {
	Op     string         `json:"op"` // insert | update | delete
	Schema string         `json:"schema"`
	Table  string         `json:"table"`
	Key    map[string]any `json:"key"`
	Values map[string]any `json:"values"`
}

type applyParams struct {
	Session string
	Changes []Change
	DryRun  bool // só devolve o SQL (a tela mostra antes de aplicar)
}

type built struct {
	sql     string
	args    []any
	preview string
	single  bool // UPDATE/DELETE: tem de mexer em exatamente uma linha
}

// apply roda todas as edições numa transação só: ou entram todas, ou nenhuma. Um UPDATE/DELETE que pegaria zero ou
// várias linhas (a linha mudou, ou a "chave" não era única) desfaz tudo — a grade nunca altera o que você não viu.
func (e *Engine) apply(parent context.Context, p applyParams) (any, error) {
	var stmts []built
	for i, c := range p.Changes {
		b, err := e.build(c)
		if err != nil {
			return nil, proto.Fail("bad-change", "Edição %d: %v", i+1, err)
		}
		stmts = append(stmts, b)
	}
	previews := make([]string, len(stmts))
	for i, b := range stmts {
		previews[i] = b.preview
	}
	if p.DryRun {
		return map[string]any{"sql": previews}, nil
	}
	s, err := e.get(p.Session)
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(parent, 2*time.Minute)
	defer cancel()
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, asProto(err)
	}
	total := int64(0)
	for i, b := range stmts {
		r, err := tx.ExecContext(ctx, b.sql, b.args...)
		if err != nil {
			tx.Rollback()
			pe := toProto(err)
			pe.Message = fmt.Sprintf("Edição %d: %s — nada foi aplicado", i+1, pe.Message)
			pe.Data = map[string]any{"index": i}
			return nil, pe
		}
		n, _ := r.RowsAffected()
		if b.single && n != 1 {
			tx.Rollback()
			return nil, &proto.Error{Code: "row-mismatch", Data: map[string]any{"index": i, "affected": n},
				Message: fmt.Sprintf("Edição %d mexeria em %d linhas em vez de 1 (a linha mudou ou a chave não é única) — nada foi aplicado", i+1, n)}
		}
		total += n
	}
	if err := tx.Commit(); err != nil {
		return nil, asProto(err)
	}
	return map[string]any{"ok": true, "affected": total, "sql": previews}, nil
}

func (e *Engine) table(c Change) string {
	if c.Schema == "" {
		return e.D.Quote(c.Table)
	}
	return e.D.Quote(c.Schema) + "." + e.D.Quote(c.Table)
}

func sortedKeys(m map[string]any) []string {
	ks := make([]string, 0, len(m))
	for k := range m {
		ks = append(ks, k)
	}
	sort.Strings(ks)
	return ks
}

func (e *Engine) build(c Change) (built, error) {
	if c.Table == "" {
		return built{}, fmt.Errorf("tabela não informada")
	}
	t := e.table(c)
	var b built
	n := 0
	arg := func(v any) (string, string) {
		n++
		b.args = append(b.args, argValue(v))
		return e.D.Param(n), e.D.Literal(v)
	}
	where := func() (string, string, error) {
		if len(c.Key) == 0 {
			return "", "", fmt.Errorf("sem chave para achar a linha (tabela sem chave primária?)")
		}
		var w, wp []string
		for _, k := range sortedKeys(c.Key) {
			if c.Key[k] == nil {
				w = append(w, e.D.Quote(k)+" IS NULL")
				wp = append(wp, e.D.Quote(k)+" IS NULL")
				continue
			}
			ph, lit := arg(c.Key[k])
			w = append(w, e.D.Quote(k)+" = "+ph)
			wp = append(wp, e.D.Quote(k)+" = "+lit)
		}
		return strings.Join(w, " AND "), strings.Join(wp, " AND "), nil
	}
	switch c.Op {
	case "update":
		if len(c.Values) == 0 {
			return b, fmt.Errorf("nada para alterar")
		}
		var set, setp []string
		for _, k := range sortedKeys(c.Values) {
			ph, lit := arg(c.Values[k])
			set = append(set, e.D.Quote(k)+" = "+ph)
			setp = append(setp, e.D.Quote(k)+" = "+lit)
		}
		w, wp, err := where()
		if err != nil {
			return b, err
		}
		b.sql = fmt.Sprintf("UPDATE %s SET %s WHERE %s", t, strings.Join(set, ", "), w)
		b.preview = fmt.Sprintf("UPDATE %s SET %s WHERE %s;", t, strings.Join(setp, ", "), wp)
		b.single = true
	case "delete":
		w, wp, err := where()
		if err != nil {
			return b, err
		}
		b.sql = fmt.Sprintf("DELETE FROM %s WHERE %s", t, w)
		b.preview = fmt.Sprintf("DELETE FROM %s WHERE %s;", t, wp)
		b.single = true
	case "insert":
		var cols, phs, lits []string
		for _, k := range sortedKeys(c.Values) {
			ph, lit := arg(c.Values[k])
			cols = append(cols, e.D.Quote(k))
			phs = append(phs, ph)
			lits = append(lits, lit)
		}
		if len(cols) == 0 {
			return b, fmt.Errorf("linha nova sem valores")
		}
		b.sql = fmt.Sprintf("INSERT INTO %s (%s) VALUES (%s)", t, strings.Join(cols, ", "), strings.Join(phs, ", "))
		b.preview = fmt.Sprintf("INSERT INTO %s (%s) VALUES (%s);", t, strings.Join(cols, ", "), strings.Join(lits, ", "))
	default:
		return b, fmt.Errorf("operação desconhecida %q", c.Op)
	}
	return b, nil
}

// argValue: números chegam como json.Number (sem arredondar) e vão como texto — o banco converte para o tipo da
// coluna, como faria com o valor digitado.
func argValue(v any) any {
	switch x := v.(type) {
	case json.Number:
		return x.String()
	case map[string]any, []any:
		b, _ := json.Marshal(x)
		return string(b)
	}
	return v
}

// QuoteString: texto entre aspas simples, com a aspa dobrada.
func QuoteString(s string) string { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }

// GenericLiteral serve à maioria dos bancos; cada Dialect ajusta o que for diferente.
func GenericLiteral(v any) string {
	switch x := v.(type) {
	case nil:
		return "NULL"
	case json.Number:
		return x.String()
	case bool:
		if x {
			return "TRUE"
		}
		return "FALSE"
	case string:
		return QuoteString(x)
	case map[string]any, []any:
		b, _ := json.Marshal(x)
		return QuoteString(string(b))
	}
	return QuoteString(fmt.Sprint(v))
}

// QuoteWith cita um identificador dobrando o caractere de fechamento.
func QuoteWith(open, close, ident string) string {
	return open + strings.ReplaceAll(ident, close, close+close) + close
}
