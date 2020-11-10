"""Sample Configuration

The bot doesn't actually read sample-config.py; it reads config.py instead.
So you need to copy this file to config.py then make your local changes there.
(The reason for this extra step is to make it harder for me to accidentally
check in private information like server names or passwords.)
"""

# The bot's IRC nick
nickname = ""

# Hostname of the IRC server.  For now, only one.
serverhost = "irc.freenode.net"

# Port of the IRC server.  For now, only one.
serverport = 6697

# List of channels to join
initial_channels = []
channels_admin = []

# List of bot admins, user nicks.  
admins = []

# SQLite 3 database path.
sqlite_path = "/path/to/seagl-bot.db"
metric_path = "/path/to/channel_counts.json"

# Bot privileged users
botops = ""

# JITSI URL prefix
JITSI_PREFIX = "https://meet.seagl.org/seagl-"

# Time intervals
names_query_interval='5'
broadcaster_interval='20'
metrics_interval='120'
channel_limit_audit='600'
channel_user_audit='630'

