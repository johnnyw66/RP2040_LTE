import board
import busio
import digitalio
import time
import microcontroller
import asyncio
from queue import Queue

indicator_delay = 3000
sms_message = None

class SMSMessage:
    def __init__(self, headers, message=''):
        self.headers = headers
        self.message = message
    
    def append(self, str):
        self.message += str

    def __str__(self):
        return f"SMSMessage: headers: {self.headers} msg: <{self.message}>"

# Demonstrate scheduler is operational.
async def heartbeat(led,gsm_cmd_queue):
    global indicator_delay
    s = False
    while True:
        await asyncio.sleep_ms(indicator_delay)
        led.value = not led.value
        if (indicator_delay < 600 and not s):
            s = True
            destphone="+447753432247"
            msgtext=f"Hello World - I hope this works. {destphone}"
            print(f"send SMS '{msgtext}' to {destphone}")
            await gsm_cmd_queue.put(f'AT+CMGS="{destphone}"\r')
            await gsm_cmd_queue.put(f'{msgtext}\x1A')
 

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
            print(response)
            await response_queue.put(response)
            #print(f"uart_read_loop: response = {response} added to response queue - size = {response_queue.qsize()}")
            
        await asyncio.sleep_ms(1)  # Wait for 1 mseconds between messages

async def response_handler(response_queue, message_queue, sms_queue):
    print(f"response_handler queue = {response_queue}")
    while True:
        response = await response_queue.get()
        await parse_responses(response, message_queue, sms_queue)
        await asyncio.sleep_ms(1000)  # Wait for 1 seconds between messages
       


async def uart_write_loop(uart, message_queue):
    print("uart_write_loop")
    while True:
        message = await message_queue.get()  # Wait for a message from the queue
        print(f"WRITE {message}")
        uart.write(message.encode('utf-8'))  # Write message to UART
        await asyncio.sleep_ms(2000)  # Wait for 2 seconds between messages

async def message_complete(message):
    print(f"{message}")

async def parse_responses(response, gsm_cmd_queue, sms_queue):
    global sms_message, indicator_delay
    
    params=response.split(',')
    print(f"parse_responses: {params}")
    if (sms_message is not None):
        # Building a text message after receiving an AT '+CMGR' response
        sms_message.append(response)
        if '\r\n' in response:
            #await message_complete(sms_message)
            print("message complete", sms_message)
            await sms_queue.put(SMSMessage(sms_message.headers, sms_message.message))
            #await reset_message_timer()
            sms_message = None
    elif params[0] == "RING\r\n":
        print("RING")
    elif params[0][0:5] == "+CLIP":
        incoming_call_from = params[0][6:].strip()[1:-1]
        print("CLIP---->", incoming_call_from)
    elif params[0][0:5] == "+CMGS":
        await gsm_cmd_queue.put(f'AT+CMGD=1,4\r\n')
        await gsm_cmd_queue.put(f'AT+CMGL="SENT"\r\n')
        
    elif params[0][0:5] == "+CMTI":
        msgid = int(params[1])
        await gsm_cmd_queue.put(f'AT+CMGR={msgid}\r\n')
        await gsm_cmd_queue.put(f'AT+CMGD={msgid}\r\n')
        
    elif params[0][0:5] == "+CMGR":
        print(f"READING A TEXT MESSAGE ")
        sms_message = SMSMessage(params[1:]) # Start to build the sms text message
    elif params[0][0:5] == "+COPS":
        print("COPS CHECK", len(params), params)
        if (len(params) != 4):
            #raise NetworkException("Network Not Connected.")
            indicator_delay = 3000
        else:
            indicator_delay = 500
            
        #return len(params) == 3

async def main(client, gsm_command_queue):
    start_up_commands = [
        "AT\r\n",
        "AT+CMGF=1\r\n",
        "AT+CMGD=1,4\r\n",
        "AT+CNMI=1,1\r\n",
        "AT+CNMI?\r\n",
        "AT+CFUN?\r\n",
        "AT+CRC=1\r\n",
        #'AT+CMGL="ALL"\r\n'
        #"AT+CLIP=1\r\n",
        #"AT+COPS?\r\n",
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

print ("Test program start !")


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

asyncio.create_task(heartbeat(led,gsm_command_queue))
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




