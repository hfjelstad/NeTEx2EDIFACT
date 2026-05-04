import xml.etree.ElementTree as ET
from collections import Counter
NS = 'http://www.netex.org.uk/netex'
root = ET.parse('Source/nsr_railstations_with_mct.xml').getroot()
swedish_keywords = ['Göteborg', 'Helsingborg', 'Malmö', 'Lund', 'Värnamo',
                    'Halmstad', 'Charlottenberg', 'Hallsberg', 'Storlien',
                    'Östersund', 'Are', 'Åre', 'Kornsjø', 'Strömstad',
                    'Stockholm', 'Köbenhavn', 'København', 'Kastrup']

type_counter = Counter()
key_counter = Counter()
for sp in root.findall(f'.//{{{NS}}}StopPlace'):
    for pc in sp.findall(f'.//{{{NS}}}PrivateCode'):
        type_counter[pc.get('type', '<no-type>')] += 1
    for key in sp.findall(f'.//{{{NS}}}Key'):
        if key.text:
            key_counter[key.text] += 1

print('=== PrivateCode @type values across all StopPlaces ===')
for t, c in type_counter.most_common():
    print(f'  {c:6d}  type="{t}"')
print()
print('=== <Key> text values found ===')
for k, c in key_counter.most_common(40):
    print(f'  {c:6d}  {k}')

print()
print('=== Detail dump for Swedish/Danish stations ===')
for sp in root.findall(f'.//{{{NS}}}StopPlace'):
    name_el = sp.find(f'{{{NS}}}Name')
    name = (name_el.text or '') if name_el is not None else ''
    if not any(k in name for k in swedish_keywords):
        continue
    sp_id = sp.get('id', '')
    print(f'\n--- {sp_id}  {name} ---')
    for pc in sp.findall(f'.//{{{NS}}}PrivateCode'):
        if pc.text or pc.get('type'):
            print(f'  PrivateCode type={pc.get("type")!r}  text={pc.text!r}')
    for kv in sp.findall(f'.//{{{NS}}}KeyValue'):
        k = kv.find(f'{{{NS}}}Key')
        v = kv.find(f'{{{NS}}}Value')
        print(f'  KeyValue Key={k.text if k is not None else None!r}  Value={v.text if v is not None else None!r}')
