#!/usr/bin/env python3

import time
import json
import csv
import os
import threading
from datetime import datetime

import RPi.GPIO as GPIO

# Configuratie
SECTOR_AANTAL = 3
LEADERBOARD_BESTAND = "voorbeeld_leaderboard.csv"
STATUS_FILE = "timing_status.json"
BUTTON_PIN = 26     # Fysieke knop op GPIO17
DEBOUNCE_TIJD = 0.5

actieve_sessie = None
sessie_lock = threading.Lock()


class SessionData:
    def __init__(self, naam):
        self.naam = naam
        self.start_tijd = time.time()
        self.sector_tijden = []
        self.laatste_scan = time.time()
        self.voltooid = False

    def huidige_sector(self):
        return len(self.sector_tijden) + 1

    def is_klaar(self):
        return len(self.sector_tijden) >= SECTOR_AANTAL

    def voeg_sector_toe(self):
        nu = time.time()

        if nu - self.laatste_scan < DEBOUNCE_TIJD:
            return False

        if len(self.sector_tijden) == 0:
            sector_tijd = nu - self.start_tijd
        else:
            sector_tijd = nu - self.laatste_scan

        self.sector_tijden.append(sector_tijd)
        self.laatste_scan = nu

        print(f"Sector {len(self.sector_tijden)}: {format_tijd(sector_tijd)}")

        if self.is_klaar():
            self.voltooid = True
            self.sla_resultaat_op()

        return True

    def sla_resultaat_op(self):
        totale_tijd_sec = sum(self.sector_tijden)
        totale_tijd_str = format_tijd(totale_tijd_sec)

        sector_tijden_str = [format_tijd(t) for t in self.sector_tijden]

        file_exists = os.path.isfile(LEADERBOARD_BESTAND)
        with open(LEADERBOARD_BESTAND, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow(["Naam", "Totaaltijd", "Sector 1", "Sector 2", "Sector 3"])

            row = [self.naam, totale_tijd_str]
            for i in range(SECTOR_AANTAL):
                row.append(sector_tijden_str[i] if i < len(sector_tijden_str) else "")
            writer.writerow(row)

        print("\nKlaar!")
        print(f"Totale tijd: {totale_tijd_str}")

        print("Resultaat opgeslagen.\n")


def format_tijd(sec):
    minuten = int(sec // 60)
    return f"{minuten}:{sec % 60:.1f}"


def schrijf_status():
    with sessie_lock:
        if not actieve_sessie:
            return

        data = {
            "timestamp": time.time(),
            "actieve_sessie": {
                "naam": actieve_sessie.naam,
                "huidige_sector": actieve_sessie.huidige_sector(),
                "totaal_sectoren": SECTOR_AANTAL,
                "verstreken_tijd": time.time() - actieve_sessie.start_tijd,
                "sector_tijden": actieve_sessie.sector_tijden,
                "start_tijd": actieve_sessie.start_tijd
            }
        }

        with open(STATUS_FILE, "w") as f:
            json.dump(data, f)


def status_loop():
    while True:
        time.sleep(1)
        schrijf_status()


def button_callback(channel):
    global actieve_sessie

    with sessie_lock:
        if not actieve_sessie:
            print("Geen actieve sessie.")
            return

        if actieve_sessie.voltooid:
            print("Sessie al voltooid.")
            return

        if actieve_sessie.voeg_sector_toe():
            if actieve_sessie.voltooid:
                print("Sessie is voltooid.")
                actieve_sessie = None


def main():
    global actieve_sessie

    naam = input("Voer naam in: ")

    actieve_sessie = SessionData(naam)
    print(f"Sessie gestart voor {naam}")
    print(f"Druk op de knop voor sector registraties ({SECTOR_AANTAL} totaal).")

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    GPIO.add_event_detect(BUTTON_PIN, GPIO.FALLING, callback=button_callback, bouncetime=200)

    t = threading.Thread(target=status_loop, daemon=True)
    t.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        GPIO.cleanup()


if __name__ == "__main__":
    main()
