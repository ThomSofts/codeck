// Package mongo: MongoDB (e Atlas, por mongodb+srv://), pelo driver oficial. Comandos no estilo do mongosh:
//
//	db.clientes.find({cidade: "Recife"}, {nome: 1}).sort({nome: 1}).limit(50)
//	db.pedidos.aggregate([{$group: {_id: "$status", total: {$sum: "$valor"}}}])
//	db.clientes.updateOne({_id: ObjectId("…")}, {$set: {ativo: false}})
//	show collections · show dbs · use outro_banco
package mongo

import (
	"context"
	"fmt"
	"strings"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
	mg "go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"codeck/db/internal/docs"
	"codeck/db/internal/engine"
	"codeck/db/internal/proto"
)

type Driver struct{}

func (Driver) Engine() string { return "mongodb" }

var writes = map[string]bool{"insertOne": true, "insertMany": true, "updateOne": true, "updateMany": true, "replaceOne": true,
	"deleteOne": true, "deleteMany": true, "drop": true, "dropDatabase": true, "createIndex": true, "createIndexes": true, "dropIndex": true,
	"dropIndexes": true, "renameCollection": true, "findOneAndUpdate": true, "findOneAndReplace": true, "findOneAndDelete": true,
	"bulkWrite": true, "createCollection": true, "runCommand": true}

func (Driver) Analyze(c *docs.Call) engine.Analysis {
	a := engine.Analysis{}
	if len(c.Words) > 0 {
		a.First = strings.ToUpper(c.Words[0])
		return a
	}
	for _, s := range c.Chain {
		if !s.Call {
			continue
		}
		if writes[s.Name] {
			a.Write, a.First = true, s.Name
			a.Exec = s.Name == "runCommand"
			a.Drop = s.Name == "drop" || s.Name == "dropDatabase"
			if (s.Name == "updateMany" || s.Name == "deleteMany") && emptyFilter(s.Args) {
				a.NoWhere = true
				a.Drop = a.Drop || s.Name == "deleteMany"
			}
		}
		if s.Name == "aggregate" && len(s.Args) > 0 {
			if st, ok := s.Args[0].([]any); ok && len(st) > 0 {
				if o, ok := st[len(st)-1].(docs.Obj); ok && len(o) > 0 && (o[0].K == "$out" || o[0].K == "$merge") {
					a.Write, a.First = true, "aggregate "+o[0].K
				}
			}
		}
		if a.First == "" {
			a.First = s.Name
		}
	}
	return a
}

func emptyFilter(args []any) bool {
	if len(args) == 0 {
		return true
	}
	o, ok := args[0].(docs.Obj)
	return ok && len(o) == 0
}

type conn struct {
	c  *mg.Client
	db string
}

func (Driver) Open(ctx context.Context, p engine.ConnParams) (docs.Conn, string, *engine.CertInfo, error) {
	uri := strings.TrimSpace(p.Host)
	if !strings.HasPrefix(uri, "mongodb://") && !strings.HasPrefix(uri, "mongodb+srv://") {
		port := p.Port
		if port == 0 {
			port = 27017
		}
		uri = fmt.Sprintf("mongodb://%s:%d/", p.Host, port)
	}
	opts := options.Client().ApplyURI(uri).SetAppName("Codeck").SetServerSelectionTimeout(15 * time.Second).SetConnectTimeout(15 * time.Second)
	cap := &engine.Capture{}
	off, err := p.TLS.Off()
	if err != nil {
		return nil, "", nil, err
	}
	if !off {
		host := "" // cada nó do cluster tem o próprio nome (o driver põe no SNI)
		if h := p.Options["tlsHost"]; h != "" {
			host = h // pelo túnel SSH: o nome do servidor real
		}
		cfg := p.TLS.Config(host, cap)
		cfg.ServerName = host
		opts.SetTLSConfig(cfg)
	}
	if p.User != "" {
		src := p.Options["authSource"]
		if src == "" {
			src = "admin"
		}
		opts.SetAuth(options.Credential{Username: p.User, Password: p.Password, AuthSource: src, PasswordSet: p.Password != ""})
	}
	cl, err := mg.Connect(opts)
	if err != nil {
		return nil, "", nil, err
	}
	if err := cl.Ping(ctx, nil); err != nil {
		cl.Disconnect(context.Background())
		if ce := engine.CertError(cap); ce != nil {
			return nil, "", nil, ce
		}
		if ctx.Err() != nil || strings.Contains(err.Error(), "server selection") {
			return nil, "", nil, proto.Fail("timeout", "O servidor não respondeu (firewall, VPN desligada, IP não liberado no Atlas?) — %v", err)
		}
		return nil, "", nil, err
	}
	db := p.Database
	if db == "" {
		db = "test"
	}
	var info bson.M
	cl.Database("admin").RunCommand(ctx, bson.D{{Key: "buildInfo", Value: 1}}).Decode(&info)
	return &conn{c: cl, db: db}, fmt.Sprintf("MongoDB %v", info["version"]), cap.Get(), nil
}

func (c *conn) Close() { c.c.Disconnect(context.Background()) }

// ------------------------------------------------------------ conversão docs ↔ bson

func toBSON(v any) (any, error) {
	switch x := v.(type) {
	case docs.Obj:
		d := bson.D{}
		for _, kv := range x {
			bv, err := toBSON(kv.V)
			if err != nil {
				return nil, err
			}
			d = append(d, bson.E{Key: kv.K, Value: bv})
		}
		return d, nil
	case []any:
		a := bson.A{}
		for _, e := range x {
			bv, err := toBSON(e)
			if err != nil {
				return nil, err
			}
			a = append(a, bv)
		}
		return a, nil
	case docs.OID:
		if x == "" {
			return bson.NewObjectID(), nil
		}
		return bson.ObjectIDFromHex(string(x))
	case time.Time:
		return bson.NewDateTimeFromTime(x), nil
	case docs.Regex:
		return bson.Regex{Pattern: x.Pattern, Options: x.Flags}, nil
	case docs.Long:
		return int64(x), nil
	case docs.Int32:
		return int32(x), nil
	case docs.Decimal:
		return bson.ParseDecimal128(string(x))
	case docs.UUID:
		h := strings.ReplaceAll(string(x), "-", "")
		b := make([]byte, len(h)/2)
		if _, err := fmt.Sscanf(h, "%x", &b); err != nil {
			return nil, fmt.Errorf("UUID inválido")
		}
		return bson.Binary{Subtype: 4, Data: b}, nil
	}
	return v, nil
}

func fromBSON(v any) any {
	switch x := v.(type) {
	case bson.D:
		o := docs.Obj{}
		for _, e := range x {
			o = append(o, docs.KV{K: e.Key, V: fromBSON(e.Value)})
		}
		return o
	case bson.A:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = fromBSON(e)
		}
		return out
	case bson.ObjectID:
		return docs.OID(x.Hex())
	case bson.DateTime:
		return x.Time()
	case bson.Decimal128:
		return docs.Decimal(x.String())
	case bson.Binary:
		if x.Subtype == 4 && len(x.Data) == 16 {
			h := fmt.Sprintf("%x", x.Data)
			return h[0:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:]
		}
		return x.Data
	case bson.Regex:
		return docs.Regex{Pattern: x.Pattern, Flags: x.Options}
	case bson.Timestamp:
		return fmt.Sprintf("Timestamp(%d, %d)", x.T, x.I)
	case int32, int64, float64, string, bool, nil:
		return x
	}
	return fmt.Sprint(v)
}

func arg(s docs.Seg, i int) any {
	if i < len(s.Args) {
		return s.Args[i]
	}
	return nil
}

func bsonArg(s docs.Seg, i int, def any) (any, error) {
	v := arg(s, i)
	if v == nil {
		return def, nil
	}
	return toBSON(v)
}

func readAll(ctx context.Context, cur *mg.Cursor, max int) ([]docs.Obj, bool, error) {
	defer cur.Close(ctx)
	out := []docs.Obj{}
	for cur.Next(ctx) {
		if len(out) >= max {
			return out, true, nil
		}
		var d bson.D
		if err := cur.Decode(&d); err != nil {
			return out, false, err
		}
		out = append(out, fromBSON(d).(docs.Obj))
	}
	return out, false, cur.Err()
}

func n64(n int64) *int64 { return &n }

// ------------------------------------------------------------ comandos

func (c *conn) Run(ctx context.Context, call *docs.Call, max int) (*docs.Output, error) {
	if w := call.Words; len(w) > 0 {
		switch {
		case w[0] == "use" && len(w) > 1:
			c.db = strings.Trim(w[1], ";")
			return &docs.Output{Messages: []string{"Banco atual: " + c.db}}, nil
		case w[0] == "show" && len(w) > 1 && (w[1] == "dbs" || w[1] == "databases"):
			names, err := c.c.ListDatabaseNames(ctx, bson.D{})
			return list("name", names), err
		case w[0] == "show" && len(w) > 1 && w[1] == "collections":
			names, err := c.c.Database(c.db).ListCollectionNames(ctx, bson.D{})
			return list("name", names), err
		}
		return nil, fmt.Errorf("comando desconhecido: %s", strings.Join(w, " "))
	}
	ch := call.Chain
	if len(ch) < 2 || ch[0].Name != "db" || ch[0].Call {
		return nil, fmt.Errorf("comece com db. (ex.: db.clientes.find())")
	}
	db := c.c.Database(c.db)
	i := 1
	var coll string
	switch {
	case ch[1].Call && ch[1].Name == "getCollection":
		coll, i = fmt.Sprint(arg(ch[1], 0)), 2
	case ch[1].Call:
		return c.dbMethod(ctx, db, ch[1])
	default:
		coll, i = ch[1].Name, 2
	}
	if i >= len(ch) || !ch[i].Call {
		return nil, fmt.Errorf("faltou o método: db.%s.find(), .aggregate(), .insertOne()…", coll)
	}
	return c.collMethod(ctx, db.Collection(coll), ch[i], ch[i+1:], max)
}

func list(col string, names []string) *docs.Output {
	out := &docs.Output{KeyCol: col, Docs: []docs.Obj{}}
	for _, n := range names {
		out.Docs = append(out.Docs, docs.Obj{{K: col, V: n}})
	}
	return out
}

func (c *conn) dbMethod(ctx context.Context, db *mg.Database, s docs.Seg) (*docs.Output, error) {
	switch s.Name {
	case "getCollectionNames":
		names, err := db.ListCollectionNames(ctx, bson.D{})
		return list("name", names), err
	case "runCommand", "stats":
		cmd, err := bsonArg(s, 0, bson.D{{Key: "dbStats", Value: 1}})
		if err != nil {
			return nil, err
		}
		var d bson.D
		if err := db.RunCommand(ctx, cmd).Decode(&d); err != nil {
			return nil, err
		}
		return &docs.Output{Docs: []docs.Obj{fromBSON(d).(docs.Obj)}}, nil
	case "dropDatabase":
		return &docs.Output{Messages: []string{"Banco apagado: " + db.Name()}}, db.Drop(ctx)
	}
	return nil, fmt.Errorf("método desconhecido: db.%s()", s.Name)
}

func (c *conn) collMethod(ctx context.Context, coll *mg.Collection, m docs.Seg, mods []docs.Seg, max int) (*docs.Output, error) {
	switch m.Name {
	case "find", "findOne":
		filter, err := bsonArg(m, 0, bson.D{})
		if err != nil {
			return nil, err
		}
		fo := options.Find()
		limit := int64(0)
		if p := arg(m, 1); p != nil {
			pv, err := toBSON(p)
			if err != nil {
				return nil, err
			}
			fo.SetProjection(pv)
		}
		for _, md := range mods {
			v, err := bsonArg(md, 0, nil)
			if err != nil {
				return nil, err
			}
			switch md.Name {
			case "sort":
				fo.SetSort(v)
			case "limit":
				limit = toInt(v)
			case "skip":
				fo.SetSkip(toInt(v))
			case "project", "projection":
				fo.SetProjection(v)
			case "toArray", "pretty", "count":
			default:
				return nil, fmt.Errorf("modificador desconhecido: .%s()", md.Name)
			}
		}
		if m.Name == "findOne" {
			limit = 1
		}
		eff := int64(max) + 1
		if limit > 0 && limit < eff {
			eff = limit
		}
		fo.SetLimit(eff)
		cur, err := coll.Find(ctx, filter, fo)
		if err != nil {
			return nil, err
		}
		ds, trunc, err := readAll(ctx, cur, max)
		out := &docs.Output{Docs: ds, KeyCol: "_id", Truncated: trunc}
		if trunc { // quantos são, se der para contar rápido
			cctx, cancel := context.WithTimeout(ctx, 3*time.Second)
			if n, e := coll.CountDocuments(cctx, filter); e == nil {
				out.Total = &n
			}
			cancel()
		}
		return out, err
	case "aggregate":
		pipe, err := bsonArg(m, 0, bson.A{})
		if err != nil {
			return nil, err
		}
		cur, err := coll.Aggregate(ctx, pipe)
		if err != nil {
			return nil, err
		}
		ds, trunc, err := readAll(ctx, cur, max)
		return &docs.Output{Docs: ds, KeyCol: "_id", Truncated: trunc}, err
	case "countDocuments", "count":
		filter, err := bsonArg(m, 0, bson.D{})
		if err != nil {
			return nil, err
		}
		n, err := coll.CountDocuments(ctx, filter)
		return &docs.Output{Docs: []docs.Obj{{{K: "count", V: n}}}}, err
	case "estimatedDocumentCount":
		n, err := coll.EstimatedDocumentCount(ctx)
		return &docs.Output{Docs: []docs.Obj{{{K: "count", V: n}}}}, err
	case "distinct":
		filter, err := bsonArg(m, 1, bson.D{})
		if err != nil {
			return nil, err
		}
		var vals bson.A
		if err := coll.Distinct(ctx, fmt.Sprint(arg(m, 0)), filter).Decode(&vals); err != nil {
			return nil, err
		}
		out := &docs.Output{KeyCol: "value", Docs: []docs.Obj{}}
		for _, v := range vals {
			out.Docs = append(out.Docs, docs.Obj{{K: "value", V: fromBSON(v)}})
		}
		return out, nil
	case "insertOne":
		d, err := bsonArg(m, 0, nil)
		if err != nil || d == nil {
			return nil, fmt.Errorf("insertOne precisa de um documento")
		}
		r, err := coll.InsertOne(ctx, d)
		if err != nil {
			return nil, err
		}
		return &docs.Output{Affected: n64(1), Messages: []string{fmt.Sprintf("Inserido: %v", fromBSON(r.InsertedID))}}, nil
	case "insertMany":
		d, err := bsonArg(m, 0, nil)
		arr, ok := d.(bson.A)
		if err != nil || !ok {
			return nil, fmt.Errorf("insertMany precisa de uma lista de documentos")
		}
		r, err := coll.InsertMany(ctx, []any(arr))
		if err != nil {
			return nil, err
		}
		return &docs.Output{Affected: n64(int64(len(r.InsertedIDs)))}, nil
	case "updateOne", "updateMany", "replaceOne":
		filter, err := bsonArg(m, 0, bson.D{})
		if err != nil {
			return nil, err
		}
		upd, err := bsonArg(m, 1, nil)
		if err != nil || upd == nil {
			return nil, fmt.Errorf("%s precisa do filtro e da alteração", m.Name)
		}
		upsert := false
		if o, ok := arg(m, 2).(docs.Obj); ok {
			if v, ok := o.Get("upsert"); ok {
				upsert = v == true
			}
		}
		var r *mg.UpdateResult
		switch m.Name {
		case "updateOne":
			r, err = coll.UpdateOne(ctx, filter, upd, options.UpdateOne().SetUpsert(upsert))
		case "updateMany":
			r, err = coll.UpdateMany(ctx, filter, upd, options.UpdateMany().SetUpsert(upsert))
		default:
			r, err = coll.ReplaceOne(ctx, filter, upd, options.Replace().SetUpsert(upsert))
		}
		if err != nil {
			return nil, err
		}
		msg := fmt.Sprintf("%d encontrado(s), %d alterado(s)", r.MatchedCount, r.ModifiedCount)
		if r.UpsertedID != nil {
			msg += fmt.Sprintf(", criado %v", fromBSON(r.UpsertedID))
		}
		return &docs.Output{Affected: n64(r.ModifiedCount + r.UpsertedCount), Messages: []string{msg}}, nil
	case "deleteOne", "deleteMany":
		filter, err := bsonArg(m, 0, bson.D{})
		if err != nil {
			return nil, err
		}
		var r *mg.DeleteResult
		if m.Name == "deleteOne" {
			r, err = coll.DeleteOne(ctx, filter)
		} else {
			r, err = coll.DeleteMany(ctx, filter)
		}
		if err != nil {
			return nil, err
		}
		return &docs.Output{Affected: n64(r.DeletedCount)}, nil
	case "drop":
		return &docs.Output{Messages: []string{"Coleção apagada: " + coll.Name()}}, coll.Drop(ctx)
	case "createIndex":
		keys, err := bsonArg(m, 0, nil)
		if err != nil || keys == nil {
			return nil, fmt.Errorf("createIndex precisa das chaves")
		}
		io := options.Index()
		if o, ok := arg(m, 1).(docs.Obj); ok {
			if v, ok := o.Get("unique"); ok {
				io.SetUnique(v == true)
			}
			if v, ok := o.Get("name"); ok {
				io.SetName(fmt.Sprint(v))
			}
		}
		name, err := coll.Indexes().CreateOne(ctx, mg.IndexModel{Keys: keys, Options: io})
		return &docs.Output{Messages: []string{"Índice criado: " + name}}, err
	case "getIndexes", "indexes":
		cur, err := coll.Indexes().List(ctx)
		if err != nil {
			return nil, err
		}
		ds, _, err := readAll(ctx, cur, 1000)
		return &docs.Output{Docs: ds, KeyCol: "name"}, err
	}
	return nil, fmt.Errorf("método desconhecido: .%s()", m.Name)
}

func toInt(v any) int64 {
	switch x := v.(type) {
	case int64:
		return x
	case int32:
		return int64(x)
	case float64:
		return int64(x)
	}
	return 0
}

// ------------------------------------------------------------ catálogo

func (c *conn) Databases(ctx context.Context) ([]string, error) {
	names, err := c.c.ListDatabaseNames(ctx, bson.D{})
	if err != nil {
		return []string{c.db}, nil // sem permissão para listar: só o banco da conexão
	}
	return names, nil
}

func (c *conn) Objects(ctx context.Context) ([]engine.Object, error) {
	specs, err := c.c.Database(c.db).ListCollectionSpecifications(ctx, bson.D{})
	if err != nil {
		return nil, err
	}
	out := []engine.Object{}
	for _, s := range specs {
		if strings.HasPrefix(s.Name, "system.") {
			continue
		}
		k := "table"
		if s.Type == "view" {
			k = "view"
		}
		out = append(out, engine.Object{Schema: c.db, Name: s.Name, Kind: k})
	}
	return out, nil
}

func (c *conn) Table(ctx context.Context, schema, name string) (*engine.TableInfo, error) {
	if schema == "" {
		schema = c.db
	}
	coll := c.c.Database(schema).Collection(name)
	cur, err := coll.Aggregate(ctx, bson.A{bson.D{{Key: "$sample", Value: bson.D{{Key: "size", Value: 200}}}}})
	if err != nil {
		return nil, err
	}
	ds, _, err := readAll(ctx, cur, 200)
	if err != nil {
		return nil, err
	}
	t := &engine.TableInfo{Schema: schema, Name: name, Columns: docs.Columns(ds, "_id"), FKs: []engine.ForeignKey{}, Indexes: []engine.Index{}}
	if len(t.Columns) == 0 {
		t.Columns = []engine.Column{{Name: "_id", Type: "objectid", PK: 1}}
	}
	if specs, err := coll.Indexes().ListSpecifications(ctx); err == nil {
		for _, s := range specs {
			var keys bson.D
			bson.Unmarshal(s.KeysDocument, &keys)
			ix := engine.Index{Name: s.Name, Unique: s.Unique != nil && *s.Unique, Primary: s.Name == "_id_"}
			for _, k := range keys {
				ix.Columns = append(ix.Columns, k.Key)
			}
			t.Indexes = append(t.Indexes, ix)
		}
	}
	return t, nil
}

// ------------------------------------------------------------ edições da grade

func (c *conn) find(ctx context.Context, coll *mg.Collection, key any) (bson.D, bson.D, error) {
	try := []any{key}
	if s, ok := key.(string); ok && len(s) == 24 {
		if oid, err := bson.ObjectIDFromHex(s); err == nil {
			try = []any{oid, s}
		}
	}
	for _, k := range try {
		var doc bson.D
		f := bson.D{{Key: "_id", Value: k}}
		if err := coll.FindOne(ctx, f).Decode(&doc); err == nil {
			return f, doc, nil
		}
	}
	return nil, nil, fmt.Errorf("documento não encontrado (_id %v) — ele mudou ou foi apagado", key)
}

func (c *conn) Exists(ctx context.Context, ch engine.Change) error {
	db := ch.Schema
	if db == "" {
		db = c.db
	}
	_, _, err := c.find(ctx, c.c.Database(db).Collection(ch.Table), ch.Key["_id"])
	return err
}

func (c *conn) Apply(ctx context.Context, ch engine.Change) (int64, string, error) {
	db := ch.Schema
	if db == "" {
		db = c.db
	}
	coll := c.c.Database(db).Collection(ch.Table)
	switch ch.Op {
	case "insert":
		d := bson.D{}
		for _, kv := range sortedValues(ch.Values) {
			v := docs.Coerce(kv.V, nil)
			if kv.K == "_id" {
				if s, ok := v.(string); ok && len(s) == 24 {
					v = docs.OID(s)
				}
			}
			bv, err := toBSON(v)
			if err != nil {
				return 0, "", err
			}
			d = append(d, bson.E{Key: kv.K, Value: bv})
		}
		_, err := coll.InsertOne(ctx, d)
		return 1, "", err
	case "update", "delete":
		filter, doc, err := c.find(ctx, coll, ch.Key["_id"])
		if err != nil {
			return 0, "", err
		}
		if ch.Op == "delete" {
			r, err := coll.DeleteOne(ctx, filter)
			if err != nil {
				return 0, "", err
			}
			return r.DeletedCount, "", nil
		}
		cur := fromBSON(doc).(docs.Obj)
		set := bson.D{}
		for _, kv := range sortedValues(ch.Values) {
			like, _ := cur.Get(kv.K)
			bv, err := toBSON(docs.Coerce(kv.V, like))
			if err != nil {
				return 0, "", err
			}
			set = append(set, bson.E{Key: kv.K, Value: bv})
		}
		r, err := coll.UpdateOne(ctx, filter, bson.D{{Key: "$set", Value: set}})
		if err != nil {
			return 0, "", err
		}
		if r.MatchedCount != 1 {
			return 0, "", fmt.Errorf("o documento não foi encontrado na hora de gravar")
		}
		return 1, "", nil
	}
	return 0, "", fmt.Errorf("operação desconhecida %q", ch.Op)
}

func sortedValues(m map[string]any) docs.Obj {
	o := docs.Obj{}
	for k, v := range m {
		o = append(o, docs.KV{K: k, V: v})
	}
	for i := 1; i < len(o); i++ {
		for j := i; j > 0 && o[j].K < o[j-1].K; j-- {
			o[j], o[j-1] = o[j-1], o[j]
		}
	}
	return o
}

func (c *conn) Describe(ch engine.Change) string {
	id := ch.Key["_id"]
	idS := fmt.Sprintf("%q", fmt.Sprint(id))
	if s, ok := id.(string); ok && len(s) == 24 {
		idS = fmt.Sprintf("ObjectId(%q)", s)
	}
	switch ch.Op {
	case "insert":
		return fmt.Sprintf("db.%s.insertOne(%s)", ch.Table, docs.JSON(sortedValues(ch.Values)))
	case "delete":
		return fmt.Sprintf("db.%s.deleteOne({_id: %s})", ch.Table, idS)
	}
	return fmt.Sprintf("db.%s.updateOne({_id: %s}, {$set: %s})", ch.Table, idS, docs.JSON(sortedValues(ch.Values)))
}
