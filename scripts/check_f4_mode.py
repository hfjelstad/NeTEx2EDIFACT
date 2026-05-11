import xml.etree.ElementTree as ET
NS = "http://www.netex.org.uk/netex"
f4 = ET.parse(r"c:\Users\hfjelstad\Documents\UIC NeTex Profile\NeTEx2EDIFACT\tmp_vyg\VYG_F4.xml").getroot()

for line in f4.iter(f"{{{NS}}}Line"):
    print("Line:", line.attrib.get("id"))
    for child in line:
        ln = child.tag.split("}")[-1]
        print(f"  {ln}: {child.text}")

print()
for sj in list(f4.iter(f"{{{NS}}}ServiceJourney"))[:2]:
    print("ServiceJourney:", sj.attrib.get("id"))
    for child in sj:
        ln = child.tag.split("}")[-1]
        val = (child.text or "").strip() or str(child.attrib)
        print(f"  {ln}: {val}")
    print()
