package tls

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	stdtls "crypto/tls"
	"crypto/x509"
	"math/big"
	"net"
	"testing"
	"time"

	"github.com/sagernet/sing-box/option"
	"github.com/sagernet/sing/common/json/badoption"
	"github.com/sagernet/sing/common/logger"
)

func TestEblitCertificatePinHandshake(t *testing.T) {
	certificate, err := GenerateKeyPair(nil, nil, time.Now, "localhost")
	if err != nil {
		t.Fatal(err)
	}
	leaf, err := x509.ParseCertificate(certificate.Certificate[0])
	if err != nil {
		t.Fatal(err)
	}
	certificateHash := sha256.Sum256(leaf.Raw)
	publicKeyHash := sha256.Sum256(leaf.RawSubjectPublicKeyInfo)
	wrongHash := sha256.Sum256([]byte("different certificate"))
	leaf.SerialNumber = big.NewInt(12345)
	reissuedDER, err := x509.CreateCertificate(rand.Reader, leaf, leaf, leaf.PublicKey, certificate.PrivateKey)
	if err != nil {
		t.Fatal(err)
	}
	reissued := &stdtls.Certificate{
		Certificate: [][]byte{reissuedDER},
		PrivateKey:  certificate.PrivateKey,
	}

	for _, useUTLS := range []bool{false, true} {
		engine := "go"
		if useUTLS {
			engine = "utls"
		}
		for _, scenario := range []struct {
			name        string
			certificate *stdtls.Certificate
			certHashes  [][]byte
			keyHashes   [][]byte
			wantError   bool
		}{
			{"matching certificate", certificate, [][]byte{certificateHash[:]}, nil, false},
			{"wrong certificate", certificate, [][]byte{wrongHash[:]}, nil, true},
			{"reissued same key fails certificate pin", reissued, [][]byte{certificateHash[:]}, nil, true},
			{"existing public key pin accepts reissue", reissued, nil, [][]byte{publicKeyHash[:]}, false},
			{"either pin may match", certificate, [][]byte{wrongHash[:]}, [][]byte{publicKeyHash[:]}, false},
			{"both pins fail", certificate, [][]byte{wrongHash[:]}, [][]byte{wrongHash[:]}, true},
		} {
			t.Run(engine+"/"+scenario.name, func(t *testing.T) {
				options := option.OutboundTLSOptions{
					Enabled:                    true,
					ServerName:                 "localhost",
					CertificateSHA256:          badoption.Listable[[]byte](scenario.certHashes),
					CertificatePublicKeySHA256: badoption.Listable[[]byte](scenario.keyHashes),
				}
				if useUTLS {
					options.UTLS = &option.OutboundUTLSOptions{Enabled: true, Fingerprint: "firefox"}
				}
				err := eblitPinnedHandshake(t, scenario.certificate, options)
				if (err != nil) != scenario.wantError {
					t.Fatalf("handshake error = %v, wantError = %v", err, scenario.wantError)
				}
			})
		}
	}
}

func eblitPinnedHandshake(t *testing.T, certificate *stdtls.Certificate, options option.OutboundTLSOptions) error {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	serverDone := make(chan struct{})
	go func() {
		defer close(serverDone)
		connection, acceptErr := listener.Accept()
		if acceptErr != nil {
			return
		}
		defer connection.Close()
		connection.SetDeadline(time.Now().Add(5 * time.Second))
		stdtls.Server(connection, &stdtls.Config{Certificates: []stdtls.Certificate{*certificate}}).Handshake()
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	clientConfig, err := NewClient(ctx, logger.NOP(), "localhost", options)
	if err != nil {
		t.Fatal(err)
	}
	connection, err := net.DialTimeout("tcp", listener.Addr().String(), 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	connection.SetDeadline(time.Now().Add(5 * time.Second))
	tlsConnection, handshakeErr := ClientHandshake(ctx, connection, clientConfig)
	if handshakeErr == nil {
		tlsConnection.Close()
	}
	<-serverDone
	return handshakeErr
}

func TestEblitCertificatePinRejectsUnsupportedModes(t *testing.T) {
	for _, options := range []option.OutboundTLSOptions{
		{Enabled: true, Engine: "windows"},
		{Enabled: true, Engine: "apple"},
		{Enabled: true, Reality: &option.OutboundRealityOptions{Enabled: true}},
	} {
		options.CertificateSHA256 = badoption.Listable[[]byte]{make([]byte, 32)}
		if _, err := NewClient(context.Background(), logger.NOP(), "localhost", options); err == nil {
			t.Fatal("certificate pin was ignored in unsupported mode")
		}
	}
	if err := VerifyPinnedCertificate([][]byte{make([]byte, 32)}, nil, nil); err == nil {
		t.Fatal("missing certificate was accepted")
	}
}
