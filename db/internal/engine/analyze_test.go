package engine

import "testing"

func TestAnalyze(t *testing.T) {
	cases := []struct {
		sql                          string
		style                        SplitStyle
		write, tx, noWhere, drop, ex bool
	}{
		{"SELECT REPLACE(nome, 'a', 'b') FROM t WHERE x = 'UPDATE'", SplitSemicolon, false, false, false, false, false},
		{"select * from t for update", SplitSemicolon, false, false, false, false, false},
		{"UPDATE t SET a = 1", SplitSemicolon, true, false, true, false, false},
		{"update t set a = 1 where id = 2", SplitSemicolon, true, false, false, false, false},
		{"WITH x AS (SELECT 1) DELETE FROM t", SplitSemicolon, true, false, true, false, false},
		{"commit", SplitSemicolon, false, true, false, false, false},
		{"END", SplitSemicolon, false, true, false, false, false},
		{"SELECT CASE WHEN a THEN 1 END FROM t", SplitSemicolon, false, false, false, false, false},
		{"SELECT 1\nCOMMIT\nUPDATE t SET a=1 WHERE id=1", SplitGo, true, true, false, false, false},
		{"IF 1=1 BEGIN SELECT 1 END", SplitGo, false, false, false, false, false},
		{"BEGIN TRAN; DELETE FROM t WHERE id=1", SplitGo, true, true, false, false, false},
		{"EXEC dbo.limpa", SplitGo, true, false, false, false, true},
		{"SELECT * INTO copia FROM t", SplitGo, true, false, false, false, false},
		{"DROP TABLE t", SplitSemicolon, true, false, false, true, false},
		{"-- UPDATE t\nSELECT 1 /* DELETE */", SplitSemicolon, false, false, false, false, false},
		{"SELECT [update], \"delete\" FROM t", SplitGo, false, false, false, false, false},
		{"CREATE TRIGGER tr AFTER UPDATE ON t BEGIN UPDATE x SET a=1; END", SplitSemicolon, true, false, false, false, false},
		{"SELECT nome FROM dbo.update_log", SplitGo, false, false, false, false, false},
		{"PRAGMA wal_checkpoint(TRUNCATE)", SplitSemicolon, false, false, false, false, false},
		{"PRAGMA user_version = 3", SplitSemicolon, true, false, false, false, false},
	}
	for _, c := range cases {
		var w, tx, nw, dr, ex bool
		for _, a := range Analyze(c.sql, c.style) {
			w, tx, nw, dr, ex = w || a.Write, tx || a.TxControl, nw || a.NoWhere, dr || a.Drop, ex || a.Exec
		}
		if w != c.write || tx != c.tx || nw != c.noWhere || dr != c.drop || ex != c.ex {
			t.Errorf("%q: write=%v tx=%v noWhere=%v drop=%v exec=%v", c.sql, w, tx, nw, dr, ex)
		}
	}
}

func TestSplit(t *testing.T) {
	got := Split("select 1; select ';'; -- ; comentário\nselect $$a;b$$; ", SplitSemicolon)
	if len(got) != 3 {
		t.Fatalf("esperava 3 comandos, veio %d: %+v", len(got), got)
	}
	got = Split("select 1\nGO\nselect 2;select 3\n  go  \n", SplitGo)
	if len(got) != 2 {
		t.Fatalf("GO: esperava 2 lotes, veio %d: %+v", len(got), got)
	}
	got = Split("CREATE TRIGGER t AFTER INSERT ON a BEGIN INSERT INTO b VALUES (1); UPDATE c SET d = 1; END; SELECT 1", SplitSemicolon)
	if len(got) != 2 {
		t.Fatalf("trigger: esperava 2, veio %d: %+v", len(got), got)
	}
}
