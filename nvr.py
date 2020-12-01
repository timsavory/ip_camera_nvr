# external imports
import sys, os, logging, time, signal, glob, shutil
import yaml
import logging.handlers
from datetime import datetime
from threading import Event, Thread
# internal imports
from recorder import FFmpegRecorder, Timeout

# read the configuration file
CONFIG_FILE = os.environ.get('CONFIG_FILE','/config/config.yml')
with open(CONFIG_FILE) as f:
    CONFIG = yaml.safe_load(f)

# length of each segment in seconds
segment_time = CONFIG.get('segment_time', 300) 
# number of days to save files for
saving_period = CONFIG.get('saving_period', 1) 
# Restart threshold in seconds, if file size is the same after this seconds, process will be restarted
restart_threshold = CONFIG.get('restart_threshold',30) 
# monitoring interval in seconds
monitor_interval = CONFIG.get('monitor_interval',5) 
# cameral url
src = CONFIG['input']
protocol = CONFIG['protocol']

# create the video recording directory

out_path = '/clips'
if not os.path.exists(out_path):
    print('path did not exist')
    if not os.path.islink(out_path):
        print('path islink not true')
        os.makedirs(out_path)
        print('path ', out_path,' made')

# initialise stop event and monitoring status
event = Event()
monitoring = False

# setup functions to check on status of ffmpeg and alert if process is
# stuck

class AlertDecider:
    def __init__(self, threshold, max_interval):
        self._threshold = threshold
        self._max_interval = max_interval
        self._counter = 1
        self._counter_steps = 1

    def reset(self):
        self._counter = 1
        self._counter_steps = 1

    def check(self, elapsed_secs):
        ratio = elapsed_secs / self._threshold
        if ratio > self._counter:
            return True
        return False

    def update(self, elapsed_secs):
        ratio = elapsed_secs / self._threshold
        if ratio > self._counter:
            self._counter += self._counter_steps
            if self._counter_steps * self._threshold < self._max_interval:
                self._counter_steps += 1

    def is_alerted(self):
        if self._counter > 1:
            return True
        return False

# function to create clip storage directories, delete data older
# than saving_period days and to check recorder status and restart
# if necessary

def monitor(out_path, interval, saving_period, restart_threshold):

    # initialise variables

    today_ts = None
    tomorrow_ts = None
    remove_at_ts = 0

    filename = None
    file_ts = int(time.mktime(time.localtime()))
    file_size = 0

    alert_decider = AlertDecider(restart_threshold, 900)

    # start the monitoring process
    print("Monitoring thread starts")
    while monitoring:
        try:
            # Create the directory 3 minutes ahead of the time
            ts = int(time.mktime(time.localtime()))
            new_today_ts = (int(ts/(3600*24)))*3600*24
            
            new_tomorrow_ts = (int((ts+180)/(3600*24)))*3600*24

            if new_today_ts != today_ts:
                today_ts = new_today_ts
                tv = datetime.fromtimestamp(today_ts)
                today_path = os.path.join(out_path, tv.strftime("%Y%m%d"))
                if not os.path.isdir(today_path):
                    print("Making today's directory %s" % today_path)
                    try:
                        os.mkdir(today_path)
                    except Exception as e:
                        print(e)
            if new_tomorrow_ts != new_today_ts and new_tomorrow_ts != tomorrow_ts:
                tomorrow_ts = new_tomorrow_ts
                tv = datetime.fromtimestamp(tomorrow_ts)
                tomorrow_path = os.path.join(out_path, tv.strftime("%Y%m%d"))
                if not os.path.isdir(tomorrow_path):
                    print("Making tomorrow's directory %s" % tomorrow_ts)
                    os.mkdir(tomorrow_path)
            
            # Delete old data
            current_dates = glob.glob(os.path.join(out_path, '*'))
            current_dates.sort()
            new_remove_at_ts = (int((ts-saving_period*24*3600)/(3600*24)))*3600*24

            if new_remove_at_ts != remove_at_ts:
                #print("dates = ",current_dates)
                #print("ts = ",ts)
                #print(datetime.fromtimestamp(ts))
                #print(new_today_ts)
                #print(datetime.fromtimestamp(new_today_ts))
                #print(new_tomorrow_ts)
                #print(datetime.fromtimestamp(new_tomorrow_ts))

                remove_at_ts = new_remove_at_ts
                tv = datetime.fromtimestamp(remove_at_ts)
                #print("tv = ",tv)

                remove_at_path = os.path.join(out_path, tv.strftime("%Y%m%d"))
                print("remove path = ",remove_at_path)

                for p in current_dates:
                    if p >= remove_at_path:
                        break
                    else:
                        print("  removing: ", p)
                        shutil.rmtree(p)

            # Check file name & file size
            # Raise alert if size has not been change for threshold secs
            new_filename = recorder.current_filename()
            new_file_ts = int(time.mktime(time.localtime()))
            if new_filename == None:
                new_file_size = 0
            else:
                try:
                    new_file_size = os.path.getsize(new_filename)
                except OSError as e:
                    print("Can't get size of file %s: %s" % (new_filename, e))
                    new_file_size = 0
               
            # If filename is different
            if new_filename != filename or new_file_size != file_size:
                if new_filename != filename:
                    #print("New file name: %s" % new_filename)
                    filename = new_filename
                file_ts = new_file_ts
                file_size = new_file_size
                if alert_decider.is_alerted():
                    alert_decider.reset()
            elif new_file_ts - file_ts > restart_threshold:
                msg = "Size of %s has not changed after %d seconds, restart the recording process now" % (
                            filename, new_file_ts - file_ts)
                print(msg)

                if alert_decider.check(new_file_ts-file_ts):
                    print("FFmpeg Recording Process Stucks", msg)
                while True:
                    try:
                        recorder.restart(5)
                        break
                    except Timeout as e:
                        print(e)
                        print("FFmpeg Recording Restart TIMEOUT", "%s\nTrying again..." % e)
                print("FFmpeg recording process restarted successfully")
                if alert_decider.check(new_file_ts-file_ts):
                    print("Restart", "FFmpeg recording process restarted successfully")
                alert_decider.update(new_file_ts-file_ts)
        except:
            print("Something went wrong in the monitoring thread")

        if event.wait(interval):
            break

    print("Monitoring thread stopped")

# function to handle stop/interupt signals received from user

def system_signal(sig_num, stack_frame):
    print("Receiving SYSTEM SIGNAL: %s" % sig_num)

    global monitoring
    monitoring = False
    event.set()
    recorder.stop()
    monitor_thread.join()
    sys.exit()

# start the main program
if __name__ == '__main__':

    # Initialise the recoder
    recorder = FFmpegRecorder(protocol, src, segment_time, out_path)
    
    # Start monitoring thread
    monitor_thread = Thread(target=monitor, args=(out_path, monitor_interval, saving_period,
                                                    restart_threshold))
    monitoring = True
    event.clear()
    monitor_thread.start()

    # Start recording
    signal.signal(signal.SIGINT, system_signal)
    signal.signal(signal.SIGTERM, system_signal)
    recorder.start()
    print("FFmpeg Recording starts for camera, file length %d minutes, saving period %d days, " % (
                  segment_time/60, saving_period))

    # Wait for recording to stop
    while True:
        if event.wait(monitor_interval):
            break

    # Do something
    print("FFmpeg Recording for camera is stopped")
