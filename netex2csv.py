# -*- coding: utf-8 -*-
"""
This module  provides implementation of a converter from the nordic netex file
format into a specific csv format.

There are at least two files in netex : _XXX_Shared.xml and the XXX_Number.xml
The csv format is designed to be converted in EDIFACT

The package read every xml file in the ./NETEX directory and try to convert them
into the ./CSV directory

"""
import glob
from netex_lib import NetexLib
from writer import Writer
import csv2SKDUPD as skdupd
import zipper 

class Netex2csv:
    """
    Main Class ton convert netex nordic profile in CSV (merits style)
    """

    def __init__(self):
        self.cpt = 0
        self.lib = NetexLib()
        self.writer = Writer()

    def process(self, main_liste_files):
        """
        Nordic profile always have one or more netex file + one shared file.
        Read the files and create csv file in the ./CSV directory

        Parameters
        ----------
        main_liste_files : liste
            [list_of_netex_files, path_of_the_shared_file]

        Returns
        -------
        None.

        """
        #print(repr(main_liste_files[6:]))
        for liste_files, shared_file in main_liste_files:
            self.lib.process_shared(shared_file)
            for file in liste_files:
                self.lib.process_file(file)
                self.writer.process(self.lib)
        


    def process_directory(self, path):
        """
        Nordic netex file looks like this :
            VYG_R41.xml
            VYG_R45.xml
            _VYG_Shared.xml

        This function read all .xml files in the given directory
        If a file contains "Shared" it will load this file and all the files with
        the same prefix and send  them to self.process

        Parameters
        ----------
        path :  text
        The directory path to find the netex files.

        Returns
        -------
        None.

        """
        for shared_file in glob.glob(path+"/_*.xml"):
            shared_name = shared_file.split('_')[1]
            liste_file = []
            for file2 in glob.glob(path+"/"+shared_name+"*.xml"):
                liste_file.append(file2)
            main_liste = [(liste_file, shared_file)]
            self.process(main_liste)
        self.writer.close()

def main():
    netex2csv = Netex2csv()
    netex2csv.process_directory('./NETEX')
if __name__ == "__main__":
    main()
    
    