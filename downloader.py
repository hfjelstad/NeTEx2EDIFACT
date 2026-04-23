# -*- coding: utf-8 -*-
"""
Created on Fri Feb 10 15:32:03 2023

@author: hfjelstad
"""

from google.cloud import storage
import re
import os
import logging
import http.client

#logging.basicConfig(level=logging.DEBUG)
#http.client.HTTPConnection.debuglevel=5

def filSjekk(filnavn):
    mappe = "DOWNLOAD/"
    filnavn_sjekk = filnavn[:4]
    for fil in os.listdir(mappe):
        if fil.startswith(filnavn_sjekk):
            return "file_excist"
    
def download_from_cloud():
    FLB, VYG, GOA, SJN, NSB, GJB, FLX = "", "", "", "", "", "", ""
    #project = "ent-nisaba-prd"
    storage_client = storage.Client(project="ent-nisaba-prd")
    bucket_name = "ror-nisaba-exchange-varelager-production"
    
    blobs = storage_client.list_blobs(bucket_name)
    for blob in blobs:
        check = str(blob.name)
        if re.search(".*flb.*", check):
            FLB = check
        elif re.search(".*vyg.*", check):
            VYG = check
        elif re.search(".*goa.*", check):
            GOA = check
        elif re.search(".*sjn.*", check):
            SJN = check
        elif re.search(".*nsb.*", check):
            NSB = check
        elif re.search(".*gjb.*", check):
            GJB = check
        elif re.search(".*flx.*", check):
            FLX = check

     
    make_list = [FLB, VYG, GOA, SJN, NSB, GJB, FLX]
    print(make_list)
    bucket = storage_client.bucket(bucket_name)
    for x in make_list:
        try:
            if filSjekk(x[13:]) == "file_excist":
                filsti = os.path.join("DOWNLOAD/", x[13:])
                os.remove(filsti)
            download_blob = bucket.blob(x)
            download_blob.download_to_filename("DOWNLOAD/" + x[13:])
        except:
            print("Did not find files for all codespaces")

if __name__ == "__main__":
    download_from_cloud()
