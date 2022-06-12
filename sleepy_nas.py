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


class HooksError(Error):
    """Raised when problem with hooks occured"""
    pass


class Config:
    def __init__(self,
                 probe_duration=300,
                 probe_count=2,
                 probe_interval=300,
                 threshold_value=8,
                 interface="eth0",
                 command='suspend_stub_command',
                 command_backoff_interval=30,
                 sidecar_enabled=False,
                 sidecar_address="",
                 sidecar_server_id="unknown",
                 sleep_hooks="",
                 wake_hooks=""
                 ):
        self.probe_duration = probe_duration
        self.probe_count = probe_count
        self.probe_interval = probe_interval
        self.threshold_value = threshold_value
        self.command = command
        self.command_backoff_interval = command_backoff_interval
        self.interface = interface
        self.sidecar_enabled = sidecar_enabled
        self.sidecar_address = sidecar_address
        self.sidecar_server_id = sidecar_server_id
        self.sleep_hooks = sleep_hooks
        self.wake_hooks = wake_hooks

    def __str__(self):
        return "probe_duration: {0}, \
        probe_count: {1}, \
        probe_interval: {2}, \
        threshold_value: {3}, \
        command: {4}, \
        interface {5}, \
        command_backoff_interval {6},  \
        sidecar_enabled {7}, \
        sidecar_address {8}, \
        sidecar_server_id {9}, \
        sleep_hooks {10}, \
        wake_hooks {11} ".format(
            self.probe_duration,
            self.probe_count,
            self.probe_interval,
            self.threshold_value,
            self.command,
            self.interface,
            self.command_backoff_interval,
            self.sidecar_enabled,
            self.sidecar_address,
            self.sidecar_server_id,
            self.sleep_hooks,
            self.wake_hooks
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
            if config.has_option("sidecar", "sidecar_address"):
                self.sidecar_enabled = True
                self.sidecar_address = config.get("sidecar", "sidecar_address")
            if self.sidecar_enabled:
                if not config.has_option("sidecar", "sidecar_server_id"):
                    raise ConfigError("Server ID for sidecar is not set!")
                else:
                    self.sidecar_server_id = config.get("sidecar", "sidecar_server_id")
                    logging.debug("Sidecar config loaded, sidecar integration enabled")
            if config.has_option("hooks", "before_sleep"):
                self.sleep_hooks = config.get("hooks", "before_sleep")
            if config.has_option("hooks", "after_sleep"):
                self.wake_hooks = config.get("hooks", "after_sleep")

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


def call_sidecar(sidecar_address, sidecar_server_id, sidecar_status, sidecar_timeout=2):
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    logging.debug("Sidecar integration enabled, calling sidecar {0} to set server {1} status to {2}".
                  format(sidecar_address, sidecar_server_id, sidecar_status))
    request = Request(sidecar_address + "/status/" + sidecar_status + "/" + sidecar_server_id, urlencode({}).encode())
    try:
        json = urlopen(request, timeout=sidecar_timeout).read().decode()
        logging.info("Sidecar reply: {0}".format(json))
    except Exception as e:
        logging.error("Error accessing sidecar: {0}".format(e))


def call_hooks(folder, onsleep=True):
    from os import system
    if onsleep:
        logging.info("Calling pre-sleep hooks")
        command_line = "run-parts --exit-on-error {0}".format(folder)
    else:
        logging.info("Calling post-wake hooks")
        command_line = "run-parts  {0}".format(folder)
    return system(command_line)


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
        else:
            logging.info("sar sanity check passed!")
    except SarError:
        logging.exception("sar sanity check failed")
        raise



    logging.debug("Loading config file {0}".format(args.ini))
    currentConfig = Config()
    currentConfig.load_ini_file(args.ini)
    logging.debug("Config loaded: {0}".format(currentConfig))

    if currentConfig.sleep_hooks or currentConfig.wake_hooks:
        try:
            if call(['which', 'run-parts'],
                    stdout=DEVNULL,
                    stderr=STDOUT):
                raise HooksError("run-parts command not found")
            else:
                logging.info("run-parts sanity check passed!")
        except HooksError:
            logging.exception("run-parts sanity check failed")
            raise



    global running
    signal.signal(signal.SIGINT, sigint_handler)

    while running:

        result = call_sar(currentConfig.probe_duration, currentConfig.probe_count, currentConfig.interface)
        if result <= currentConfig.threshold_value:
            if running:
                logging.info("Threshold crossed, executing  command")

                can_i_sleep = True
                if currentConfig.sleep_hooks:
                    hook_res = call_hooks(currentConfig.sleep_hooks, True)
                    if hook_res != 0:
                        can_i_sleep = False
                        logging.error("Sleep hooks execution failed, skipping command execution!")

                if can_i_sleep:
                    if currentConfig.sidecar_enabled:
                        call_sidecar(currentConfig.sidecar_address, currentConfig.sidecar_server_id, "sleep")

                    call_command(currentConfig.command, currentConfig.command_backoff_interval)

                    if currentConfig.sidecar_enabled:
                        call_sidecar(currentConfig.sidecar_address, currentConfig.sidecar_server_id, "wake")

                    if currentConfig.wake_hooks:
                        call_hooks(currentConfig.wake_hooks, False)
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
