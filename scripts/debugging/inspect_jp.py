import zipfile, xml.etree.ElementTree as ET, sys
NS = 'http://www.netex.org.uk/netex'

def local(tag): return tag.split('}')[-1] if '}' in tag else tag

zip_path = sys.argv[1]
with zipfile.ZipFile(zip_path) as z:
    for name in z.namelist():
        if name.endswith('.xml') and not name.startswith('_'):
            root = ET.fromstring(z.read(name))
            sjs = root.findall(f'.//{{{NS}}}ServiceJourney')
            print(f"File: {name}  ({len(sjs)} SJs)")
            shown = 0
            for sj in sjs:
                sn = sj.findtext(f'{{{NS}}}PrivateCode', '')
                jps = sj.findall(f'.//{{{NS}}}JourneyPart')
                for jp in jps[:1]:  # look at first JP
                    # Collect all direct child tags
                    children = [local(ch.tag) for ch in jp]
                    sfs_inline = jp.find(f'{{{NS}}}ServiceFacilitySet')
                    sfs_ref = jp.find(f'.//{{{NS}}}ServiceFacilitySetRef')
                    if shown < 8:
                        print(f"  SJ={sn} JP children: {children}")
                        if sfs_inline is not None:
                            fac_children = [local(ch.tag) + '=' + (ch.text or '').strip()[:30] for ch in sfs_inline]
                            print(f"    inline SFS: {fac_children}")
                        if sfs_ref is not None:
                            print(f"    SFSRef: {sfs_ref.get('ref','')}")
                        shown += 1
            break
