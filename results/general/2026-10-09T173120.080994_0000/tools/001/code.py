rows = []
simple_sum = 0
cube_sum = 0
for n in range(1, 21):
    simple_sum += n
    cube_sum += n**3
    rows.append({'n': n, 'integer_sum': simple_sum, 'cube_sum': cube_sum, 'integer_sum_squared': simple_sum**2, 'difference': cube_sum - simple_sum**2})
result = {'raw_data': rows, 'scope': 'Integers n from 1 through 20; empirical comparison only'}