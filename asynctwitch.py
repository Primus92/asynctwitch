import asyncio
import traceback
import sys
import os
import io
import re
import inspect
import math
import json
import configparser
import datetime
import subprocess
	
sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding=sys.stdout.encoding, errors="backslashreplace", line_buffering=True)
# fix unicode characters breaking the bot
	
class Message:
	"""
	Custom message object to combine message, author and timestamp
	"""
	
	def __init__(self, m, a, bot):
		self.content = m
		self.author = a
		self.timestamp = datetime.datetime.utcnow()
	#
	
	
class Command:
	
	"""
	A command class to provide methods we can use with it
	"""
	
	def __init__(self, bot, comm, *, alias=[], desc='', admin=False, unprefixed=False, listed=True):
		self.bot = bot
		self.comm = comm
		self.desc = desc
		self.alias = alias
		self.admin = admin
		self.listed = listed
		self.unprefixed = unprefixed
		self.subcommands = []
		bot.commands.append(self)
	#
	
	def subcommand(self, *args, **kwargs):
		"""
		Create subcommands 
		"""
		return SubCommand(self, *args, **kwargs) # set subcommand
	#
	
	def __call__(self, func):
		"""
		Make it able to be a decorator
		"""
		
		self.func = func

		return self
	#
	
	async def run(self, message):
		"""
		Does type checking for command arguments
		"""
	
		args = message.content.split(" ")[1:] # Get arguments from message
		
		args_name = inspect.getfullargspec(self.func)[0][1:] # Get amount of arguments needed
		
		if len(args) > len(args_name):
			args[len(args_name)-1] = " ".join(args[len(args_name)-1:]) # Put all leftovers in final argument
			
			args = args[:len(args_name)]
				
		elif len(args) < len(args_name): # Not enough arguments, Error
			raise Exception('Not enough arguments for {}, required arguments: {}'.format(self.comm, ', '.join(args_name)))
			
		ann = self.func.__annotations__ # Get type hints
		
		for x in range(0, len(args_name)): # loop through arguments
			v = args[x]
			k = args_name[x]
			
			if type(v) == ann[k]: 
				pass # Content is correct type already
				
			else:
				try:
					v = ann[k](v) # Try calling __init__() with the argument
					
				except: # Invalid type or type unsupported
					raise TypeError("Invalid type: got {}, {} expected".format(ann[k].__name__, v.__name__))
					
			args[x] = v # add to arguments

		if len(self.subcommands)>0: # Command has subcommands
			subcomm = args.pop(0) # Find subcommands
			
			for s in self.subcommands:
				if subcomm == s.comm:
					c = message.content.split(" ")
					message.content = c[0] + " " + " ".join(c[2:])
					
					await s.run(message) # Run subcommand
					break
			
		else: # Run command
			await self.func(message, *args)
	#

	
class SubCommand(Command):
	"""
	Subcommand class
	"""
	
	def __init__(self, parent, comm, *, desc=''):
		self.comm = comm
		self.parent = parent
		self.bot = parent.bot
		self.subcommands = []
		self.parent.subcommands.append(self) # add to parent command
	#
	
	def __call__(self, func):
		"""
		Make it a decorator
		"""
		self.func = func
		
		return self
	#
	
	
class Bot:
	"""
	Bot class without command support 
	"""
	
	def __init__(self, *, oauth=None, user=None, channel='#twitch', prefix='!', admins=[], config=None):
		if config:
			self.load(config)
			
		else:
			self.prefix = prefix
			self.oauth = oauth
			self.nick = user
			self.chan = "#" + channel.lower()
		
		self.loop = asyncio.ProactorEventLoop()
		asyncio.set_event_loop(self.loop)
		self.host = 'irc.twitch.tv'
		self.port = 6667
		
		self.admins = admins
	#
	
	def load(self, path):
		"""
		Loads settings from file
		"""
		config = configparser.ConfigParser(interpolation=None)
		config.read(path)
		self.oauth = config.get('Settings', 'oauth', fallback=None)
		self.nick = config.get('Settings', 'username', fallback=None)
		self.chan = "#" + config.get('Settings', 'channel', fallback="twitch")
		self.prefix = config.get('Settings', 'prefix', fallback="!")
	#
	
	def override(self, func):
		"""
		Allows for overriding certain functions
		"""
		setattr(self, func.__name__, func)
	#
	
	def start(self):
		"""
		Starts the event loop,
		Blocking call
		"""
		
		self.loop.run_until_complete(self._tcp_echo_client())
	#
	
	
	# ------------------------ #
	# --- Needed Functions --- #
	# ------------------------ #
	
	async def _pong(self, msg):
		"""
		Tell remote we're still alive
		"""
		self.writer.write(bytes('PONG %s\r\n' % msg, 'UTF-8'))
	#

	async def say(self, msg):
		"""
		Send messages
		"""
		self.writer.write(bytes('PRIVMSG %s :%s\r\n' % (self.chan, str(msg)), 'UTF-8'))
	#

	async def _nick(self):
		"""
		Send name
		"""
		self.writer.write(bytes('NICK %s\r\n' % self.nick, 'UTF-8'))
	#

	async def _pass(self):
		"""
		Send oauth token
		"""
		self.writer.write(bytes('PASS %s\r\n' % self.oauth, 'UTF-8'))
	#
	
	async def _join(self):
		"""
		Join a channel
		"""
		self.writer.write(bytes('JOIN %s\r\n' % self.chan, 'UTF-8'))
	#

	async def _part(self):
		"""
		Leave a channel
		"""
		self.writer.write(bytes('PART %s\r\n' % self.chan, 'UTF-8'))
	#

	async def _special(self, mode):
		"""
		Allows for more events
		"""
		self.writer.write(bytes('CAP REQ :twitch.tv/%s\r\n' % mode,'UTF-8'))
	#
	
	async def _tcp_echo_client(self):
		"""
		Receive messages and send to parser
		"""
	
		self.reader, self.writer = await asyncio.open_connection(self.host, self.port, loop=self.loop) # Open connections
		
		await self._pass()		#
		await self._nick()		# Log in and join
		await self._join()		#
		
		modes = ['JOIN','PART','MODE']
		for m in modes:
			await self._special(m)
			
		await self.event_ready()
		
		while True: # Loop to keep receiving messages
			rdata = (await self.reader.read(1024)).decode('utf-8') # Received bytes to str
			await self.raw_event(rdata)

			if not rdata:
				continue
				
			try:
				p = re.compile("(?P<data>.*?) (?P<action>[A-Z]*?) (?P<data2>.*)")
				m = p.match(rdata)
			
				action = m.group('action')
				data = m.group('data')
				data2 = m.group('data2')
			except:
				pass
			else:
				try:
					if action == 'PING':
						await self._pong(line[1]) # Send PONG to server
						
					elif action == 'PRIVMSG':
						sender = re.match(":(?P<author>[a-zA-Z0-9_]+)!(?P=author)@(?P=author).tmi.twitch.tv", data).group('author')
						message = re.match("#[a-zA-Z0-9_]+ :(?P<content>.+)", data2).group('content')
						
						messageobj = Message(message, sender, self) # Create Message object
						
						await self.event_message(messageobj) # Try parsing
					
					elif action == 'JOIN':
						sender = re.match(":(?P<author>[a-zA-Z0-9_]+)!(?P=author)@(?P=author).tmi.twitch.tv", data).group('author')
						await self.event_user_join(sender)
						
					elif action == 'PART':
						sender = re.match(":(?P<author>[a-zA-Z0-9_]+)!(?P=author)@(?P=author).tmi.twitch.tv", data).group('author')
						await self.event_user_leave(sender)
					
					elif action == 'MODE':
						m = re.match("#[a-zA-Z0-9]+ (?P<mode>[+-])o (?P<user>.+?)", data2)
						mode = m.group('mode')
						user = m.group('user')
						await self.event_user_mode(mode, user)
					
					else:
						print("Unknown event:", action)
						print(rdata)
						
				except Exception as e:
					fname = e.__traceback__.tb_next.tb_frame.f_code.co_name
					print("Ignoring exception in {}:".format(fname))
					traceback.print_exc()
	#
	
	async def stop(self, exit=False):
		"""
		Stops the bot and disables using it again.
		Useful for a restart command I guess
		"""
		self.player.terminate()
		self.loop.stop()
		self.loop.close()
		if exit:
			os._exit(0)
	#
	
	async def play_file(self, file):
		"""
		Plays audio.
		For this to work, ffplay, ffmpeg and ffprobe, downloadable from the ffmpeg website,
		have to be in the same folder as the bot OR added to path.
		"""
		
		j = await self.loop.run_in_executor(None, subprocess.check_output, ['ffprobe', '-v', '-8', '-print_format', 'json', '-show_format', file])
		
		j = json.loads(j.decode().strip())
		
		self.player = await asyncio.create_subprocess_exec('ffplay', '-nodisp', '-autoexit', '-v', '-8', file, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
		await asyncio.sleep( math.ceil( float( j['format']['duration'] )) + 2)
		return True
	#
	
	async def play_ytdl(self, query, *, filename='song.mp3', cleanup=True, options={}):
		"""
		Requires youtube_dl to be installed
		`pip install youtube_dl`
		"""
		import youtube_dl
		
		args = {
			'format': 'bestaudio/best',
			'noplaylist': True,
			'audioformat': 'mp3',
			'default_search': 'auto',
			'loglevel':'quiet',
			'outtmpl': filename
		}
		args.update(options)
		ytdl = youtube_dl.YoutubeDL(args)
		await self.loop.run_in_executor(None, ytdl.download, ([query]))
		await self.play_file(filename)
		if cleanup:
			os.remove(filename)
	#
	
	async def event_ready(self):
		"""
		Called when the bot is ready for use
		"""
		pass
	#
	
	async def raw_event(self, data):
		"""
		Called on all events after event_ready
		"""
		pass
	#
	
	async def event_user_join(self, user):
		"""
		Called when a user joins
		"""
		pass
	#
	
	async def event_user_leave(self, user):
		"""
		Called when a user leaves
		"""
		pass
	#
	
	async def event_user_mode(self, mode, user):
		"""
		Called when a user is opped/de-opped
		"""
		pass
	#
	
	async def event_message(self, rm):
		"""
		Called when a message is sent
		"""
		pass
	#
	
	
class CommandBot(Bot):
	"""
	Allows the usage of Commands more easily
	"""
	
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.commands = []
		self.playlist = []
		self.playing = None
	#
	
	async def event_message(self, rm):
		"""
		Shitty command parser I made
		"""
		
		if rm.content.startswith(self.prefix):
	
			m = rm.content[len(self.prefix):]
			l = m.split(" ")
			w = l.pop(0).lower().replace("\r","")
			m = " ".join(l)
			
			for c in self.commands:
				if (w == c.comm or w in c.alias) and not c.unprefixed:

					if c.admin and not rm.author in self.admins:
						await rm.reply("You are not allowed to use this command")
						return
					await c.run(rm)

		else:
			l = rm.content.split(" ")
			w = l.pop(0).lower()
			
			for c in self.commands:
				if (w == c.comm or w in c.alias) and c.unprefixed:
					await c.run(rm)
					break
	#
	
	def command(self, *args, **kwargs):
		"""
		Add a command 
		"""
		
		return Command(self, *args, **kwargs)
	#
	
	async def play_list(self, l):
		self.playlist = l
		while self.playlist:
			song = self.playlist.pop(0)
			self.playing = song
			await self.play_ytdl(song)
	#