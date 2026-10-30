package engine

import (
	"regexp"
	"strings"
)

// SplitStyle diz onde um script se divide em comandos:
//   - SplitSemicolon: no ";" fora de texto, identificador entre aspas/colchetes, comentário e $tag$ (Postgres);
//     o MySQL aceita também "DELIMITER //" (procedures); no SQLite, o ";" dentro de BEGIN…END de trigger não divide;
//   - SplitGo: só na linha "GO" (SQL Server) — o ";" faz parte do lote, como no SSMS.
type SplitStyle int

const (
	SplitSemicolon SplitStyle = iota
	SplitGo
)

var goLine = regexp.MustCompile(`(?im)^[ \t]*GO[ \t]*(?:--[^\n]*)?$`)

// Split devolve os comandos com o deslocamento de cada um no texto original (a tela marca onde deu erro).
type Stmt struct {
	SQL    string `json:"sql"`
	Offset int    `json:"offset"`
}

func Split(src string, style SplitStyle) []Stmt {
	if style == SplitGo {
		var out []Stmt
		prev := 0
		for _, m := range goLine.FindAllStringIndex(src, -1) {
			out = appendStmt(out, src, prev, m[0])
			prev = m[1]
		}
		return appendStmt(out, src, prev, len(src))
	}
	var out []Stmt
	delim := ";"
	start, depth := 0, 0
	trigger := false
	n := len(src)
	for i := 0; i < n; {
		c := src[i]
		switch {
		case c == '-' && i+1 < n && src[i+1] == '-', c == '#' && mysqlMode: // comentário de linha (# só no MySQL)
			for i < n && src[i] != '\n' {
				i++
			}
			continue
		case c == '/' && i+1 < n && src[i+1] == '*':
			end := strings.Index(src[i+2:], "*/")
			if end < 0 {
				i = n
			} else {
				i += end + 4
			}
			continue
		case c == '\'' || c == '"' || c == '`':
			i = skipQuoted(src, i, c)
			continue
		case c == '[' && !mysqlish(src):
			end := strings.IndexByte(src[i:], ']')
			if end < 0 {
				i = n
			} else {
				i += end + 1
			}
			continue
		case c == '$':
			if tag := dollarTag(src[i:]); tag != "" {
				end := strings.Index(src[i+len(tag):], tag)
				if end < 0 {
					i = n
				} else {
					i += len(tag) + end + len(tag)
				}
				continue
			}
		}
		if atLineStart(src, i) && hasWordAt(src, i, "DELIMITER") { // MySQL: DELIMITER //  (a linha não vai ao servidor)
			out = appendStmt(out, src, start, i)
			eol := strings.IndexByte(src[i:], '\n')
			if eol < 0 {
				eol = n - i
			}
			if f := strings.Fields(src[i : i+eol]); len(f) > 1 {
				delim = f[1]
			}
			i += eol
			start = i
			continue
		}
		if isWordStart(src, i) {
			switch {
			case hasWordAt(src, i, "TRIGGER"):
				trigger = true
			case trigger && (hasWordAt(src, i, "BEGIN") || hasWordAt(src, i, "CASE")):
				depth++
			case trigger && hasWordAt(src, i, "END") && depth > 0:
				depth--
			}
		}
		if strings.HasPrefix(src[i:], delim) && depth == 0 {
			out = appendStmt(out, src, start, i)
			i += len(delim)
			start = i
			trigger = false
			continue
		}
		i++
	}
	return appendStmt(out, src, start, n)
}

func appendStmt(out []Stmt, src string, a, b int) []Stmt {
	s := src[a:b]
	t := strings.TrimSpace(s)
	if t == "" || onlyComments(t) {
		return out
	}
	return append(out, Stmt{SQL: t, Offset: a + strings.Index(s, t)})
}

func onlyComments(s string) bool {
	for _, ln := range strings.Split(s, "\n") {
		ln = strings.TrimSpace(ln)
		if ln != "" && !strings.HasPrefix(ln, "--") && !(strings.HasPrefix(ln, "/*") && strings.HasSuffix(ln, "*/")) {
			return false
		}
	}
	return true
}

func skipQuoted(s string, i int, q byte) int {
	for j := i + 1; j < len(s); j++ {
		if s[j] == '\\' && q != '"' && mysqlish(s) {
			j++
			continue
		}
		if s[j] == q {
			if j+1 < len(s) && s[j+1] == q { // '' dentro do texto
				j++
				continue
			}
			return j + 1
		}
	}
	return len(s)
}

var dollarRe = regexp.MustCompile(`^\$[A-Za-z_]?[A-Za-z0-9_]*\$`)

func dollarTag(s string) string { return dollarRe.FindString(s) }

func isWordStart(s string, i int) bool {
	return i == 0 || !isIdent(s[i-1])
}

func hasWordAt(s string, i int, w string) bool {
	if i+len(w) > len(s) || !strings.EqualFold(s[i:i+len(w)], w) {
		return false
	}
	return isWordStart(s, i) && (i+len(w) == len(s) || !isIdent(s[i+len(w)]))
}

func atLineStart(s string, i int) bool {
	for j := i - 1; j >= 0; j-- {
		if s[j] == '\n' {
			return true
		}
		if s[j] != ' ' && s[j] != '\t' {
			return false
		}
	}
	return true
}

func isIdent(c byte) bool {
	return c == '_' || c >= '0' && c <= '9' || c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z'
}

// mysqlish: o plugin do MySQL liga isto (barra invertida escapa dentro de texto e # é comentário).
var mysqlMode bool

func mysqlish(string) bool { return mysqlMode }

// SetMySQL é chamado uma vez pelo plugin do MySQL/MariaDB.
func SetMySQL() { mysqlMode = true }
