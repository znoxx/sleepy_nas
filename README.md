# Sleepy NAS

The purpose of this script is to measure traffic on selected physical interface and put your server to sleep (or execute any other command) in case low threshold is crossed.

Why it is needed:

* You don't use your NAS 24x7
* The purpose of your NAS is to serve you your files via network
* Your NAS provides some noise (ATX-based builds)
* Your NAS eats some electricity (x86 hardware)
* Electricity costs money, better sleep is priceless

For sure -- spin-up and spin-down counts of HDD drives can be not the best trade-off (but modern systems still spindown HDDs to save power). 

So, decision is up to you.

## Prerequisites

* Modern Linux system (systemd is recommended)
* Python 3.x
* sysstat package version 11.7.4+ (older versions do not provide needed flags but still somehow usable after code modifications).
* Working command to put system to sleep (e.g. `systemctl suspend`)
* Working way to wake your system (WOL support or even physical button)

## What script does
* Measures traffic on selected interface in way described in .ini file
* If sum of rx/tx kb per second is below or equal to selected threshold -- puts your server to sleep (or executes desired command).
* If sum of rx/tx kb per second is above threshold -- script sleeps for desired amount of time and then repeats measurement.

sar tool, which is used inside script can do N probes for particular interface for desired period of time and provide average speeds for rx/tx

Let's consider an example:

```
$ LC_ALL=C sar -n DEV --dec=0 --iface=enp5s0 10 2
Linux 5.17.4-arch1-1-vfio (ZNO-Ryzen) 	05/15/22 	_x86_64_	(16 CPU)

16:32:23        IFACE   rxpck/s   txpck/s    rxkB/s    txkB/s   rxcmp/s   txcmp/s  rxmcst/s   %ifutil
16:32:33       enp5s0         2         2         0         0         0         0         0         0

16:32:33        IFACE   rxpck/s   txpck/s    rxkB/s    txkB/s   rxcmp/s   txcmp/s  rxmcst/s   %ifutil
16:32:43       enp5s0         2         2         0         0         0         0         0         0

Average:        IFACE   rxpck/s   txpck/s    rxkB/s    txkB/s   rxcmp/s   txcmp/s  rxmcst/s   %ifutil
Average:       enp5s0         2         2         0         0         0         0         0         0

```

In this example measurement called for interface `enp5s0` 2 times 10 seconds each. In total -- 20 seconds to get data.

Script takes fields "rxKB/s" and "txKB/s" and compares summary value to threshold defined in .ini file.

One can play around with this tool and get some automated measurements 

## INI file parameters and timeline

Let's check parameters one by one:

```
[main]
# Duration of single sar probe in seconds. Must be >0
probe_duration=300
# Count of sar probes. Must be >0
probe_count=2
# Interval between sar calls in seconds. Can be 0.
probe_interval=300
# Minimal value of traffic. On linux sar is in kilobytes. Cannot be 0.
threshold_value=8
# Your physical interface. Better to use physical interface to meausre traffic. Avoid virtual interfaces for false positive/negative results.
interface=enp2s0
# Command to execute (usually suspend). One can safely add sudo if passwordless sudo for this command is set up properly and script running without root permissions.
command=systemctl suspend
# Back-off interval in seconds after command execution. Usually used to let system wake from sleep. Can be 0, but for predictable results use something like 10 seconds.
command_backoff_interval=10
```

So timeline will be:

* Start measurement
* Measure for `probe_duration*probe_count` (total -- 600 seconds).
* If threshold is below 8kb/s -- `systemctl suspend` will be called.
* After wake up (if we were below threshold and gone to sleep ).`command_backoff_interval` sleep will be taken -- 10 seconds. (It allows to safely wait for system to wake up).
* `probe_interval` sleep will be taken.
* Cycle will restart from the beginning (start measurement).

Current settings work for me, e.g. I use NAS to broadcast movies via PLEX before bedtime. 
When I'm done with a movie, my NAS automagically goes to sleep after 20 minutes, since there is no traffic.

## Running script

Command line:
```
$ ./sleepy_nas.py --help
usage: sleepy_nas.py [-h] [-v] [INI]

Measures traffic via sar tool on interface described in .ini file with desired number of probes and period. If no .ini specified -- will try to load 'sleepy_nas.ini' from current folder. On failure -- will use some defaults for illustration purposes.

positional arguments:
  INI            Ini file with parameters

options:
  -h, --help     show this help message and exit
  -v, --verbose  increase output verbosity
```

One must supply own values, described in .ini file. However, default values include dummy "suspend_stub_command" which will fail on execution (unless you have such command defined in your Linux ).

Good option is to run script with '--verbose' to see what is loaded and how it is running before putting it into everyday usage.

INI template contains some numbers, which "work for me".

## Using it via systemd

* Copy script itself to /opt/sleepy_nas/sleepy_nas.py.
* Copy INI file -- `cp sleepy_nas.ini.template /opt/sleepy_nas/sleepy_nas.ini`.
* Modify file `/opt/sleepy_nas/sleepy_nas.ini` and put your own values. Make sure selected command to suspend system is working (see prerequisites section).
* Copy systemd service file -- `cp sleepy_nas.service.tempate /lib/systemd/system/sleepy_nas.service`.
* Modify file `/lib/systemd/system/sleepy_nas.service` if needed, however it is completely generic. Avoid to change KillSignal value, since SIGINT is used to gracefully stop the script.
* Enable service: `sudo systemctl enable sleepy_nas`.
* Start service: `sudo systemctl start sleepy_nas`.

You can stop tool at any time via `systemctl stop sleepy_nas` and enjoy your server running 24x7.

Enjoy some savings on electricity bill and better sleep.

## Area of improvement (someday)

* Get rid of "sar" dependency -- implement iface statistics on pure python.
* Checks of BSD systems (unfortunately I don't have any at hand).

## Tested platforms

Tests are made on x86 systems, however should be no problem running it on e.g. ARM-based hardware. 

Generally it will work, if system can be put to sleep via command and wake up is possible via WOL or button.

Tested on:

* Ubuntu 20.04 -- my own "production" NAS.
* Manjaro (rolling release).
* Fedora 34 (sar command only to produce expected results).

## Historical data

This tool inspired by this post: https://hackaday.com/2013/02/21/self-waking-computer-for-diy-cloud-storage/

Unfortunately, original post linked to H-a-D article in N/A. For some reasons I saved initial scripts for system sleep on "no traffic". They worked for me for years "somehow". but I decided to rework them to something more predictable and maintainable.

You can find original shell scripts in folder "original_shell".




