# -*- coding: utf-8 -*-
"""
Path of the node used in the netex file
"""
SERVICE_FRAME = ['PublicationDelivery', 'dataObjects', 'CompositeFrame', 'frames', 'ServiceFrame']
JOURNEY_PATTERN = SERVICE_FRAME + ['journeyPatterns', 'JourneyPattern']
STOP_POINT_IN_JP = JOURNEY_PATTERN + ['pointsInSequence']
STOP_POINT = JOURNEY_PATTERN + ['pointsInSequence', 'StopPointInJourneyPattern', 'ScheduledStopPointRef']
TIMETABLE_FRAME = ['PublicationDelivery', 'dataObjects', 'CompositeFrame',\
                   'frames', 'TimetableFrame']
SERVICE_JOURNEY = TIMETABLE_FRAME + ['vehicleJourneys', 'ServiceJourney']
TRAIN_NUMBER = TIMETABLE_FRAME + ['trainNumbers', 'TrainNumber']
SERVICE_CALENDAR = ['PublicationDelivery', 'dataObjects', 'CompositeFrame',\
                    'frames', 'ServiceCalendarFrame']
RESSOURCE_FRAME = ['PublicationDelivery', 'dataObjects', 'CompositeFrame',\
                   'frames', 'ResourceFrame']
VALIDITY = ['PublicationDelivery', 'dataObjects', 'CompositeFrame',\
            'validityConditions', 'AvailabilityCondition']
OPERATOR = ['PublicationDelivery', 'dataObjects', 'CompositeFrame',\
            'frames', 'ResourceFrame', 'organisations', 'Operator']
PASSENGER_STOP_ASSIGNMENTS = ['PublicationDelivery', 'dataObjects', 'CompositeFrame',\
                    'frames', 'ServiceFrame', 'stopAssignments', 'PassengerStopAssignment']
STOP_ROUTE_POINTS = ['PublicationDelivery', 'dataObjects', 'CompositeFrame',\
                    'frames', 'ServiceFrame', 'routePoints', 'RoutePoint']
BORDER_POINTS=['PublicationDelivery', 'dataObjects', 'CompositeFrame',\
                    'frames', 'FareFrame', 'borderPoints', 'BorderPoint']
OPERATING_DAYS = SERVICE_CALENDAR + ['operatingDays', 'OperatingDay']
DATED_SERVICE_JOURNEY = TIMETABLE_FRAME + ['vehicleJourneys', 'DatedServiceJourney']
FACILITY = TIMETABLE_FRAME + ['serviceFacilitySets', 'ServiceFacilitySet'] 
#LOCATIONS
STOP_PLACE =['PublicationDelivery', 'dataObjects', 'SiteFrame', 'stopPlaces', 'StopPlace']
QUAY =['quays', 'Quay']