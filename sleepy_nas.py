#!/usr/bin/env python3

import argparse
import configparser
import logging
import re
import time
from subprocess import Popen, PIPE, call, STDOUT, DEVNULL
import signal
from sys import maxsize as py_max_int
from threading import Event
import os
import fcntl

running = True
exit_event = Event()
label = "default"


class Error(Exception):
    """Base class for other exceptions"""
    pass


class SarError(Error):
    """Raised when sar problem occures"""
    pass


class CommandError(Error):
    """Raised when command problem occures"""
    pass


class ConfigError(Error):
    """Raied when inconsitency detected in config"""
    pass


class Config:
    def __init__(self,
                 probe_duration=300,
                 probe_count=2,
                 probe_interval=300,
                 threshold_value=8,
                 interface="eth0",
                 command='suspend_stub_command',
                 command_backoff_interval=30
                 ):
        self.probe_duration = probe_duration
        self.probe_count = probe_count
        self.probe_interval = probe_interval
        self.threshold_value = threshold_value
        self.command = command
        self.command_backoff_interval = command_backoff_interval
        self.interface = interface

    def __str__(self):
        return "probe_duration: {0}, \
        probe_count: {1}, \
        probe_interval: {2}, \
        threshold_value: {3}, \
        command: {4}, \
        interface {5}, \
        command_backoff_interval {6}".format(
            self.probe_duration,
            self.probe_count,
            self.probe_interval,
            self.threshold_value,
            self.command,
            self.interface,
            self.command_backoff_interval
        )

    def load_ini_file(self, ini_file):
        config = configparser.ConfigParser()
        try:
            with open(ini_file) as f:
                config.read_file(f)
        except IOError:
            logging.exception("Ini file {0} not loaded. Default values used: {1}".format(ini_file, self))

        try:
            if config.has_option("main", "probe_duration"):
                self.probe_duration = config.getfloat("main", "probe_duration")
                if not (self.probe_duration > 0):
                    raise ConfigError("Probe duration {0} in invalid".format(self.probe_duration))
            if config.has_option("main", "probe_count"):
                self.probe_count = config.getint("main", "probe_count")
                if not (self.probe_count > 0):
                    raise ConfigError("Probe count {0} in invalid".format(self.probe_count))
            if config.has_option("main", "probe_interval"):
                self.probe_interval = config.getfloat("main", "probe_interval")
                if not (self.probe_interval >= 0):
                    raise ConfigError("Probe interval {0} in invalid".format(self.probe_interval))
            if config.has_option("main", "threshold_value"):
                self.threshold_value = config.getint("main", "threshold_value")
                if (self.threshold_value < 0):
                    raise ConfigError("Threshold value {0} in invalid".format(self.threshold_value))
            if config.has_option("main", "command"):
                self.command = config.get("main", "command")
            if config.has_option("main", "interface"):
                self.interface = config.get("main", "interface")
            if config.has_option("main", "command_backoff_interval"):
                self.command_backoff_interval = config.getfloat("main", "command_backoff_interval")
                if not (self.command_backoff_interval >= 0):
                    raise ConfigError("Command backoff interval {0} in invalid".format(self.command_backoff_interval))
        except ConfigError:
            logging.exception("Configuration inconsistency")
            raise


def sigint_handler(signal, frame):
    global running
    global exit_event
    logging.info("Received SIGINT, processing...")
    running = False
    exit_event.set()


def sleepy_sleep(interval):
    global exit_event
    logging.debug("sleep -- Waiting for {0} seconds".format(interval))
    for i in range(int(interval / 0.1)):
        time.sleep(0.1)
        if exit_event.is_set():
            break
    logging.debug("sleep -- Finished waiting")


# https://stackoverflow.com/questions/380870/make-sure-only-a-single-instance-of-a-program-is-running
def instance_already_running(lock_label="default"):
    """
    Detect if an instance with the label is already running, globally
    at the operating system level.

    Using `os.open` ensures that the file pointer won't be closed
    by Python's garbage collector after the function's scope is exited.

    The lock will be released when the program exits, or could be
    released if the file pointer were closed.
    """

    lock_file_pointer = os.open("/tmp/sleepy_nas_{0}.lock".format(lock_label), os.O_WRONLY | os.O_CREAT)

    try:
        fcntl.lockf(lock_file_pointer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        already_running = False
    except IOError:
        already_running = True

    return already_running


def delete_lock(lock_label="default"):
    os.remove("/tmp/sleepy_nas_{0}.lock".format(lock_label))
    logging.debug("Lock deleted")


def call_sar(probe_duration, probe_count, interface):
    cmd = Popen(
        'LC_ALL=C sar -n DEV --dec=0 --iface={0} {1} {2}'.format(interface, int(probe_duration), int(probe_count)),
        shell=True, stdout=PIPE)
    rc = cmd.wait()
    logging.debug("sar call executed")
    try:
        if rc:
            raise SarError("Something went wrong. sar execution failed with error code {0}".format(rc))

        pattern = re.compile("^Average.*{0}".format(interface))
        result = ""
        for line in cmd.stdout:
            if re.match(pattern, line.decode('utf-8')):
                result = line

        if result:
            data = result.split()
        else:
            raise SarError("sar returned no data! Probably interface is not configured")

    except SarError:
        global running
        if running:
            logging.exception("Error during sar execution")
            raise
        else:
            pass
    if 'data' in locals():
        return int(data[4]) + int(data[5])
    else:
        return py_max_int


def call_command(command, backoff_interval):
    cmd = Popen('LC_ALL=C {0}'.format(command), shell=True, stdout=PIPE)
    rc = cmd.wait()
    try:
        if rc:
            raise CommandError("Something went wrong. Command {0} failed with return code {1}".format(command, rc))
        logging.debug("Command {0} executed.".format(command))
        sleepy_sleep(backoff_interval)
    except CommandError:
        global running
        if running:
            logging.exception("Error during command execution")
            raise
        else:
            pass


def main(args, loglevel):
    try:
        if instance_already_running(label):
            raise Error("Already running")
    except Error:
        logging.exception("Another instance is already running")
        raise

    logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s", level=loglevel, datefmt='%Y-%m-%d %H:%M:%S')

    try:

        if call(['which', 'sar'],
                stdout=DEVNULL,
                stderr=STDOUT):
            raise SarError("sar command not found")
    except SarError:
        logging.exception("sar sanity check failed")
        raise

    logging.info("sar sanity check passed!")

    logging.debug("Loading config file {0}".format(args.ini))
    currentConfig = Config()
    currentConfig.load_ini_file(args.ini)
    logging.debug("Config loaded: {0}".format(currentConfig))

    global running
    signal.signal(signal.SIGINT, sigint_handler)

    while running:

        result = call_sar(currentConfig.probe_duration, currentConfig.probe_count, currentConfig.interface)
        if result <= currentConfig.threshold_value:
            if running:
                logging.info("Threshold crossed, executing  command")
                call_command(currentConfig.command, currentConfig.command_backoff_interval)
        else:
            logging.debug("Threshold not crossed -- average traffic is {0} kb/s continue...".format(result))

        if running:
            sleepy_sleep(currentConfig.probe_interval)

    delete_lock(label)
    logging.info("Exiting...")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Measures traffic via sar tool on interface described in .ini file with desired number of probes "
                    "and period. If no .ini specified -- will try to load 'sleepy_nas.ini' from current folder. On "
                    "failure -- will use some defaults for illustration purposes.",
        epilog="As an alternative to the commandline, params can be placed in a file, one per line, and specified on \
        the commandline like '%(prog)s @params.conf'.",
        fromfile_prefix_chars='@')

    parser.add_argument(
        "ini",
        help="Ini file with parameters",
        metavar="INI",
        default="sleepy_nas.ini",
        nargs='?'
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="increase output verbosity",
        action="store_true")
    arguments = parser.parse_args()

    if arguments.verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    main(arguments, log_level)
