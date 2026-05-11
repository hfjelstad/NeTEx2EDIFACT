import xml.etree.ElementTree as ET
NS = 'http://www.netex.org.uk/netex'
tree = ET.parse('Nordic source material/tiamat-export-RailStations-202604262300285592.xml')
root = tree.getroot()
stops = root.findall('.//{' + NS + '}StopPlace')
print('StopPlaces:', len(stops))
sp = stops[0]
print('First StopPlace id:', sp.get('id'))
for pc in sp.iter('{' + NS + '}PrivateCode'):
    print('  PrivateCode type=' + repr(pc.get('type', 'NONE')) + ':', repr(pc.text))
for kv in sp.findall('.//{' + NS + '}KeyValue'):
    k = kv.findtext('{' + NS + '}Key')
    v = kv.findtext('{' + NS + '}Value')
    print('  KeyValue:', k, '->', v)
