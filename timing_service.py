import RPi.GPIO as GPIO
import time
import csv
import os
import threading

SECTOR_AANTAL = 3
LEADERBOARD_BESTAND = "voorbeeld_leaderboard.csv"

# Pins ------------------------------------------
BUTTON_PIN = 17       # start/sector knop
GREEN = 5
YELLOW = 6
RED = 13

GPIO.setmode(GPIO.BCM)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

GPIO.setup(GREEN, GPIO.OUT)
GPIO.setup(YELLOW, GPIO.OUT)
GPIO.setup(RED, GPIO.OUT)


def leds_off():
    GPIO.output(GREEN, 0)
    GPIO.output(YELLOW, 0)
    GPIO.output(RED, 0)


leds_off()

# ------------------------------------------------
# TIJD PARSING & CSV FUNCTIES
# ------------------------------------------------


def parse_tijd(t):
    m, s = t.split(":")
    return int(m) * 60 + float(s)


def format_tijd(sec):
    m = int(sec // 60)
    s = sec % 60
    return f"{m}:{s:04.1f}"


def haal_vorige_rit(naam):
    if not os.path.isfile(LEADERBOARD_BESTAND):
        return None

    laatste = None
    with open(LEADERBOARD_BESTAND, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)

        for row in reader:
            if len(row) < 5:
                continue
            if row[0] == naam:
                laatste = row

    if laatste is None:
        return None

    totale_tijd = parse_tijd(laatste[1])
    sector_tijden = []

    for s in laatste[2:2 + SECTOR_AANTAL]:
        if s.strip():
            sector_tijden.append(parse_tijd(s))

    return {
        "totale_tijd": totale_tijd,
        "sector_tijden": sector_tijden
    }


# ------------------------------------------------
# STOPLICHT
# ------------------------------------------------


def show_sector_light(naam, sector_index, nieuwe_tijd):
    vorige = haal_vorige_rit(naam)

    if vorige is None or sector_index >= len(vorige["sector_tijden"]):
        GPIO.output(GREEN, 1)
        GPIO.output(YELLOW, 1)
        GPIO.output(RED, 1)
        return

    oud = vorige["sector_tijden"][sector_index]
    diff = nieuwe_tijd - oud

    if diff < -10:
        GPIO.output(GREEN, 1)
        GPIO.output(YELLOW, 0)
        GPIO.output(RED, 0)
    elif diff > 10:
        GPIO.output(GREEN, 0)
        GPIO.output(YELLOW, 0)
        GPIO.output(RED, 1)
    else:
        GPIO.output(GREEN, 0)
        GPIO.output(YELLOW, 1)
        GPIO.output(RED, 0)


def party_animation():
    for i in range(18):
        GPIO.output(GREEN, i % 3 == 0)
        GPIO.output(YELLOW, i % 3 == 1)
        GPIO.output(RED, i % 3 == 2)
        time.sleep(0.12)

    leds_off()


# ------------------------------------------------
# TIMING CLASS
# ------------------------------------------------


class TimingService:
    def __init__(self, naam):
        self.naam = naam
        self.reset()

    def reset(self):
        self.start_tijd = None
        self.sector_tijden = []
        self.vorige_checkpoint = None
        leds_off()

    def start(self):
        self.start_tijd = time.time()
        self.vorige_checkpoint = self.start_tijd
        self.sector_tijden = []
        print("GESTART")

    def voeg_sector_toe(self):
        if self.start_tijd is None:
            self.start()
            return

        nu = time.time()
        sector_tijd = nu - self.vorige_checkpoint
        self.vorige_checkpoint = nu

        self.sector_tijden.append(sector_tijd)

        sector_index = len(self.sector_tijden) - 1
        show_sector_light(self.naam, sector_index, sector_tijd)

        print(f"Sector {sector_index + 1}: {format_tijd(sector_tijd)}")

        if len(self.sector_tijden) == SECTOR_AANTAL:
            self.eindig()

    def eindig(self):
        totale_tijd_sec = sum(self.sector_tijden)

        print("Totale tijd:", format_tijd(totale_tijd_sec))

        vorig = haal_vorige_rit(self.naam)
        if vorig and totale_tijd_sec < vorig["totale_tijd"]:
            print("SNELLER DAN VORIGE KEER → PARTY")
            party_animation()

        self.sla_resultaat_op(totale_tijd_sec)
        self.reset()

    def sla_resultaat_op(self, totale_tijd):
        nieuw = [
            self.naam,
            format_tijd(totale_tijd),
            *[format_tijd(t) for t in self.sector_tijden]
        ]

        bestaan = os.path.isfile(LEADERBOARD_BESTAND)
        with open(LEADERBOARD_BESTAND, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if not bestaan:
                header = ["Naam", "TotaleTijd"] + \
                         [f"Sector{i+1}" for i in range(SECTOR_AANTAL)]
                w.writerow(header)
            w.writerow(nieuw)

        print("Opgeslagen:", nieuw)


# ------------------------------------------------
# BUTTON LOOP
# ------------------------------------------------


def wacht_op_klik(callback):
    last = time.time()
    while True:
        if GPIO.input(BUTTON_PIN) == 0:
            if time.time() - last > 0.4:
                callback()
                last = time.time()
        time.sleep(0.02)


# ------------------------------------------------
# MAIN
# ------------------------------------------------

if __name__ == "__main__":
    naam = input("Naam rijder: ").strip()
    service = TimingService(naam)

    try:
        wacht_op_klik(service.voeg_sector_toe)
    finally:
        GPIO.cleanup()
