# -*- coding: utf-8 -*-
"""
Created on Mon Jan 30 11:08:47 2023

@author: hfjelstad
"""
import glob
from zipfile import ZipFile, ZIP_DEFLATED
from datetime import datetime

class UnZipper():
    def netex_unzip():
        for file in glob.glob("./DOWNLOAD"+"/*.zip"):
            with ZipFile(file, "r") as unzip:
                print("Processed: " + file[11:])
                unzip.extractall("./NETEX")

class Zipper():
    def skdupd_zip():
        filename = "new_SKDUPD.r" 
        path = "NEW_SKDUPD/"
        timeStamp = str(datetime.timestamp(datetime.now()))[0:10]
        zipName = "SKDUPD_" + timeStamp + ".zip"
        with ZipFile(path + zipName, "w", ZIP_DEFLATED, compresslevel=9) as archive:
            archive.write(path + filename, arcname= filename)
            archive.close()
        return path+zipName
def main():
    Zipper.skdupd_zip()
if __name__ == "__main__":
    main()