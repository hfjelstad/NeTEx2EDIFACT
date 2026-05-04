"""Find first PRD that includes Sandnes sentrum (007602226) and dump POR list."""
raw = open('NEW_SKDUPD/new_SKDUPD_batch.r', 'r', encoding='utf-8').read()
segs = [s.lstrip() for s in raw.split("'")]
print('total segments:', len(segs))
print('PRD segments:', sum(1 for s in segs if s.startswith('PRD+')))

found = 0
target_terminus = ('007602226', '007602230', '007602234')
for i, s in enumerate(segs):
    if not s.startswith('PRD+'):
        continue
    j = i + 1
    pors = []
    while j < len(segs) and not segs[j].startswith('PRD+'):
        if segs[j].startswith('POR+'):
            pors.append(segs[j])
        j += 1
    uics = tuple(p.split('+')[1] for p in pors)
    if len(uics) >= 3 and uics[-3:] == target_terminus:
        # Look for any odd time format in this PRD
        for p in pors:
            f = p.split('+')
            if len(f) >= 3:
                for t in f[2].split('*'):
                    if t and (':::' in t or len(t) != 4 or not t.isdigit()):
                        print('===')
                        print('PRD:', s)
                        for q in pors:
                            print(' ', q)
                        found += 1
                        break
            if found and pors[-1] is p:
                break
        if found >= 5:
            break
print('found:', found)
