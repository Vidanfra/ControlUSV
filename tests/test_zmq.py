import multiprocessing
import time
import sys
import os

# Ensure src is in python path
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from src.core.messaging import PubSubBroker, Publisher, Subscriber, Topics

def run_broker():
    broker = PubSubBroker()
    broker.start()

def run_publisher():
    # Wait for broker to come up
    time.sleep(1)
    pub = Publisher(Topics.SYSTEM_STATUS)
    count = 0
    while count < 5:
        data = {"status": "OK", "count": count, "message": "Hola"}
        print(f"[Publisher] Sending: {data}")
        pub.publish(data)
        time.sleep(1)
        count += 1
    
    # Send a finish signal if we wanted to close gracefully, but for test we just stop
    pub.close()

def run_subscriber():
    # Wait for broker
    time.sleep(1)
    sub = Subscriber([Topics.SYSTEM_STATUS])
    
    print("[Subscriber] Waiting for messages...")
    received_count = 0
    while received_count < 5:
        msg = sub.receive(timeout_ms=1000)
        if msg:
            topic, payload = msg
            print(f"[Subscriber] Received on {topic}: {payload}")
            if payload.get("message") == "Hola":
                received_count += 1
        else:
            print("[Subscriber] No message...")
    
    sub.close()

if __name__ == "__main__":
    # 1. Start Broker
    p_broker = multiprocessing.Process(target=run_broker, daemon=True)
    p_broker.start()
    
    # 2. Start Subscriber
    p_sub = multiprocessing.Process(target=run_subscriber)
    p_sub.start()
    
    # 3. Start Publisher
    p_pub = multiprocessing.Process(target=run_publisher)
    p_pub.start()
    
    # Wait for pub/sub to finish
    p_pub.join()
    p_sub.join()
    
    print("Test finished successfully.")
    # Broker is daemon, will be killed when main exits
