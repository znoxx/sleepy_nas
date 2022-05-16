#!/bin/sh
TIMEOUT=$1
sleep $TIMEOUT
sudo systemctl suspend
killall `basename $0`

