from mfrc522 import MFRC522
import RPi.GPIO as GPIO
import time

GPIO.setwarnings(False)

reader = MFRC522()

print("RFID test gestart. Scan een tag...\n")

try:
    while True:
        (status, TagType) = reader.MFRC522_Request(reader.PICC_REQIDL)
        if status == reader.MI_OK:
            (status, uid) = reader.MFRC522_Anticoll()
            if status == reader.MI_OK:
                uid_str = "-".join(str(x) for x in uid)
                print("Gescande UID:", uid_str)
                time.sleep(1)
        time.sleep(0.1)

except KeyboardInterrupt:
    GPIO.cleanup()
    print("Gestopt.")
