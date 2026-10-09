from itertools import product
checked = 0
failures = []
residuals = set()
for a,b,c,d in product(range(-3,4), repeat=4):
    length_product = (a*a+b*b)*(c*c+d*d)
    dot_square = (a*c+b*d)**2
    area_square = (a*d-b*c)**2
    residual = length_product-dot_square-area_square
    residuals.add(residual)
    checked += 1
    if residual != 0:
        failures.append([a,b,c,d,residual])
result = {'coordinate_range': [-3,3], 'checked': checked, 'residuals': sorted(residuals), 'counterexamples': failures[:10], 'counterexample_count': len(failures)}