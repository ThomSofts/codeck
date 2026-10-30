// Package redis: Redis (e compatíveis: Valkey, KeyDB, Upstash), comandos como no redis-cli — um por linha:
//
//	GET usuario:1 · HGETALL usuario:1 · LRANGE fila 0 50 · SCAN 0 MATCH usuario:* COUNT 500 · SET chave "valor"
//
// KEYS vira SCAN (KEYS trava o servidor enquanto percorre tudo). As "tabelas" são os prefixos das chaves (usuario:*).
package redis

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	rd "github.com/redis/go-redis/v9"

	"codeck/db/internal/docs"
	"codeck/db/internal/engine"
	"codeck/db/internal/proto"
)

type Driver struct{}

func (Driver) Engine() string { return "redis" }
func (Driver) Raw() bool      { return true }

var writes = map[string]bool{"SET": true, "SETEX": true, "PSETEX": true, "SETNX": true, "MSET": true, "MSETNX": true, "GETSET": true, "GETDEL": true,
	"DEL": true, "UNLINK": true, "EXPIRE": true, "PEXPIRE": true, "EXPIREAT": true, "PERSIST": true, "RENAME": true, "RENAMENX": true, "COPY": true,
	"MOVE": true, "RESTORE": true, "HSET": true, "HSETNX": true, "HMSET": true, "HDEL": true, "HINCRBY": true, "HINCRBYFLOAT": true, "INCR": true,
	"INCRBY": true, "INCRBYFLOAT": true, "DECR": true, "DECRBY": true, "APPEND": true, "SETRANGE": true, "LPUSH": true, "RPUSH": true,
	"LPUSHX": true, "RPUSHX": true, "LPOP": true, "RPOP": true, "LSET": true, "LREM": true, "LTRIM": true, "LINSERT": true, "LMOVE": true,
	"SADD": true, "SREM": true, "SPOP": true, "SMOVE": true, "ZADD": true, "ZREM": true, "ZINCRBY": true, "ZPOPMIN": true, "ZPOPMAX": true,
	"ZREMRANGEBYSCORE": true, "ZREMRANGEBYRANK": true, "XADD": true, "XDEL": true, "XTRIM": true, "FLUSHDB": true, "FLUSHALL": true,
	"EVAL": true, "EVALSHA": true, "FCALL": true, "SCRIPT": true, "CONFIG": true, "SWAPDB": true, "SHUTDOWN": true, "DEBUG": true,
	"BGSAVE": true, "SAVE": true, "BGREWRITEAOF": true, "CLIENT": true, "SLAVEOF": true, "REPLICAOF": true, "MIGRATE": true, "PFADD": true,
	"PFMERGE": true, "GEOADD": true, "SINTERSTORE": true, "SUNIONSTORE": true, "SDIFFSTORE": true, "ZUNIONSTORE": true, "ZINTERSTORE": true}

// Fields: o comando em palavras, respeitando aspas ("valor com espaço").
func Fields(s string) ([]string, error) {
	var out []string
	var b strings.Builder
	in, q, has := false, byte(0), false
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case in && c == '\\' && i+1 < len(s):
			i++
			switch s[i] {
			case 'n':
				b.WriteByte('\n')
			case 't':
				b.WriteByte('\t')
			default:
				b.WriteByte(s[i])
			}
		case in && c == q:
			in = false
		case !in && (c == '"' || c == '\''):
			in, q, has = true, c, true
		case !in && (c == ' ' || c == '\t' || c == '\n' || c == '\r'):
			if b.Len() > 0 || has {
				out = append(out, b.String())
				b.Reset()
				has = false
			}
		default:
			b.WriteByte(c)
		}
	}
	if in {
		return nil, fmt.Errorf("aspas sem fechar")
	}
	if b.Len() > 0 || has {
		out = append(out, b.String())
	}
	return out, nil
}

func (Driver) Analyze(c *docs.Call) engine.Analysis {
	f, _ := Fields(c.Text)
	a := engine.Analysis{}
	if len(f) == 0 {
		return a
	}
	cmd := strings.ToUpper(f[0])
	a.First = cmd
	if cmd == "CONFIG" || cmd == "SCRIPT" || cmd == "CLIENT" {
		a.Write = len(f) > 1 && !(strings.EqualFold(f[1], "GET") || strings.EqualFold(f[1], "EXISTS") || strings.EqualFold(f[1], "LIST") || strings.EqualFold(f[1], "INFO"))
	} else {
		a.Write = writes[cmd]
	}
	a.Exec = cmd == "EVAL" || cmd == "EVALSHA" || cmd == "FCALL"
	if cmd == "FLUSHDB" || cmd == "FLUSHALL" {
		a.Drop, a.NoWhere = true, true
	}
	return a
}

type conn struct {
	c  *rd.Client
	db int
}

func (Driver) Open(ctx context.Context, p engine.ConnParams) (docs.Conn, string, *engine.CertInfo, error) {
	port := p.Port
	if port == 0 {
		port = 6379
	}
	db, _ := strconv.Atoi(strings.TrimSpace(p.Database))
	opt := &rd.Options{Addr: fmt.Sprintf("%s:%d", p.Host, port), Username: p.User, Password: p.Password, DB: db, Protocol: 2,
		DialTimeout: 15 * time.Second, ReadTimeout: 60 * time.Second, ClientName: "Codeck"}
	cap := &engine.Capture{}
	off, err := p.TLS.Off()
	if err != nil {
		return nil, "", nil, err
	}
	if !off {
		opt.TLSConfig = p.TLS.Config(engine.TLSHost(p), cap)
	}
	cl := rd.NewClient(opt)
	if err := cl.Ping(ctx).Err(); err != nil {
		cl.Close()
		if ce := engine.CertError(cap); ce != nil {
			return nil, "", nil, ce
		}
		if ne := engine.NoTLSError(err, p.TLS); ne != nil {
			return nil, "", nil, ne
		}
		if strings.Contains(err.Error(), "EOF") && !off {
			return nil, "", nil, proto.Fail("tls", "O servidor não respondeu em TLS — se ele não usa criptografia, escolha \"Sem criptografia\" (só em rede local/VPN)")
		}
		return nil, "", nil, err
	}
	ver := ""
	if info, err := cl.Info(ctx, "server").Result(); err == nil {
		for _, ln := range strings.Split(info, "\n") {
			if strings.HasPrefix(ln, "redis_version:") {
				ver = strings.TrimSpace(strings.TrimPrefix(ln, "redis_version:"))
			}
		}
	}
	return &conn{c: cl, db: db}, "Redis " + ver, cap.Get(), nil
}

func (c *conn) Close() { c.c.Close() }

func value(v any) any {
	switch x := v.(type) {
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = value(e)
		}
		return out
	case rd.Error:
		return "(erro) " + x.Error()
	}
	return v
}

func n64(n int64) *int64 { return &n }

// scan: chaves que casam com o padrão (SCAN, sem travar o servidor), com tipo, validade e uma prévia do valor.
func (c *conn) scan(ctx context.Context, pattern string, max int) (*docs.Output, error) {
	out := &docs.Output{KeyCol: "key", Docs: []docs.Obj{}}
	var cursor uint64
	var keys []string
	for {
		ks, next, err := c.c.Scan(ctx, cursor, pattern, 1000).Result()
		if err != nil {
			return nil, err
		}
		keys = append(keys, ks...)
		cursor = next
		if cursor == 0 || len(keys) > max {
			break
		}
	}
	if len(keys) > max {
		keys, out.Truncated = keys[:max], true
	}
	sort.Strings(keys)
	pipe := c.c.Pipeline()
	types := make([]*rd.StatusCmd, len(keys))
	ttls := make([]*rd.DurationCmd, len(keys))
	for i, k := range keys {
		types[i], ttls[i] = pipe.Type(ctx, k), pipe.TTL(ctx, k)
	}
	pipe.Exec(ctx)
	pipe = c.c.Pipeline()
	prev := make([]rd.Cmder, len(keys))
	for i, k := range keys {
		switch types[i].Val() {
		case "string":
			prev[i] = pipe.Get(ctx, k)
		case "hash":
			prev[i] = pipe.HLen(ctx, k)
		case "list":
			prev[i] = pipe.LLen(ctx, k)
		case "set":
			prev[i] = pipe.SCard(ctx, k)
		case "zset":
			prev[i] = pipe.ZCard(ctx, k)
		}
	}
	pipe.Exec(ctx)
	for i, k := range keys {
		ttl := any(nil)
		if d := ttls[i].Val(); d > 0 {
			ttl = int64(d.Seconds())
		}
		var v any
		switch x := prev[i].(type) {
		case *rd.StringCmd:
			v = x.Val()
		case *rd.IntCmd:
			v = fmt.Sprintf("(%s com %d itens)", types[i].Val(), x.Val())
		}
		out.Docs = append(out.Docs, docs.Obj{{K: "key", V: k}, {K: "type", V: types[i].Val()}, {K: "ttl", V: ttl}, {K: "value", V: v}})
	}
	return out, nil
}

func pairs(list []any, a, b string) []docs.Obj {
	out := []docs.Obj{}
	for i := 0; i+1 < len(list); i += 2 {
		out = append(out, docs.Obj{{K: a, V: value(list[i])}, {K: b, V: value(list[i+1])}})
	}
	return out
}

func (c *conn) Run(ctx context.Context, call *docs.Call, max int) (*docs.Output, error) {
	f, err := Fields(call.Text)
	if err != nil || len(f) == 0 {
		return nil, fmt.Errorf("comando vazio ou com aspas sem fechar")
	}
	cmd := strings.ToUpper(f[0])
	switch cmd {
	case "KEYS":
		pat := "*"
		if len(f) > 1 {
			pat = f[1]
		}
		out, err := c.scan(ctx, pat, max)
		if out != nil {
			out.Messages = append(out.Messages, "KEYS trocado por SCAN (não trava o servidor)")
		}
		return out, err
	case "SCAN":
		pat := "*"
		for i := 1; i+1 < len(f); i++ {
			if strings.EqualFold(f[i], "MATCH") {
				pat = f[i+1]
			}
		}
		return c.scan(ctx, pat, max)
	case "SELECT":
		return nil, fmt.Errorf("para trocar de banco (número), edite o ambiente — cada conexão fica num banco só")
	case "MONITOR", "SUBSCRIBE", "PSUBSCRIBE", "SSUBSCRIBE":
		return nil, fmt.Errorf("%s fica escutando para sempre — não roda aqui", cmd)
	}
	args := make([]any, len(f))
	for i, x := range f {
		args[i] = x
	}
	res, err := c.c.Do(ctx, args...).Result()
	if err == rd.Nil {
		return &docs.Output{KeyCol: "value", Docs: []docs.Obj{{{K: "value", V: nil}}}}, nil
	}
	if err != nil {
		return nil, err
	}
	list, isList := res.([]any)
	withScores := false
	for _, x := range f {
		withScores = withScores || strings.EqualFold(x, "WITHSCORES")
	}
	switch {
	case isList && (cmd == "HGETALL" || cmd == "CONFIG"):
		return &docs.Output{KeyCol: "field", Docs: pairs(list, "field", "value")}, nil
	case isList && withScores:
		return &docs.Output{KeyCol: "member", Docs: pairs(list, "member", "score")}, nil
	case isList:
		out := &docs.Output{KeyCol: "#", Docs: []docs.Obj{}}
		for i, v := range list {
			if len(out.Docs) >= max {
				out.Truncated = true
				break
			}
			out.Docs = append(out.Docs, docs.Obj{{K: "#", V: int64(i)}, {K: "value", V: value(v)}})
		}
		return out, nil
	}
	if a := (Driver{}).Analyze(call); a.Write {
		if n, ok := res.(int64); ok {
			return &docs.Output{Affected: n64(n)}, nil
		}
		return &docs.Output{Affected: n64(1), Messages: []string{fmt.Sprint(res)}}, nil
	}
	if s, ok := res.(string); ok && cmd == "INFO" {
		out := &docs.Output{KeyCol: "field", Docs: []docs.Obj{}}
		for _, ln := range strings.Split(s, "\n") {
			if k, v, ok := strings.Cut(strings.TrimSpace(ln), ":"); ok {
				out.Docs = append(out.Docs, docs.Obj{{K: "field", V: k}, {K: "value", V: v}})
			}
		}
		return out, nil
	}
	return &docs.Output{KeyCol: "value", Docs: []docs.Obj{{{K: "value", V: value(res)}}}}, nil
}

func (c *conn) Databases(ctx context.Context) ([]string, error) {
	return []string{strconv.Itoa(c.db)}, nil
}

// Objects: os prefixos das chaves (até 5.000 chaves lidas por SCAN) — "usuario:*", "sessao:*"…
func (c *conn) Objects(ctx context.Context) ([]engine.Object, error) {
	seen := map[string]bool{}
	var cursor uint64
	n := 0
	for {
		ks, next, err := c.c.Scan(ctx, cursor, "*", 1000).Result()
		if err != nil {
			return nil, err
		}
		for _, k := range ks {
			if i := strings.IndexAny(k, ":"); i > 0 {
				seen[k[:i+1]+"*"] = true
			} else {
				seen[k] = true
			}
		}
		n += len(ks)
		cursor = next
		if cursor == 0 || n >= 5000 {
			break
		}
	}
	names := make([]string, 0, len(seen))
	for k := range seen {
		names = append(names, k)
	}
	sort.Strings(names)
	out := []engine.Object{}
	for _, k := range names {
		out = append(out, engine.Object{Name: k, Kind: "table"})
	}
	return out, nil
}

func (c *conn) Table(ctx context.Context, schema, name string) (*engine.TableInfo, error) {
	return &engine.TableInfo{Schema: schema, Name: name, FKs: []engine.ForeignKey{}, Indexes: []engine.Index{},
		Columns: []engine.Column{{Name: "key", Type: "string", PK: 1}, {Name: "type", Type: "string"}, {Name: "ttl", Type: "int", Nullable: true},
			{Name: "value", Type: "string", Nullable: true}}}, nil
}

func (c *conn) Exists(ctx context.Context, ch engine.Change) error {
	k := fmt.Sprint(ch.Key["key"])
	if n, err := c.c.Exists(ctx, k).Result(); err != nil || n == 0 {
		return fmt.Errorf("a chave %q não existe mais", k)
	}
	if ch.Op == "update" { // só valor de texto edita pela grade: confere antes de gravar qualquer coisa
		if t, _ := c.c.Type(ctx, k).Result(); t != "string" {
			return fmt.Errorf("%q é %s — edite pelo comando (HSET, LSET…)", k, t)
		}
		for f, v := range ch.Values {
			if f != "value" {
				return fmt.Errorf("aqui só o valor de texto muda (para %s, use o comando)", f)
			}
			if v == nil {
				return fmt.Errorf("Redis não guarda NULL — para apagar, exclua a linha")
			}
		}
	}
	return nil
}

func (c *conn) Apply(ctx context.Context, ch engine.Change) (int64, string, error) {
	switch ch.Op {
	case "delete":
		n, err := c.c.Del(ctx, fmt.Sprint(ch.Key["key"])).Result()
		return n, "", err
	case "insert":
		k, ok := ch.Values["key"]
		if !ok || k == nil {
			return 0, "", fmt.Errorf("a linha nova precisa da chave")
		}
		return 1, "", c.c.Set(ctx, fmt.Sprint(k), fmt.Sprint(ch.Values["value"]), 0).Err()
	}
	k := fmt.Sprint(ch.Key["key"])
	for f := range ch.Values {
		if f != "value" {
			return 0, "", fmt.Errorf("aqui só o valor de texto muda (para %s, use o comando)", f)
		}
	}
	if t, _ := c.c.Type(ctx, k).Result(); t != "string" {
		return 0, "", fmt.Errorf("%q é %s — edite pelo comando (HSET, LSET…)", k, t)
	}
	v := ch.Values["value"]
	if v == nil {
		return 0, "", fmt.Errorf("Redis não guarda NULL — para apagar, exclua a linha")
	}
	return 1, "", c.c.SetArgs(ctx, k, fmt.Sprint(v), rd.SetArgs{KeepTTL: true}).Err()
}

func (c *conn) Describe(ch engine.Change) string {
	k := strconv.Quote(fmt.Sprint(ch.Key["key"]))
	switch ch.Op {
	case "delete":
		return "DEL " + k
	case "insert":
		return fmt.Sprintf("SET %s %s", strconv.Quote(fmt.Sprint(ch.Values["key"])), strconv.Quote(fmt.Sprint(ch.Values["value"])))
	}
	return fmt.Sprintf("SET %s %s KEEPTTL", k, strconv.Quote(fmt.Sprint(ch.Values["value"])))
}
