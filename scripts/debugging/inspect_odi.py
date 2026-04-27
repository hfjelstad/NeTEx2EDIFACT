import sys
text = open(sys.argv[1], encoding='utf-8').read()
segs = [s.strip() for s in text.replace('\r','').replace('\n','').split("'") if s.strip().startswith('ODI')]
print(f'Sample ODI from {sys.argv[1]}:')
for s in segs[:20]: print(repr(s))
print(f'Total ODI segs: {len(segs)}')
# Also show unique payload codes
from collections import Counter
payloads = Counter()
for s in segs:
    parts = s.split('+')
    code = parts[2] if len(parts) > 2 else ''
    payloads[code] += 1
print('\nTop payload codes:')
for k, v in payloads.most_common(20):
    print(f'  {v:>5}  {k!r}')
