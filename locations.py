import xmltodict
from toolz.dicttoolz import get_in
from constants import STOP_PLACE, QUAY

file = "./LOCATIONS/tiamat-export-RailStations-202601301200287716.xml"
quayPublicCode = {}

def get_in_list(keys, dic):
    
    data = get_in(keys, dic)
    if data is None:
        return []
    if not isinstance(data, list):
        return [data]
    return data

def read_netex(file):

    try:
        with open(file, encoding='utf-8') as fd:
            return xmltodict.parse(fd.read())
    except UnicodeDecodeError:
        with open(file, encoding="utf-16") as fd:
            return xmltodict.parse(fd.read())
        
def quay_dic():
    data = read_netex(file)
    for locations in get_in_list(STOP_PLACE, data):
        try: 
            for quays in get_in_list(QUAY, locations):
                    quayPublicCode[quays['@id']] = quays['PublicCode']        
        except:
            pass
    return quayPublicCode    

if __name__ == "__main__":
    quay_dic()
    