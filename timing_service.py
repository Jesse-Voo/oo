#!/usr/bin/env python3
"""
Timing Service - Knop gebaseerd timing systeem
Leest rijder uit latest_detection.json en gebruikt knop voor sectoren
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
    GPIO.setwarnings(False)
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("GPIO niet beschikbaar - simulatie modus")

# Import stoplicht controller
try:
    from stoplicht_controller import StoplichtController
    STOPLICHT_AVAILABLE = True
except ImportError:
    print("⚠️  stoplicht_controller.py niet gevonden - LED feedback uitgeschakeld")
    STOPLICHT_AVAILABLE = False

# Configuratie
SECTOR_AANTAL = 3
DETECTION_FILE = "latest_detection.json"
LEADERBOARD_BESTAND = "voorbeeld_leaderboard.csv"
TOTALE_AFSTAND_KM = 7.2
KNOP_PIN = 4  # GPIO pin voor de sector knop (pas aan naar jouw setup)
DEBOUNCE_TIJD = 1.0  # Seconden tussen knop presses
STATUS_FILE = "timing_status.json"

# Actieve sessies: {rfid_id: SessionData}
actieve_sessies = {}
sessie_lock = threading.Lock()

# Initialiseer stoplicht controller
stoplicht = None
if STOPLICHT_AVAILABLE:
    stoplicht = StoplichtController()
    print("✅ Stoplicht controller geïnitialiseerd")

class SessionData:
    """Data voor een actieve timing sessie"""
    def __init__(self, rfid_id, naam):
        self.rfid_id = rfid_id
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

def lees_laatste_detectie():
    """Lees de laatste RFID detectie uit JSON bestand"""
    if not os.path.exists(DETECTION_FILE):
        return None
    
    try:
        with open(DETECTION_FILE, 'r') as f:
            data = json.load(f)
        
        return {
            'rfid_id': data.get('rfid_id'),
            'name': data.get('name', data.get('rfid_id'))
        }
    except Exception as e:
        print(f"❌ Fout bij lezen detectie: {e}")
        return None

def schrijf_status():
    """Schrijf huidige status naar JSON bestand voor Flask"""
    with sessie_lock:
        status_data = {
            "timestamp": time.time(),
            "actieve_sessies": []
        }
        
        for rfid_id, sessie in actieve_sessies.items():
            verstreken = time.time() - sessie.start_tijd
            status_data["actieve_sessies"].append({
                "rfid_id": rfid_id,
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
            # Geen actieve sessie - start nieuwe sessie
            detectie = lees_laatste_detectie()
            
            if not detectie:
                print("❌ Geen recente RFID detectie gevonden")
                print("   Scan eerst je RFID tag voordat je de knop indrukt!")
                return
            
            rfid_id = detectie['rfid_id']
            naam = detectie['name']
            
            # Start nieuwe sessie
            sessie = SessionData(rfid_id, naam)
            actieve_sessies[rfid_id] = sessie
            
            print(f"🚀 Nieuwe sessie gestart voor {naam}")
            print(f"   Druk op de knop bij elke sector ({SECTOR_AANTAL} totaal)")
            
        else:
            # Er is al een actieve sessie - registreer sector
            # Neem de eerst actieve sessie (normaal is er maar 1)
            rfid_id = list(actieve_sessies.keys())[0]
            sessie = actieve_sessies[rfid_id]
            
            if sessie.voltooid:
                print(f"⚠️  Sessie voor {sessie.naam} is al voltooid")
                del actieve_sessies[rfid_id]
                return
            
            print(f"📍 {sessie.naam} - Sector {sessie.huidige_sector()} geregistreerd")
            
            if sessie.voeg_sector_toe():
                if sessie.voltooid:
                    # Sessie is klaar, verwijder uit actieve sessies
                    del actieve_sessies[rfid_id]
                    print(f"🏁 Sessie beëindigd voor {sessie.naam}")
    
    # Update status file
    schrijf_status()

def setup_knop():
    """Initialiseer GPIO knop"""
    if not GPIO_AVAILABLE:
        print("🔧 GPIO simulatie modus - geen echte knop")
        return
    
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(KNOP_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
        # Verwijder eerst oude event detection als die bestaat
        try:
            GPIO.remove_event_detect(KNOP_PIN)
        except:
            pass  # Geen event detection om te verwijderen
        
        # Interrupt op dalende flank (knop indrukken)
        GPIO.add_event_detect(KNOP_PIN, GPIO.FALLING, 
                             callback=knop_ingedrukt, 
                             bouncetime=300)  # 300ms debounce
        
        print(f"✅ Knop geconfigureerd op GPIO {KNOP_PIN}")
        print("   Druk op de knop om te starten of een sector te registreren")
    except Exception as e:
        print(f"❌ Fout bij configureren knop: {e}")
        print("   Probeer: sudo python3 timing_service.py")
        raise

def status_reporter_loop():
    """Achtergrond thread die periodiek status rapporteert"""
    while True:
        time.sleep(30)  # Elke 30 seconden
        
        with sessie_lock:
            if actieve_sessies:
                print(f"\n📊 Status: {len(actieve_sessies)} actieve sessie(s)")
                for rfid_id, sessie in actieve_sessies.items():
                    verstreken = time.time() - sessie.start_tijd
                    print(f"   • {sessie.naam}: Sector {sessie.huidige_sector()}/{SECTOR_AANTAL} ({format_tijd(verstreken)})")
                print()
        
        # Update status file
        schrijf_status()

def simulatie_loop():
    """Simulatie modus voor testen zonder GPIO"""
    print("\n⌨️  SIMULATIE MODUS")
    print("Druk op ENTER om een knop druk te simuleren")
    print("Type 'quit' om te stoppen\n")
    
    while True:
        cmd = input()
        if cmd.lower() == 'quit':
            break
        knop_ingedrukt(None)

def main():
    """Start de timing service"""
    print("=" * 60)
    print("🏁 Dirty Hill Timing Service (Knop Mode)")
    print("=" * 60)
    print(f"Sectoren: {SECTOR_AANTAL}")
    print(f"Afstand: {TOTALE_AFSTAND_KM} km")
    print(f"Detectie bestand: {DETECTION_FILE}")
    print(f"Knop pin: GPIO {KNOP_PIN}")
    print("=" * 60 + "\n")
    
    # Start status reporter thread
    status_thread = threading.Thread(target=status_reporter_loop, daemon=True)
    status_thread.start()
    
    # Setup knop
    setup_knop()
    
    try:
        if GPIO_AVAILABLE:
            print("🎯 Service actief - wachten op knop presses...\n")
            # Blijf draaien
            while True:
                time.sleep(1)
        else:
            # Simulatie modus
            simulatie_loop()
    except KeyboardInterrupt:
        print("\n\n🛑 Service gestopt")
    finally:
        if GPIO_AVAILABLE:
            GPIO.cleanup()
        if stoplicht:
            stoplicht.cleanup()

if __name__ == "__main__":
    main()
