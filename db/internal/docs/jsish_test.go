package docs

import (
	"testing"
	"time"
)

func TestParse(t *testing.T) {
	c, err := ParseCall(`db.clientes.find({cidade: "Recife", 'idade': {$gte: 18}, _id: ObjectId("650000000000000000000001"), nome: /^an/i, criado: {$lt: ISODate("2025-01-01")}}, {nome: 1}).sort({nome: -1, _id: 1}).limit(5)`, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(c.Chain) != 5 || c.Chain[2].Name != "find" || c.Chain[4].Name != "limit" {
		t.Fatalf("cadeia: %+v", c.Chain)
	}
	f := c.Chain[2].Args[0].(Obj)
	if f[0].K != "cidade" || f[1].K != "idade" || f[2].V.(OID) != "650000000000000000000001" {
		t.Fatalf("filtro: %+v", f)
	}
	if r := f[3].V.(Regex); r.Pattern != "^an" || r.Flags != "i" {
		t.Fatalf("regex: %+v", r)
	}
	if _, ok := f[4].V.(Obj)[0].V.(time.Time); !ok {
		t.Fatal("data")
	}
	sort := c.Chain[3].Args[0].(Obj)
	if sort[0].K != "nome" || sort[0].V.(int64) != -1 {
		t.Fatalf("sort perdeu a ordem: %+v", sort)
	}
	c, err = ParseCall("collection('clientes').where('cidade', '==', 'Recife').orderBy('nome', 'desc')", 0)
	if err != nil || c.Chain[1].Args[2] != "Recife" {
		t.Fatalf("firestore: %v %+v", err, c)
	}
	if _, err := ParseCall("db.x.find({a: })", 0); err == nil {
		t.Fatal("deveria recusar")
	}
}

func TestSplit(t *testing.T) {
	got := SplitCalls("db.a.find({x: ';'})\n  .limit(2)\ndb.b.count()\n\n// comentário\nshow collections; use teste")
	if len(got) != 4 {
		t.Fatalf("esperava 4, veio %d: %+v", len(got), got)
	}
}
