from microcontroller import watchdog as wdt
from watchdog import WatchDogMode
import time

wdt.timeout=2.5 # Set a timeout of 2.5 seconds
print(dir(WatchDogMode))

wdt.mode = WatchDogMode.RESET   # WatchDogMode.RAISE to raise an exception

while True:
    wdt.feed()
    print("feed")
    time.sleep(3)
    