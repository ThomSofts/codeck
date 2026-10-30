package engine

import (
	"codeck/db/internal/proto"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"errors"
	"sync"
	"time"
)

// TLSParams vem da conexão salva. Mode:
//   - "verify": certificado assinado por uma autoridade do sistema e com o nome do host (padrão);
//   - "pin":    aceita só o certificado com esta impressão digital (servidor com certificado próprio, como todo
//     SQL Server antigo). Sem Pin, a conexão falha com "cert-unknown" e a impressão vai junto, para você aceitar;
//   - "off":    sem criptografia. Só vale com AllowOff, que o backend liga depois de conferir as regras.
//
// Legacy aceita TLS 1.0/1.1 e as cifras antigas (SQL Server 2008 R2 sem atualização) — só na conexão que pedir.
type TLSParams struct {
	Mode     string `json:"mode"`
	Pin      string `json:"pin"`
	Legacy   bool   `json:"legacy"`
	AllowOff bool   `json:"allowOff"`
}

// CertInfo é o que a tela mostra sobre o certificado (e o que se fixa).
type CertInfo struct {
	SHA256   string `json:"sha256"`
	Subject  string `json:"subject"`
	Issuer   string `json:"issuer"`
	NotAfter string `json:"notAfter"`
	Version  string `json:"version"`
	Cipher   string `json:"cipher"`
	Problem  string `json:"problem,omitempty"` // unknown | changed | invalid
	Detail   string `json:"detail,omitempty"`
}

// Capture guarda o certificado visto no handshake: o driver costuma embrulhar o erro do TLS num texto, então o
// motivo exato (desconhecido, mudou, inválido) é lido daqui depois que a conexão falha.
type Capture struct {
	mu   sync.Mutex
	info *CertInfo
}

func (c *Capture) set(i *CertInfo) { c.mu.Lock(); c.info = i; c.mu.Unlock() }
func (c *Capture) Get() *CertInfo  { c.mu.Lock(); defer c.mu.Unlock(); return c.info }

var errTLS = errors.New("certificado recusado")

// Off diz se a conexão vai sem TLS (e se isso foi autorizado).
func (p TLSParams) Off() (bool, error) {
	if p.Mode != "off" {
		return false, nil
	}
	if !p.AllowOff {
		return true, &codeErr{"tls-off-denied", "Conexão sem criptografia não autorizada para este banco"}
	}
	return true, nil
}

// Config monta o tls.Config. A verificação é feita aqui (e não pelo Go) para guardar o certificado mesmo quando ele é
// recusado — sem isso, a tela não teria a impressão digital para você conferir e fixar.
func (p TLSParams) Config(host string, cap *Capture) *tls.Config {
	c := &tls.Config{ServerName: host, InsecureSkipVerify: true, MinVersion: tls.VersionTLS12}
	if p.Legacy {
		c.MinVersion = tls.VersionTLS10
		for _, s := range tls.CipherSuites() {
			c.CipherSuites = append(c.CipherSuites, s.ID)
		}
		for _, s := range tls.InsecureCipherSuites() { // RSA puro, 3DES, CBC-SHA256: o que um 2008 R2 oferece
			c.CipherSuites = append(c.CipherSuites, s.ID)
		}
	}
	c.VerifyConnection = func(cs tls.ConnectionState) error {
		if len(cs.PeerCertificates) == 0 {
			return errTLS
		}
		leaf := cs.PeerCertificates[0]
		sum := sha256.Sum256(leaf.Raw)
		info := &CertInfo{SHA256: hex.EncodeToString(sum[:]), Subject: leaf.Subject.String(), Issuer: leaf.Issuer.String(),
			NotAfter: leaf.NotAfter.UTC().Format(time.RFC3339), Version: tls.VersionName(cs.Version), Cipher: tls.CipherSuiteName(cs.CipherSuite)}
		defer cap.set(info)
		if p.Mode == "pin" {
			switch {
			case p.Pin == "":
				info.Problem = "unknown"
				return errTLS
			case p.Pin != info.SHA256:
				info.Problem = "changed"
				return errTLS
			}
			return nil
		}
		inter := x509.NewCertPool()
		for _, ic := range cs.PeerCertificates[1:] {
			inter.AddCert(ic)
		}
		name := host
		if name == "" { // host vazio: cada conexão confere o próprio nome (os nós de um cluster MongoDB Atlas)
			name = cs.ServerName
		}
		if _, err := leaf.Verify(x509.VerifyOptions{DNSName: name, Intermediates: inter}); err != nil {
			info.Problem, info.Detail = "invalid", err.Error()
			return errTLS
		}
		return nil
	}
	return c
}

// CertError: o motivo da recusa do certificado como erro para a tela (nil se não houve problema de certificado).
func CertError(cap *Capture) error {
	info := cap.Get()
	if info == nil || info.Problem == "" {
		return nil
	}
	msg := map[string]string{
		"unknown": "Certificado do servidor ainda não conferido — confira a impressão digital e fixe",
		"changed": "O certificado do servidor MUDOU desde que foi fixado — pode ser outro servidor no meio do caminho",
		"invalid": "Certificado do servidor não é válido para este host",
	}[info.Problem]
	return &proto.Error{Code: "cert-" + info.Problem, Message: msg, Data: info}
}

// TLSHost: o nome que o certificado tem de ter — o do servidor real, mesmo quando a conexão passa por um túnel SSH.
func TLSHost(p ConnParams) string {
	if h := p.Options["tlsHost"]; h != "" {
		return h
	}
	return p.Host
}
