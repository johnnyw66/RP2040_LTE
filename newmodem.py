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
# Get wifi and SMS phone details and more from a secrets.py file
try:
    from secrets import secrets
except ImportError:
    print("WiFi secrets are kept in secrets.py, please add them there!")
    secrets = {
        "ssid":"YOUR_SSID",
        "password":"YOUR_WIFI_PASSWORD",
        "phone":"+447712345678",

    }
    #raise

DELAY_BETWEEN_AT_COMMANDS = 1000
QUALITY_HEARTBEAT = 30000

indicator_delay = 3000
sms_message = None
http_response = None
http_response_size = 0

class SMSMessage:
    def __init__(self, headers, message=''):
        self.headers = headers
        self.message = message
    
    def append(self, str):
        self.message += str

    def __str__(self):
        return f"SMSMessage: headers: {self.headers} msg: <{self.message}>"


async def quality_heartbeat(gsm_cmd_queue):
    while True:
        await asyncio.sleep_ms(QUALITY_HEARTBEAT)
        await gsm_cmd_queue.put(f'AT+CSQ\r\n')

# Demonstrate scheduler is operational.
async def heartbeat(led,gsm_cmd_queue):
    global indicator_delay
    s = False
    while True:
        await asyncio.sleep_ms(indicator_delay)
        led.value = not led.value
        if (indicator_delay < 600 and not s):
            s = True
            if True:
                destphone= secrets['phone']
                msgtext=f"WOW! Hello NEW NEW World - I hope this works. {destphone}"
                print(f"send SMS '{msgtext}' to {destphone}")                
                await gsm_cmd_queue.put(f'AT+CMGS="{destphone}"\r')
                await gsm_cmd_queue.put(f'{msgtext}\x1A')
                print("Initiate Grabbing Web Page over 4g")
                await grab_web_page(gsm_cmd_queue)
 

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
    print("uart_write_loop")
    while True:
        message = await message_queue.get()  # Wait for a message from the queue
        print(f"WRITE <{message}>")
        uart.write(message.encode('utf-8'))  # Write message to UART
        await asyncio.sleep_ms(DELAY_BETWEEN_AT_COMMANDS)  # Wait for 2 seconds between messages

async def message_complete(message):
    print(f"{message}")

async def parse_responses(response, gsm_cmd_queue, sms_queue):
    global sms_message, http_response, http_response_size, indicator_delay
    
    params=response.split(',')
    print(f"parse_responses: {params}")
    if http_response_size <= 0 and http_response is not None:
        print("FINAL>>>>>>",http_response)
        http_response = None
        

    if (http_response_size > 0):
        http_response += response
        http_response_size -= len(response)
        print("LEN = ", len(response), "Remaining", http_response_size)
            
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
        #await gsm_cmd_queue.put(f'AT+CMGD={msgid}\r\n')
        await gsm_cmd_queue.put(f'AT+CMGD=1,4\r\n')
        
        
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
    
    
async def main(client, gsm_command_queue):
    start_up_commandsX= [
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
    
    start_up_commands = [
        "AT\r\n",
        "ATE0\r\n",
        "AT+CMGF=1\r\n",
        "AT+CMGD=1,4\r\n",
        "AT+CNMI=1,1\r\n",
        "AT+CNMI?\r\n",
        "AT+CFUN?\r\n",
        "AT+CRC=1\r\n",

        #"AT+UCALLSTAT=1\r\n",
        "AT+CREG=1\r\n",
        "AT+CREG?\r\n",
        "AT+CEREG=2\r\n",
        "AT+CEREG?\r\n",
        "AT+CPMS?\r\n",
        
        
        
        "ATS0=0\r\n",
        "AT+CGACT=1,1\r\n",
        "AT+CGDCONT?\r\n",
        'AT+CGCONTRDP\r\n',

        "AT+CMEE=2\r\n",

        #'AT+UDELFILE="postdata.txt"\r\n',

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
    # Allow us to change link and force setup mode 
    #option = Pin(10, mode=Pin.IN, pull=Pin.PULL_UP)
    while True:
        await asyncio.sleep(5)
        #if (option.value() == 0):
        #    machine.reset()   


async def wifi_loop(esp):
    
    print("Resetting ESP module")
    esp.hard_reset()

    first_pass = True
    while True:
        try:
            if first_pass:
                # Some ESP do not return OK on AP Scan.
                # See https://github.com/adafruit/Adafruit_CircuitPython_ESP_ATcontrol/issues/48
                # Comment out the next 3 lines if you get a No OK response to AT+CWLAP
                print("Scanning for AP's")
                for ap in esp.scan_APs():
                    print(ap)
                print("Checking connection...")
                # secrets dictionary must contain 'ssid' and 'password' at a minimum
                print("Connecting...")
                esp.connect(secrets)
                print("Connected to AT software version ", esp.version)
                print("IP address ", esp.local_ip)
                first_pass = False
            print("Pinging 8.8.8.8...", end="")
            print(esp.ping("8.8.8.8"))
            await asyncio.sleep(10)
        except (ValueError, RuntimeError, adafruit_espatcontrol.OKError) as e:
            print("Failed to get data, retrying\n", e)
            print("Resetting ESP module")
            esp.hard_reset()
            continue
   
# ***** Note  ******: Below
# The unfriendly pin names are down to the firmware of CircuitPython I have blown
# into my iLabs 'Challenger RP2040 Connectivity'. This board supports LTE/WiFi/BLE.
# At the time - the only suitable firmware that existed was for the 'RP2040 Challanger LTE'
#  - which only supported comms over LTE. This version was 'perfect' for SARA LTE modem
# support. The demo sends and receives SMS as well as supporting HTTP POST over LTE.
# For demonstration I also ping a DNS server over WiFi.

# Fudges were needed for the ESP32 AT support.
# Johnny Wilson - Brighton 2024

print ("Test program start !")
debugflag = False
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

#led = digitalio.DigitalInOut(microcontroller.pin.GPIO19)
#led.direction = digitalio.Direction.OUTPUT

#while True:
#    led.value = not led.value
#    time.sleep(0.5)
    
# LED
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

asyncio.create_task(heartbeat(led, gsm_command_queue))
asyncio.create_task(quality_heartbeat(gsm_command_queue))

asyncio.create_task(wifi_loop(esp))

asyncio.create_task(uart_read_loop(uart, gsm_response_queue))
asyncio.create_task(uart_write_loop(uart, gsm_command_queue))
asyncio.create_task(response_handler(gsm_response_queue, gsm_command_queue, sms_queue))
asyncio.create_task(gsm_networkconnection_loop(gsm_command_queue))

try:
    asyncio.run(main(None, gsm_command_queue))
    

finally:
#     client.close()  # Prevent LmacRxBlk:1 errors
    asyncio.new_event_loop()

#led = digitalio.DigitalInOut(microcontroller.pin.GPIO19)
#led.direction = digitalio.Direction.OUTPUT

#while True:
#    led.value = not led.value
#    time.sleep(0.5)



