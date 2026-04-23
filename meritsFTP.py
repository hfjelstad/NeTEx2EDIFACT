# -*- coding: utf-8 -*-
"""
Created on Tue Feb  7 13:40:31 2023

@author: hfjelstad
"""
from dotenv import load_dotenv
import os
from ftplib import FTP
from pathlib import Path
load_dotenv()

test_user = os.environ.get("test_merits_username")
test_psw = os.environ.get("test_merits_password")
prod_user = os.environ.get("prod_merits_username")
prod_psw = os.environ.get("prod_merits_password")

def send_skdupd(filePath, env):
    file = Path(filePath)
    merits = FTP('ftp.hacon.de')
    if env == "TEST":
        merits.login(user=test_user ,passwd=test_psw)
    else:
        merits.login(user=prod_user ,passwd=prod_psw)
    merits.cwd('in')
    readFile = open(file, 'rb')
    merits.storbinary(f'STOR {file.name}', readFile)
    merits.quit()