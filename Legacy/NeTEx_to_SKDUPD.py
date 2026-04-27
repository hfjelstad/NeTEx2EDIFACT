"""
Created on Mon Feb  6 12:29:10 2023

@author: hakon.fjelstad@entur.org
"""
import zipper
import netex2csv
import remove_files
import meritsFTP
import downloader
import csv2SKDUPD as skdupd

def main(env):
    """
    Prerequisites
    """
    remove_files.empty_folders()
    downloader.download_from_cloud()
    zipper.UnZipper.netex_unzip()
    remove_files.preHandling()
    """
    Converting NeTEx to CSV
    """
    netex2csv.main()
    print("Finished converting from NeTEx to CSV")
    """
    Converting CSV to EDIFACT
    """
    skdupd.main()
    print("Finished converting from CSV to SKDUPD")
    """
    Zipping files 
    """
    zipped_skdupd = zipper.Zipper.skdupd_zip()
    print("Finished zipping SKDUPD file: " + zipped_skdupd[11:])
    """
    Uploading zip file to MERITS's test enviorment
    """
    meritsFTP.send_skdupd(zipped_skdupd, "TEST")
    print("Uploaded to TEST")
    """
    Uploading zip file to MERITS's prod enviorment
    """
    meritsFTP.send_skdupd(zipped_skdupd, "PROD")
    print("Uploaded to PROD")
    
    exit()
    
if __name__ == "__main__":
    main("['TEST']")