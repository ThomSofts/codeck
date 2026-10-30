package engine

import (
	"crypto/tls"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

// Um servidor que só fala TLS 1.0 com cifra RSA antiga, como um SQL Server 2008 R2 sem atualização (openssl s_server).
func legacyServer(t *testing.T) (addr string, stop func()) {
	ossl := "/opt/homebrew/bin/openssl"
	if _, err := os.Stat(ossl); err != nil {
		if p, err := exec.LookPath("openssl"); err == nil {
			ossl = p
		} else {
			t.Skip("sem openssl")
		}
	}
	dir := t.TempDir()
	key, crt := filepath.Join(dir, "k.pem"), filepath.Join(dir, "c.pem")
	if out, err := exec.Command(ossl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt, "-days", "1",
		"-subj", "/CN=SQLServer-antigo").CombinedOutput(); err != nil {
		t.Skipf("openssl req: %v %s", err, out)
	}
	l, _ := net.Listen("tcp", "127.0.0.1:0")
	addr = l.Addr().String()
	l.Close()
	cmd := exec.Command(ossl, "s_server", "-accept", addr, "-cert", crt, "-key", key, "-tls1", "-cipher", "AES128-SHA:@SECLEVEL=0", "-quiet")
	if err := cmd.Start(); err != nil {
		t.Skipf("s_server: %v", err)
	}
	for i := 0; i < 50; i++ {
		if c, err := net.Dial("tcp", addr); err == nil {
			c.Close()
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	return addr, func() { cmd.Process.Kill(); cmd.Wait() }
}

func dial(addr string, p TLSParams) (*tls.ConnectionState, *Capture, error) {
	cap := &Capture{}
	raw, err := net.DialTimeout("tcp", addr, 5*time.Second)
	if err != nil {
		return nil, cap, err
	}
	defer raw.Close()
	c := tls.Client(raw, p.Config("SQLServer-antigo", cap))
	c.SetDeadline(time.Now().Add(5 * time.Second))
	if err := c.Handshake(); err != nil {
		return nil, cap, err
	}
	st := c.ConnectionState()
	return &st, cap, nil
}

func TestLegacyTLS10(t *testing.T) {
	addr, stop := legacyServer(t)
	defer stop()

	// sem o modo legado: recusa (TLS 1.2+)
	if _, _, err := dial(addr, TLSParams{Mode: "pin", Pin: "x"}); err == nil {
		t.Fatal("conectou em TLS 1.0 sem o modo legado")
	}
	// legado, certificado ainda não conferido: falha com a impressão digital para fixar
	_, cap, err := dial(addr, TLSParams{Mode: "pin", Legacy: true})
	info := cap.Get()
	if err == nil || info == nil || info.Problem != "unknown" || len(info.SHA256) != 64 {
		t.Fatalf("esperava cert desconhecido com a impressão: err=%v info=%+v", err, info)
	}
	// legado com o certificado fixado: TLS 1.0
	st, _, err := dial(addr, TLSParams{Mode: "pin", Legacy: true, Pin: info.SHA256})
	if err != nil {
		t.Fatalf("legado com certificado fixado falhou: %v", err)
	}
	if st.Version != tls.VersionTLS10 {
		t.Fatalf("versão %s", tls.VersionName(st.Version))
	}
	// certificado trocado: recusa
	_, cap, err = dial(addr, TLSParams{Mode: "pin", Legacy: true, Pin: "00" + info.SHA256[2:]})
	if err == nil || cap.Get().Problem != "changed" {
		t.Fatalf("esperava certificado trocado: %v %+v", err, cap.Get())
	}
	// verificação normal: certificado próprio não é aceito
	_, cap, err = dial(addr, TLSParams{Mode: "verify", Legacy: true})
	if err == nil || cap.Get().Problem != "invalid" {
		t.Fatalf("esperava certificado inválido: %v %+v", err, cap.Get())
	}
}
