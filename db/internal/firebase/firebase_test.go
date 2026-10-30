package firebase

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"codeck/db/internal/docs"
)

func TestValues(t *testing.T) {
	in := docs.Obj{{K: "nome", V: "Ana"}, {K: "n", V: int64(3)}, {K: "f", V: 1.5}, {K: "ok", V: true}, {K: "nada", V: nil},
		{K: "quando", V: time.Date(2025, 1, 2, 3, 4, 5, 0, time.UTC)}, {K: "tags", V: []any{"a", int64(2)}}, {K: "end", V: docs.Obj{{K: "uf", V: "PE"}}}}
	raw, _ := json.Marshal(map[string]any{"fields": objToFields(in)})
	d := json.NewDecoder(strings.NewReader(string(raw)))
	d.UseNumber()
	var back map[string]any
	d.Decode(&back)
	row := docRow("projects/p/databases/(default)/documents/clientes/abc", back["fields"])
	got := docs.JSON(row)
	want := `{"__name__":"abc","end":{"uf":"PE"},"f":1.5,"n":3,"nada":null,"nome":"Ana","ok":true,"quando":"2025-01-02T03:04:05Z","tags":["a",2]}`
	if got != want {
		t.Fatalf("ida e volta:\n%s\n%s", got, want)
	}
}

func TestAnalyzeAndHosts(t *testing.T) {
	for src, write := range map[string]bool{"collection('a').where('x', '==', 1)": false, "doc('a/b').update({x: 1})": true,
		"ref('a').remove()": true, "collection('a').add({x: 1})": true, "ref('a').orderByChild('x').limitToFirst(2)": false} {
		c, err := docs.ParseCall(src, 0)
		if err != nil {
			t.Fatal(src, err)
		}
		if a := (Driver{}).Analyze(c); a.Write != write {
			t.Errorf("%s: write=%v", src, a.Write)
		}
	}
	for u, ok := range map[string]bool{"https://firestore.googleapis.com/v1/x": true, "https://meu-app.firebaseio.com/a.json": true,
		"https://x.southamerica-east1.firebasedatabase.app/a.json": true, "http://firestore.googleapis.com/": false,
		"https://firebaseio.com.evil.com/": false, "https://evil.com/?x=firebaseio.com": false} {
		if allowed(u) != ok {
			t.Errorf("allowed(%s) = %v", u, !ok)
		}
	}
	if _, err := safePath("a/../b"); err == nil {
		t.Error("caminho com .. aceito")
	}
}
