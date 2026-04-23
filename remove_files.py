# -*- coding: utf-8 -*-
"""
Created on Mon Feb  6 13:09:26 2023

@author: hfjelstad
"""

import os

def preHandling():
    if os.path.exists("NETEX/VYG_F8.xml"):
        os.remove("NETEX/VYG_F8.xml")
        print('Removed "VYG_F8.xml"')

def empty_download_folder():
    try:
        dir_list = os.listdir("DOWNLOAD/")
        for x in dir_list:
            os.remove("DOWNLOAD/" + x)
    except:
        print("No files to remove")
        
def empty_netex_folder():
    try:
        dir_list = os.listdir("NETEX/")
        for x in dir_list:
            os.remove("NETEX/" + x)
    except:
        print("No files to remove")

def empty_skdupd_folder():
    try:
        dir_list = os.listdir("NEW_SKDUPD/")
        for x in dir_list:
            os.remove("NEW_SKDUPD/" + x)
    except:
        print("No files to remove")
        
def empty_folders():
    empty_download_folder()
    empty_netex_folder()
    empty_skdupd_folder()
        
if __name__ == "__main__":
    empty_download_folder()
    empty_netex_folder()