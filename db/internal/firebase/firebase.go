// Package firebase: Cloud Firestore e Realtime Database, pela REST API do Google com a conta de serviço (o JSON da
// service account fica no cofre do Codeck e chega aqui como "senha"). Sem SDK: o token é um JWT RS256 assinado com a
// chave da conta (biblioteca padrão do Go) e trocado por um token de acesso de 1 hora.
//
// Firestore:
//
//	collection('clientes').where('cidade', '==', 'Recife').orderBy('nome').limit(50)
//	collectionGroup('pedidos').where('status', '==', 'pago')
//	doc('clientes/abc') · doc('clientes/abc').update({ativo: false}) · collection('clientes').add({nome: 'Ana'})
//	listCollections() · doc('clientes/abc').listCollections()
//
// Realtime Database (o servidor é a URL https://….firebaseio.com ou …firebasedatabase.app):
//
//	ref('clientes').orderByChild('cidade').equalTo('Recife').limitToFirst(50)
//	ref('clientes/abc').update({ativo: false}) · ref('clientes').push({nome: 'Ana'}) · ref('x').remove()
package firebase

import (
	"bytes"
	"context"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"codeck/db/internal/docs"
	"codeck/db/internal/engine"
	"codeck/db/internal/proto"
)

type Driver struct{}

func (Driver) Engine() string { return "firebase" }

var writes = map[string]bool{"add": true, "set": true, "update": true, "delete": true, "remove": true, "push": true}

func (Driver) Analyze(c *docs.Call) engine.Analysis {
	a := engine.Analysis{}
	for _, s := range c.Chain {
		if a.First == "" {
			a.First = s.Name
		}
		if s.Call && writes[s.Name] {
			a.Write, a.First = true, s.Name
			if s.Name == "remove" || s.Name == "delete" {
				a.Drop = true
			}
			if s.Name == "set" && len(c.Chain) > 0 && c.Chain[0].Name == "ref" && len(c.Chain[0].Args) > 0 &&
				!strings.Contains(strings.Trim(fmt.Sprint(c.Chain[0].Args[0]), "/"), "/") {
				a.NoWhere = true // set() num nó da raiz substitui a "coleção" inteira
			}
		}
	}
	return a
}

type sa struct {
	ClientEmail string `json:"client_email"`
	PrivateKey  string `json:"private_key"`
	ProjectID   string `json:"project_id"`
	TokenURI    string `json:"token_uri"`
}

type conn struct {
	sa      sa
	key     *rsa.PrivateKey
	http    *http.Client
	mu      sync.Mutex
	token   string
	expires time.Time
	rtdb    string // URL do Realtime Database; vazio = Firestore
	rtdbNS  string // emulador: o nome do banco vai em ?ns=
	fsdb    string // id do banco do Firestore
}

// emulator: os emuladores do Firebase em 127.0.0.1 (só nos testes — o Codeck não repassa esta variável ao plugin).
var emulator = strings.TrimSpace(os.Getenv("CODECK_FIREBASE_EMULATOR")) // "firestore=127.0.0.1:8080,database=127.0.0.1:9000"

func emu(kind string) string {
	for _, part := range strings.Split(emulator, ",") {
		if k, v, ok := strings.Cut(part, "="); ok && k == kind && strings.HasPrefix(v, "127.0.0.1:") {
			return "http://" + v
		}
	}
	return ""
}

// só domínios do Google: a conta de serviço nunca vai para outro lugar
func allowed(u string) bool {
	p, err := url.Parse(u)
	if err == nil && emulator != "" && p.Scheme == "http" && p.Hostname() == "127.0.0.1" {
		return true
	}
	if err != nil || p.Scheme != "https" {
		return false
	}
	h := p.Hostname()
	return h == "oauth2.googleapis.com" || h == "firestore.googleapis.com" || strings.HasSuffix(h, ".firebaseio.com") || strings.HasSuffix(h, ".firebasedatabase.app")
}

func (Driver) Open(ctx context.Context, p engine.ConnParams) (docs.Conn, string, *engine.CertInfo, error) {
	var acc sa
	if err := json.Unmarshal([]byte(p.Password), &acc); err != nil || acc.ClientEmail == "" || acc.PrivateKey == "" {
		return nil, "", nil, proto.Fail("bad-credentials", "Cole o JSON da conta de serviço (Firebase → Configurações do projeto → Contas de serviço → Gerar nova chave privada) no campo Senha")
	}
	if acc.TokenURI == "" {
		acc.TokenURI = "https://oauth2.googleapis.com/token"
	}
	blk, _ := pem.Decode([]byte(acc.PrivateKey))
	if blk == nil {
		return nil, "", nil, proto.Fail("bad-credentials", "A chave privada da conta de serviço é inválida")
	}
	k, err := x509.ParsePKCS8PrivateKey(blk.Bytes)
	if err != nil {
		if k2, err2 := x509.ParsePKCS1PrivateKey(blk.Bytes); err2 == nil {
			k, err = k2, nil
		}
	}
	rk, ok := k.(*rsa.PrivateKey)
	if err != nil || !ok {
		return nil, "", nil, proto.Fail("bad-credentials", "A chave privada da conta de serviço não é RSA")
	}
	c := &conn{sa: acc, key: rk, http: &http.Client{Timeout: 60 * time.Second, CheckRedirect: func(r *http.Request, _ []*http.Request) error {
		if !allowed(r.URL.String()) {
			return fmt.Errorf("redirecionamento para fora do Google recusado")
		}
		return nil
	}}}
	host := strings.TrimRight(strings.TrimSpace(p.Host), "/")
	if e := emu("database"); e != "" && strings.HasPrefix(host, "https://") {
		c.rtdbNS = strings.SplitN(strings.TrimPrefix(host, "https://"), ".", 2)[0]
		host = e
	}
	if strings.HasPrefix(host, "https://") || c.rtdbNS != "" {
		if !allowed(host + "/") {
			return nil, "", nil, proto.Fail("bad-host", "O endereço do Realtime Database tem de ser https://….firebaseio.com ou ….firebasedatabase.app")
		}
		c.rtdb = host
	} else {
		c.fsdb = p.Database
		if c.fsdb == "" {
			c.fsdb = "(default)"
		}
		if host != "" && host != acc.ProjectID {
			acc.ProjectID = host // o servidor pode ser o id de outro projeto que a conta acessa
			c.sa.ProjectID = host
		}
	}
	if _, err := c.access(ctx); err != nil {
		return nil, "", nil, err
	}
	what := "Cloud Firestore · " + c.sa.ProjectID
	if c.rtdb != "" {
		what = "Realtime Database · " + strings.TrimPrefix(c.rtdb, "https://")
		var probe any
		if err := c.rest(ctx, "GET", c.rtdb+"/.json?shallow=true&limitToFirst=1", nil, &probe); err != nil {
			return nil, "", nil, err
		}
	} else if _, err := c.listCollections(ctx, ""); err != nil {
		return nil, "", nil, err
	}
	return c, what, nil, nil
}

func (c *conn) Close() {}

func (c *conn) access(ctx context.Context) (string, error) {
	if emulator != "" {
		return "owner", nil // o emulador aceita o token "owner"
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.token != "" && time.Now().Before(c.expires) {
		return c.token, nil
	}
	now := time.Now()
	head := base64.RawURLEncoding.EncodeToString([]byte(`{"alg":"RS256","typ":"JWT"}`))
	claims, _ := json.Marshal(map[string]any{"iss": c.sa.ClientEmail, "aud": c.sa.TokenURI, "iat": now.Unix(), "exp": now.Add(time.Hour).Unix(),
		"scope": "https://www.googleapis.com/auth/datastore https://www.googleapis.com/auth/firebase.database https://www.googleapis.com/auth/userinfo.email"})
	body := head + "." + base64.RawURLEncoding.EncodeToString(claims)
	sum := sha256.Sum256([]byte(body))
	sig, err := rsa.SignPKCS1v15(rand.Reader, c.key, crypto.SHA256, sum[:])
	if err != nil {
		return "", err
	}
	if !allowed(c.sa.TokenURI) {
		return "", fmt.Errorf("token_uri fora do Google recusado")
	}
	form := url.Values{"grant_type": {"urn:ietf:params:oauth:grant-type:jwt-bearer"}, "assertion": {body + "." + base64.RawURLEncoding.EncodeToString(sig)}}
	req, _ := http.NewRequestWithContext(ctx, "POST", c.sa.TokenURI, strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := c.http.Do(req)
	if err != nil {
		return "", proto.Fail("timeout", "Não consegui falar com o Google: %v", err)
	}
	defer resp.Body.Close()
	var t struct {
		AccessToken string `json:"access_token"`
		ExpiresIn   int    `json:"expires_in"`
		Error       string `json:"error_description"`
	}
	json.NewDecoder(resp.Body).Decode(&t)
	if t.AccessToken == "" {
		return "", proto.Fail("auth", "O Google recusou a conta de serviço: %s", t.Error)
	}
	c.token, c.expires = t.AccessToken, now.Add(time.Duration(t.ExpiresIn-120)*time.Second)
	return c.token, nil
}

func (c *conn) rest(ctx context.Context, method, u string, body any, out any) error {
	if c.rtdbNS != "" && strings.Contains(u, ".json") { // emulador do Realtime Database: o banco vai em ?ns=
		sep := "?"
		if strings.Contains(u, "?") {
			sep = "&"
		}
		u += sep + "ns=" + url.QueryEscape(c.rtdbNS)
	}
	if !allowed(u) {
		return fmt.Errorf("endereço fora do Google recusado")
	}
	tok, err := c.access(ctx)
	if err != nil {
		return err
	}
	var rd io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		rd = bytes.NewReader(b)
	}
	req, _ := http.NewRequestWithContext(ctx, method, u, rd)
	req.Header.Set("Authorization", "Bearer "+tok)
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 256<<20))
	if resp.StatusCode >= 300 {
		var e struct {
			Error any `json:"error"`
		}
		json.Unmarshal(raw, &e)
		msg := fmt.Sprint(e.Error)
		if m, ok := e.Error.(map[string]any); ok {
			msg = fmt.Sprint(m["message"])
		}
		if resp.StatusCode == 403 || resp.StatusCode == 401 {
			return proto.Fail("auth", "Sem permissão (%d): %s — a conta de serviço precisa de acesso a este banco", resp.StatusCode, msg)
		}
		return fmt.Errorf("%d: %s", resp.StatusCode, msg)
	}
	if out != nil && len(raw) > 0 {
		d := json.NewDecoder(bytes.NewReader(raw))
		d.UseNumber()
		return d.Decode(out)
	}
	return nil
}

// ------------------------------------------------------------ valores do Firestore

func (c *conn) docsBase() string {
	if e := emu("firestore"); e != "" {
		return fmt.Sprintf("%s/v1/projects/%s/databases/%s/documents", e, url.PathEscape(c.sa.ProjectID), url.PathEscape(c.fsdb))
	}
	return fmt.Sprintf("https://firestore.googleapis.com/v1/projects/%s/databases/%s/documents", url.PathEscape(c.sa.ProjectID), url.PathEscape(c.fsdb))
}

func fromFS(v map[string]any) any {
	for k, x := range v {
		switch k {
		case "nullValue":
			return nil
		case "booleanValue", "stringValue", "doubleValue":
			if n, ok := x.(json.Number); ok {
				f, _ := n.Float64()
				return f
			}
			return x
		case "integerValue":
			n, _ := strconv.ParseInt(fmt.Sprint(x), 10, 64)
			return n
		case "timestampValue":
			t, err := time.Parse(time.RFC3339Nano, fmt.Sprint(x))
			if err != nil {
				return fmt.Sprint(x)
			}
			return t
		case "referenceValue":
			s := fmt.Sprint(x)
			if i := strings.Index(s, "/documents/"); i >= 0 {
				return s[i+len("/documents/"):]
			}
			return s
		case "bytesValue":
			b, _ := base64.StdEncoding.DecodeString(fmt.Sprint(x))
			return b
		case "geoPointValue":
			m, _ := x.(map[string]any)
			return docs.Obj{{K: "latitude", V: num(m["latitude"])}, {K: "longitude", V: num(m["longitude"])}}
		case "arrayValue":
			m, _ := x.(map[string]any)
			arr := []any{}
			for _, e := range asList(m["values"]) {
				if em, ok := e.(map[string]any); ok {
					arr = append(arr, fromFS(em))
				}
			}
			return arr
		case "mapValue":
			m, _ := x.(map[string]any)
			return fieldsToObj(m["fields"])
		}
	}
	return nil
}

func num(v any) any {
	if n, ok := v.(json.Number); ok {
		f, _ := n.Float64()
		return f
	}
	return v
}

func asList(v any) []any {
	l, _ := v.([]any)
	return l
}

func fieldsToObj(f any) docs.Obj {
	m, _ := f.(map[string]any)
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	o := docs.Obj{}
	for _, k := range keys {
		if vm, ok := m[k].(map[string]any); ok {
			o = append(o, docs.KV{K: k, V: fromFS(vm)})
		}
	}
	return o
}

func toFS(v any) map[string]any {
	switch x := v.(type) {
	case nil:
		return map[string]any{"nullValue": nil}
	case bool:
		return map[string]any{"booleanValue": x}
	case int64:
		return map[string]any{"integerValue": strconv.FormatInt(x, 10)}
	case docs.Long:
		return map[string]any{"integerValue": strconv.FormatInt(int64(x), 10)}
	case docs.Int32:
		return map[string]any{"integerValue": strconv.FormatInt(int64(x), 10)}
	case float64:
		return map[string]any{"doubleValue": x}
	case string:
		return map[string]any{"stringValue": x}
	case time.Time:
		return map[string]any{"timestampValue": x.UTC().Format(time.RFC3339Nano)}
	case []byte:
		return map[string]any{"bytesValue": base64.StdEncoding.EncodeToString(x)}
	case []any:
		vals := []any{}
		for _, e := range x {
			vals = append(vals, toFS(e))
		}
		return map[string]any{"arrayValue": map[string]any{"values": vals}}
	case docs.Obj:
		return map[string]any{"mapValue": map[string]any{"fields": objToFields(x)}}
	}
	return map[string]any{"stringValue": fmt.Sprint(v)}
}

func objToFields(o docs.Obj) map[string]any {
	f := map[string]any{}
	for _, kv := range o {
		f[kv.K] = toFS(kv.V)
	}
	return f
}

func docRow(name string, fields any) docs.Obj {
	id := name
	if i := strings.Index(name, "/documents/"); i >= 0 {
		id = name[i+len("/documents/"):]
	}
	row := docs.Obj{{K: "__name__", V: id[strings.LastIndex(id, "/")+1:]}}
	if strings.Count(id, "/") > 1 {
		row = append(row, docs.KV{K: "__path__", V: id})
	}
	return append(row, fieldsToObj(fields)...)
}

// ------------------------------------------------------------ comandos

func strArg(s docs.Seg, i int) string {
	if i < len(s.Args) {
		return fmt.Sprint(s.Args[i])
	}
	return ""
}

func n64(n int64) *int64 { return &n }

var ops = map[string]string{"==": "EQUAL", "!=": "NOT_EQUAL", "<": "LESS_THAN", "<=": "LESS_THAN_OR_EQUAL", ">": "GREATER_THAN",
	">=": "GREATER_THAN_OR_EQUAL", "array-contains": "ARRAY_CONTAINS", "in": "IN", "not-in": "NOT_IN", "array-contains-any": "ARRAY_CONTAINS_ANY"}

func safePath(p string) (string, error) {
	p = strings.Trim(p, "/")
	if p == "" || strings.Contains(p, "..") || strings.ContainsAny(p, "?#") {
		return "", fmt.Errorf("caminho inválido %q", p)
	}
	return p, nil
}

func (c *conn) Run(ctx context.Context, call *docs.Call, max int) (*docs.Output, error) {
	if len(call.Words) > 0 || len(call.Chain) == 0 {
		return nil, fmt.Errorf("comece com collection('…'), doc('…') ou ref('…')")
	}
	if c.rtdb != "" {
		return c.runRTDB(ctx, call, max)
	}
	head := call.Chain[0]
	switch head.Name {
	case "listCollections":
		names, err := c.listCollections(ctx, "")
		out := &docs.Output{KeyCol: "name", Docs: []docs.Obj{}}
		for _, n := range names {
			out.Docs = append(out.Docs, docs.Obj{{K: "name", V: n}})
		}
		return out, err
	case "doc":
		path, err := safePath(strArg(head, 0))
		if err != nil {
			return nil, err
		}
		if strings.Count(path, "/")%2 == 0 {
			return nil, fmt.Errorf("doc() precisa de coleção/documento (ex.: doc('clientes/abc'))")
		}
		m := lastCall(call.Chain[1:])
		switch m.Name {
		case "", "get":
			var d map[string]any
			if err := c.rest(ctx, "GET", c.docsBase()+"/"+escPath(path), nil, &d); err != nil {
				return nil, err
			}
			return &docs.Output{KeyCol: "__name__", Docs: []docs.Obj{docRow(fmt.Sprint(d["name"]), d["fields"])}}, nil
		case "listCollections":
			names, err := c.listCollections(ctx, path)
			out := &docs.Output{KeyCol: "name", Docs: []docs.Obj{}}
			for _, n := range names {
				out.Docs = append(out.Docs, docs.Obj{{K: "name", V: n}})
			}
			return out, err
		case "set", "update":
			o, ok := argAt(m, 0).(docs.Obj)
			if !ok {
				return nil, fmt.Errorf("%s() precisa de um objeto", m.Name)
			}
			u := c.docsBase() + "/" + escPath(path)
			merge := m.Name == "update"
			if mo, ok := argAt(m, 1).(docs.Obj); ok {
				if v, _ := mo.Get("merge"); v == true {
					merge = true
				}
			}
			q := url.Values{}
			if merge {
				for _, kv := range o {
					q.Add("updateMask.fieldPaths", kv.K)
				}
			}
			if m.Name == "update" {
				q.Set("currentDocument.exists", "true")
			}
			if len(q) > 0 {
				u += "?" + q.Encode()
			}
			return &docs.Output{Affected: n64(1)}, c.rest(ctx, "PATCH", u, map[string]any{"fields": objToFields(o)}, nil)
		case "delete":
			return &docs.Output{Affected: n64(1)}, c.rest(ctx, "DELETE", c.docsBase()+"/"+escPath(path), nil, nil)
		}
		return nil, fmt.Errorf("método desconhecido: .%s()", m.Name)
	case "collection", "collectionGroup":
		path, err := safePath(strArg(head, 0))
		if err != nil {
			return nil, err
		}
		if head.Name == "collection" && strings.Count(path, "/")%2 == 1 {
			return nil, fmt.Errorf("collection() precisa do caminho de uma coleção (ex.: collection('clientes'))")
		}
		if m := lastCall(call.Chain[1:]); m.Name == "add" {
			o, ok := argAt(m, 0).(docs.Obj)
			if !ok {
				return nil, fmt.Errorf("add() precisa de um objeto")
			}
			var d map[string]any
			err := c.rest(ctx, "POST", c.docsBase()+"/"+escPath(path), map[string]any{"fields": objToFields(o)}, &d)
			return &docs.Output{Affected: n64(1), Messages: []string{fmt.Sprintf("Criado: %v", d["name"])}}, err
		}
		return c.query(ctx, head.Name == "collectionGroup", path, call.Chain[1:], max)
	}
	return nil, fmt.Errorf("comece com collection('…'), collectionGroup('…'), doc('…') ou listCollections()")
}

func argAt(s docs.Seg, i int) any {
	if i < len(s.Args) {
		return s.Args[i]
	}
	return nil
}

func lastCall(segs []docs.Seg) docs.Seg {
	for i := len(segs) - 1; i >= 0; i-- {
		if segs[i].Call && segs[i].Name != "get" {
			return segs[i]
		}
	}
	return docs.Seg{}
}

func escPath(p string) string {
	parts := strings.Split(p, "/")
	for i := range parts {
		parts[i] = url.PathEscape(parts[i])
	}
	return strings.Join(parts, "/")
}

func (c *conn) query(ctx context.Context, group bool, path string, mods []docs.Seg, max int) (*docs.Output, error) {
	parent, coll := "", path
	if i := strings.LastIndex(path, "/"); i >= 0 && !group {
		parent, coll = path[:i], path[i+1:]
	}
	sq := map[string]any{"from": []any{map[string]any{"collectionId": coll, "allDescendants": group}}}
	var filters []any
	var order []any
	limit := 0
	for _, m := range mods {
		switch m.Name {
		case "where":
			op := ops[strArg(m, 1)]
			if op == "" {
				return nil, fmt.Errorf("operador desconhecido %q (use ==, !=, <, <=, >, >=, in, not-in, array-contains)", strArg(m, 1))
			}
			filters = append(filters, map[string]any{"fieldFilter": map[string]any{"field": map[string]any{"fieldPath": strArg(m, 0)}, "op": op, "value": toFS(argAt(m, 2))}})
		case "orderBy":
			dir := "ASCENDING"
			if strings.EqualFold(strArg(m, 1), "desc") {
				dir = "DESCENDING"
			}
			order = append(order, map[string]any{"field": map[string]any{"fieldPath": strArg(m, 0)}, "direction": dir})
		case "limit":
			limit, _ = strconv.Atoi(strArg(m, 0))
		case "offset":
			n, _ := strconv.Atoi(strArg(m, 0))
			sq["offset"] = n
		case "select":
			fs := []any{}
			for i := range m.Args {
				fs = append(fs, map[string]any{"fieldPath": strArg(m, i)})
			}
			sq["select"] = map[string]any{"fields": fs}
		case "get":
		default:
			return nil, fmt.Errorf("modificador desconhecido: .%s()", m.Name)
		}
	}
	if len(filters) == 1 {
		sq["where"] = filters[0]
	} else if len(filters) > 1 {
		sq["where"] = map[string]any{"compositeFilter": map[string]any{"op": "AND", "filters": filters}}
	}
	if len(order) > 0 {
		sq["orderBy"] = order
	}
	eff := max + 1
	if limit > 0 && limit < eff {
		eff = limit
	}
	sq["limit"] = eff
	u := c.docsBase()
	if parent != "" {
		u += "/" + escPath(parent)
	}
	var res []map[string]any
	if err := c.rest(ctx, "POST", u+":runQuery", map[string]any{"structuredQuery": sq}, &res); err != nil {
		return nil, err
	}
	out := &docs.Output{KeyCol: "__name__", Docs: []docs.Obj{}}
	for _, r := range res {
		d, ok := r["document"].(map[string]any)
		if !ok {
			continue
		}
		if len(out.Docs) >= max {
			out.Truncated = true
			break
		}
		out.Docs = append(out.Docs, docRow(fmt.Sprint(d["name"]), d["fields"]))
	}
	return out, nil
}

func (c *conn) listCollections(ctx context.Context, doc string) ([]string, error) {
	u := c.docsBase()
	if doc != "" {
		u += "/" + escPath(doc)
	}
	var names []string
	token := ""
	for page := 0; page < 20; page++ {
		var r struct {
			CollectionIds []string `json:"collectionIds"`
			NextPageToken string   `json:"nextPageToken"`
		}
		body := map[string]any{"pageSize": 300}
		if token != "" {
			body["pageToken"] = token
		}
		if err := c.rest(ctx, "POST", u+":listCollectionIds", body, &r); err != nil {
			return nil, err
		}
		names = append(names, r.CollectionIds...)
		if token = r.NextPageToken; token == "" {
			break
		}
	}
	sort.Strings(names)
	return names, nil
}

// ------------------------------------------------------------ Realtime Database

func jsonToDocs(v any) any {
	switch x := v.(type) {
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		o := docs.Obj{}
		for _, k := range keys {
			o = append(o, docs.KV{K: k, V: jsonToDocs(x[k])})
		}
		return o
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = jsonToDocs(e)
		}
		return out
	case json.Number:
		if n, err := x.Int64(); err == nil {
			return n
		}
		f, _ := x.Float64()
		return f
	}
	return v
}

func docsToJSON(v any) any {
	switch x := v.(type) {
	case docs.Obj:
		m := map[string]any{}
		for _, kv := range x {
			m[kv.K] = docsToJSON(kv.V)
		}
		return m
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = docsToJSON(e)
		}
		return out
	case time.Time:
		return x.UnixMilli()
	case docs.Long:
		return int64(x)
	case docs.Int32:
		return int64(x)
	}
	return v
}

func (c *conn) runRTDB(ctx context.Context, call *docs.Call, max int) (*docs.Output, error) {
	head := call.Chain[0]
	if head.Name != "ref" {
		return nil, fmt.Errorf("no Realtime Database, comece com ref('caminho')")
	}
	path := strings.Trim(strArg(head, 0), "/")
	if strings.Contains(path, "..") || strings.ContainsAny(path, "?#.$[]") {
		return nil, fmt.Errorf("caminho inválido %q", path)
	}
	u := c.rtdb + "/" + escPath(path) + ".json"
	q := url.Values{}
	limit := 0
	for _, m := range call.Chain[1:] {
		enc := func(v any) string { b, _ := json.Marshal(docsToJSON(v)); return string(b) }
		switch m.Name {
		case "orderByChild":
			q.Set("orderBy", enc(strArg(m, 0)))
		case "orderByKey":
			q.Set("orderBy", `"$key"`)
		case "orderByValue":
			q.Set("orderBy", `"$value"`)
		case "equalTo", "startAt", "endAt":
			q.Set(m.Name, enc(argAt(m, 0)))
		case "limitToFirst", "limitToLast":
			limit, _ = strconv.Atoi(strArg(m, 0))
			q.Set(m.Name, strconv.Itoa(limit))
		case "get", "once":
		case "set", "update", "push":
			method := map[string]string{"set": "PUT", "update": "PATCH", "push": "POST"}[m.Name]
			var out map[string]any
			if err := c.rest(ctx, method, u, docsToJSON(argAt(m, 0)), &out); err != nil {
				return nil, err
			}
			msg := []string{}
			if out["name"] != nil {
				msg = append(msg, fmt.Sprintf("Criado: %v", out["name"]))
			}
			return &docs.Output{Affected: n64(1), Messages: msg}, nil
		case "remove":
			return &docs.Output{Affected: n64(1)}, c.rest(ctx, "DELETE", u, nil, nil)
		default:
			return nil, fmt.Errorf("método desconhecido: .%s()", m.Name)
		}
	}
	if q.Get("orderBy") == "" && (q.Has("limitToFirst") || q.Has("limitToLast")) {
		q.Set("orderBy", `"$key"`)
	}
	if limit == 0 && q.Get("orderBy") == "" {
		q.Set("orderBy", `"$key"`)
		q.Set("limitToFirst", strconv.Itoa(max+1))
	}
	var v any
	if err := c.rest(ctx, "GET", u+"?"+q.Encode(), nil, &v); err != nil {
		return nil, err
	}
	out := &docs.Output{KeyCol: "__key__", Docs: []docs.Obj{}}
	switch x := jsonToDocs(v).(type) {
	case docs.Obj:
		for _, kv := range x {
			if len(out.Docs) >= max {
				out.Truncated = true
				break
			}
			row := docs.Obj{{K: "__key__", V: kv.K}}
			if o, ok := kv.V.(docs.Obj); ok {
				row = append(row, o...)
			} else {
				row = append(row, docs.KV{K: "value", V: kv.V})
			}
			out.Docs = append(out.Docs, row)
		}
	case nil:
	default:
		out.Docs = append(out.Docs, docs.Obj{{K: "__key__", V: path}, {K: "value", V: x}})
	}
	return out, nil
}

// ------------------------------------------------------------ catálogo e edições

func (c *conn) Databases(ctx context.Context) ([]string, error) {
	if c.rtdb != "" {
		return []string{c.rtdb}, nil
	}
	return []string{c.fsdb}, nil
}

func (c *conn) Objects(ctx context.Context) ([]engine.Object, error) {
	out := []engine.Object{}
	if c.rtdb != "" {
		var v map[string]any
		if err := c.rest(ctx, "GET", c.rtdb+"/.json?shallow=true", nil, &v); err != nil {
			return nil, err
		}
		keys := make([]string, 0, len(v))
		for k := range v {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			out = append(out, engine.Object{Schema: "", Name: k, Kind: "table"})
		}
		return out, nil
	}
	names, err := c.listCollections(ctx, "")
	for _, n := range names {
		out = append(out, engine.Object{Schema: "", Name: n, Kind: "table"})
	}
	return out, err
}

func (c *conn) Table(ctx context.Context, schema, name string) (*engine.TableInfo, error) {
	key := "__name__"
	var res *docs.Output
	var err error
	if c.rtdb != "" {
		key = "__key__"
		res, err = c.runRTDB(ctx, &docs.Call{Chain: []docs.Seg{{Name: "ref", Call: true, Args: []any{name}}, {Name: "limitToFirst", Call: true, Args: []any{int64(200)}}}}, 200)
	} else {
		res, err = c.query(ctx, false, name, nil, 200)
	}
	if err != nil {
		return nil, err
	}
	return &engine.TableInfo{Schema: schema, Name: name, Columns: docs.Columns(res.Docs, key), FKs: []engine.ForeignKey{}, Indexes: []engine.Index{}}, nil
}

func (c *conn) Exists(ctx context.Context, ch engine.Change) error {
	coll, err := safePath(ch.Table)
	if err != nil {
		return err
	}
	if c.rtdb != "" {
		var cur any
		key := fmt.Sprint(ch.Key["__key__"])
		if err := c.rest(ctx, "GET", c.rtdb+"/"+escPath(coll)+"/"+url.PathEscape(key)+".json?shallow=true", nil, &cur); err != nil || cur == nil {
			return fmt.Errorf("o registro %q não existe mais", key)
		}
		return nil
	}
	id := fmt.Sprint(ch.Key["__name__"])
	path := coll + "/" + id
	if p, ok := ch.Key["__path__"]; ok && p != nil {
		path = fmt.Sprint(p)
	}
	var d map[string]any
	if err := c.rest(ctx, "GET", c.docsBase()+"/"+escPath(path)+"?mask.fieldPaths=__name__", nil, &d); err != nil {
		return fmt.Errorf("o documento %q não existe mais", id)
	}
	return nil
}

func (c *conn) Apply(ctx context.Context, ch engine.Change) (int64, string, error) {
	coll, err := safePath(ch.Table)
	if err != nil {
		return 0, "", err
	}
	if c.rtdb != "" {
		key := fmt.Sprint(ch.Key["__key__"])
		base := c.rtdb + "/" + escPath(coll)
		switch ch.Op {
		case "delete":
			return 1, "", c.rest(ctx, "DELETE", base+"/"+url.PathEscape(key)+".json", nil, nil)
		case "insert":
			vals := c.coerce(ch.Values, nil)
			if k, ok := ch.Values["__key__"]; ok && k != nil {
				delete(vals, "__key__")
				return 1, "", c.rest(ctx, "PUT", base+"/"+url.PathEscape(fmt.Sprint(k))+".json", vals, nil)
			}
			return 1, "", c.rest(ctx, "POST", base+".json", vals, nil)
		}
		var cur any
		if err := c.rest(ctx, "GET", base+"/"+url.PathEscape(key)+".json", nil, &cur); err != nil || cur == nil {
			return 0, "", fmt.Errorf("o registro %q não existe mais", key)
		}
		like, _ := jsonToDocs(cur).(docs.Obj)
		return 1, "", c.rest(ctx, "PATCH", base+"/"+url.PathEscape(key)+".json", c.coerce(ch.Values, like), nil)
	}
	id := fmt.Sprint(ch.Key["__name__"])
	if p, ok := ch.Key["__path__"]; ok && p != nil {
		coll, id = fmt.Sprint(p)[:strings.LastIndex(fmt.Sprint(p), "/")], fmt.Sprint(p)[strings.LastIndex(fmt.Sprint(p), "/")+1:]
	}
	u := c.docsBase() + "/" + escPath(coll) + "/" + url.PathEscape(id)
	switch ch.Op {
	case "delete":
		return 1, "", c.rest(ctx, "DELETE", u+"?currentDocument.exists=true", nil, nil)
	case "insert":
		o := docs.Obj{}
		for k, v := range ch.Values {
			if k != "__name__" && k != "__path__" {
				o = append(o, docs.KV{K: k, V: docs.Coerce(v, nil)})
			}
		}
		target := c.docsBase() + "/" + escPath(coll)
		if n, ok := ch.Values["__name__"]; ok && n != nil {
			target += "?documentId=" + url.QueryEscape(fmt.Sprint(n))
		}
		return 1, "", c.rest(ctx, "POST", target, map[string]any{"fields": objToFields(o)}, nil)
	}
	var d map[string]any
	if err := c.rest(ctx, "GET", u, nil, &d); err != nil {
		return 0, "", fmt.Errorf("o documento %q não existe mais", id)
	}
	cur := fieldsToObj(d["fields"])
	o := docs.Obj{}
	q := url.Values{}
	for k, v := range ch.Values {
		like, _ := cur.Get(k)
		o = append(o, docs.KV{K: k, V: docs.Coerce(v, like)})
		q.Add("updateMask.fieldPaths", k)
	}
	q.Set("currentDocument.exists", "true")
	return 1, "", c.rest(ctx, "PATCH", u+"?"+q.Encode(), map[string]any{"fields": objToFields(o)}, nil)
}

func (c *conn) coerce(vals map[string]any, like docs.Obj) map[string]any {
	out := map[string]any{}
	for k, v := range vals {
		l, _ := like.Get(k)
		out[k] = docsToJSON(docs.Coerce(v, l))
	}
	return out
}

func (c *conn) Describe(ch engine.Change) string {
	vals := docs.Obj{}
	for k, v := range ch.Values {
		vals = append(vals, docs.KV{K: k, V: v})
	}
	sort.Slice(vals, func(i, j int) bool { return vals[i].K < vals[j].K })
	if c.rtdb != "" {
		ref := fmt.Sprintf("ref(%q)", ch.Table+"/"+fmt.Sprint(ch.Key["__key__"]))
		switch ch.Op {
		case "delete":
			return ref + ".remove()"
		case "insert":
			return fmt.Sprintf("ref(%q).push(%s)", ch.Table, docs.JSON(vals))
		}
		return ref + ".update(" + docs.JSON(vals) + ")"
	}
	d := fmt.Sprintf("doc(%q)", ch.Table+"/"+fmt.Sprint(ch.Key["__name__"]))
	switch ch.Op {
	case "delete":
		return d + ".delete()"
	case "insert":
		return fmt.Sprintf("collection(%q).add(%s)", ch.Table, docs.JSON(vals))
	}
	return d + ".update(" + docs.JSON(vals) + ")"
}
