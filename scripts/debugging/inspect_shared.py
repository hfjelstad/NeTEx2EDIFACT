import zipfile, xml.etree.ElementTree as ET, sys
NS = 'http://www.netex.org.uk/netex'

def local(tag): return tag.split('}')[-1] if '}' in tag else tag

zip_path = sys.argv[1]
with zipfile.ZipFile(zip_path) as z:
    # Find shared file
    shared = None
    for name in z.namelist():
        if name.endswith('.xml') and (name.startswith('_') or 'shared' in name.lower()):
            shared = ET.fromstring(z.read(name))
            print(f"Shared file: {name}")
            break
    if shared is None:
        print("No shared file found"); exit(1)

    # List types of elements in shared
    top_tags = {}
    for el in shared.iter():
        t = local(el.tag)
        top_tags[t] = top_tags.get(t, 0) + 1

    interesting = ['JourneyPartCouple','ServiceFacilitySet','Train','TrainComponent','TrainElement',
                   'Journey','CompoundTrain','JourneyPart','Block','BlockPart']
    for k in interesting:
        if k in top_tags:
            print(f"  {top_tags[k]:>5} x {k}")

    print()
    # Look at first JourneyPartCouple or similar
    for tag in ['JourneyPartCouple', 'Train', 'CompoundTrain']:
        els = shared.findall(f'.//{{{NS}}}{tag}')
        if els:
            el = els[0]
            print(f"First {tag} children: {[local(ch.tag) for ch in el]}")
            sfs_refs = el.findall(f'.//{{{NS}}}ServiceFacilitySetRef')
            sfss = el.findall(f'.//{{{NS}}}ServiceFacilitySet')
            print(f"  SFSRef: {[r.get('ref','') for r in sfs_refs]}")
            print(f"  Inline SFS count: {len(sfss)}")
            if sfss:
                for sfs in sfss[:2]:
                    print(f"  Inline SFS children: {[local(ch.tag)+'='+((ch.text or '').strip()[:20]) for ch in sfs]}")
            break

    # Also show first ServiceFacilitySet
    for sfs in shared.findall(f'.//{{{NS}}}ServiceFacilitySet')[:3]:
        sfs_id = sfs.get('id','')
        children = [local(ch.tag)+'='+((ch.text or '').strip()[:30]) for ch in sfs]
        print(f"SFS id={sfs_id}: {children}")
