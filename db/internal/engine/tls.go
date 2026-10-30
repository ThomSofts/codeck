package engine

import (
	"codeck/db/internal/proto"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"errors"
	"strings"
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
// RC4 (só com Legacy): o SQL Server 2008/2008 R2 sem Service Pack derruba a conexão quando o cliente divide os
// registros TLS 1.0 com cifra CBC (a defesa contra o BEAST, que o Go sempre aplica); com RC4, uma cifra de fluxo, não
// há divisão. RC4 é fraca — mas ainda melhor que a senha sem criptografia. Ligada só por escolha, em cada conexão.
type TLSParams struct {
	Mode     string `json:"mode"`
	Pin      string `json:"pin"`
	Legacy   bool   `json:"legacy"`
	RC4      bool   `json:"rc4"`
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
	if p.Legacy && p.RC4 {
		c.MinVersion, c.MaxVersion = tls.VersionTLS10, tls.VersionTLS10
		for _, s := range tls.InsecureCipherSuites() {
			if strings.Contains(s.Name, "RC4") {
				c.CipherSuites = append(c.CipherSuites, s.ID)
			}
		}
	} else if p.Legacy {
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

// LegacyCBCError: o servidor aceitou TLS 1.0 com CBC e caiu logo depois — o SQL Server sem Service Pack que não
// aguenta a divisão dos registros. A tela explica e oferece a compatibilidade RC4.
func LegacyCBCError(cap *Capture, err error, p TLSParams) error {
	info := cap.Get()
	if err == nil || info == nil || info.Problem != "" || p.RC4 || info.Version != "TLS 1.0" || !strings.Contains(info.Cipher, "CBC") {
		return nil
	}
	if m := strings.ToLower(err.Error()); !strings.Contains(m, "eof") && !strings.Contains(m, "reset") {
		return nil
	}
	return &proto.Error{Code: "legacy-cbc", Data: info,
		Message: "O servidor aceitou TLS 1.0 mas derrubou a conexão logo depois — é o SQL Server antigo sem Service Pack, que não aguenta a " +
			"divisão de registros do TLS 1.0 com CBC. Ligue a compatibilidade RC4 nesta conexão (ou atualize o servidor para o SP3 com TLS 1.2)"}
}

// NoTLSError: o servidor não fala TLS — disse que não suporta (PostgreSQL, MySQL, SQL Server) ou respondeu em texto
// puro (Redis, MongoDB). O Codeck nunca cai para texto puro sozinho (como o "prefer" de outras ferramentas): a tela
// explica e pergunta se conecta sem criptografia nesta conexão.
func NoTLSError(err error, p TLSParams) error {
	if err == nil || p.Mode == "off" {
		return nil
	}
	m := strings.ToLower(err.Error())
	for _, s := range []string{"server refused tls connection", "server does not support tls", "server does not support encryption",
		"does not look like a tls handshake"} {
		if strings.Contains(m, s) {
			return &proto.Error{Code: "tls-unsupported", Message: "O servidor não oferece criptografia (TLS) — usuário, senha e dados só " +
				"passam legíveis. Conecte sem criptografia (só em rede local/VPN) ou ligue o TLS no servidor"}
		}
	}
	return nil
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
