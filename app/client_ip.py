"""Trust forwarded addresses only when the immediate TCP peer is a configured proxy."""
import ipaddress


def parse_address(value):
    address = ipaddress.ip_address(value)
    return getattr(address, 'ipv4_mapped', None) or address


class ClientAddresses:
    def __init__(self, cidrs=''):
        try:
            self.networks = [ipaddress.ip_network(c.strip(), strict=False)
                             for c in cidrs.split(',') if c.strip()]
            if any(network.prefixlen == 0 for network in self.networks):
                raise ValueError()
        except ValueError:
            raise RuntimeError('TRUSTED_PROXY_CIDRS must contain explicit trusted proxy IPs/CIDRs, never all addresses') from None

    def trusted(self, address):
        return any(address in network for network in self.networks)

    def ip(self, request):
        peer = request.client.host if request.client else 'unknown'
        try:
            address = parse_address(peer)
        except ValueError:
            return peer
        if not self.trusted(address):
            return str(address)
        # A trusted proxy must replace/append its observed client address to XFF.
        # Walk from the peer backwards; ignore spoofed prefixes before the first untrusted hop.
        values = request.headers.getlist('x-forwarded-for')
        if len(values) != 1 or len(values[0]) > 2048:
            return str(address)
        parts = values[0].split(',')
        if len(parts) > 32:
            return str(address)
        try:
            chain = [parse_address(part.strip()) for part in parts]
        except ValueError:
            return str(address)
        for hop in reversed(chain):
            address = hop
            if not self.trusted(address):
                break
        return str(address)
