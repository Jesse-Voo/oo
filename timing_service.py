#!/usr/bin/env python3
"""
Timing Service - RFID voor rijder identificatie, knop voor sectoren
Scan RFID → Start sessie, Druk op knop → Registreer sector
"""

import time
import csv
import os
import json
import threading
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

# Import stoplicht controller
try:
    from stoplicht_controller import StoplichtController
    STOPLICHT_AVAILABLE = True
except ImportError:
    print("⚠️  stoplicht_controller.py niet gevonden - LED feedback uitgeschakeld")
    STOPLICHT_AVAILABLE = False

# Configuratie
SECTOR_AANTAL = 3
TAGS_BESTAND = "tags.csv"
LEADERBOARD_BESTAND = "voorbeeld_leaderboard.csv"
TOTALE_AFSTAND_KM = 7.2
KNOP_PIN = 26  # GPIO pin voor de sector knop
DEBOUNCE_TIJD = 1.0  # Seconden tussen knop presses
STATUS_FILE = "timing_status.json"

# Actieve sessies: {uid: SessionData}
actieve_sessies = {}
sessie_lock = threading.Lock()
laatste_rfid_scan = {"uid": None, "tijd": 0}

# Initialiseer stoplicht controller
stoplicht = None
if STOPLICHT_AVAILABLE:
    stoplicht = StoplichtController()
    print("✅ Stoplicht controller geïnitialiseerd")

class SessionData:
    """Data voor een actieve timing sessie"""
    def __init__(self, uid, naam):
        self.uid = uid
        self.naam = naam
        self.start_tijd = time.time()
        self.sector_tijden = []
        self.laatste_sector = time.time()
        self.voltooid = False
        
    def huidige_sector(self):
        return len(self.sector_tijden) + 1
    
    def is_klaar(self):
        return len(self.sector_tijden) >= SECTOR_AANTAL
    
    def voeg_sector_toe(self):
        """Registreer een sector tijd"""
        nu = time.time()
        
        # Check debounce
        if nu - self.laatste_sector < DEBOUNCE_TIJD:
            print("⚠️  Te snel - wacht even tussen sectoren")
            return False
        
        if len(self.sector_tijden) == 0:
            # Eerste sector - tijd sinds start
            sector_tijd = nu - self.start_tijd
        else:
            # Volgende sectoren - tijd sinds laatste sector
            sector_tijd = nu - self.laatste_sector
        
        self.sector_tijden.append(sector_tijd)
        self.laatste_sector = nu
        
        sector_nummer = len(self.sector_tijden)
        print(f"  Sector {sector_nummer}: {format_tijd(sector_tijd)}")
        
        # STOPLICHT FEEDBACK VOOR SECTOR
        if stoplicht:
            stoplicht.vergelijk_sector(self.naam, sector_nummer, sector_tijd)
        
        if self.is_klaar():
            self.voltooid = True
            self.sla_resultaat_op()
        
        return True
    
    def sla_resultaat_op(self):
        """Sla de volledige rit op in CSV"""
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
        
        print(f"\n✅ Rit voltooid voor {self.naam}!")
        print(f"   Totale tijd: {totale_tijd_str}")
        print(f"   Gem. snelheid: {round(gem_snelheid, 2)} km/h")
        print(f"   Opgeslagen in {LEADERBOARD_BESTAND}\n")
        
        # STOPLICHT FEEDBACK VOOR TOTALE TIJD
        if stoplicht:
            stoplicht.vergelijk_totaal(self.naam, totale_tijd_sec)
            # Herlaad beste tijden voor volgende vergelijking
            stoplicht.laad_beste_tijden()

def format_tijd(seconden):
    """Format seconden naar mm:ss.s"""
    minuten = int(seconden // 60)
    sec = seconden % 60
    return f"{minuten}:{sec:.1f}"

def zoek_naam(uid_str):
    """Zoek naam bij UID in tags bestand"""
    if not os.path.isfile(TAGS_BESTAND):
        return uid_str
    
    with open(TAGS_BESTAND, newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        next(reader, None)  # Skip header
        for row in reader:
            if row and row[0] == uid_str:
                return row[1]
    
    return uid_str

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
                "verstreken_tijd": verstreken,
                "sector_tijden": sessie.sector_tijden,
                "start_tijd": sessie.start_tijd
            })
        
        try:
            with open(STATUS_FILE, 'w') as f:
                json.dump(status_data, f)
        except Exception as e:
            print(f"Fout bij schrijven status: {e}")

def knop_ingedrukt(channel):
    """Callback wanneer knop wordt ingedrukt"""
    print("\n🔘 KNOP INGEDRUKT")
    
    with sessie_lock:
        if len(actieve_sessies) == 0:
            # Geen actieve sessie - check of er recent een RFID scan was
            if laatste_rfid_scan["uid"] is None:
                print("❌ Geen RFID scan gevonden")
                print("   Scan eerst je RFID tag voordat je de knop indrukt!")
                return
            
            # Check of scan niet te oud is (max 10 seconden)
            scan_age = time.time() - laatste_rfid_scan["tijd"]
            if scan_age > 10:
                print(f"⚠️  RFID scan te oud ({scan_age:.1f}s geleden)")
                print("   Scan opnieuw je RFID tag!")
                return
            
            uid = laatste_rfid_scan["uid"]
            naam = zoek_naam(uid)
            
            # Start nieuwe sessie
            sessie = SessionData(uid, naam)
            actieve_sessies[uid] = sessie
            
            print(f"🚀 Nieuwe sessie gestart voor {naam}")
            print(f"   Druk op de knop bij elke sector ({SECTOR_AANTAL} totaal)")
            
            # Reset laatste scan
            laatste_rfid_scan["uid"] = None
            
        else:
            # Er is al een actieve sessie - registreer sector
            # Neem de eerste actieve sessie (normaal is er maar 1)
            uid = list(actieve_sessies.keys())[0]
            sessie = actieve_sessies[uid]
            
            if sessie.voltooid:
                print(f"⚠️  Sessie voor {sessie.naam} is al voltooid")
                del actieve_sessies[uid]
                return
            
            print(f"📍 {sessie.naam} - Sector {sessie.huidige_sector()} geregistreerd")
            
            if sessie.voeg_sector_toe():
                if sessie.voltooid:
                    # Sessie is klaar, verwijder uit actieve sessies
                    del actieve_sessies[uid]
                    print(f"🏁 Sessie beëindigd voor {sessie.naam}")
    
    # Update status file
    schrijf_status()

def rfid_scanner_loop():
    """Hoofdloop die continu naar RFID scans luistert (alleen voor naam)"""
    if not RFID_AVAILABLE:
        print("⚠️  RFID niet beschikbaar - dummy mode actief")
        return
    
    reader = MFRC522()
    laatste_uid = None
    laatste_scan_tijd = 0
    
    print("🎯 RFID scanner actief - scan je tag om een sessie voor te bereiden...\n")
    
    while True:
        try:
            (status, TagType) = reader.MFRC522_Request(reader.PICC_REQIDL)
            if status == reader.MI_OK:
                (status, uid) = reader.MFRC522_Anticoll()
                if status == reader.MI_OK:
                    uid_str = "-".join(str(x) for x in uid)
                    nu = time.time()
                    
                    # Debounce - voorkom dubbele scans
                    if uid_str != laatste_uid or (nu - laatste_scan_tijd) > 2.0:
                        naam = zoek_naam(uid_str)
                        
                        with sessie_lock:
                            # Check of deze rijder al een actieve sessie heeft
                            if uid_str in actieve_sessies:
                                print(f"ℹ️  {naam} heeft al een actieve sessie")
                            else:
                                # Sla scan op voor wanneer knop wordt ingedrukt
                                laatste_rfid_scan["uid"] = uid_str
                                laatste_rfid_scan["tijd"] = nu
                                print(f"✅ RFID scan: {naam}")
                                print(f"   Druk op de knop om de sessie te starten!")
                        
                        laatste_uid = uid_str
                        laatste_scan_tijd = nu
            
            time.sleep(0.3)
            
        except KeyboardInterrupt:
            print("\n\n🛑 Service gestopt")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(1)

def setup_knop():
    """Initialiseer GPIO knop"""
    if not RFID_AVAILABLE:
        print("🔧 GPIO simulatie modus - geen echte knop")
        return
    
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(KNOP_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    # Interrupt op dalende flank (knop indrukken)
    GPIO.add_event_detect(KNOP_PIN, GPIO.FALLING, 
                         callback=knop_ingedrukt, 
                         bouncetime=300)  # 300ms debounce
    
    print(f"✅ Knop geconfigureerd op GPIO {KNOP_PIN}")
    print("   Druk op de knop om te starten of een sector te registreren\n")

def status_reporter_loop():
    """Achtergrond thread die periodiek status rapporteert"""
    while True:
        time.sleep(30)  # Elke 30 seconden
        
        with sessie_lock:
            if actieve_sessies:
                print(f"\n📊 Status: {len(actieve_sessies)} actieve sessie(s)")
                for uid, sessie in actieve_sessies.items():
                    verstreken = time.time() - sessie.start_tijd
                    print(f"   • {sessie.naam}: Sector {sessie.huidige_sector()}/{SECTOR_AANTAL} ({format_tijd(verstreken)})")
                print()
        
        # Update status file
        schrijf_status()

def main():
    """Start de timing service"""
    print("=" * 60)
    print("🏁 Dirty Hill Timing Service")
    print("=" * 60)
    print(f"Sectoren: {SECTOR_AANTAL}")
    print(f"Afstand: {TOTALE_AFSTAND_KM} km")
    print(f"Knop pin: GPIO {KNOP_PIN}")
    print(f"Mode: RFID voor naam, Knop voor sectoren")
    print("=" * 60 + "\n")
    
    # Start status reporter thread
    status_thread = threading.Thread(target=status_reporter_loop, daemon=True)
    status_thread.start()
    
    # Setup knop
    setup_knop()
    
    # Start RFID scanner (hoofdloop)
    try:
        rfid_scanner_loop()
    finally:
        if RFID_AVAILABLE:
            GPIO.cleanup()
        if stoplicht:
            stoplicht.cleanup()

if __name__ == "__main__":
    main()
