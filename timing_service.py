#!/usr/bin/env python3
"""
Timing Service - Beheert meerdere gelijktijdige timing sessies
Draait als achtergrond service en luistert naar RFID scans
"""

import time
import csv
import os
import json
import threading
import requests
from datetime import datetime
from collections import defaultdict

try:
    import RPi.GPIO as GPIO
    from mfrc522 import MFRC522
    GPIO.setwarnings(False)
    RFID_AVAILABLE = True
except ImportError:
    RFID_AVAILABLE = False
    print("RFID libraries niet beschikbaar - dummy mode")

# Configuratie
SECTOR_AANTAL = 3
TAGS_BESTAND = "tags.csv"
LEADERBOARD_BESTAND = "voorbeeld_leaderboard.csv"
TOTALE_AFSTAND_KM = 7.2
DEBOUNCE_TIJD = 3.0  # Seconden tussen scans van dezelfde tag
FLASK_URL = "http://localhost:5000"
STATUS_FILE = "timing_status.json"

# Actieve sessies: {uid: SessionData}
actieve_sessies = {}
sessie_lock = threading.Lock()

class SessionData:
    """Data voor een actieve timing sessie"""
    def __init__(self, uid, naam):
        self.uid = uid
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
        """Registreer een sector tijd"""
        nu = time.time()
        
        # Check debounce
        if nu - self.laatste_scan < DEBOUNCE_TIJD:
            return False
        
        if len(self.sector_tijden) == 0:
            sector_tijd = nu - self.start_tijd
        else:
            sector_tijd = nu - self.laatste_scan
        
        self.sector_tijden.append(sector_tijd)
        self.laatste_scan = nu
        
        print(f"  Sector {len(self.sector_tijden)}: {format_tijd(sector_tijd)}")
        
        if self.is_klaar():
            self.voltooid = True
            self.sla_resultaat_op()
        
        return True
    
    def sla_resultaat_op(self):
        totale_tijd_sec = sum(self.sector_tijden)
        totale_tijd_str = format_tijd(totale_tijd_sec)
        
        # Bereken gemiddelde snelheid
        totale_tijd_uur = totale_tijd_sec / 3600
        gem_snelheid = TOTALE_AFSTAND_KM / totale_tijd_uur
        
        # Format sector tijden
        sector_tijden_str = [format_tijd(t) for t in self.sector_tijden]
        
        # Schrijf naar CSV
        file_exists = os.path.isfile(LEADERBOARD_BESTAND)
        with open(LEADERBOARD_BESTAND, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow(["Naam", "Totaaltijd", "Sector 1", "Sector 2", "Sector 3", "Gem. snelheid (km/h)"])
            
            row = [self.naam, totale_tijd_str]
            for i in range(SECTOR_AANTAL):
                row.append(sector_tijden_str[i] if i < len(sector_tijden_str) else "")
            row.append(round(gem_snelheid, 2))
            writer.writerow(row)
        
        print(f"\n✔ Rit voltooid voor {self.naam}!")
        print(f"   Totale tijd: {totale_tijd_str}")
        print(f"   Gem. snelheid: {round(gem_snelheid, 2)} km/h")
        print(f"   Opgeslagen in {LEADERBOARD_BESTAND}\n")

def format_tijd(seconden):
    """Format seconden naar mm:ss.s"""
    minuten = int(seconden // 60)
    sec = seconden % 60
    return f"{minuten}:{sec:.1f}"

def zoek_naam(uid_str):
    if not os.path.isfile(TAGS_BESTAND):
        return uid_str
    
    with open(TAGS_BESTAND, newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        next(reader, None)  # Skip header
        for row in reader:
            if row and row[0] == uid_str:
                return row[1]
    
    return uid_str

def is_registratie_modus():
    try:
        response = requests.get(f"{FLASK_URL}/rfid/is_registratie_modus", timeout=0.5)
        if response.ok:
            data = response.json()
            return data.get("registratie_modus", False)
    except:
        pass
    return False

def schrijf_status():
    """Schrijf huidige status naar JSON bestand voor Flask"""
    with sessie_lock:
        status_data = {
            "timestamp": time.time(),
            "actieve_sessies": []
        }
        
        for uid, sessie in actieve_sessies.items():
            verstreken = time.time() - sessie.start_tijd
            status_data["actieve_sessies"].append({
                "uid": uid,
                "naam": sessie.naam,
                "huidige_sector": sessie.huidige_sector(),
                "totaal_sectoren": SECTOR_AANTAL,
                "verstreken_tijd": round(verstreken, 1),
                "sector_tijden": sessie.sector_tijden,
                "start_tijd": sessie.start_tijd
            })
        
        try:
            with open(STATUS_FILE, 'w', encoding='utf-8') as f:
                json.dump(status_data, f)
        except Exception as e:
            print(f"Fout bij schrijven status: {e}")

def verwerk_scan(uid_str):
    """Verwerk een RFID scan"""
    if is_registratie_modus():
        print(f"⚠ Registratie modus actief - scan genegeerd")
        return
    
    with sessie_lock:
        if uid_str in actieve_sessies:
            sessie = actieve_sessies[uid_str]
            if sessie.voltooid:
                print(f"❌ {sessie.naam} heeft al een voltooide rit. Scan genegeerd.")
                schrijf_status()
                return
            print(f"📌 {sessie.naam} - Sector {sessie.huidige_sector()} scan")
            if sessie.voeg_sector_toe() and sessie.voltooid:
                del actieve_sessies[uid_str]
                print(f"✅ Sessie beëindigd voor {sessie.naam}")
        else:
            naam = zoek_naam(uid_str)
            sessie = SessionData(uid_str, naam)
            actieve_sessies[uid_str] = sessie
            print(f"\n🚀 Nieuwe sessie gestart voor {naam}")
            print(f"   Scan je tag bij elke sector ({SECTOR_AANTAL} totaal)")
    
    schrijf_status()

def rfid_scanner_loop():
    if not RFID_AVAILABLE:
        print("⚠ RFID niet beschikbaar - dummy mode actief")
        return
    
    reader = MFRC522()
    laatste_uid = None
    laatste_scan_tijd = 0
    
    print("🎯 Timing service actief - wachten op RFID scans...\n")
    
    while True:
        try:
            (status, TagType) = reader.MFRC522_Request(reader.PICC_REQIDL)
            if status == reader.MI_OK:
                (status, uid) = reader.MFRC522_Anticoll()
                if status == reader.MI_OK:
                    uid_str = "-".join(str(x) for x in uid)
                    nu = time.time()
                    if uid_str != laatste_uid or (nu - laatste_scan_tijd) > 1.0:
                        verwerk_scan(uid_str)
                        laatste_uid = uid_str
                        laatste_scan_tijd = nu
            time.sleep(0.3)
            
        except KeyboardInterrupt:
            print("\n🛑 Service gestopt")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(1)

def status_reporter_loop():
    """Achtergrond thread die periodiek status rapporteert"""
    while True:
        time.sleep(1)  # Update nu elke seconde
        with sessie_lock:
            if actieve_sessies:
                print(f"\n📝 Status: {len(actieve_sessies)} actieve sessie(s)")
                for uid, sessie in actieve_sessies.items():
                    verstreken = time.time() - sessie.start_tijd
                    print(f"   • {sessie.naam}: Sector {sessie.huidige_sector()}/{SECTOR_AANTAL} ({format_tijd(verstreken)})")
                print()
        schrijf_status()

def main():
    print("=" * 60)
    print("🚩 Dirty Hill Timing Service")
    print("=" * 60)
    print(f"Sectoren: {SECTOR_AANTAL}")
    print(f"Afstand: {TOTALE_AFSTAND_KM} km")
    print(f"Debounce: {DEBOUNCE_TIJD}s")
    print("=" * 60 + "\n")
    
    # Start status reporter thread
    status_thread = threading.Thread(target=status_reporter_loop, daemon=True)
    status_thread.start()
    
    # Start RFID scanner (hoofdloop)
    try:
        rfid_scanner_loop()
    finally:
        if RFID_AVAILABLE:
            GPIO.cleanup()

if __name__ == "__main__":
    main()
