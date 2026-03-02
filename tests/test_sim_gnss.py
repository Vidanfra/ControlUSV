# Modified for valid test
from src.core.messaging import Subscriber, Topics
sub = Subscriber([Topics.SENSOR_GNSS])
while True:
    msg = sub.receive()
    if msg:
        print(msg)