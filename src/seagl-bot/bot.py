#!/usr/bin/env python3

"""An IRC Bot for the Seattle GNU/Linux Conference."""

import os
import re
import sys
import time
import json
import config
import getpass
import logging
import getpass
import random
import channel_logger

from twisted.internet import defer, endpoints, protocol, reactor, ssl, task
from twisted.python import log
from twisted.words.protocols import irc

import database

RANDOM_TOAST = {
    "0":"'A cup of tea is a cup of peace.' - Soshitsu Sen XV, Tea Life, Tea Mind",
    "1":"'Many kinds of monkeys have a strong taste for tea, coffee and spirituous liqueurs.' - Charles Darwin",
    "2":"'A cup of tea would restore my normality.' - Douglas Adams",
    "3":"'Rainy days should be spent at home with a cup of tea and a good book.' - Bill Watterson",
    "4":"'Honestly, if you're given the choice between Armageddon or tea, you don't say 'what kind of tea?'' - Neil Gaiman",
    "5":"Tea ... is a religion of the art of life. - Kakuzō Okakura"
}

HELP = """\n
!schedule                       - Schedule for SeaGL 2020\n
!createroom (!cr): <room-name>  - Create channel and conference chat room\n
!listrooms (!lr): <page-number> - List Conference chat rooms\n
!jointopic (!jt): <topic-name>  - Join topic list, receive invites and information\n
!listtopics (!lt):              - List topics to join\n
!teagl (!tea): <nick>           - Send a Teagl toast to a friend\n
!ask:                           - Send Conference Speaker a question\n
"""

class IRCProtocol(irc.IRCClient):
    nickname = config.nickname


    def __init__(self):
        self.lineRate = 1
        self.password = ''
        self.deferred = defer.Deferred()

        # Keep track of the last room ID that got a channel count taken
        self.last_chan_id = 1

        bot_log_path = os.path.join('/home', str(getpass.getuser()), 'seagl-bot.d')
        channel_logs = os.path.join(bot_log_path, 'channels-logs')
        if not os.path.exists(channel_logs):
            os.mkdir(channel_logs, 0o755)
        self.cl = channel_logger.channel_logger(channel_logs)


    def connectionLost(self, reason):
        logging.info("Connection Lost: "+str(reason))
        self.deferred.errback(reason)


    def signedOn(self):
        for channel in self.factory.channels:
            logging.info("Signon: " + channel)
            self.join(channel)

        c = task.LoopingCall(self.query_names)
        c.start(int(config.names_query_interval))

        b = task.LoopingCall(self.broadcaster)
        b.start(int(config.broadcaster_interval))

        m = task.LoopingCall(self.publish_metrics)
        m.start(int(config.metrics_interval))

        k = task.LoopingCall(self.check_channel_limit)
        k.start(int(config.channel_limit_audit))

        j = task.LoopingCall(self.chan_user_audit)
        j.start(int(config.channel_user_audit))


    def userJoined(self, user, channel):
        nick, _, host = user.partition("!")
        self.cl.log_chan(nick, channel, "joined-channel")

    def userLeft(self, user, channel):
        nick, _, host = user.partition("!")
        self.cl.log_chan(nick, channel, "Left-channel")

    def privmsg(self, user, channel, message):
        nick, _, host = user.partition("!")
        message = message.strip()
        self.cl.log_chan(nick, channel, message)

        if not message.startswith("!"):
            return
        command, sep, rest = message.lstrip("!").partition(" ")

        func = getattr(self, "command_" + command, None)
        if not func:
            return
        deferred = defer.maybeDeferred(func, nick, channel, rest)
        deferred.addErrback(self._showError)
        if channel == self.nickname:
            deferred.addCallback(self._sendMessage, nick)
        else:
            deferred.addCallback(self._sendMessage, channel, nick)


    def _sendMessage(self, msg, target, nick=None):
        if nick:
            msg = "%s, %s" % (nick, msg)
        self.msg(target, msg)


    def _showError(self, failure):
        return failure.getErrorMessage()


    def command_ping(self, nick, channel, rest):
        self.cl.log_chan("seagl-bot", channel, "pong")
        return "pong"


    def command_help(self, nick, channel, rest):
        self.cl.log_chan("seagl-bot", channel, HELP)
        return HELP


    def broadcaster(self):
        """ Send messages listed in the msg_queue table.
            This function is run as a thread off of the main
            reactor loop. Throttling the messaging keeps the bot
            from being kicked on network for flooding.
        """

        db = database.Database(config.sqlite_path)
        tpl = db.dequeue_msg()
        if tpl != ():
            ID   = tpl[0]
            dest = tpl[1]
            msg  = tpl[2]
            self.msg(str(dest), str(msg))

            size = db.msg_queue_size()
            logging.info("mst queue size:"+size) 
            logging.info("Broadcast to: " + str(ID) + ":" + dest + ":" + msg)
        return


    def command_schedule(self, nick, channel, rest):
        return "https://osem.seagl.org/conferences/seagl2020/schedule#2020-11-13"
        #       https://osem.seagl.org/conferences/seagl2020/schedule#2020-11-14
    command_sched = command_schedule


    def command_conf_announce(self, nick, channel, rest):
        """ Send announcement message to all conference channels.
            Return: string

            Keyword arguments:
            nick -- string: user nick
            channel -- string: channel
            rest -- string: input from user
        """

        if not nick in config.botops:
            return "Operation not permitted user."

        """ Sanitize input """
        san_args = rest
        for c in ["'", "\"", ";", "*"]:
            san_args = san_args.replace(c, "")
        msg = re.sub(' +', ' ', san_args)

        db = database.Database(config.sqlite_path)
        conf_channels = db.get_room_list()
        for i in range(len(conf_channels)):
            if not conf_channels[i].startswith('#'):
                conf_channels[i] = "#"+conf_channels[i]

        for dest in conf_channels:
            db.enqueue_msg(dest, "Announcement: "+msg)
        return "Announcement Queued."

    command_CA = command_conf_announce


    def command_admin_announce(self, nick, channel, rest):
        """ Send announcement message to all Admin channels.
            Return: string

            Keyword arguments:
            nick -- string: user nick
            channel -- string: channel
            rest -- string: input from user
        """

        if not nick in config.botops:
            return "Operation not permitted user."

        """ Sanitize input """
        san_args = rest
        for c in ["'", "\"", ";", "*"]:
            san_args = san_args.replace(c, "")
        msg_to_admins = re.sub(' +', ' ', san_args)

        admin_channels = config.channels_admin
        for i in range(len(admin_channels)):
            if not admin_channels[i].startswith('#'):
                admin_channels[i] = "#"+admin_channels[i]

        db = database.Database(config.sqlite_path) 
        for dest in admin_channels:
            db.enqueue_msg(dest, "Announcement: "+msg_to_admins)
        return "Announcement Queued."

    command_AA = command_admin_announce


    def command_list_announce(self, nick, channel, rest):
        """ Send announcement message to all users of a topic list. 
            Return: string

            Keyword arguments:
            nick -- string: user nick 
            channel -- string: channel
            rest -- string: input from user
        """

        if not nick in config.botops:
            return "Operation not permitted user."

        if rest == "":
            return "Error: Missing arguments, <topic-group> <message>"

        san_args = rest
        for c in ["'", "\"", ";", "*"]:
            san_args = san_args.replace(c, "")

        san_args = re.sub(' +', ' ', san_args)
        args_lst = san_args.split(" ")
        topic = args_lst[0] 

        if not self.factory.db.topic_exists(topic+'_list'):
            return "Error: Topic does not exist."
        msg = " ".join(args_lst[1:])

        """ Combine theese 2 commands """
        subscribers = self.factory.db.topic_subs(nick, topic)
        lst = subscribers.split(" ")

        sub_lst = list(filter(lambda x: x != "", lst))
        db = database.Database(config.sqlite_path)
        for dest in sub_lst:
            db.enqueue_msg(dest, "Announcement: "+msg)
        return "Announcement Queued."

    command_LA = command_list_announce


    def command_jointopic(self, nick, channel, rest):
        """ Add user nick to topic list.
            Return: string

            Keyword arguments:
            nick -- string: user nick 
            channel -- string: channel
            rest -- string: input from user
        """
    
        topic = rest
        for c in [" ","'", "\"", ";", "*"]:
            topic = topic.replace(c, "")

        if topic == "":
            return 'Error: No argument provided'

        # CHECK CREATE_TOPIC POLICY

        self.factory.db.join_topic(nick, topic)
        rtn = "Adding "+ nick + " to list: " + topic
        self.cl.log_chan("seagl-bot", channel, rtn)
        return rtn 
    command_jt = command_jointopic
    command_joingame = command_jointopic


    def command_topicsubs(self, nick, channel, rest):
        """ Get list of user of a topic.
            Return: string

            Keyword arguments:
            nick -- string: user nick 
            channel -- string: channel
            rest -- string: input from user
        """

        """ Sanitize """
        topic = rest
        for c in [" ", "'", "\"", ";", "*",]:
            topic = topic.replace(c, "")

        if topic == "":
            return 'Error: No argument provided'
        rtn = self.factory.db.topic_subs(nick, topic)
        self.cl.log_chan("seagl-bot", channel, rtn)
        return rtn
    command_ts = command_topicsubs


    def command_listtopics(self, nick, channel, rest):
        """ Get list of topics.
            Return: string

            Keyword arguments:
            nick -- string: user nick 
            channel -- string: channel
            rest -- string: input from user
        """

        rtn = self.factory.db.list_topics()
        self.cl.log_chan("seagl-bot", channel, rtn)
        return rtn
    command_lt = command_listtopics


    def command_teagl(self, nick, channel, rest):
        user_id = rest
        for c in [" ", "'", "\"", ";", "*",]:
            room_id = user_id.replace(c, "")

        if user_id == "":
            logging.error("Error: No argument provided "+ nick +" "+ channel+" "+rest)
            return 'Error: No argument provided'

        db = database.Database(config.sqlite_path)
        msg = "".join([user_id, ', ', nick, ' sent you a toast: ', RANDOM_TOAST[str(random.randint(0,5))]])
        db.enqueue_msg(channel, msg)
        return "Message Queued."
    command_tea = command_teagl


    def command_questions(self, nick, channel, rest):
        """ Read channel question list
            Return: string

            Keyword arguments:
            nick -- string: user nick 
            channel -- string: channel
            rest -- string: input from user
        """

        try:
            config.botops.index(nick)
        except Exception as e:
            return "Not permitted"

        qnum = 1
        user_input = rest
        for c in [" ", "'", "\"", ";", "*",]:
            user_input = user_input.replace(c, "")

        try:
            if user_input.isdigit():
                qnum = int(user_input)
            if qnum < 1:
                qnum = 1
        except Exception as e:
            logging.error("command_ask():" + str(e))
        return self.factory.db.read_question(qnum, channel)
    command_q = command_questions


    def command_ask(self, nick, channel, rest):
        """ Ask a Question 
            Return: string

            Keyword arguments:
            nick -- string: user nick 
            channel -- string: channel
            rest -- string: user input
        """

        user_input = rest
        for c in ["'", "\"", ";", "*",]:
            user_input = user_input.replace(c, "")

        user_input = rest
        for c in ["'", "\"", ";", "*",]:
            user_input = user_input.replace(c, "")

        if user_input == "":
            logging.error("Error: No argument provided "+ nick +" "+ channel+" "+rest)
            return 'Error: No argument provided'

        # CHECK CREATE_ROOM POLICY. 

        self.factory.db.add_question(nick, user_input, channel)

        rtn = "Question Submitted."
        self.cl.log_chan("seagl-bot", channel, rtn)
        logging.info(rtn)
        return rtn
    command_ask = command_ask
    

    def command_clear_question_list(self, nick, channel, rest):
        """
        """

        try:
            config.botops.index(nick)
        except Exception as e:
            return "Not permitted"

        if not self.factory.db.clear_question_list(channel):
            logging.error("Error: command_clear_question_list() Failed to delete table")
            return "Failed to clear list"
        return "Question list cleared"


    def command_createroom(self, nick, channel, rest):
        """ Create channel and jitsi room 
            Return: string

            Keyword arguments:
            nick -- string: user nick 
            channel -- string: channel
            rest -- string: input from user
        """

        room_id = rest
        for c in [" ", "'", "\"", ";", "*",]:
            room_id = room_id.replace(c, "")

        if room_id == "":
            logging.error("Error: No argument provided "+ nick +" "+ channel+" "+rest)
            return 'Error: No argument provided'


        # CHECK CREATE_ROOM POLICY. 

        channel = "#seagl-" + room_id
        link    = config.JITSI_PREFIX + room_id
        #link    = "https://meet.seagl.org/seagl-" + room_id
        self.factory.db.add_room(nick, link, channel)
        self.join(channel)
        self.topic(channel, link)

        rtn = " ".join(["Created Channel:", channel, " Video-conf:", link])
        self.cl.log_chan("seagl-bot", channel, rtn)
        logging.info(rtn)
        return rtn
    command_cr = command_createroom


    def command_listrooms(self, nick, channel, rest):
        """ Get list of rooms. 
            Return: string

            Keyword arguments:
            nick -- string: user nick 
            channel -- string: channel
            rest -- string: input from user
        """

        page_num = rest
        rtn = self.factory.db.list_rooms(page_num)
        self.cl.log_chan("seagl-bot", channel, rtn)
        return rtn
    command_lr = command_listrooms        


    def command_shuffle(self, nick, channel, rest):
        """ Shuffle user name of a topic list and divide into groups of N size.
            Return: string

            Keyword arguments:
            nick -- string: user nick 
            channel -- string: channel
            rest -- string: input from user
        """

        if not nick in config.botops:
            return "Operation not permitted user."

        rtn = self.factory.db.shuffle_users(rest)
        self.cl.log_chan("seagl-bot", channel, str(rtn))
        return "done" 
    command_st = command_shuffle


    def alarm(self, channel, msg):
        self.cl.log_chan("seagl-bot", channel, msg)
        self.notice(channel, msg)


    def command_timer(self, nick, channel, rest):
        """ Set Timer/Alarm

            Keyword arguments:
            nick -- string: user nick
            channel -- string: channel
            rest -- string: arg string
        """

        alarm_name = ''

        string = re.sub(' +', ' ', rest)
        str_lst = string.split(' ')
        if len(str_lst) < 1:
            return "nope"
        else:
            val = str_lst[0]
            if len(str_lst) > 1:
                alarm_name = str_lst[1]

        try:
            alarm_time = int(val) * 60
        except Exception as e:
            logging.error("command_timer():"+str(val)+":"+str(e))
            return "Incorrect time value: !timer <integer> <name>"

        set_msg = " ".join(["Set ", str(alarm_time), " sec Alarm."])
        self.cl.log_chan("seagl-bot", channel, set_msg)
        self.msg(channel, set_msg)

        if alarm_name:
            alarm_msg = " ".join(["!!!!!! ", alarm_name, ":", str(alarm_time), "sec ALARM !!!!!!!"])
        else:
            alarm_msg = " ".join(["!!!!!!", str(alarm_time), "sec ALARM !!!!!!!"])

        reactor.callLater(alarm_time, self.alarm, channel, alarm_msg)
        reactor.run()
    command_timer = command_timer



    def command_names(self, nick, channel, rest):
        "List the users in 'channel', usage: client.who('#testroom')"
        #print("Calling for names: "+ channel)
        self.sendLine("NAMES %s" % channel)


    def query_names(self):
        """ Query the chanserv for the List of users in a channel 
        """
        
        row = self.last_chan_id + 1

        db = database.Database(config.sqlite_path)
        num_channels = db.rooms_table_size()

        if row > num_channels:
            row = row % num_channels
        
        channel = db.get_channel_row(row)
        if channel:
            self.last_chan_id = row 
            logging.info("INFO: query_names():" + channel)
            self.sendLine("NAMES %s" % channel)
        else:
            self.last_chan_id = 1


    def irc_RPL_NAMREPLY(self, prefix, params):
        """ Called when chanserv replys to a NAMES request.

            Keyword arguments:
            prefix -- string: irc endpoint name i.e. blah.freenode.net
            params -- list: ['seagl-bot', '@', '<channel>', '<users list>' ]
        """

        channel = params[2].lower()
        nicklist = params[3].split(' ')
        db = database.Database(config.sqlite_path)

        # Validate the data.
        if not isinstance(nicklist, list):
            logging.error("Error: irc_RPL_NAMREPLY(): Nicklist type error")
            return
        if not db.channel_exists(channel):
            logging.error("Error: irc_RPL_NAMREPLY(): db.channel_exists")
            return

        # Write to the database channel_counts table
        try:
            db.add_channel_count(channel, nicklist)
        except Exception as e:
            logging.error("Error: rc_RPL_NAMREPLY(): " + str(e))

        logging.info('Info: rc_RPL_NAMREPLY(): %s, %s' % (nicklist, channel))
        return


    def irc_RPL_ENDOFNAMES(self, prefix, params):
        logging.info("INFO: irc_RPL_ENDOFNAMES")


    #def irc_unknown(self, prefix, command, params):
    #    "Print all unhandled replies, for debugging."
    #    print ('UNKNOWN:', prefix, command, params)


    def publish_metrics(self):
        """ Write json file
        """

        db = database.Database(config.sqlite_path)
        metric_dict = db.get_channel_count_metric()
        with open(config.metric_path, 'w') as fp:
            json.dump(metric_dict, fp)
        return 


    def check_channel_limit(self):
        """ Check if nearing channel limit, and send Alert if so.
        """

        db = database.Database(config.sqlite_path)
        metric_dict = db.get_channel_count_metric()
        if len(metric_dict.keys()) > 105:
            for dest in config.channels_admin:
                if not dest.startswith('#'):
                    dest = "#" + dest
                    logging.warning("!!!---  "+ str(dest))
                db.enqueue_msg(dest, "ALERT! Channel Limit Approaching")


    def chan_user_audit(self):
        """ Leave inactive channels
        """

        db = database.Database(config.sqlite_path)
        chans_to_leave = db.audit_channels()
        logging.info("chans_to_leave:" + str(chans_to_leave))

        if not db.remove_rooms(chans_to_leave):
            logging.error("Error: remove_rooms(): return false")
        
        for channel in chans_to_leave:
            if not (channel in config.channels_admin and channel in config.initial_channels):
                self.leave(channel, reason="Too Few Participants...")
        return
        

class IRCFactory(protocol.ReconnectingClientFactory):
    def __init__(self, passwd):
        self.protocol = IRCProtocol
        self.protocol.password = passwd
        self.db = database.Database(config.sqlite_path)
        channel_list = self.db.get_room_list()
        channel_list = channel_list + config.initial_channels + config.channels_admin

        if len(channel_list) ==0:
            print("Channel List is empty. No channels will be joined")
            sys.exit(1)

        self.channels = channel_list


def run(reactor, host, port, passwd):
    FORMAT = '%(asctime)-15s %(message)s'
    bot_log_path = os.path.join('/home', str(getpass.getuser()), 'seagl-bot.d')
    if not os.path.exists(bot_log_path):
        os.mkdir(bot_log_path, 0o755)
    bot_log = os.path.join(bot_log_path, 'bot.log')
    logging.basicConfig(filename=bot_log, level=logging.DEBUG, format=FORMAT)

    options = ssl.optionsForClientTLS(host)
    endpoint = endpoints.SSL4ClientEndpoint(reactor, host, port, options)
    factory = IRCFactory(passwd)
    deferred = endpoint.connect(factory)
    deferred.addCallback(lambda protocol: protocol.deferred)
    return deferred


def main():
    log.startLogging(sys.stderr)

    try:
        passwd = getpass.getpass()
    except Exception as e:
        logging.error("Error:" + str(e))

    task.react(run, (config.serverhost, config.serverport, passwd))


if __name__ == "__main__":
    main()
