"""Assinatura do canal de atualização: ECDSA P-256 com SHA-256 (o que `openssl dgst -sha256 -sign` produz).

Só a VERIFICAÇÃO mora aqui — a chave privada fica com a ThomSoft (Keychain de quem publica e segredo do CI). Sem
dependência: a biblioteca padrão do Python não tem ECDSA, e verificar só usa dados públicos (nada a vazar por tempo).
"""
import hashlib

# Curva P-256 (secp256r1 / prime256v1), FIPS 186-4
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
      0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def _on_curve(pt):
    x, y = pt
    return 0 <= x < _P and 0 <= y < _P and (y * y - (x * x * x + _A * x + _B)) % _P == 0


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    (x1, y1), (x2, y2) = p, q
    if x1 == x2:
        if (y1 + y2) % _P == 0:
            return None
        lam = (3 * x1 * x1 + _A) * pow(2 * y1, -1, _P) % _P
    else:
        lam = (y2 - y1) * pow(x2 - x1, -1, _P) % _P
    x3 = (lam * lam - x1 - x2) % _P
    return x3, (lam * (x1 - x3) - y1) % _P


def _mul(k, pt):
    out = None
    while k:
        if k & 1:
            out = _add(out, pt)
        pt = _add(pt, pt)
        k >>= 1
    return out


def _der_int(buf, i):
    if buf[i] != 0x02:
        raise ValueError
    n = buf[i + 1]
    if n == 0 or n > 33:
        raise ValueError
    return int.from_bytes(buf[i + 2:i + 2 + n], "big"), i + 2 + n


def _parse_der(sig):
    if len(sig) < 8 or sig[0] != 0x30 or sig[1] != len(sig) - 2:
        raise ValueError
    r, i = _der_int(sig, 2)
    s, i = _der_int(sig, i)
    if i != len(sig):
        raise ValueError
    return r, s


def verify(pubkey_hex, data, der_sig):
    """True só se `der_sig` (DER) é a assinatura de `data` pela chave pública (ponto não comprimido 04||X||Y, em hex)."""
    try:
        raw = bytes.fromhex(pubkey_hex)
        if len(raw) != 65 or raw[0] != 4:
            return False
        q = (int.from_bytes(raw[1:33], "big"), int.from_bytes(raw[33:], "big"))
        if not _on_curve(q):
            return False
        r, s = _parse_der(der_sig)
    except (ValueError, IndexError):
        return False
    if not (1 <= r < _N and 1 <= s < _N):
        return False
    e = int.from_bytes(hashlib.sha256(data).digest(), "big")
    w = pow(s, -1, _N)
    pt = _add(_mul(e * w % _N, _G), _mul(r * w % _N, q))
    return pt is not None and pt[0] % _N == r
