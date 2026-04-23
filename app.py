# -*- coding: utf-8 -*-
"""
Created on Mon Jan  9 14:30:09 2023

@author: hfjelstad
"""

import os
import NeTEx_to_SKDUPD as n2s
from slack_bolt import App
from flask import Flask, request, Response
from threading import Thread
#from journeyPlannerHandling import RealtimeTrainNumber
#from cred import SLACK_SECRET,SLACK_TOKEN

SLACK_TOKEN = os.getenv("SLACK_TOKEN")
SLACK_SECRET = os.getenv("SLACK_SECRET")
#rtn = RealtimeTrainNumber()

#FLASK - Listen for POST from slack and route "text"
flask = Flask(__name__)
"""
def handler(requests):
    print("handler ok")
    print(requests['channel_id'])
    rtn.trainNumber(requests['channel_id'], requests['text'])
    print(requests['text'])
 """   
def dick_handler(dic):
    env = str(dic['text'])
    print(env)
    n2s.main(env)
"""    
@flask.route('/slack/RT', methods=['POST'])
def respond():
    #getDict = request.form.to_dict(flat=False)
    rtn.requestHandler(request.form.to_dict(flat=False))
    #RealtimeTrainNumber.requestHandler(request.form.to_dict(flat=False))
    #rtn.requestHandler(request.form.to_dict(flat=False))
    return Response(status="200")
"""
@flask.route('/slack/UIC', methods=['POST'])
def respond():
    Thread(target=dick_handler, args=(request.form.to_dict(flat=False), )).start()
    return Response(status="200")

#FLASK - END
#SLACK - Initializes your app with your bot token and signing secret
app = App(
    token=SLACK_TOKEN,
    signing_secret=SLACK_SECRET
)

if __name__ == "__main__":
    flask.run(port=int(os.environ.get("PORT", 3000)))
