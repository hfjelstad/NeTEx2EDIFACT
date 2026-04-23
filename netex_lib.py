# -*- coding: utf-8 -*-
"""
this module  is used to read netex file (Norway profile) and extract the data
needed to convert them in EDIFACT.

"""
import csv
import xmltodict
import locations
from toolz.dicttoolz import get_in
from constants import VALIDITY, OPERATOR, STOP_ROUTE_POINTS, \
OPERATING_DAYS, JOURNEY_PATTERN, SERVICE_JOURNEY, DATED_SERVICE_JOURNEY, \
TRAIN_NUMBER, FACILITY, PASSENGER_STOP_ASSIGNMENTS, STOP_POINT_IN_JP

def count_stops(service, journeyPattern, start_loc, end_loc):
    """
    Count the number of stops in passingTimes between two times.
    Return the number of stops minus one.

    Parameters
    ----------
    service : dictionary
        The netex ServiceJourney dictionary
    start : string
        The departure time HH:MM:SS
    end : string
        The arrival time HH:MM:SS
    offset_start : string
        The departure offset
    offset_end : string
        The arrival offset

    Returns
    -------
    cpt : int
        The number of stops -1

    """
    
    cpt = None
    start_order = None
    end_order = None
    start_count = False
    cpt_v2 = 0
    for StopPointInJourneyPattern in get_in_list(['pointsInSequence', 'StopPointInJourneyPattern'], journeyPattern):
        if start_count == True:
            cpt_v2 += 1
        if StopPointInJourneyPattern['ScheduledStopPointRef']['@ref'] == start_loc['@ref']:
            start_order = StopPointInJourneyPattern['@order']
            start_count = True
        elif StopPointInJourneyPattern['ScheduledStopPointRef']['@ref'] == end_loc['@ref']:
            end_order = StopPointInJourneyPattern['@order']
            start_count = False
    try:
        cpt = int(end_order) - int(start_order)
    except:
        cpt = 1
    if cpt != cpt_v2:
        print(str(cpt) + " " + str(cpt_v2) + " " + journeyPattern['@id'])
        cpt = cpt_v2
    return cpt
    


def convert_time(time):
    """
    Convert time from the format HH:MM:SS to the format HHMM

    Args:
        time (string) : time with the format HH:MM:SS

    Returns:
        string: time with the format HHMM
    """
    return time[:2]+time[3:5]

def read_netex(file):
    print(file)
    """
    Try to convert an xml file to dictionnary.
    Try encoding utf-8 and utf-16

    Args:
        file (string) : the path of the file

    Returns:
        dict
    """
    try:
        with open(file, encoding='utf-8') as fd:
            return xmltodict.parse(fd.read())
    except UnicodeDecodeError:
        with open(file, encoding="utf-16") as fd:
            return xmltodict.parse(fd.read())

def get_in_list(keys, dic):
    """
    get_in_list is a generalization of get_in from toolz.dicttoolz
    Always return a list.

    Args:
        keys (list) : the searched nested keys
        dic (dict) : the dict we want to search

    Returns :
        list
    """
    data = get_in(keys, dic)
    if data is None:
        return []
    if not isinstance(data, list):
        return [data]
    return data

def process_key_value(liste, key):
    """
    Return the value of a KeyValue list for a given key
    <KeyValue>
        <Key>9039</Key>
        <Value>55</Value>
    </KeyValue>

    Parameters
    ----------
    liste : list
        The netext Key/Value list
    key : string
        The searched key

    Returns
    -------
    String
        The value of the key

    """
    for elem in liste:
        if elem['Key'] == key:
            return elem['Value']

class NetexLib:
    """
    Main class to read netex nordic profile
    """

    def __init__(self):
        self.config_path = './Configuration/'
        self.dic_shared = {}
        self.dic_locations = locations.quay_dic()
        self.dic_file = {}
        self.mapping_service_mode = {}
        self.mapping_facility = {}
        self.mapping_brand = {}
        self.dic_warnings = {}
        self.load_mapping_files()

    def load_mapping_files(self):
        """
        Read the file:
            mapping_service_mode.txt
            mapping_facility.txt
            mapping_brand.txt
        and load them in the dictionaries:
            self.mapping_service_mode
            self.mapping_facility
            self.mapping_brand
        """
        liste = [(self.mapping_service_mode, "mapping_service_mode.txt"),
                 (self.mapping_facility, "mapping_facility.txt"),
                 (self.mapping_brand, 'mapping_brand.txt')]
        for dic, file in liste:
            with open('./Configuration/'+file, encoding='utf-8') as fd:
                reader = csv.reader(fd, delimiter=':', quotechar='"')
                for k, v in reader:
                    dic[k] = v

    def process_shared(self, shared_file):
        """
        Read a netex shared file and extract the needed data.
        """
        self.dic_shared = read_netex(shared_file)
        #self.tupple_validity = self.shared_validity()
        self.dic_operator = self.shared_operator()
        self.dic_stop_assignments = self.shared_stop_assignments()
        self.dic_operating_days = self.shared_operationg_days()

    def shared_validity(self):
        """
        Returns
        -------
        Tupple (FromDate,ToDate)

        """
        for validity in get_in_list(VALIDITY, self.dic_shared):
            from_date = validity['FromDate'].split('T')[0]
            to_date = validity['ToDate'].split('T')[0]
        return (from_date, to_date)

    def shared_operator(self):
        """
        Returns
        -------
        dictionary operator_ID -> RICS_CODE 
        """
        dic_operator = {}
        for operator in get_in_list(OPERATOR, self.dic_shared):
            ID = operator['@id']
            RICS = process_key_value(get_in_list(['keyList', 'KeyValue'], operator), 'RICS code')
            dic_operator[ID] = RICS
        return dic_operator

    def shared_stop_assignments(self):
        """
        Returns
        -------
        dictionary  stop_ID -> UIC_code 
        """
        dic_stops = {}
        dic_stops['borderpoint'] = []

        for route_point in get_in_list(STOP_ROUTE_POINTS, self.dic_shared):
            border = False
            ID = route_point['@id']
            if 'BorderCrossing' in route_point and route_point['BorderCrossing'] == 'true':
                border = True
            UIC = None
            if 'keyList' in route_point and 'KeyValue' in route_point['keyList']:
                UIC = process_key_value(get_in_list(['keyList', 'KeyValue'], route_point), 'UIC')
                dic_stops[ID] = (UIC, border)

            for projection in get_in_list(['projections', 'PointProjection'], route_point):
                ref = projection['ProjectedPointRef']['@ref']
                if UIC is not None:
                    dic_stops[ref] = (UIC, border)
        return dic_stops

    def shared_operationg_days(self):
        """
        Returns
        -------
        dictionary  day_ID -> YYYY-MM-DD 
        """
        dic_operating_days = {}
        for sc in get_in_list(OPERATING_DAYS, self.dic_shared):
            ID = sc['@id']
            date = sc['CalendarDate']
            dic_operating_days[ID] = date
        return dic_operating_days


    def process_file(self, file):
        """
        Read a netex not shared file and extract the needed data.
        """
        self.dic_file = read_netex(file)
        self.dic_train_number = self.file_number_train()
        self.dic_journey_parts = self.file_journey_parts()
        self.dic_journey_pattern, self.dic_mapping_stop = self.file_journey_pattern()
        self.dic_timetable = self.file_timetable()
        self.dic_service = self.file_service_journey()
        self.dic_dated_service = self.file_dated_service_journey()
        self.dic_facility = self.file_facility()

    def file_journey_pattern(self):
        """
        Returns
        -------
        dictionaries dic_journey_pattern, dic_mapping_stop
        """
        dic_journey_pattern = {}
        dic_mapping_stop = {}
        for journey_pattern in get_in_list(JOURNEY_PATTERN, self.dic_file):
            for stop_point in get_in_list(['pointsInSequence', \
                                           'StopPointInJourneyPattern'], journey_pattern):
                ID2 = stop_point['@id']
                stop_ref = stop_point['ScheduledStopPointRef']['@ref']
                dic_mapping_stop[ID2] = stop_ref
                dic_journey_pattern[ID2] = [stop_ref]
                restriction = additional_information = ''

                if 'ForAlighting' in stop_point and 'ForBoarding' in stop_point:
                    if stop_point['ForAlighting'] == 'false' and \
                       stop_point['ForBoarding'] == 'false':
                        restriction = '4'
                elif 'ForAlighting' in stop_point and stop_point['ForAlighting'] == 'false':
                    restriction = '1'
                elif 'ForBoarding' in stop_point and stop_point['ForBoarding'] == 'false':
                    restriction = '2'
                if 'StopOnRequest' in stop_point and stop_point['StopOnRequest'] == 'true':
                    additional_information = '230'
                #if 'BorderPoint' in stop_point and stop_point['BorderPoint'] == 'true':
                #    additional_information = '17'
                dic_journey_pattern[ID2] = dic_journey_pattern[ID2] \
                    + [restriction, additional_information]
        return dic_journey_pattern, dic_mapping_stop

    def file_timetable(self):
        """
        Returns
        -------
        dict dic_timetable
        """
        dic_timetable_passing_time = {}
        for service_journey in get_in_list(SERVICE_JOURNEY, self.dic_file):
            ID = service_journey['@id']
            last_offset=''
            dic_timetable_passing_time[ID] = []
            for passingTime in get_in_list(['passingTimes', 'TimetabledPassingTime'], service_journey):
                stop_ref = passingTime['StopPointInJourneyPatternRef']['@ref']
                quayPublicCode = ''

                for jp in get_in_list(JOURNEY_PATTERN, self.dic_file):
                    for pointsInSeq in get_in_list(['pointsInSequence'], jp):
                        for stopPoint in get_in_list(['StopPointInJourneyPattern'], pointsInSeq):    
                            if stopPoint['@id'] == stop_ref:
                                scheduledSP = stopPoint['ScheduledStopPointRef']['@ref']
                                for PassengerStop in get_in_list(PASSENGER_STOP_ASSIGNMENTS, self.dic_shared):
                                    if scheduledSP == PassengerStop['ScheduledStopPointRef']['@ref']:
                                        try:
                                            quayPublicCode = self.dic_locations[PassengerStop['QuayRef']['@ref']]
                                        except:
                                            pass

                arrival = arrivalPlatform = departure = departurePlatform = offset_A = offset_D = ''
                if 'ArrivalTime' in passingTime:
                    arrival = convert_time(passingTime['ArrivalTime'])
                    arrivalPlatform = quayPublicCode
                if 'DepartureTime' in passingTime:
                    departure = convert_time(passingTime['DepartureTime'])
                    departurePlatform = quayPublicCode
                if 'ArrivalDayOffset' in passingTime:
                    offset_A = passingTime['ArrivalDayOffset']
                    if offset_A==last_offset:
                        offset_A=''
                    else:
                        offset_A='1'
                    last_offset = passingTime['ArrivalDayOffset']
                if 'DepartureDayOffset' in passingTime:
                    offset_D = passingTime['DepartureDayOffset']
                    if offset_D==last_offset:
                        offset_D=''
                    else:
                        offset_D='1'
                    last_offset = passingTime['DepartureDayOffset']
                dic_timetable_passing_time[ID] = dic_timetable_passing_time[ID] \
                    + [(stop_ref, arrival, arrivalPlatform, offset_A, departure, departurePlatform, offset_D)]
        return dic_timetable_passing_time

    def file_service_journey(self):
        """
        Returns
        -------
        dictionary dic_service_journey
        """
        dic_service_journey = {}
        for service_journey in get_in_list(SERVICE_JOURNEY, self.dic_file):
            ID = service_journey['@id']
            dic_service_journey[ID] = {}
            service_mode = service_journey['TransportMode']
            service_mode = self.mapping_service_mode[service_mode]
            service_provider = service_journey['OperatorRef']['@ref']
            try:
                value=list(service_journey['TransportSubmode'].values())[0]
            except:
                pass
            privateCode = service_journey['PrivateCode']
            if value in self.mapping_brand:
                submode = self.mapping_brand[value]
            else:
                if value not in self.dic_warnings:
                    self.dic_warnings[value]=1
                    print('Warning : ',value,"not in the mapping file")
                submode=''
            dic_service_journey[ID]['Brand'] = submode
            dic_service_journey[ID]['Service_provider'] = service_provider
            dic_service_journey[ID]['part'] = []

            for journey_part in get_in_list(['parts', 'JourneyPart'], service_journey):
                ID2 = journey_part['@id']
                dic_service_journey[ID]['part'] = dic_service_journey[ID]['part']+[ID2]

            for journey_part in get_in_list(['parts', 'JourneyPartRef'], service_journey):
                ref = journey_part['@ref']
                dic_service_journey[ID]['part'] = dic_service_journey[ID]['part']+[ref]

            if 'parts' not in service_journey:
                #number = service_journey['TrainNumberRef']['@ref']
                train_number = self.dic_train_number[privateCode]
                number_of_stops=-1
                for passing_time in get_in_list(['passingTimes', 'TimetabledPassingTime'], service_journey):
                    number_of_stops += 1
                try:
                    facility = service_journey['facilities']['ServiceFacilitySetRef']['@ref']
                except KeyError:
                    facility = ''
                self.dic_journey_parts[ID] = (train_number, number_of_stops, facility)
                dic_service_journey[ID]['part']=[ID]

            
            service_number, second_service_number = self.dic_journey_parts[dic_service_journey[ID]['part'][0]][0]
            dic_service_journey[ID]['Second_service_number'] = second_service_number
            dic_service_journey[ID]['Service_number'] = privateCode
            dic_service_journey[ID]['Service_mode'] = service_mode
        return dic_service_journey

    def file_dated_service_journey(self):
        """
        Returns
        -------
        dictionary dic_dated_service_journey
        """
        dic_dated_service_journey = {}
        for dated_service_journey in get_in_list(DATED_SERVICE_JOURNEY, self.dic_file):
            ID = dated_service_journey['ServiceJourneyRef']['@ref']
            SA = ['']
            if ID not in dic_dated_service_journey:
                dic_dated_service_journey[ID] = []
            '''
            Added a check for "ServiceAlteration",
            used "try" since the element is not mandatory
            '''
            try:
                SA = dated_service_journey['ServiceAlteration']
            except KeyError:
                SA = ['']
            operating_day_ref = dated_service_journey['OperatingDayRef']['@ref']
            '''
            Added a handling of "ServiceAlteration",
            if the value is "replaced" or "cancellation" the reference is set to "null"
            this is to handle and ignore these objects in the writer.py
            '''
            if SA == 'replaced' or SA == 'cancellation':
                operating_day_ref = 'null'
            dic_dated_service_journey[ID] = dic_dated_service_journey[ID]\
                + [operating_day_ref]
        return dic_dated_service_journey

    def file_number_train(self):
        """
        Returns
        -------
        dictionary dic_number_train
        """
        dic_number_train = {}
        for train_number in get_in_list(TRAIN_NUMBER, self.dic_file):
            ID = train_number['@id']
            advert = train_number['ForAdvertisement']
            prod = ''
            """
            prod = train_number['ForProduction']
            if prod == advert:
                prod = ''
            """
            dic_number_train[ID] = (advert, prod)
        return dic_number_train

    def file_facility(self):
        """
        Returns
        -------
        dictionary dic_facility
        """
        dic_facility = {}
        for facility in get_in_list(FACILITY, self.dic_file):
            ID = facility['@id']
            dic_facility[ID] = []
            for key in facility.keys():
                if key in ['@version', '@id']:
                    pass
                elif key == 'keyList':
                    for k in facility['keyList']['KeyValue']:
                        dic_facility[ID] = dic_facility[ID]+[k['Key']+'_'+k['Value']]
                else:
                    for fac in facility[key].split(' '):
                        dic_facility[ID] = dic_facility[ID]+[fac]
        return dic_facility

    def lookup_journeyPattern(self, journeyPatternIdentifier):
        for x in get_in_list(JOURNEY_PATTERN, self.dic_file):
            if x['@id'] == journeyPatternIdentifier:
                return x
        
    
    def file_journey_parts(self):
        """
        Returns
        -------
        dictionary dic_journey_part
        """
        dic_journey_part = {}
        for service in get_in_list(SERVICE_JOURNEY, self.dic_file):
            journey_P_Ref = service['JourneyPatternRef']['@ref']
            journeyPattern = self.lookup_journeyPattern(journey_P_Ref)
            for journey_part in get_in_list(['parts', 'JourneyPart'], service):
                ID = journey_part['@id']
                number = journey_part['TrainNumberRef']['@ref']
                train_number = self.dic_train_number[number]
                try:
                    start_loc = journey_part['FromStopPointRef']
                except:
                    print(ID)
                end_loc = journey_part['ToStopPointRef']
                number_of_stops = count_stops(service, journeyPattern, start_loc, end_loc)
                try:
                    facility = journey_part['facilities']['ServiceFacilitySetRef']['@ref']
                except KeyError:
                    facility = ''
                dic_journey_part[ID] = (train_number, number_of_stops, facility)
        return dic_journey_part
                