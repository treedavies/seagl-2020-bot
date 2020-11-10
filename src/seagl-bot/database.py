
import re
import os
import time
import math
import config
import sqlite3
import logging
import random

ROOMS_TABLE = """
CREATE TABLE rooms (
    id INTEGER PRIMARY KEY ASC,
    creator TEXT,
    irc_channel TEXT,
    jitsi_room TEXT,
    Timestamp DATE DEFAULT (datetime('now','localtime'))
);
"""

MSG_QUEUE_TABLE = """
    CREATE TABLE IF NOT EXISTS msg_queue (
    id INTEGER PRIMARY KEY ASC, 
    destination TEXT, 
    message TEXT,
    Timestamp DATE DEFAULT (datetime('now','localtime'))
    );
"""

CHANNEL_COUNTS_TABLE = """
    CREATE TABLE IF NOT EXISTS channel_counts (
    id INTEGER PRIMARY KEY ASC,
    Timestamp DATE DEFAULT (datetime('now','localtime'))
    channel TEXT,
    count INTEGER,
    nicks TEXT
    );
"""

CHANNEL_USER_AUDIT = """
    CREATE TABLE IF NOT EXISTS channel_user_audit (
    id INTEGER PRIMARY KEY ASC,
    Timestamp DATE DEFAULT (datetime('now','localtime'))
    channel TEXT,
    count INTEGER
    );
"""


class Database:
    def __init__(self, sqlite_path):
        exists = os.path.exists(sqlite_path) and os.path.getsize(sqlite_path) > 0
        dirname = os.path.dirname(sqlite_path)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        self.connection = sqlite3.connect(sqlite_path)
        # Allow accessing row items by name
        self.connection.row_factory = sqlite3.Row
        if not exists:
            logging.info("Initializing new DB")
            self.create_db()

            logging.info("Adding config.initial_channels to DB")
            for ic in config.initial_channels:
                chan = "#"+ic
                room = config.JITSI_PREFIX + ic
                #room = "https://meet.seagl.org/"+ic 
                rtn = self.add_room("seagl-bot", room, chan)

            logging.info("Adding config.channels_admin to DB")
            for ca in config.channels_admin:
                chan = "#"+ca
                room = config.JITSI_PREFIX + ca
                #room = "https://meet.seagl.org/"+ca
                rtn = self.add_room("seagl-bot", room, chan)


    def create_db(self):
        """
        """

        try:
            self.connection.execute(ROOMS_TABLE)
            self.connection.execute(MSG_QUEUE_TABLE)
            self.connection.execute(CHANNEL_USER_AUDIT)
            self.connection.execute(CHANNEL_COUNTS_TABLE)
        except Exception as e:
            logging.error(str(e))


    def question_table_count(self, qtable):
        """
        """

        rtn = 0
        try:
            cursor = self.connection.cursor()
            qry = "SELECT COUNT(ALL) FROM %s" % qtable
            cursor.execute(qry)
            val = cursor.fetchall()
            if len(val) < 1:
                rtn = 0
            rtn = int(val[0][0])
        except Exception as e:
            logging.error("ERROR: question_table_count(): " + qry + ":" + str(e))
        cursor.close()
        return int(rtn)


    def clear_question_list(self, channel):
        """
        """

        rtn = False
        cursor = self.connection.cursor()

        try:
            qtable = 'questions_' + channel.replace('#','').replace('-','_')
            query = """DELETE FROM %s""" % qtable
            cursor.execute(query)
            self.connection.commit()
            rtn = True
        except Exception as e:
            logging.error("Error: clear_question_list()" + str(e))

        cursor.close()
        return rtn


    def read_question(self, qnum, channel):
        """ Read questions from DB table

            Keyword arguments:
            qnum -- string:
            channel -- string: channel name
        """

        rtn = ""
        qtable = 'questions_' + channel.replace('#','').replace('-','_')
        qcount = self.question_table_count(qtable)
        if qcount == 0 or qcount < 0 or qnum > qcount:
            return "No Questions Found"

        cursor = self.connection.cursor()
        try:
            qtable = 'questions_' + channel.replace('#','').replace('-','_')
            query = "SELECT Timestamp, id, creator, question FROM %s WHERE id=%s" % (qtable, str(qnum))
            cursor.execute(query)
            rows = cursor.fetchall()
        except Exception as e:
            logging.error("read_question(): "  + str(e))
        cursor.close()

        if len(rows[0]) > 0:
            timestamp = rows[0][0]
            username  = rows[0][2]
            question  = rows[0][3]
            rtn = "".join(["[", str(qnum), "/", str(qcount), "] ", timestamp, " : ", username, ": ", question ])
        return rtn


    def add_question(self, nick, question, channel):
        """ Add questions to DB table

            Keyword arguments:
            nick -- string: user nick 
            question -- string:
            channel -- string: channel name
        """
        rtn = False
        qtable = 'questions_' + channel.replace('#','').replace('-','_')

        cursor = self.connection.cursor()
        try:
            query = """CREATE TABLE IF NOT EXISTS %s (
                        id INTEGER PRIMARY KEY ASC, 
                        Timestamp DATE DEFAULT (datetime('now','localtime')),
                        creator TEXT, irc_channel TEXT, question TEXT); """ % qtable
            cursor.execute(query)
        except Exception as e:
            logging.error("Error: add_question(): create table: " + str(e))

        try:
            query = """INSERT INTO %s (creator, irc_channel, question) VALUES (?, ?, ?)""" % qtable
            cursor.execute(query, (nick, channel, question))
            self.connection.commit()
            rtn = True
        except Exception as e:
            logging.error("Error: add_question(): insert: " + str(e))
        cursor.close()
        return rtn


    def add_room(self, nick, room, channel):
        """ Add room and channel to DB 'rooms' table

            Keyword arguments:
            nick -- string: user nick 
            room -- string: room name
            channel -- string: channel name
        """
        channel = channel.lower()
        room = room.lower()

        with self.connection:
            cursor = self.connection.cursor()

            # Replace with helper method, which would also be used in MANREPLY()
            try:
                cursor.execute("SELECT irc_channel FROM rooms WHERE irc_channel=?", (channel,))
                rows = cursor.fetchall()
                if (len(rows)):
                    logging.info("Ignoring Add_entry (channel): "+str(channel)+" Already exists")
                    return False
            except Exception as e:
                logging.error("Exception: DB verification of channel: " + str(e))
                return False

            try:
                cursor.execute("SELECT jitsi_room FROM rooms WHERE jitsi_room=?", (room,))
                rows = cursor.fetchall()
                if (len(rows)):
                    logging.info("Ignorting Add Entry (room): "+str(room)+" Already Exists")
                    return False
            except Exception as e:
                logging.error("Exception: DB verification of room: " + str(e))
                return False

            try:
                query = """INSERT INTO rooms (creator, irc_channel, jitsi_room) VALUES (?, ?, ?)"""
                room = room.strip()
                channel = channel.strip()
                cursor.execute(query, (nick, channel, room))
            except Exception as e:
                logging.error("Exception: DB insert room/channel: " + str(e))
                return False        
        return True


    def remove_rooms(self, room_lst):
        rtn = False
        cursor = self.connection.cursor()
        try:
            for r in room_lst:
                cursor.execute("DELETE FROM rooms WHERE irc_channel=?", (r,))
                self.connection.commit()
            rtn = True
        except Exception as e:
            logging.error("Error: remove_rooms(): " + str(e))
        return rtn


    def get_room_list(self):
        """ Return list strings: list of room names """
        lst = []
        with self.connection:
            query = "SELECT irc_channel FROM rooms"
            try:
                cursor = self.connection.cursor()
                cursor.execute(query)
                rooms = cursor.fetchall()
                num_rooms = len(rooms)
                if num_rooms > 0:
                    for r in rooms:
                        lst.append(str(r[0]))
                cursor.close()
            except Exception as e:
                logging.error("get_room_list():'"+ query + "':" + str(e))
                cursor.close()
        return lst


    def list_rooms(self, page_num):
        """ Return a string of room/chanel info 

            Keyword arguments:
            page_num -- string:  
        """
        rtn = ""
        LINES_PER_PAGE = 4

        if not page_num.isdigit():
            page_num = int(1)
        page_num = int(page_num)
        if page_num <= 0:
            page_num = int(1)

        with self.connection:
            query = "SELECT irc_channel, jitsi_room FROM rooms" 
            try:
                cursor = self.connection.cursor() 
                cursor.execute(query)
                rooms = cursor.fetchall()
                num_rooms = len(rooms)
                num_pages = math.ceil(len(rooms) / LINES_PER_PAGE)

                stop = page_num * LINES_PER_PAGE
                start = stop - LINES_PER_PAGE

                if num_rooms < stop:
                    stop = num_rooms
                if num_rooms < start:
                    return ''
   
                rtn = "Listing Page: " + str(page_num) + "/"+ str(num_pages) + " of room list" + " - IRC command: !lr " + str(page_num)
                for room in rooms[start:stop]:
                    rtn += "\n" + '{:<13} {:<13}'.format(str(room[0]), str(room[1]))
            except Exception as e:
                logging.error("list_rooms():" + str(page_num) + ":" + str(e))
            return rtn
     

    def dequeue_msg(self):
        """ Return tuple representing first row in msg_queue table 
            The entry will be removed from the table.

            tuple format: (prim_key, destination, message)
        """

        try:
            cursor = self.connection.cursor()
            select_query = "SELECT * FROM msg_queue ORDER BY ROWID ASC LIMIT 1;"
            cursor.execute(select_query)

            rows = cursor.fetchall()
            if len(rows) < 1:
                return () 

            rtn = (str(rows[0][0]), str(rows[0][1]), str(rows[0][2]))
        except Exception as e:
            logging.error("dequeue(): '" + str(select_query) + "'" + str(e))
        cursor.close()

        try:
            cursor = self.connection.cursor()
            delete_querey = "DELETE FROM msg_queue WHERE ID='"+str(rows[0][0])+"';"
            cursor.execute(delete_querey)
            self.connection.commit()
        except Exception as e:
            logging.error("dequeue(): '" + str(delete_querey) + "'" + str(e))
        cursor.close()
        return rtn


    def enqueue_msg(self, dest, msg):
        """ Add messages to a queue for scheduled delivery

            Keyword arguments:
            dest -- string: Channel or handle name
            msg -- string: message to be sent
        """

        rtn = False
        try:
            cursor = self.connection.cursor()
            qry = "INSERT INTO msg_queue (destination, message) VALUES (?, ?)"
            cursor.execute(qry, (dest, msg))
            self.connection.commit()
            rtn = True
        except Exception as e:
            logging.error("enqueue():" + qry + ":" + str(e))
        cursor.close()
        return rtn


    def get_channel_row(self, row):
        rtn = ""
        rid = int(row)-1
        logging.info("getting id: "+ str(rid))
        try:
            cursor = self.connection.cursor()
            query = "SELECT irc_channel FROM rooms"
            cursor.execute(query)
            val = cursor.fetchall()
            rtn = str(val[rid][0])
        except Exception as e:
            logging.error("ERROR: get_channel_from_id():" + str(e))
        cursor.close()
        
        logging.info("get_channel_row() Returning " + str(rtn))
        return rtn


    def channel_counts_table_size(self):
        """ Return channel_counts table size
        """

        rtn = 0
        try:
            cursor = self.connection.cursor()
            qry = "SELECT COUNT(ALL) FROM channel_counts"
            cursor.execute(qry)
            val = cursor.fetchall()
            if len(val) < 1:
                rtn = 0
            rtn = int(val[0][0])
        except Exception as e:
            logging.error("ERROR: channel_counts_table_size(): " + qry + ":" + str(e))
        cursor.close()
        return int(rtn)


    def rooms_table_size(self):
        """ Return rooms table size
        """

        rtn = 0
        try:
            cursor = self.connection.cursor()
            qry = "SELECT COUNT(ALL) FROM rooms"
            cursor.execute(qry)
            val = cursor.fetchall()
            if len(val) < 1:
                rtn = 0
            rtn = int(val[0][0])
        except Exception as e:
            logging.error("ERROR: msg_queue_size(): " + qry + ":" + str(e))
        cursor.close()
        return int(rtn)

        

    def msg_queue_size(self):
        """ Return msg_queue table size
        """

        rtn = 0
        try:
            cursor = self.connection.cursor()
            qry = "SELECT COUNT(ALL) FROM msg_queue"
            cursor.execute(qry)
            val = cursor.fetchall()
            if len(val) < 1:
                rtn = 0
            rtn = str(val[0][0])
        except Exception as e:
            logging.error("msg_queue_size:" + qry + ":" + str(e))
        cursor.close()
        return str(rtn)



    def join_topic(self, nick, lst):
        """ Add user handle to topic list

            Keyword arguments:
            nick -- string: irc handle
            lst -- string: name of topic list 
        """

        lst = lst + '_list'
        rtn = False
        table_exists = True 

        """ Check if table exists """
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=\'" + lst + "\';")
            rows = cursor.fetchall()
            if len(rows) < 1:
                table_exists = False
        except Exception as e:
            logging.error("ERROR: join_topic(): "+str(e))
            cursor.close()
            return
        cursor.close()


        """ Check if user is in botops"""
        if not table_exists:
            try:
                config.botops.index(nick)
            except Exception as e:
                return "Topic list creation Not permitted"


        """ Create table """
        try:
            cursor = self.connection.cursor()
            create_table = "CREATE TABLE IF NOT EXISTS "+lst+" (id INTEGER PRIMARY KEY ASC, user_id TEXT, Timestamp DATETIME DEFAULT CURRENT_TIMESTAMP);"
            cursor.execute(create_table)
        except Exception as e:
            logging.error("join_topic(): '"+ create_table + "'" + str(e))
        cursor.close()


        """ Check if user is already in list """
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT user_id FROM "+lst+" WHERE user_id=?", (nick,))
            rows = cursor.fetchall()
            if len(rows) > 0:
                return False
        except Exception as e:
            logging.error("join_topic(): '"+ query + "'" + str(e)) 
        cursor.close()


        """ Add nick to list  """
        try:
            cursor = self.connection.cursor()
            qry = "INSERT INTO " + lst + " (user_id) VALUES (?)"
            cursor.execute(qry, (nick,))
            self.connection.commit()
        except Exception as e:
            logging.error("ERROR: join_topic():" + qry + ":" + str(e))
        cursor.close()


    def list_topics(self):
        """ Return string of topics """
        rtn = ""
        lst = []
        cursor = self.connection.cursor()
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_list';")
            rows = cursor.fetchall()
            for tbl in rows:
                    t = tbl[0].replace("_list","")
                    lst.append(str(t))
            lst = sorted(lst,  key=str.lower)
            rtn = ", ".join(lst)
        except Exception as e:
            logging.error("ERROR: list_topics():" + str(e))
        cursor.close()
        return rtn


    def topic_subs(self, nick, lst):
        """ Return string of user IDs subscribed to a topic.

            Keyword arguments:
            nick  -- string 
            lst   -- list
        """

        rtn = ""

        lst = lst + '_list'
        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT * FROM " + lst)
            rows = cursor.fetchall()
            for row in rows:
                rtn = rtn + " " + str(row[1])
        except Exception as e:
            logging.error("ERROR: topic_subs(): "+str(e))
            rtn =  "Could not find topic list"
        cursor.close()
        return rtn


    def shuffle_users(self, args):
        """ Shuffle user IDs into equal groups of n

            Keyword arguments:
            args -- string 
        """ 

        if not args:
            return "Error: Missing required args <topic-name> and <group-size>"

        sanitized_string = re.sub(' +', ' ', args)
        lst = sanitized_string.split(" ")
        lst = list(filter(lambda x: x != "", lst))
        if len(lst) < 2:
            return "Error: Missing required args <topic-name> and <group-size>"

        topic = lst[0] + '_list'
        group_size = lst[1]
        if not group_size.isdigit():
            return "Error: group-size is not an integer"
        if not self.topic_exists(topic):
            return "Error: Topic not found."

        # READ ALL USER IDS FROM TOPIC TABLE
        user_list = []
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM " + topic)
            rows = cursor.fetchall()
            for row in rows:
                user_list.append(str(row[1]))
        except Exception as e:
            logging.error("ERROR: shuffle_users(): "+str(e))
            return "Error" + str(e)
        cursor.close()

        # RANDOMIZE sublists
        num_groups = int(len(user_list) / int(group_size))
        group_dict = {}
        for group in range(num_groups):
            if str(group) not in group_dict.keys():
                group_dict[str(group)] = []

        # Randomize
        for i in range(len(user_list)):
            group = int(i % num_groups)
            b = len(user_list)-1
            r = random.randint(0, b)
            ruser = user_list.pop(r)
            logging.info("group:"+ str(group) + " " + ruser)
            group_dict[str(group)].append(ruser)

        logging.info(str(group_dict))
        for k in group_dict.keys():
            channel = "".join(["#seagl-", topic, "_", k])
            #room = "".join(["https://meet.seagl.org/", topic, "_", k])
            room = "".join([config.JITSI_PREFIX, topic, "_", k])
            if not self.add_room('seagl-bot', room, channel):
                logging.error("Error: shuffle_users() add_room" )
        return 


    def topic_exists(self, topic_name):
        """ return True/Fase if topic exists.

            Keyword arguments:
            topic_name -- string 
        """
        rtn = False
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=\'" + topic_name + "\';")
            rows = cursor.fetchall()
            if len(rows) > 0:
                rtn = True 
        except Exception as e:
            logging.error("ERROR: topic_exists():"+str(e))
        cursor.close()
        return rtn


    def channel_exists(self, chan):
        """ return True/Fase if channel exists.

            Keyword arguments:
            chan -- string 
        """

        rtn = False
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT irc_channel FROM rooms WHERE irc_channel=\'" + chan + "\';")
            rows = cursor.fetchall()
            if len(rows) > 0:
                rtn = True
        except Exception as e:
            logging.error("ERROR: topic_exists():"+str(e))
        cursor.close()
        return rtn


    def add_channel_count(self, channel, nicklist):
        """ Add channel and count to channel_counts table

            Keyword arguments:
            channel -- string 
            count -- string
            nicklist -- list
        """
        count = str(len(nicklist))
        nicks = ",".join(nicklist)
        rtn = False

        try:
            cursor = self.connection.cursor()
            query = """INSERT INTO channel_counts (channel, count, nicks) VALUES (?, ?, ?)"""
            cursor.execute(query, (channel, count, nicks))
            self.connection.commit()
            rtn = True
        except Exception as e:
            logging.error("ERROR: "+str(e))
        cursor.close()
        return rtn
    
        
    def get_channel_count_metric(self):
        """ return a dict of channel counts data 

            Keyword arguments:
        """

        rtn_dict = {}
        row_count = self.channel_counts_table_size()
        num_channels = self.rooms_table_size()

        if row_count < num_channels:
            limit = str(row_count)
        else:
            limit = str(num_channels)
 
        rows = []
        try:
            query = "SELECT * FROM channel_counts ORDER BY id DESC LIMIT " + str(limit)
            cursor = self.connection.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
        except Exception as e:
            logging.error("ERROR: db.get_channel_count_metric(): "+ str(e))
        cursor.close()

        if len(rows) > 0:
            for row in rows:
                channel = row[2]
                count = row[3]
                nicklist = row[4]
                rtn_dict[str(channel)] = [count, nicklist]

        return rtn_dict


    def channel_user_audit_table_dict(self):
        """ return a dict of channel counts data from channel_user_audit table

            Keyword arguments:
        """

        rtn_dict = {}
        rows = []
        try:
            query = "SELECT channel, count  FROM channel_user_audit"
            cursor = self.connection.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
        except Exception as e:
            logging.error("ERROR: db.get_channel_count_metric(): "+ str(e))
        cursor.close()

        if len(rows) > 0:
            for row in rows:
                channel = row[0]
                count = row[1]
                rtn_dict[str(channel)] = count

        return rtn_dict


    def audit_channels(self): 
        """ return list of channels flagged for inactivity.
        """

        rtn_lst = []
        """ channel_counts = { <chan-name>: [count, [user1, user2...]] } """
        channel_counts = self.get_channel_count_metric()
        """ audit_table = { <chan-name>: <count>}  """
        audit_table = self.channel_user_audit_table_dict()        

        if len(audit_table.keys()) == 0:
            rtn_lst = []

        # COMPARE
        for chan in audit_table.keys():
            if chan in channel_counts.keys():
                if audit_table[chan] < 3 and channel_counts[chan][0] < 3:
                    rtn_lst.append(chan)
                   
        try:
            cursor = self.connection.cursor()
            query = """DELETE FROM channel_user_audit"""
            cursor.execute(query)
            self.connection.commit()

            query = """INSERT INTO channel_user_audit (channel, count) VALUES (?, ?)"""
            for k in channel_counts.keys(): 
                usr_count = str(channel_counts[k][0])
                if int(usr_count) < 3:
                    cursor.execute(query,(k, usr_count))
                    self.connection.commit()
        except Exception as e:
            logging.error("Error: audit_channels(): " + str(e))
        cursor.close()
        return rtn_lst        


