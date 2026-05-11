import re, sys
with open('Nordic source material/tiamat-export-Current-202605081200012583.xml', 'rb') as f:
    text = f.read(10000000)
txt = text.decode('utf-8', errors='replace')
idx = txt.find('id="NSR:Quay:')
if idx == -1:
    print('No NSR:Quay: found in first 10MB')
    sys.exit()
start = txt.rfind('<', 0, idx)
end = txt.find('</quay>', idx)
if end == -1:
    end = txt.find('</Quay>', idx)
if end == -1:
    end = start + 1000
print('Snippet:')
print(txt[start:end+10])
