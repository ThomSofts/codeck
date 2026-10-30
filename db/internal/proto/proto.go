// Package proto: o protocolo dos plugins de banco do Codeck — uma linha JSON por mensagem no stdin/stdout.
//
// Pedido:   {"id": 1, "method": "query", "params": {...}}
// Resposta: {"id": 1, "result": {...}} ou {"id": 1, "error": {"code": "...", "message": "..."}}
//
// Cada pedido roda na sua goroutine (um "cancel" chega enquanto a consulta roda). O plugin não abre porta nem
// arquivo de log: fala só com o backend que o iniciou, e sai quando o stdin fecha (o Codeck fechou ou morreu).
package proto

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"sync"
)

// Version sobe quando o formato das mensagens muda de um jeito que o backend precisa saber.
const Version = 1

type request struct {
	ID     int64           `json:"id"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params"`
}

type response struct {
	ID     int64  `json:"id"`
	Result any    `json:"result,omitempty"`
	Error  *Error `json:"error,omitempty"`
}

// Error é o erro que chega à interface: Code é estável (a tela decide o que fazer por ele), Message é para pessoas.
type Error struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	Data    any    `json:"data,omitempty"`
}

func (e *Error) Error() string { return e.Message }

func Fail(code, format string, args ...any) *Error {
	return &Error{Code: code, Message: fmt.Sprintf(format, args...)}
}

// Handler atende um método. secrets são trechos (senhas) que nunca podem sair numa mensagem de erro.
type Handler func(ctx context.Context, method string, params json.RawMessage) (any, error)

// Scrubber devolve os segredos conhecidos até agora, para apagar de qualquer texto de erro.
type Scrubber func() []string

func Serve(h Handler, scrub Scrubber) {
	in := bufio.NewReaderSize(os.Stdin, 1<<20)
	out := bufio.NewWriter(os.Stdout)
	var mu sync.Mutex
	write := func(r response) {
		b, err := json.Marshal(r)
		if err != nil {
			b, _ = json.Marshal(response{ID: r.ID, Error: Fail("encode", "Resposta impossível de codificar: %v", err)})
		}
		mu.Lock()
		out.Write(b)
		out.WriteByte('\n')
		out.Flush()
		mu.Unlock()
	}
	ctx, stop := context.WithCancel(context.Background())
	defer stop()
	var wg sync.WaitGroup
	for {
		line, err := in.ReadBytes('\n')
		if len(strings.TrimSpace(string(line))) > 0 {
			var req request
			if jerr := json.Unmarshal(line, &req); jerr != nil {
				write(response{Error: Fail("bad-request", "Pedido inválido")})
			} else {
				wg.Add(1)
				go func(req request) {
					defer wg.Done()
					res, err := safe(ctx, h, req)
					if err != nil {
						write(response{ID: req.ID, Error: toError(err, scrub)})
						return
					}
					write(response{ID: req.ID, Result: res})
				}(req)
			}
		}
		if err != nil { // EOF: quem nos iniciou foi embora — cancela o que estiver rodando e sai
			stop()
			wg.Wait()
			return
		}
	}
}

func safe(ctx context.Context, h Handler, req request) (res any, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = Fail("internal", "Erro interno do plugin: %v", r)
		}
	}()
	return h(ctx, req.Method, req.Params)
}

func toError(err error, scrub Scrubber) *Error {
	var e *Error
	if !errors.As(err, &e) {
		e = &Error{Code: "db", Message: err.Error()}
	}
	if scrub != nil {
		for _, s := range scrub() {
			if len(s) >= 3 {
				e.Message = strings.ReplaceAll(e.Message, s, "•••")
			}
		}
	}
	return e
}
