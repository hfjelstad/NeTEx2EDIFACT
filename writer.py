    # -*- coding: utf-8 -*-
"""
This module is used to write csv files from netex dictionnaries.
'./CSV/SKDUPD_TRAIN.csv'
'./CSV/SKDUPD_POR.csv'
'./CSV/SKDUPD_ODI.csv'
'./CSV/SKDUPD_RELATION.csv'

These files can then be converted in EDIFACT
"""
import csv
import datetime
import copy

def create_bit_dates(liste_date):
    """
    Convert a list of operating days from the format YYYY-MM-DD to the UIC format
    110000111 where 1 means operating day and 0 means not operating.

    Args:
        liste_date (list) : list of operating days YYYY-MM-DD

    Returns:
        string: operating days in bits format.
    """
    begin = liste_date[0]
    end = liste_date[-1]
    begin = datetime.datetime(int(begin[:4]), int(begin[5:7]), int(begin[8:10]))
    end = datetime.datetime(int(end[:4]), int(end[5:7]), int(end[8:10]))
    current = begin
    bits = ''
    stopCondition = ''
    while stopCondition != 'true':
        current_date = current.strftime('%Y-%m-%d')
        if current_date in liste_date:
            bits += '1'
        else:
            bits += '0'
        if current == end:
            stopCondition = 'true'
        current += datetime.timedelta(1)
    return bits


class Writer:
    """
    Main class to write csv file from the netex nordic profile
    """
    def __init__(self):
        self.cpt = 0
        self.missing_uic = {}
        self.dic_warnings = {}
        self.init_files()

    def process(self, lib):
        """
        Read the netex_lib dictionnaries to create the MERITS csv files
        """
        for ID in lib.dic_service:
            self.cpt += 1
            self.process_train(self.cpt, ID, lib)
            self.process_stops(self.cpt, ID, lib)
            self.process_odi(self.cpt, ID, lib)
            self.process_relation(self.cpt, ID, lib)

    def close(self):
        """
        Close the csv files

        Returns
        -------
        None.

        """
        self.file_train.close()
        self.file_stops.close()
        self.file_relation.close()
        self.file_odi.close()

        if len(self.missing_uic) >= 1:
            print('Please, add the UIC code for this netex codes :')
            print(repr(list(self.missing_uic)))

    def init_files(self):
        """
        Open the csv files in the ./CSV/ directory

        Returns
        -------
        None.

        """
        self.file_train = open('./CSV/SKDUPD_TRAIN.csv', 'w', newline='')
        self.writer_train = csv.writer(self.file_train, delimiter=';')
        self.writer_train.writerow(['ID', 'Service_number', 'Reservation', \
                              'Tariff', 'Service_Mode', 'Service_Name', \
                              'Service_Provider', 'not_used', 'Reservation_system', \
                              'First_day', 'Last_day', 'Operation_days', 'Second_service_number'])

        self.file_stops = open('./CSV/SKDUPD_POR.csv', 'w', newline='')
        self.writer_stops = csv.writer(self.file_stops, delimiter=';')
        self.writer_stops.writerow(['ID', 'Stop_number', 'UIC', 'Arrival_time', \
                              'Arrival_offset', 'Departure_time', 'Departure_offset', \
                              'Platform_arrival', 'Platform_departure', 'Stop_property', \
                              'Traffic_restriction', 'Distance', 'Loading_vehicles', \
                              'Unloading_vehicles', 'check_out', 'check_in'])

        self.file_odi = open('./CSV/SKDUPD_ODI.csv', 'w', newline='')
        self.writer_odi = csv.writer(self.file_odi, delimiter=';')
        self.writer_odi.writerow(['ID', 'FromStopNumber', 'ToStopNumber',\
                                  'ASD_or_SER_or_TFF', 'Reservation_in_equipment',\
                                      'Equipment', 'Tariff_in_equipment'])

        self.file_relation = open('./CSV/SKDUPD_RELATION.csv', 'w', newline='')
        self.writer_relation = csv.writer(self.file_relation, delimiter=';')
        self.writer_relation.writerow(['ID', 'Stop_number', 'Service', 'Relation',\
                                       'Transfer_time', 'Certainty'])

    def process_train(self, CPT, ID, lib):
        """
        Add one train in the file SKDUPD_TRAIN.csv

        Parameters
        ----------
        CPT : int
            unique ID for a train in the CSV files
        ID : string
            ID of the train in the netex file
        lib : netex_lib
            The netex_lib with the netex data

        Returns
        -------
        None.

        """
        dic_train = {'ID':'',
                     'Service_number':'',
                     'Reservation':'',
                     'Tariff':'',
                     'Service_mode':'',
                     'Service_name':'',
                     'Service_provider':'',
                     'Information_provider':'',
                     'Reservation_company':'',
                     'First_day':'',
                     'Last_day':'',
                     'Operating_days':'',
                     'Second_service_number':''
                     }
        blacklist = "93","94","95","96"
        dic_train['ID'] = CPT
        dic_train['Service_number'] = lib.dic_service[ID]['Service_number']
        dic_train['Service_mode'] = lib.dic_service[ID]['Service_mode']
        dic_train['Reservation_company'] = '92'
        dic_train['Service_provider'] = lib.dic_operator[lib.dic_service[ID]['Service_provider']]
        for n in blacklist:
            if dic_train['Service_number'] == n:
                dic_train['Reservation_company'] = ''
        if 'Second_service_number' in lib.dic_service[ID]:
            dic_train['Second_service_number'] = lib.dic_service[ID]['Second_service_number']

        liste_date = []
        
        for date in lib.dic_dated_service[ID]:
            if date != 'null':
                liste_date.append(lib.dic_operating_days[date])
        liste_date.sort()
        if bool(liste_date):
            dic_train['First_day'] = liste_date[0]
            dic_train['Last_day'] = liste_date[-1]
            dic_train['Operating_days'] = create_bit_dates(liste_date)
        else:
            dic_train['First_day'] = '2017-09-22'
            dic_train['Last_day'] = '2017-09-22'
            dic_train['Operating_days'] = '1'

        if 'Facility' in lib.dic_service[ID]:
            for facility in lib.dic_service[ID]['Facility']:
                if facility[0] == 'R':
                    dic_train['Reservation'] = facility[1:]
        self.writer_train.writerow(list(dic_train.values()))

    def process_stops(self, CPT, ID, lib):
        """
        Add stops in the file SKDUPD_POR.csv

        Parameters
        ----------
        CPT : int
            unique ID for a train in the CSV files
        ID : string
            ID of the train in the netex file
        lib : netex_lib
            The netex_lib with the netex data

        Returns
        -------
        None.

        """
        for cpt, (stopPatternID, arrival, arrivalPlatform, offset_A, departure, departurePlatform, offset_D) \
            in enumerate(lib.dic_timetable[ID]):
            is_border = False
            dic_por = {'ID':'',
                       'cpt':'',
                       'UIC':'',
                       'Arrival_time':'',
                       'Offset_arrival':'',
                       'Departure_time':'',
                       'Offset_departure':'',
                       'Platform_arrival':'',
                       'Platform_departure':'',
                       'Stop_property':'',
                       'Traffic_restriction':'',
                       'Distance':'',
                       'Loading':'',
                       'Unloading':'',
                       'Check_out':'',
                       'Check_in':''
                       }
            dic_por['ID'] = CPT
            stop_netex, restrictions, additional_information = lib.dic_journey_pattern[stopPatternID]
            try:
                UIC, is_border = lib.dic_stop_assignments[stop_netex]
            except KeyError:
                self.missing_uic[stop_netex] = 1
                UIC='MISSING-UIC'
                #UIC='007602324'
                is_border=False
                #continue
            dic_por['UIC'] = UIC
            if is_border:
                additional_information = '17'
            dic_por['cpt'] = cpt+1
            dic_por['Arrival_time'] = arrival
            dic_por['Platform_arrival'] = arrivalPlatform
            dic_por['Offset_arrival'] = offset_A
            dic_por['Departure_time'] = departure
            dic_por['Platform_departure'] = departurePlatform
            dic_por['Offset_departure'] = offset_D
            dic_por['Stop_property'] = additional_information
            dic_por['Traffic_restriction'] = restrictions
            self.writer_stops.writerow(list(dic_por.values()))

    def process_odi(self, CPT, ID, lib):
        """
        Add service data in the file SKDUPD_ODI.csv

        Parameters
        ----------
        CPT : int
            unique ID for a train in the CSV files
        ID : string
            ID of the train in the netex file
        lib : netex_lib
            The netex_lib with the netex data

        Returns
        -------
        None.

        """
        stop_count = 1
        dic_odi = {'ID':'',
                   'From':'',
                   'To':'',
                   'ASD_or_SER_code':'',
                   'Reservation':'',
                   'Equipment':'',
                   'Tariff':''
               }
        dic_odi['ID'] = CPT
        if 'part' in lib.dic_service[ID]:
            for part in lib.dic_service[ID]['part']:
                dic_odi['From'] = str(stop_count)
                if lib.dic_journey_parts[part][1]==None:
                    continue
                stop_count += lib.dic_journey_parts[part][1]
                #print(ID + " " + str(lib.dic_journey_parts[part][0]) + " " + str(stop_count))
                dic_odi['To'] = str(stop_count)
                if lib.dic_journey_parts[part][2]!='':   
                    for fac in lib.dic_facility[lib.dic_journey_parts[part][2]]:
                        tag = fac[:4]
                        if tag == '7161':
                            value = 'S'+fac[5:]
                        elif tag == '9039':
                            value = 'F'+fac[5:]
                        elif tag == '7037':
                            value = 'R'+fac[5:]
                        else:
                            if fac in lib.mapping_facility:
                                value = lib.mapping_facility[fac]
                            else:
                                if fac not in self.dic_warnings:
                                    print('Warning : ',fac,'not in the mapping file')
                                    self.dic_warnings[fac]=1
                                continue
                        new_dic = copy.deepcopy(dic_odi)
                        if value[0] == 'R':
                            new_dic['Reservation'] = value[1:]
                        else:
                            new_dic['ASD_or_SER_code'] = value
                        self.writer_odi.writerow(list(new_dic.values()))
                """ 
                else:
                    new_dic = copy.deepcopy(dic_odi)
                    new_dic['Equipment'] = brand
                    self.writer_odi.writerow(list(new_dic.values()))
                """
                
        else:
            print('No parts found')
        dic_odi['From'] = '1'
        dic_odi['ASD_or_SER_code'] = ''
        dic_odi['Reservation'] =''
        dic_odi['Equipment'] = lib.dic_service[ID]['Brand']
        self.writer_odi.writerow(list(dic_odi.values()))
   
             
    def process_relation(self, CPT, ID, lib):
        """
        Should add the relation in the file SKDUPD_RELATION.csv.
        Not implemented

        Parameters
        ----------
        CPT : int
            unique ID for a train in the CSV files
        ID : string
            ID of the train in the netex file
        lib : netex_lib
            The netex_lib with the netex data

        Returns
        -------
        None.

        """
        dic_relation = {'ID':'',
                        'Stop_position':'',
                        'Service':'',
                        'Relation':'',
                        'Transfer_time':'',
                        'Certainty':''
                        }
