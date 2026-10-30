package engine

import "strings"

// Analysis diz o que um comando faz, lendo só as palavras fora de texto, comentário e nome entre aspas. Serve às
// regras de produção (somente leitura, confirmação) — a garantia de verdade é a transação desfeita no banco; isto
// evita chegar até ela e pega o que a transação não segura (COMMIT no meio do script).
type Analysis struct {
	Offset    int    `json:"offset"`
	First     string `json:"first"`
	Write     bool   `json:"write"`     // altera dados ou estrutura (ou pode alterar: EXEC, CALL)
	TxControl bool   `json:"txControl"` // COMMIT, ROLLBACK, BEGIN TRAN… — sairia da transação de proteção
	NoWhere   bool   `json:"noWhere"`   // UPDATE/DELETE sem WHERE: a tabela inteira
	Drop      bool   `json:"drop"`      // DROP / TRUNCATE
	Alter     bool   `json:"alter"`
	Exec      bool   `json:"exec"` // procedure: pode alterar dados
	Words     string `json:"-"`
}

var writeWords = map[string]bool{"INSERT": true, "UPDATE": true, "DELETE": true, "MERGE": true, "CREATE": true, "ALTER": true, "DROP": true,
	"TRUNCATE": true, "GRANT": true, "REVOKE": true, "RENAME": true, "REPLACE": true, "INTO": true, "COPY": true, "VACUUM": true,
	"REINDEX": true, "CLUSTER": true, "REFRESH": true, "LOCK": true, "ATTACH": true, "DETACH": true, "LOAD": true, "HANDLER": true,
	"OPTIMIZE": true, "REPAIR": true, "KILL": true, "SHUTDOWN": true, "BACKUP": true, "RESTORE": true, "DBCC": true, "BULK": true,
	"RECONFIGURE": true, "UPSERT": true, "IMPORT": true, "DISABLE": true, "ENABLE": true, "COMMENT": true, "SECURITY": true}

var txStart = map[string]bool{"COMMIT": true, "ROLLBACK": true, "BEGIN": true, "START": true, "END": true, "ABORT": true, "SAVEPOINT": true,
	"RELEASE": true, "PREPARE": true}

// Analyze divide o texto em comandos pelo ";" (inclusive no SQL Server, só para analisar) e classifica cada um.
func Analyze(src string, style SplitStyle) []Analysis {
	var out []Analysis
	parts := Split(src, style)
	if style == SplitGo {
		var sub []Stmt
		for _, b := range parts {
			for _, s := range Split(b.SQL, SplitSemicolon) {
				s.Offset += b.Offset
				sub = append(sub, s)
			}
		}
		parts = sub
	}
	for _, st := range parts {
		out = append(out, analyzeOne(st, style == SplitGo))
	}
	return out
}

type word struct {
	w     string
	paren bool // seguida de "(" — é função: REPLACE(x, …) não altera nada
}

func analyzeOne(st Stmt, tsql bool) Analysis {
	ws := words(st.SQL)
	a := Analysis{Offset: st.Offset}
	if len(ws) > 0 {
		a.First = ws[0].w
	}
	if a.First == "PRAGMA" { // PRAGMA x = y grava; PRAGMA x(arg) lê (wal_checkpoint(TRUNCATE) não é o TRUNCATE de tabela)
		a.Write = strings.Contains(st.SQL, "=")
		return a
	}
	hasWhere := false
	for i, x := range ws {
		prev := ""
		if i > 0 {
			prev = ws[i-1].w
		}
		next := ""
		if i+1 < len(ws) {
			next = ws[i+1].w
		}
		switch {
		case x.paren:
		case x.w == "WHERE":
			hasWhere = true
		case x.w == "UPDATE" && prev == "FOR", x.w == "UPDATE" && prev == "ON", x.w == "DELETE" && prev == "ON":
			// SELECT … FOR UPDATE; ON UPDATE CASCADE (dentro de CREATE, que já conta)
		case x.w == "EXEC" || x.w == "EXECUTE" || x.w == "CALL" || x.w == "DO":
			a.Write, a.Exec = true, true
		case x.w == "PRAGMA":
			a.Write = a.Write || strings.Contains(st.SQL, "=")
		case writeWords[x.w]:
			a.Write = true
			switch x.w {
			case "DROP", "TRUNCATE":
				a.Drop = true
			case "ALTER":
				a.Alter = true
			}
		}
		// controle de transação: no começo do comando; no T-SQL, em qualquer ponto do lote (BEGIN TRAN, COMMIT…)
		if tsql {
			switch x.w {
			case "COMMIT", "ROLLBACK":
				a.TxControl = true
			case "BEGIN", "SAVE":
				a.TxControl = a.TxControl || next == "TRAN" || next == "TRANSACTION" || next == "DISTRIBUTED"
			}
		} else if i == 0 && txStart[x.w] {
			a.TxControl = true
		}
		if x.w == "SET" && (next == "TRANSACTION" || next == "AUTOCOMMIT" || next == "IMPLICIT_TRANSACTIONS") {
			a.TxControl = true
		}
	}
	for _, x := range ws {
		if (x.w == "UPDATE" || x.w == "DELETE") && !hasWhere && a.Write && !a.Alter && firstDML(ws) {
			a.NoWhere = true
		}
	}
	return a
}

// firstDML: o comando é um UPDATE/DELETE (talvez depois de WITH), não um CREATE TRIGGER … ON UPDATE.
func firstDML(ws []word) bool {
	if len(ws) == 0 {
		return false
	}
	switch ws[0].w {
	case "UPDATE", "DELETE":
		return true
	case "WITH":
		for _, x := range ws {
			if x.w == "UPDATE" || x.w == "DELETE" {
				return true
			}
		}
	}
	return false
}

// words: as palavras do comando em maiúsculas, fora de texto, comentário, nome entre aspas/colchetes e $corpo$.
func words(s string) []word {
	var out []word
	n := len(s)
	for i := 0; i < n; {
		c := s[i]
		switch {
		case c == '-' && i+1 < n && s[i+1] == '-', c == '#' && mysqlMode:
			for i < n && s[i] != '\n' {
				i++
			}
		case c == '/' && i+1 < n && s[i+1] == '*':
			if end := strings.Index(s[i+2:], "*/"); end < 0 {
				i = n
			} else {
				i += end + 4
			}
		case c == '\'' || c == '"' || c == '`':
			i = skipQuoted(s, i, c)
		case c == '[' && !mysqlMode:
			if end := strings.IndexByte(s[i:], ']'); end < 0 {
				i = n
			} else {
				i += end + 1
			}
		case c == '$' && dollarTag(s[i:]) != "":
			tag := dollarTag(s[i:])
			if end := strings.Index(s[i+len(tag):], tag); end < 0 {
				i = n
			} else {
				i += len(tag) + end + len(tag)
			}
		case isIdent(c) && (c < '0' || c > '9'):
			j := i
			for j < n && (isIdent(s[j]) || s[j] == '$' || s[j] == '@' || s[j] == '#') {
				j++
			}
			k := j
			for k < n && (s[k] == ' ' || s[k] == '\t' || s[k] == '\r' || s[k] == '\n') {
				k++
			}
			// "schema.tabela" e "@variavel" não são palavras-chave
			if (i == 0 || (s[i-1] != '.' && s[i-1] != '@')) && (j >= n || s[j] != '.') {
				out = append(out, word{w: strings.ToUpper(s[i:j]), paren: k < n && s[k] == '('})
			}
			i = j
		default:
			i++
		}
	}
	return out
}
