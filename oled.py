#from ssd1306 import SSD1306_I2C
import time
import adafruit_ssd1306
import adafruit_ds3231

import framebuf
import rtc

# OLED Stuff
import board


WIDTH  = 128                                            # oled display width
HEIGHT = 64                                            # oled display height
FB_WIDTH = 32
FB_HEIGHT = 32

days = ("Mon", "Tues", "Wed", "Thur", "Fri", "Sat", "Sun")

def print_rtc(dev, r):
    date_str, time_str =  get_datetime(r)
    print(dev, date_str, time_str)
    
def get_datetime(r):
    t = r.datetime
    date_str = f"{days[int(t.tm_wday)]} {t.tm_mday}/{t.tm_mon}/{t.tm_year}"
    time_str = f"{t.tm_hour}:{t.tm_min:02}:{t.tm_sec:02}"
    return date_str, time_str
try:
    i2c = board.I2C()  # uses board.SCL and board.SDA
    oled = adafruit_ssd1306.SSD1306_I2C(WIDTH, HEIGHT, i2c)
except Exception as e:
    oled = None
    print(e)

try:
    rtca = adafruit_ds3231.DS3231(i2c)
except Exception as e:
    rtca = None
rtc = rtc.RTC()
# rtca.datetime = rtc.datetime

#t = time.struct_time((2024, 01, 01, 07, 19, 00, 0, -1, -1))
    # you must set year, mon, date, hour, min, sec and weekday
    # yearday is not supported, isdst can be set but we don't do anything with it at this time
#print("Setting time to:", t)  # uncomment for debugging
#rtc.datetime = t
    
print(rtc)
while True:
    # print(t)     # uncomment for debugging
    if (rtca):
        print_rtc("DS323",rtca)
    if (rtc):
        print_rtc("RTC", rtc)
    print()
    date_str, time_str = get_datetime(rtc)
    if (oled):
        oled.fill(0)
        
        oled.text( date_str , 8, 8, 1)
        oled.text( time_str , 8, 16, 1)
        oled.text( "xxx" , 8, 24, 1)
        
        oled.show()
    time.sleep(1)

