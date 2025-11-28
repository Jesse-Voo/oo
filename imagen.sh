#!/bin/bash

# 1. Kies bron-disk uit menu
SRC=$(lsblk -dno NAME,SIZE | while read n s; do
    echo "$n \"$s\"";
done | whiptail --title "Bron-disk kiezen" --menu "Welke disk wil je imagen?" 20 60 10 3>&1 1>&2 2>&3)

SRCDEV="/dev/$SRC"

# 2. Kies doelmap uit menu (alle gemounte locaties)
DSTDIR=$(df -h | awk 'NR>1 {print $6" \""$6"\""}' \
    | whiptail --title "Map kiezen" --menu "Waar moet het image komen?" 20 60 10 3>&1 1>&2 2>&3)

# 3. Bestandsnaam via standaard invoer
DSTFILE=$(whiptail --inputbox "Bestandsnaam:" 10 60 "pi_backup.img.gz" 3>&1 1>&2 2>&3)

# 4. Bevestiging
whiptail --yesno "Image maken van $SRCDEV naar $DSTDIR/$DSTFILE ?" 10 60 || exit 1

# 5. Uitvoeren
dd if="$SRCDEV" bs=4M status=progress | gzip > "$DSTDIR/$DSTFILE"
sync

whiptail --msgbox "Klaar! Bestand staat op: $DSTDIR/$DSTFILE" 10 40
