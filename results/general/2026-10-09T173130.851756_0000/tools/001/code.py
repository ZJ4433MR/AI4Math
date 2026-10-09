from math import isqrt
records = []
prime_ns = []
first_composite = None
for n in range(1001):
    value = n*n+n+41
    remainder = value
    factors = []
    divisor = 2
    while divisor*divisor <= remainder:
        exponent = 0
        while remainder % divisor == 0:
            remainder //= divisor
            exponent += 1
        if exponent:
            factors.append([divisor, exponent])
        divisor = 3 if divisor == 2 else divisor+2
    if remainder > 1:
        factors.append([remainder, 1])
    prime = len(factors) == 1 and factors[0] == [value, 1]
    record = {'n': n, 'value': value, 'is_prime': prime, 'factorization': factors}
    records.append(record)
    if prime:
        prime_ns.append(n)
    elif first_composite is None:
        first_composite = record
result = {'range': [0, 1000], 'method': 'exact integer trial division; empirical output awaiting independent verification', 'records': records, 'prime_count': len(prime_ns), 'first_composite': first_composite, 'initial_prime_interval_end': first_composite['n']-1 if first_composite is not None else 1000}
