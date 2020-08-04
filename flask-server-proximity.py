
import time
import board
import busio
import adafruit_vl53l0x

from flask import Flask, render_template, Response
import sys
from statistics import mean

import requests
import threading

# Initialize I2C bus and sensor.
i2c = busio.I2C(board.SCL, board.SDA)
vl53 = adafruit_vl53l0x.VL53L0X(i2c)

# Optionally adjust the measurement timing budget to change speed and accuracy.
# See the example here for more details:
#   https://github.com/pololu/vl53l0x-arduino/blob/master/examples/Single/Single.ino
# For example a higher speed but less accurate timing budget of 20ms:
# vl53.measurement_timing_budget = 20000
# Or a slower but more accurate timing budget of 200ms:
#vl53.measurement_timing_budget = 200000

vl53.measurement_timing_budget = 100000 #100ms timing budget
# The default timing budget is 33ms, a good compromise of speed and accuracy.

#Flask server setup
app = Flask(__name__)

# Global status definitions
previous_status = 'IDLE'
#wash_time = 0
#wash_buffer_time = 0
#done_buffer_time = 0

wakeFlag = False

LAUNCH_TIME = time.time()

idle_start_time = LAUNCH_TIME
wash_start_time = LAUNCH_TIME
done_start_time = LAUNCH_TIME
wash_idle_start_time = LAUNCH_TIME

TEMPORAL_SMOOTHING_ARRAY_LENGTH = 5

# Distance Constants
PERSON_DETECTION_THRESHOLD = 5000 #Updated to account for smoothing from 2000mm or 200cm
WAVE_DETECTION_THRESHOLD = 300 #Updated to account for smoothing from 200mm or 20cm

# Time Constants
IDLE_TIMEOUT_PERIOD = 10 #seconds
WASH_TIMEOUT_PERIOD = 4 #seconds
DONE_TIMEOUT_PERIOD = 4 #seconds

WASH_GIF_LENGTH = 25.5 #seconds

last_ten_readings = []

# Logging values
deviceSerialNumber = 'xxxxxxxxx1'
loggingServerURL = 'http://76.95.244.164:5000/'

# DEFINE THREADING class
class loggingThread (threading.Thread):
   def __init__(self, logEventType):
      threading.Thread.__init__(self)
      self.logEventType = logEventType

   def run(self):
      #print ("Starting thread")
      #print_time(self.name, self.counter, 5)
      logStatus(self.logEventType)
      #print ("Exiting thread")

# METHOD DEFINITIONS
def buildLogURL(eventIDCode):
    return loggingServerURL+'log-event?deviceID='+deviceSerialNumber+'&logEventID='+str(eventIDCode)

def logStatus(logStatusIndex):
    # log_status_indices
    # 1 = Initialized
    # 2 = Wake-Homescreen-Sleep
    # 3 = Wake-Homescreen-Wave-Incomplete
    # 4 = Wake-Homescreen-Wave-Complete
    # 5 = Homescreen-Sleep
    # 6 = Homescreen-Wave-Incomplete
    # 7 = Homescreen-Wave-Complete

    logURL = buildLogURL(logStatusIndex)

    try:
        post_request = requests.post(logURL)
    except requests.exceptions.RequestException as e:
        #raise SystemExit(e) #raise error and exit
        print ("Error connecting to logging server")
    
    #print(post_request.text) #TODO: Remove prints

def get_message():
    global previous_status

    # any function that blocks until data is ready - MAIN DETECTION FUNCTION
    #time.sleep(1.0)

    sensor_reading = triggerSensor() # returns 0, 1, or 2

    statusReturn = updateStatus(sensor_reading)
    #print('Previous Status: '+ previous_status + ' Current Status: '+ statusReturn[1] + ' Status Change Flag: ' + statusReturn[0])


    while (statusReturn[0]=='N'):
        sensor_reading = triggerSensor()
        statusReturn = updateStatus(sensor_reading)
        #print('Previous Status: '+ previous_status + ' Current Status: '+ statusReturn[1] + ' Status Change Flag: ' + statusReturn[0])

    #print('What message would you like to send the browser?')

    message = statusReturn[1]
    #print('Sending message to UI: ' + message)

    previous_status = statusReturn[1]

    return message

# Read sensor and return 2 if nothing detected, 1 if non-waving person detected, and 0 if waving detected
def triggerSensor():
    global last_ten_readings
    sensed_classifier = -1

    sensed_range = vl53.range

    last_ten_readings.append(sensed_range)

    if (len(last_ten_readings)>TEMPORAL_SMOOTHING_ARRAY_LENGTH):
        last_ten_readings.pop(0)

    temporally_smoothed_readings = mean(last_ten_readings)

    if (temporally_smoothed_readings > PERSON_DETECTION_THRESHOLD):
        sensed_classifier = 2
    elif (temporally_smoothed_readings <= PERSON_DETECTION_THRESHOLD and temporally_smoothed_readings > WAVE_DETECTION_THRESHOLD):
        sensed_classifier = 1
    elif (temporally_smoothed_readings <= WAVE_DETECTION_THRESHOLD):
        sensed_classifier = 0
    else:
        print('Invalid range sensed')


    # if (sensed_range > PERSON_DETECTION_THRESHOLD):
    #     sensed_classifier = 2
    # elif (sensed_range <= PERSON_DETECTION_THRESHOLD and sensed_range > WAVE_DETECTION_THRESHOLD):
    #     sensed_classifier = 1
    # elif (sensed_range <= WAVE_DETECTION_THRESHOLD):
    #     sensed_classifier = 0
    # else:
    #     print('Invalid range sensed')

    #print("Detected Range is: "+ str(sensed_range) +" | Smoothed Range is: " + str(temporally_smoothed_readings) + " | Sensed Classifier is: "+ str(sensed_classifier))
    return sensed_classifier

# Update handwashing status
def updateStatus(action_index):
    global previous_status
    global idle_start_time
    global wash_start_time
    global wash_idle_start_time
    global done_start_time
    global wakeFlag

    current_status = 'INIT'
    status_change_flag = 'N'

    #print('IN updateStatus | Previous Status: '+previous_status+' Action Index: '+str(action_index))
    # Read sensor and return 0 if nothing detected, 1 if non-waving person detected, and 2 if waving detected

    if ((previous_status == 'INIT') or (previous_status == 'IDLE')):
        if action_index == 0:
            current_status = 'INWASH'
            status_change_flag = 'Y'
            wash_start_time = time.time()
            idle_start_time = LAUNCH_TIME
        elif action_index == 1:
            #reset & start blackout Timer
            idle_start_time = time.time()
        elif action_index == 2:
            # if blackout timer > blackout time set status to BLACK and stop blackput timer; else do nothing
            if (idle_start_time == LAUNCH_TIME):
                idle_start_time = time.time()
            elif (time.time() - idle_start_time >= IDLE_TIMEOUT_PERIOD):
                #print (time.time() - idle_start_time)
                idle_start_time = LAUNCH_TIME
                current_status = 'BLACK'
                status_change_flag = 'Y'
                #logStatus(2) #log sleep
                if (wakeFlag): #NEW
                    loggingThread(2).start()
                    wakeFlag = False
                else:
                    loggingThread(5).start()
    elif (previous_status == 'BLACK'):
        if ((action_index == 0) or (action_index == 1)):
            current_status = 'IDLE'
            status_change_flag = 'Y'
            #logStatus(3) #log wake
            wakeFlag = True
            loggingThread(3).start()
        # elseif action_index == 2, do nothing
    elif (previous_status == 'INWASH'):
        if ((action_index == 0) or (action_index == 1)):
            # if time has exceeded WASH_GIF_LENGTH, send to DONE screen; else do nothing
            if (time.time() - wash_start_time >= WASH_GIF_LENGTH):
                #print(time.time() - wash_start_time)
                wash_start_time = LAUNCH_TIME
                current_status = 'DONE'
                status_change_flag = 'Y'
                #loggingThread(5).start() #log wake-wave-complete
                if (wakeFlag): #NEW
                    loggingThread(4).start()
                    wakeFlag = False
                else:
                    loggingThread(7).start()
        if (action_index == 2):
            # if buffer time is expired, send to home screen
            if (wash_idle_start_time == LAUNCH_TIME):
                wash_idle_start_time = time.time()
            elif (time.time() - wash_idle_start_time >= WASH_TIMEOUT_PERIOD):
                current_status = 'IDLE'
                status_change_flag = 'Y'
                wash_idle_start_time = LAUNCH_TIME
                #loggingThread(4).start() #log wake-wave-incomplete
                if (wakeFlag): #NEW
                    loggingThread(3).start()
                    wakeFlag = False
                else:
                    loggingThread(6).start()
    elif (previous_status == 'DONE'):
        # Handle 0, 1, 2 cases
        if (action_index == 0):
            current_status = 'INWASH'
            status_change_flag = 'Y'
            wash_start_time = time.time()
        elif ((action_index == 1) or (action_index == 2)):
            if (done_start_time == LAUNCH_TIME):
                done_start_time = time.time()
            elif (time.time() - done_start_time >= DONE_TIMEOUT_PERIOD):
                current_status = 'IDLE'
                status_change_flag = 'Y'
                done_start_time = LAUNCH_TIME

    return [status_change_flag, current_status]


############# End method definitions #########

# FLASK ROUTES
@app.route('/')
def initApplication():
    #return 'Hello, World!'
    #time.sleep(5) # wait 5 seconds for network to be initialized - removed because raspi-config allows waiting til network is initialized
    print('At init logging step!')
    logStatus(1) #log init
    #loggingThread(1).start()
    return render_template('gui-v2.html')

@app.route('/stream')
def stream():
    def eventStream():
        while True:
            # poll for changes
            # wait for source data to be available, then push it
            yield 'data: {}\n\n'.format(get_message())
    return Response(eventStream(), mimetype="text/event-stream")


if __name__=='__main__':
    # SPIN UP FLASK SERVER
    app.debug = True
    app.run(threaded=True)

# Loop for detecting changes
# while True:
#     print("Range: {0}mm".format(vl53.range))
