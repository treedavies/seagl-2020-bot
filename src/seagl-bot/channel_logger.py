
import os
import logging
import datetime

class channel_logger:

    def __init__(self, path):
        self.logd = {}
        self.path = path

    def log_chan(self, user, name, message):
        date_time = datetime.datetime.now()
        time_stamp = str(date_time.strftime("%m.%d.%y-%H:%M:%S "))
        msg = time_stamp + ":" + user + ":" + message + "\n"

        file_path  = os.path.join(self.path, name)
        try:
            self.logd[name] = open(file_path, "a")
            self.logd[name].write(msg)
            self.logd[name].close()
        except Exception as e:
            logging.error("log_chan():"+str(e))
            print(str(e))

