import zipfile, xml.etree.ElementTree as ET, sys
NS = 'http://www.netex.org.uk/netex'
zip_path = sys.argv[1]
with zipfile.ZipFile(zip_path) as z:
    for name in z.namelist():
        if name.endswith('.xml') and not name.startswith('_'):
            root = ET.fromstring(z.read(name))
            sjs = root.findall(f'.//{{{NS}}}ServiceJourney')
            print(f"File: {name}, SJ count: {len(sjs)}")
            no_jp = 0
            has_sfs_on_sj = 0
            has_sfs_in_jp = 0
            no_sfs = 0
            for sj in sjs:
                jps = sj.findall(f'.//{{{NS}}}JourneyPart')
                sfs_on_sj = sj.find(f'{{{NS}}}ServiceFacilitySetRef')
                if not jps:
                    no_jp += 1
                    if sfs_on_sj is not None:
                        has_sfs_on_sj += 1
                    else:
                        no_sfs += 1
                else:
                    has_sfs_in_jp += 1
            print(f"  SJs with JourneyParts: {has_sfs_in_jp}")
            print(f"  SJs without JourneyParts, with SFSRef: {has_sfs_on_sj}")
            print(f"  SJs without JourneyParts, no SFSRef: {no_jp - has_sfs_on_sj}")
            # Show a few with SFS on SJ
            shown = 0
            for sj in sjs:
                sn = sj.findtext(f'{{{NS}}}PrivateCode', '')
                jps = sj.findall(f'.//{{{NS}}}JourneyPart')
                sfs_on_sj = sj.find(f'{{{NS}}}ServiceFacilitySetRef')
                if not jps and sfs_on_sj is not None and shown < 5:
                    print(f"  Example: SJ={sn} SFSRef={sfs_on_sj.get('ref','')}")
                    shown += 1
            break
