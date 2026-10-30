// Package docs: o que os plugins de banco de documentos (MongoDB, Firebase) têm em comum — o leitor das chamadas no
// estilo do shell (db.clientes.find({cidade: "Recife"}).sort({nome: 1})), as sessões e a conversão de documentos
// em linhas para a mesma grade dos bancos SQL.
package docs

import (
	"fmt"
	"strconv"
	"strings"
	"time"
	"unicode"
)

// KV e Obj: objeto com a ordem das chaves preservada (no MongoDB, {nome: 1, idade: -1} num sort depende da ordem).
type KV struct {
	K string
	V any
}
type Obj []KV

func (o Obj) Get(k string) (any, bool) {
	for _, kv := range o {
		if kv.K == k {
			return kv.V, true
		}
	}
	return nil, false
}

// Valores especiais do shell.
type (
	OID     string // ObjectId("…")
	Regex   struct{ Pattern, Flags string }
	Long    int64  // NumberLong(…)
	Int32   int32  // NumberInt(…)
	Decimal string // NumberDecimal("…")
	UUID    string
)

// Seg é um pedaço da cadeia: nome, ou nome(args).
type Seg struct {
	Name   string
	Call   bool
	Args   []any
	Offset int
}

// Call: o comando inteiro — "show collections", "use x" ou a cadeia db.x.find(…).limit(…).
type Call struct {
	Text   string
	Offset int
	Words  []string // show / use
	Chain  []Seg
}

type parser struct {
	s string
	i int
}

func (p *parser) fail(format string, a ...any) error {
	line := strings.Count(p.s[:min(p.i, len(p.s))], "\n") + 1
	return fmt.Errorf("linha %d: %s", line, fmt.Sprintf(format, a...))
}

func (p *parser) ws() {
	for p.i < len(p.s) {
		c := p.s[p.i]
		switch {
		case c == ' ' || c == '\t' || c == '\n' || c == '\r':
			p.i++
		case strings.HasPrefix(p.s[p.i:], "//"):
			for p.i < len(p.s) && p.s[p.i] != '\n' {
				p.i++
			}
		case strings.HasPrefix(p.s[p.i:], "/*"):
			if e := strings.Index(p.s[p.i+2:], "*/"); e >= 0 {
				p.i += e + 4
			} else {
				p.i = len(p.s)
			}
		default:
			return
		}
	}
}

func (p *parser) ident() string {
	st := p.i
	for p.i < len(p.s) {
		r := rune(p.s[p.i])
		if r == '_' || r == '$' || unicode.IsLetter(r) || unicode.IsDigit(r) && p.i > st {
			p.i++
			continue
		}
		break
	}
	return p.s[st:p.i]
}

// ParseCall lê um comando.
func ParseCall(text string, offset int) (*Call, error) {
	c := &Call{Text: text, Offset: offset}
	t := strings.TrimSpace(text)
	if f := strings.Fields(t); len(f) >= 1 && (f[0] == "show" || f[0] == "use") {
		c.Words = f
		return c, nil
	}
	p := &parser{s: text}
	for {
		p.ws()
		st := p.i
		name := p.ident()
		if name == "" {
			return nil, p.fail("esperava um nome (ex.: db.clientes.find())")
		}
		seg := Seg{Name: name, Offset: offset + st}
		p.ws()
		if p.i < len(p.s) && p.s[p.i] == '(' {
			p.i++
			seg.Call = true
			for {
				p.ws()
				if p.i < len(p.s) && p.s[p.i] == ')' {
					p.i++
					break
				}
				v, err := p.value()
				if err != nil {
					return nil, err
				}
				seg.Args = append(seg.Args, v)
				p.ws()
				if p.i < len(p.s) && p.s[p.i] == ',' {
					p.i++
					continue
				}
				if p.i < len(p.s) && p.s[p.i] == ')' {
					p.i++
					break
				}
				return nil, p.fail("esperava , ou ) em %s(…)", name)
			}
		}
		c.Chain = append(c.Chain, seg)
		p.ws()
		if p.i < len(p.s) && p.s[p.i] == '.' {
			p.i++
			continue
		}
		if p.i < len(p.s) && p.s[p.i] == ';' {
			p.i++
			p.ws()
		}
		if p.i < len(p.s) {
			return nil, p.fail("texto sobrando: %q", strings.TrimSpace(p.s[p.i:min(p.i+30, len(p.s))]))
		}
		return c, nil
	}
}

func (p *parser) value() (any, error) {
	p.ws()
	if p.i >= len(p.s) {
		return nil, p.fail("valor faltando")
	}
	c := p.s[p.i]
	switch {
	case c == '{':
		return p.object()
	case c == '[':
		p.i++
		arr := []any{}
		for {
			p.ws()
			if p.i < len(p.s) && p.s[p.i] == ']' {
				p.i++
				return arr, nil
			}
			v, err := p.value()
			if err != nil {
				return nil, err
			}
			arr = append(arr, v)
			p.ws()
			if p.i < len(p.s) && p.s[p.i] == ',' {
				p.i++
				continue
			}
			if p.i < len(p.s) && p.s[p.i] == ']' {
				p.i++
				return arr, nil
			}
			return nil, p.fail("esperava , ou ] na lista")
		}
	case c == '"' || c == '\'' || c == '`':
		return p.str()
	case c == '/':
		end := p.i + 1
		for end < len(p.s) && p.s[end] != '/' {
			if p.s[end] == '\\' {
				end++
			}
			end++
		}
		if end >= len(p.s) {
			return nil, p.fail("regex sem fim")
		}
		pat := p.s[p.i+1 : end]
		p.i = end + 1
		return Regex{Pattern: pat, Flags: p.ident()}, nil
	case c == '-' || c == '+' || c == '.' || c >= '0' && c <= '9':
		st := p.i
		p.i++
		for p.i < len(p.s) && strings.ContainsRune("0123456789.eE+-", rune(p.s[p.i])) {
			p.i++
		}
		lit := p.s[st:p.i]
		if n, err := strconv.ParseInt(lit, 10, 64); err == nil {
			return n, nil
		}
		f, err := strconv.ParseFloat(lit, 64)
		if err != nil {
			return nil, p.fail("número inválido %q", lit)
		}
		return f, nil
	}
	name := p.ident()
	switch name {
	case "true":
		return true, nil
	case "false":
		return false, nil
	case "null", "undefined":
		return nil, nil
	case "new":
		p.ws()
		name = p.ident()
	case "":
		return nil, p.fail("valor inesperado %q", string(c))
	}
	p.ws()
	if p.i >= len(p.s) || p.s[p.i] != '(' {
		return nil, p.fail("valor inesperado %q (texto entre aspas?)", name)
	}
	p.i++
	var arg any
	p.ws()
	if p.i < len(p.s) && p.s[p.i] != ')' {
		v, err := p.value()
		if err != nil {
			return nil, err
		}
		arg = v
		p.ws()
	}
	if p.i >= len(p.s) || p.s[p.i] != ')' {
		return nil, p.fail("esperava ) em %s(…)", name)
	}
	p.i++
	return special(name, arg, p)
}

func special(name string, arg any, p *parser) (any, error) {
	s := fmt.Sprint(arg)
	switch name {
	case "ObjectId":
		if arg == nil {
			return OID(""), nil
		}
		return OID(s), nil
	case "ISODate", "Date":
		if arg == nil {
			return time.Now().UTC(), nil
		}
		if n, ok := arg.(int64); ok {
			return time.UnixMilli(n).UTC(), nil
		}
		for _, f := range []string{time.RFC3339Nano, "2006-01-02T15:04:05", "2006-01-02 15:04:05", "2006-01-02"} {
			if t, err := time.Parse(f, s); err == nil {
				return t.UTC(), nil
			}
		}
		return nil, p.fail("data inválida %q", s)
	case "NumberLong":
		n, err := strconv.ParseInt(s, 10, 64)
		if err != nil {
			return nil, p.fail("NumberLong inválido")
		}
		return Long(n), nil
	case "NumberInt":
		n, err := strconv.ParseInt(s, 10, 32)
		if err != nil {
			return nil, p.fail("NumberInt inválido")
		}
		return Int32(n), nil
	case "NumberDecimal", "Decimal128":
		return Decimal(s), nil
	case "UUID":
		return UUID(s), nil
	}
	return nil, p.fail("função desconhecida %s()", name)
}

func (p *parser) str() (string, error) {
	q := p.s[p.i]
	p.i++
	var b strings.Builder
	for p.i < len(p.s) {
		c := p.s[p.i]
		if c == q {
			p.i++
			return b.String(), nil
		}
		if c == '\\' && p.i+1 < len(p.s) {
			p.i++
			switch e := p.s[p.i]; e {
			case 'n':
				b.WriteByte('\n')
			case 't':
				b.WriteByte('\t')
			case 'r':
				b.WriteByte('\r')
			case 'u':
				if p.i+4 < len(p.s) {
					if r, err := strconv.ParseUint(p.s[p.i+1:p.i+5], 16, 32); err == nil {
						b.WriteRune(rune(r))
						p.i += 5
						continue
					}
				}
				b.WriteByte(e)
			default:
				b.WriteByte(e)
			}
			p.i++
			continue
		}
		b.WriteByte(c)
		p.i++
	}
	return "", p.fail("texto sem fechar as aspas")
}

func (p *parser) object() (Obj, error) {
	p.i++ // {
	o := Obj{}
	for {
		p.ws()
		if p.i < len(p.s) && p.s[p.i] == '}' {
			p.i++
			return o, nil
		}
		var key string
		if p.i < len(p.s) && (p.s[p.i] == '"' || p.s[p.i] == '\'') {
			k, err := p.str()
			if err != nil {
				return nil, err
			}
			key = k
		} else {
			key = p.identDotted()
		}
		if key == "" {
			return nil, p.fail("esperava o nome do campo")
		}
		p.ws()
		if p.i >= len(p.s) || p.s[p.i] != ':' {
			return nil, p.fail("esperava : depois de %q", key)
		}
		p.i++
		v, err := p.value()
		if err != nil {
			return nil, err
		}
		o = append(o, KV{key, v})
		p.ws()
		if p.i < len(p.s) && p.s[p.i] == ',' {
			p.i++
			continue
		}
		if p.i < len(p.s) && p.s[p.i] == '}' {
			p.i++
			return o, nil
		}
		return nil, p.fail("esperava , ou } no objeto")
	}
}

// identDotted: chave sem aspas pode ter ponto ($set: {endereco.cidade: 1} não é JS válido, mas é útil e comum).
func (p *parser) identDotted() string {
	st := p.i
	for p.i < len(p.s) {
		r := rune(p.s[p.i])
		if r == '_' || r == '$' || r == '.' || unicode.IsLetter(r) || unicode.IsDigit(r) {
			p.i++
			continue
		}
		break
	}
	return p.s[st:p.i]
}

// SplitCalls divide o texto em comandos: no ";" e na quebra de linha quando a próxima linha não continua a cadeia
// (não começa com "."), fora de texto, comentário e parênteses.
func SplitCalls(src string) []struct {
	Text   string
	Offset int
} {
	var out []struct {
		Text   string
		Offset int
	}
	depth, start := 0, 0
	var q byte
	push := func(a, b int) {
		t := strings.TrimSpace(src[a:b])
		if t != "" && !strings.HasPrefix(t, "//") {
			out = append(out, struct {
				Text   string
				Offset int
			}{t, a + strings.Index(src[a:b], t)})
		}
	}
	for i := 0; i < len(src); i++ {
		c := src[i]
		if q != 0 {
			if c == '\\' {
				i++
			} else if c == q {
				q = 0
			}
			continue
		}
		switch {
		case c == '"' || c == '\'' || c == '`':
			q = c
		case strings.HasPrefix(src[i:], "//"):
			for i < len(src) && src[i] != '\n' {
				i++
			}
			i--
		case c == '(' || c == '{' || c == '[':
			depth++
		case c == ')' || c == '}' || c == ']':
			depth--
		case c == ';' && depth == 0:
			push(start, i)
			start = i + 1
		case c == '\n' && depth == 0:
			rest := strings.TrimLeft(src[i+1:], " \t\r\n")
			if !strings.HasPrefix(rest, ".") && strings.TrimSpace(src[start:i]) != "" {
				push(start, i)
				start = i + 1
			}
		}
	}
	push(start, len(src))
	return out
}
