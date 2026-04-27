import zipfile, xml.etree.ElementTree as ET, sys
NS = 'http://www.netex.org.uk/netex'
def local(tag): return tag.split('}')[-1] if '}' in tag else tag

zip_path = sys.argv[1]
with zipfile.ZipFile(zip_path) as z:
    for name in z.namelist():
        if not name.endswith('.xml'): continue
        root = ET.fromstring(z.read(name))
        sfss = root.findall(f'.//{{{NS}}}ServiceFacilitySet')
        if sfss:
            print(f"File: {name}")
            for sfs in sfss[:10]:
                sfs_id = sfs.get('id','')
                children = [local(ch.tag)+'='+((ch.text or '').strip()[:40]) for ch in sfs]
                print(f"  SFS id={sfs_id!r}: {children}")
