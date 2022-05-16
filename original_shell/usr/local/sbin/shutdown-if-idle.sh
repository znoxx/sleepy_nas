#!/bin/bash

#/root/shutdown-if-idle.sh

# Dominic Canare
# dom@domstyle.net

shutdownDelay=120   # seconds to wait before shutdown
samplePeriod=300 # seconds to query network per sample
sampleCount=2    # number of samples

threshold=8      # kb threshold for idle status
iface=enp2s0      # interface to watch

# get current net stats | look at the average for our iface || get total transfer | truncate to integer
usage=$(sar -n DEV $samplePeriod $sampleCount | grep "Average: *$iface" | tr -s " ")
tx=$(echo "$usage" | cut -d " " -f 5 | cut -d "." -f 1)
rx=$(echo "$usage" | cut -d " " -f 6 | cut -d "." -f 1)
echo "Usage is '$tx' + '$rx' vs '$threshold' $(date)" >> /dev/shm/usage.log
usage=$(($tx + $rx))

if [ "$usage" -lt "$threshold" ]; then
echo "Suspending..." >>/dev/shm/usage.log
/usr/local/sbin/go-to-sleep.sh $shutdownDelay &
else
killall go-to-sleep.sh
echo "Cancelling suspend..." >>/dev/shm/usage.log
fi
