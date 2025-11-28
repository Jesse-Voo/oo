#!/bin/bash

SRC=$(lsblk -ndo NAME,SIZE | awk '{print $1" ("$2")"}' \
      | whiptail --title "Select source disk" --menu "Disk to image:" 20 78 10 3>&1 1>&2 2>&3)

SRCDEV="/dev/$(echo $SRC | cut -d' ' -f1)"

DST=$(whiptail --inputbox "Path to output image file (e.g. /media/pi/USB/backup.img.gz)" 10 60 3>&1 1>&2 2>&3)

whiptail --yesno "Confirm: image $SRCDEV → $DST ?" 10 60
if [ $? -ne 0 ]; then
    exit 1
fi

dd if="$SRCDEV" bs=4M status=progress | gzip > "$DST"
sync

whiptail --msgbox "Image completed." 10 40
