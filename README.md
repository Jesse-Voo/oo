sudo dd if=/dev/mmcblk0 bs=4M status=progress | gzip > /media/usb/pi_backup.img.gz
sync
