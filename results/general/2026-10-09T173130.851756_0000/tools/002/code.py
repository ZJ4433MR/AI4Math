records = []
for n in range(41):
    value = n*n+n+41
    divisor = 2
    first_factor = None
    while divisor*divisor <= value:
        if value % divisor == 0:
            first_factor = divisor
            break
        divisor += 1
    records.append({'n': n, 'value': value, 'is_prime': first_factor is None, 'first_factor': first_factor, 'cofactor': value//first_factor if first_factor is not None else None})
result = {'range': [0, 40], 'records': records, 'method': 'exact trial division through square root; awaiting independent verification'}