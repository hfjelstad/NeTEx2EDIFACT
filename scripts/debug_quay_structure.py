"""Debug: find first Quay element with an NSR:Quay: id and print its subtree."""
import xml.etree.ElementTree as ET

target_prefix = 'NSR:Quay:'
xml_path = 'Nordic source material/tiamat-export-Current-202605081200012583.xml'

count = 0
found = 0
for event, elem in ET.iterparse(xml_path, events=('start', 'end')):
    tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
    if event == 'end' and tag == 'Quay':
        eid = elem.get('id', '')
        if eid.startswith(target_prefix):
            found += 1
            if found <= 2:
                print(f'=== Quay id={eid} ===')
                print(ET.tostring(elem, encoding='unicode')[:1500])
                print()
            if found >= 3:
                break
        # Free memory
        elem.clear()

print(f'Found {found} Quay elements with NSR:Quay: prefix so far')
