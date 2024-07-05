"""
 Demo CircuitPython code for the iLabs Connectivity RP2040 LTE/WIFI/BLE board
 At the time of writing there was no CircuitPython build for this particular board -
 so I used the iLabs Connectivity RP2040 LTE version. This meant I had to define the pins for the ESP WiFi comms.
 
 - Note the board, at the time was a Major version behind on its ESP-AT chip (a year out of date).
 - My ESP-AT chip had version 2.3 and the current version at the time of buying the board was 3.3

- The code demonstrates WiFi (MQTT over WiFi), SMS (sending and receiving) and HTTP requests over LTE and WiFi.

 John Wilson, Sussex 2024
 
"""
import board
import busio
import digitalio
import time
import microcontroller
from digitalio import DigitalInOut
from digitalio import Direction
from adafruit_espatcontrol import adafruit_espatcontrol

import asyncio
from queue import Queue
import binascii
import json
import rtc
import time


GRAB_WEB_PAGE_DEMO = True
PING_DEMO=True


example_post= [
        "ATE0\r\n",
        "AT+CMEE=2\r\n",
        "AT+ULSTFILE=\r\n",
        'AT+URDFILE="postdata.txt"\r\n',
        'AT+ULSTFILE=2,"result.txt"\r\n',
        'AT+URDFILE="result.txt"\r\n',

        'AT+URDFILE="postdata.txt"\r\n'
        'AT+UDELFILE="postdata.txt"\r\n',
        'AT+UDELFILE="postdata.txt"\r\n',
        'AT+UDELFILE="postdata.txt"\r\n',
        'AT+UDELFILE="postdata.txt"\r\n',
        'AT+UDELFILE="postdata.txt"\r\n',
        "AT+ULSTFILE=\r\n",
        'AT+UDWNFILE="postdata.txt",11\r',
        'Fello Curly\x1A',        
        'AT+URDFILE="postdata.txt"\r\n'
        "AT+UHTTP=0\r\n",
        'AT+UHTTP=0,1,"httpbin.org"\r\n',
        'AT+UHTTP=0,5,80\r\n',
        'AT+UHTTPC=0,4,"/post","result.txt","postdata.txt",1\r\n'

        ]
 
# Get wifi details and more from a secrets.py file
try:
    from secrets import secrets
except ImportError:
    print("WiFi secrets are kept in secrets.py, please add them there!")
    secrets = {
            "ssid":"xxxxx",
            "password":"password",
            "phone":"+4477500000",
            "mqtt_host":"mqttHOST",
            "mqtt_username":"USER",
            "mqtt_password":"PWD",
            "mqtt_port":1883
            
        }
    
    #raise

DELAY_BETWEEN_AT_COMMANDS = 1000
QUALITY_HEARTBEAT = 30000

indicator_delay = 3000
sms_message = None
http_response = None
http_response_size = 0


def parse_iso8601(date_string):
    year = int(date_string[0:4])
    month = int(date_string[5:7])
    day = int(date_string[8:10])
    hour = int(date_string[11:13])
    minute = int(date_string[14:16])
    second = int(date_string[17:19])
    # Assuming the timezone is fixed or you handle it separately
    return time.struct_time((year, month, day, hour, minute, second, 0, 0, -1))

def format_iso8601(t):
    return '{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}'.format(t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)


class DongleStats:
    
    def __init__(self, name, rtc):
        self.name = name
        self.insms = 0
        self.outsms = 0
        self.time = 0
        self.lastin = 0
        self.lastout = 0
        self._rtc = rtc
        
        
    def update_time(self,t):
        self.time = self.time + t
        
    def mark_insms(self, sms):
        self.insms += 1
        self.lastin = format_iso8601(self._rtc.datetime)
        
    
    def mark_outsms(self, sms):
        self.outsms += 1
        self.lastout = format_iso8601(self._rtc.datetime)
        
    def __str__(self):
        return f"{self.name}#{self.insms}#{self.lastin}#{self.outsms}#{self.lastout}#{format_iso8601(self._rtc.datetime)}"
    
class SMSMessage:
    def __init__(self, headers, message=''):
        self.headers = headers
        self.message = message
    
    def append(self, str):
        self.message += str
        
    def base64encode(self):
        b64_string=str(binascii.b2a_base64(self.datify().encode('utf-8')).decode('utf-8').strip())
        return b64_string
   
    def datify(self):
        return f"{self.headers[0][1:-1]}:{self.headers[2][1:]}:{self.headers[3][:-6]}:{self.message[0:125]}"
    
    def __str__(self):
        return f"SMSMessage: headers: {self.headers} msg: <{self.message}>"


async def quality_heartbeat(gsm_cmd_queue):
    while True:
        await asyncio.sleep_ms(QUALITY_HEARTBEAT)
        await gsm_cmd_queue.put(f'AT+CSQ\r\n')
        
def sms_sender_factory(gsm_cmd_queue, dongle_stats):
    async def sms_send(destphone, msgtext):
        print("sms_send-->",destphone, msgtext)
        await gsm_cmd_queue.put(f'AT+CMGS="{destphone}"\r')
        await gsm_cmd_queue.put(f'{msgtext}\x1A')
        dongle_stats.mark_outsms("@TODO")
        
    return sms_send

async def sms_send(gsm_cmd_queue, destphone, msgtext):
    await gsm_cmd_queue.put(f'AT+CMGS="{destphone}"\r')
    await gsm_cmd_queue.put(f'{msgtext}\x1A')

async def post_web_page(gsm_cmd_queue,url):
    grab_commands = [
            'AT+UDELFILE="postdata.txt"\r\n',
            'AT+UDWNFILE="postdata.txt",11\r',
            'Fello Curly\x1A',
            "AT+UHTTP=0\r\n",
            f'AT+UHTTP=0,1,"{url}"\r\n',
            'AT+UHTTP=0,5,80\r\n',
            'AT+UHTTPC=0,4,"/post","result.txt","postdata.txt",1\r\n'
                    
        ]
    print("GRAB WEB PAGE")
    for command in grab_commands:
        print(f"COMMAND {command}")
        await gsm_command_queue.put(command)
    
               
# Demonstrate scheduler is operational.
async def heartbeat(led, dongle_stats, gsm_cmd_queue):
    global indicator_delay
    s = False
    sms_sender = sms_sender_factory(gsm_cmd_queue, dongle_stats)

    while True:
        await asyncio.sleep_ms(indicator_delay)
        led.value = not led.value
        if (indicator_delay < 600 and not s):
            s = True
            if True:
                await sms_sender(secrets['phone'], f"Our dongle named '{dongle_stats.name}', has just booted up.")
                if (GRAB_WEB_PAGE_DEMO): 
                    print("Initiate Grabbing Web Page over 4g")
                    await post_web_page(gsm_cmd_queue, 'httpbin.org')
 

async def gsm_networkconnection_loop(gsm_cmd_queue, delay_in_secs = 45):
    while True:
        print(f"GSM Network Connection Test")
        await gsm_cmd_queue.put('AT+COPS?\r\n')
        await asyncio.sleep(delay_in_secs)  


async def uart_read_loop(uart, response_queue):
    print(f"uart_read_loop queue = {response_queue}")
    while True:
        if uart.in_waiting > 0:
            data = uart.readline()
            response = data.decode('utf-8')
            #print(response)
            await response_queue.put(response)
            #print(f"uart_read_loop: response = {response} added to response queue - size = {response_queue.qsize()}")
            
        await asyncio.sleep_ms(1)  # Wait for 1 mseconds between messages

async def response_handler(response_queue, message_queue, sms_queue):
    print(f"response_handler queue = {response_queue}")
    while True:
        response = await response_queue.get()
        await parse_responses(response, message_queue, sms_queue)
        await asyncio.sleep_ms(100)  # Wait for 1 seconds between messages
       


async def uart_write_loop(uart, message_queue):
    print("uart_write_loop", message_queue)
    while True:
        message = await message_queue.get()  # Wait for a message from the queue
        #print(f"WRITE ",message_queue,f"<{message}>")
        uart.write(message.encode('utf-8'))  # Write message to UART
        await asyncio.sleep_ms(DELAY_BETWEEN_AT_COMMANDS)  # Wait for 2 seconds between messages

async def message_complete(message):
    print(f"{message}")

async def parse_responses(response, gsm_cmd_queue, sms_queue):
    global sms_message, http_response, http_response_size, indicator_delay
    
    params=response.split(',')
    #print(f"parse_responses: {params}")
    if http_response_size <= 0 and http_response is not None:
        print("FINAL>>>>>>",http_response)
        http_response = None
        

    if (http_response_size > 0):
        http_response += response
        http_response_size -= len(response)
        #print("LEN = ", len(response), "Remaining", http_response_size)
            
    if (sms_message is not None):
        # Building a text message after receiving an AT '+CMGR' response
        sms_message.append(response)
        if '\r\n' in response:
            #await message_complete(sms_message)
            print("message complete", sms_message)
            await sms_queue.put(SMSMessage(sms_message.headers, sms_message.message))
            #await reset_message_timer()
            sms_message = None
    elif '+UUHTTPCR:' in params[0]:
            print("RESULT FILE WAITING....INITIATE READING RESULTS....")
            await gsm_cmd_queue.put(f'AT+URDFILE="result.txt"\r\n')

    elif '+URDFILE:' in params[0]:
            print("Params 2", f"<{params[2]}>")
            # The actual response starts from the 3rd parameter (params[2])
            # and that will include a sup
            file_size = int(params[1])
            
            init_str = params[2][1:1+file_size]
            print(f"INIT_STR = <{init_str}>")
            
            http_response_size = file_size - len(init_str)
            print("Waiting for ",http_response_size, " bytes")
            http_response = init_str
            
            
    elif params[0] == "RING\r\n":
        print("RING")
    elif '+CSQ:' in params[0]:
        print("QUALITY ", params[0], params[1])
    elif '+CGDC' in params[0]:
        print("Internet",params)
    elif "+CLIP" in params[0]:
        incoming_call_from = params[0][6:].strip()[1:-1]
        print("CLIP---->", incoming_call_from)
    elif  "+CMGS" in params[0]:
        await gsm_cmd_queue.put(f'AT+CMGD=1,4\r\n')
        await gsm_cmd_queue.put(f'AT+CMGL="ALL"\r\n')
        
    elif "+CMTI:" in params[0]:
        msgid = int(params[1])
        await gsm_cmd_queue.put(f'AT+CMGR={msgid}\r\n')
        await gsm_cmd_queue.put(f'AT+CMGD={msgid}\r\n')
        
        
    elif "+CMGR" in params[0]:
        print(f"READING A TEXT MESSAGE ")
        sms_message = SMSMessage(params[1:]) # Start to build the sms text message
        
    elif "+COPS" in params[0] and "?" not in params[0]:
        print("COPS CHECK", len(params), params)
        if (len(params) != 4):
            #raise NetworkException("Network Not Connected.")
            indicator_delay = 3000
        else:
            indicator_delay = 500
            
        #return len(params) == 3
async def grab_web_page(gsm_command_queue):
    grab_commands = [
            #'AT+UDELFILE="postdata.txt"\r\n',
            #'AT+UDWNFILE="postdata.txt",11\r',
            #'Fello Curly\x1A',
            "AT+UHTTP=0\r\n",
            'AT+UHTTP=0,1,"httpbin.org"\r\n',
            'AT+UHTTP=0,5,80\r\n',
            'AT+UHTTPC=0,4,"/post","result.txt","postdata.txt",1\r\n'
                    
        ]
    print("GRAB WEB PAGE")
    for command in grab_commands:
        print(f"COMMAND {command}")
        await gsm_command_queue.put(command)
    
def form_at_esp_mqtt_credentials():
    username = secrets["mqtt_username"]
    password = secrets["mqtt_password"]
    return f'AT+MQTTUSERCFG=0,1,"client_id_12","{username}","{password}",0,0,""'

def form_at_esp_mqtt_connect():
    host = secrets["mqtt_host"]
    port = secrets["mqtt_port"]
    reconnect = 1 # 1 or 0
    return f'AT+MQTTCONN=0,"{host}",{port},{reconnect}'

def form_at_esp_subscribe(topic):
    return f'AT+MQTTSUB=0,"{topic}",1'
    
def form_at_esp_publish(topic,data,qos=1,retain=0):
    return f'AT+MQTTPUB=0,"{topic}","{data}",{qos},{retain}'

# Not yet used - ESP AT latest versions
def form_at_esp_prepublish(topic,data,qos=1,retain=0):
    return f'AT+MQTTPUBRAW=0,"{topic}",{len(data)},{qos},{retain}'

def form_at_esp_postpublish(data):
    return f'{data}'

async def main(client, gsm_command_queue):
   
    start_up_commands = [
        "AT\r\n",
        "ATE0\r\n",
        "AT+CMGF=1\r\n",
        "AT+CMGD=1,4\r\n",
        "AT+CNMI=1,1\r\n",
        #"AT+CNMI?\r\n",
        #"AT+CFUN?\r\n",
        "AT+CRC=1\r\n",

        "AT+CREG=1\r\n",
        #"AT+CREG?\r\n",
        "AT+CEREG=2\r\n",
        #"AT+CEREG?\r\n",
        #"AT+CPMS?\r\n",
        
        
        
        #"AT+CGACT=1,1\r\n",
        #"AT+CGDCONT?\r\n",
        #'AT+CGCONTRDP\r\n',

        "AT+CMEE=2\r\n",

    ]


    try:
        for command in start_up_commands:
            #print(f"put {command} in queue")
            await gsm_command_queue.put(command)
        #await client.connect()

    except OSError:
        print('Connection failed.')
        machine.reset()
        return

    while True:
        await asyncio.sleep(5)
        #if (option.value() == 0):
        #    machine.reset()

def build_mqtt_subscribe_message(data_string):
        
    # Example string
    #data_string = '+MQTTSUBRECV:0,"torratorratorra",46,{"to":"+447753432247","message":"Hello World"}'

    # Splitting the string based on commas
    parts = data_string.split(',')

    prefix = parts[0]  # +MQTTSUBRECV:0
    topic = parts[1].strip('"')  # torratorratorra
    msg_size_bytes = int(parts[2])  # 46

    # Extracting JSON object
    json_str = ','.join(parts[3:])  # Reconstruct the JSON string

    # Calculate the size of the JSON string in bytes
    json_size_calculated = len(json_str.encode('utf-8'))


    # Print comparison
    print(f"Provided Size: {msg_size_bytes} bytes")
    print(f"Calculated Size: {json_size_calculated} bytes")
    
    # Checking if they match
    if msg_size_bytes != json_size_calculated:
        print("WARNING ... Sizes do not match.")
    
    return topic, json_str
    
def update_esp32at_messages_factory(esp, sms_sender):
    uart = esp._uart
    async def update_espat():
        nonlocal uart 
        while True:
            #print("update esp",uart.in_waiting)
            if uart.in_waiting > 0:
                data = uart.readline()
                response = data.decode('utf-8')                
                print(response)
                if '+MQTTSUBRECV:' in response:
                    topic, sub_message = build_mqtt_subscribe_message(response)
                    print(topic, sub_message)
                    json_message = json.loads(sub_message)
                    print(json_message)
                    await sms_sender(json_message["to"], json_message["message"])

                            
            await asyncio.sleep(1)
    return  update_espat

def update_dongle_status_factory(esp, dongle_stats, delay = 30):
    print("update_dongle_status... ")
    count = 1    
         
    async def update_dongle_status():
        nonlocal count
        while True:
            print(f"Update DONGLE STATUS time: {dongle_stats.time}  publish:{dongle_stats}")
            resp = esp.at_response(form_at_esp_publish(f"status/{dongle_stats.name}",f"{dongle_stats}"))
            count = count + 1
            dongle_stats.update_time(delay)
            await asyncio.sleep(delay)
            
    return  update_dongle_status


async def ping_demo():
    while True:
        print("Pinging 8.8.8.8...", end="")
        print(esp.ping("8.8.8.8"))
        await asyncio.sleep(10)
      
def wifi_init(esp):
    esp.hard_reset()
    print("Scanning for AP's")
    # Some ESP do not return OK on AP Scan.
    # See https://github.com/adafruit/Adafruit_CircuitPython_ESP_ATcontrol/issues/48
    # Comment out the next 3 lines if you get a No OK response to AT+CWLAP
    # secrets dictionary must contain 'ssid' and 'password' at a minimum

    for ap in esp.scan_APs():
        print(ap)
    print("Checking connection...")
    
    esp.connect(secrets)
    print("Connected to AT software version ", esp.version)
    print("IP address ", esp.local_ip)
    
    print("SETTING MQTT CREDENTIALS")
                
    resp = esp.at_response(form_at_esp_mqtt_credentials())
    print("MQTT CREDENTIALS RESPONSE",resp)
                
    print(" MQTT CONNECTING....")                
    resp = esp.at_response(form_at_esp_mqtt_connect())
    print("MQTT CONNECT RESPONSE",resp)
    
    print("MQTT SUBSCRIBING....")
    resp = esp.at_response(form_at_esp_subscribe("torratorratorra"))
    print("MQTT SUBSCRIBE",resp)
    

     
async def wifi_loop(esp, dongle_stats, sms_sender, sms_queue):
    
    first_pass = True
    while True:
        try:

            if first_pass:
                print("FIRST PASS ON WIFI LOOP")
                wifi_init(esp)
                first_pass = False
                update_dongle_status = update_dongle_status_factory(esp, dongle_stats)
                update_subscribe_messages = update_esp32at_messages_factory(esp, sms_sender)
                
                asyncio.create_task(update_dongle_status())
                asyncio.create_task(update_subscribe_messages())
                asyncio.create_task(ping_demo())
                
            if (True):
                sms = await sms_queue.get()
                dongle_stats.mark_insms(sms)
                message64 = sms.base64encode()
                #b64_string=str(binascii.b2a_base64(message.encode('utf-8')).decode('utf-8').strip())
                print("MESSAGE", sms, "MESSAGE64", message64)
                resp = esp.at_response(form_at_esp_publish(f"smsgwin/{dongle_stats.name}",message64))
                

        except (ValueError, RuntimeError, adafruit_espatcontrol.OKError) as e:
            print("Failed to get data, retrying\n", e)
            print("Resetting ESP module")
            wifi_init(esp)
            continue
        
async def update_rtc(rtc, esp):
    while True:
        try:
            urlreq='AT+HTTPCLIENT=2,0,"http://worldtimeapi.org/api/timezone/Europe/London","worldtimeapi.org","/",1'
            resp = esp.at_response(urlreq).decode('utf-8')
            stra = ','.join(resp.split(',')[1:])
            jsonr = json.loads(stra)
            print("JSON RESPONSE ", jsonr['datetime'])
            dt = parse_iso8601(jsonr['datetime'])
            rtc.datetime = dt
            # 2024-07-03T16:01:31.572608+01:00
            print(format_iso8601(rtc.datetime))

        except Exception as e:
            print("Exception ", e)
            
        print("update_rtc....")
        await asyncio.sleep(10)
        
# ***** Note  ******: Below
# Portions of this example have been taken from iLabs website.
# This is for demo purposes only - I certainly would not recommend using this code
# for production/home use. I recommend you play with the code - understand what it is doing
# and then proceed to completely rewrite it!
# The unfriendly pin names are down to the firmware of CircuitPython I have blown
# into my iLabs 'Challenger RP2040 Connectivity'. This board supports LTE/WiFi/BLE.
# At the time - the only suitable firmware that existed was for the 'RP2040 Challanger LTE'
#  - which only supported comms over LTE. This version was 'perfect' for SARA LTE modem
# support. The demo sends and receives SMS as well as supporting HTTP POST over LTE.
# HTTP GET over WiFi 
# For demonstration I also ping a DNS server over WiFi.

# Fudges were needed for the ESP32 AT support.
# Johnny Wilson - Brighton,June 2024

    
r = rtc.RTC()
r.datetime = time.struct_time((2019, 5, 29, 15, 14, 15, 0, -1, -1))

dongle_stats = DongleStats("dongleESP32", r)

print (f"Test program start ! Dongle name: {dongle_stats.name}")
debugflag = False	#Set this to True - if you want to debug ESP-AT commands.

#  These pins are the serial uart pins to the ESP32-AT mpu. 
TX = microcontroller.pin.GPIO16
RX = microcontroller.pin.GPIO17
resetpin = DigitalInOut(microcontroller.pin.GPIO24)
rtspin = False
uart = busio.UART(TX, RX, baudrate=11520, receiver_buffer_size=2048)
esp_boot = DigitalInOut(microcontroller.pin.GPIO25)
esp_boot.direction = Direction.OUTPUT
esp_boot.value = True


print("ESP AT commands")
# For Boards that do not have an rtspin like challenger_rp2040_wifi set rtspin to False.
esp = adafruit_espatcontrol.ESP_ATcontrol(
    uart, 115200, reset_pin=resetpin, rts_pin=rtspin, debug=debugflag
   
)


led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

# SARA LDO enable control signal
sara_pwr = digitalio.DigitalInOut(board.SARA_PWR)
sara_pwr.direction = digitalio.Direction.OUTPUT
# Make sure the modem is fully restarted
sara_pwr.value = 0
time.sleep(1)
sara_pwr.value = 1

# Power on button
sara_btn = digitalio.DigitalInOut(board.SARA_BTN)
sara_btn.direction = digitalio.Direction.INPUT
sara_btn.pull = digitalio.Pull.UP

# Reset pin
sara_rst = digitalio.DigitalInOut(board.SARA_RST)
sara_rst.direction = digitalio.Direction.INPUT
sara_rst.pull = digitalio.Pull.UP

# Perform a SARA power on sequence
print ("Powering the SARA modem on.")
sara_btn.direction = digitalio.Direction.OUTPUT
sara_btn.value = 0
time.sleep(0.15)
sara_btn.direction = digitalio.Direction.INPUT
sara_btn.pull = digitalio.Pull.UP
# A short delay is required here to allow the modem to startup
time.sleep(1)
print ("Reset done, waiting for modem to start.")

uart = busio.UART(tx=board.SARA_TX, rx=board.SARA_RX, rts=board.SARA_RTS, cts=board.SARA_CTS, baudrate=115200, timeout=0.25)

print ("Starting test sequence")
to_count = 40
while to_count:
    uart.write(bytes("AT\r\n", 'utf-8'))
    result = uart.readline();
    print (".", end="")
    if type(result) == bytes:
        print(result)
        if result.decode('utf-8').startswith("AT"):
            result = uart.readline();
            print(result)
            if result.decode('utf-8').startswith("OK"):
                break
    result = uart.readline()
    to_count -= 1
    
if not to_count:
    print ("\nThe modem did not start correctly!")
else:
    print ("\nModem started !")


gsm_response_queue = Queue()
gsm_command_queue = Queue()
sms_queue = Queue()




asyncio.create_task(heartbeat(led, dongle_stats, gsm_command_queue))
asyncio.create_task(quality_heartbeat(gsm_command_queue))

asyncio.create_task(wifi_loop(esp, dongle_stats, sms_sender_factory(gsm_command_queue, dongle_stats), sms_queue))
asyncio.create_task(update_rtc(r, esp))


asyncio.create_task(uart_read_loop(uart, gsm_response_queue))
asyncio.create_task(uart_write_loop(uart, gsm_command_queue))
asyncio.create_task(response_handler(gsm_response_queue, gsm_command_queue, sms_queue))
asyncio.create_task(gsm_networkconnection_loop(gsm_command_queue))

try:
    asyncio.run(main(None, gsm_command_queue))
    

finally:
    asyncio.new_event_loop()




