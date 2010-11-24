# -*- coding: utf-8 -*-

"""Module for functionality for wrapping a Minecraft server and handling its
packets.

"""

import asyncore
import sys

import autoproto.packet
from minecraft.packet import *
from minecraft.proxy import MinecraftForwarder

__author__ = 'andreas@blixt.org (Andreas Blixt)'

__all__ = [
    'MinecraftWrapper', 'Player', 'command', 'packet_handler']

def _load_module(module):
    m = sys.modules.get(module)
    if m:
        reload(m)
    else:
        __import__(module)
    return sys.modules[module]

class MinecraftWrapper(object):
    def __init__(self):
        self.forwarder = MinecraftForwarder(('', 25564), ('localhost', 25565),
            self.handle_packet)
        self._players = {}

    def handle_packet(self, proxy, packet):
        # Get the client connection for the current packet (even if the packet
        # was sent by the server).
        if packet.direction == autoproto.packet.TO_SERVER:
            client = proxy
        else:
            client = proxy.other

        # Set up a Player object for every client.
        if client not in self._players:
            self._players[client] = Player(client)
        player = self._players[client]

        # Do some special handling of certain packets.
        if isinstance(packet, LogIn):
            # This is a client logging in.
            player.username = packet.username
        elif isinstance(packet, LoggedIn):
            # A player has been logged in and now has an entity id.
            player.id = packet.player_id
        elif isinstance(packet, ChatMessage) and \
                packet.direction == autoproto.packet.TO_SERVER:
            message = packet.message

            # Only handle messages that start with a slash.
            if message[0] == '/':
                # Parse the command string.
                args = message[1:].split(' ')
                command = args.pop(0)

                if command == 'reload':
                    # Special command /reload for reloading handlers.
                    self.reload()
                    packet.suppress()
                elif command in self._commands:
                    try:
                        self._commands[command](player, packet, *args)
                    except Exception, e:
                        print e
                        player.message(u'§6An error occurred.')
                    # Don't send handled commands to the server.
                    packet.suppress()
        elif isinstance(packet, (Move, MoveAndLook, MoveAndLookCorrection)):
            # Player moved.
            player.x = packet.x
            player.y = packet.y
            player.z = packet.z
        elif isinstance(packet, SpawnPosition) or \
                (isinstance(packet, TeleportEntity) and
                 packet.entity_id == player.id):
            # Player was teleported.
            player.x = float(packet.x)
            player.y = float(packet.y)
            player.z = float(packet.z)
        elif isinstance(packet, (MoveEntity, MoveAndPointEntity)) and \
                packet.entity_id == player.id:
            # Player moved (relative).
            player.x += float(packet.x)
            player.y += float(packet.y)
            player.z += float(packet.z)

        # Send the packet to any handler that has been set up for its type and
        # direction.
        key = (packet.__class__, packet.direction)
        if key not in self._handlers:
            return

        for handler in self._handlers[key]:
            handler(player, packet)

    def load_command_module(self, module):
        """Loads a module containing command handler functions. If the module
        has already been loaded, it will be reloaded.

        Currently only supports one module at a time.

        """
        print 'Loading command handlers...'

        m = _load_module(module)

        self._commands = {}
        self._commands_module = module

        for attr_name, attr in m.__dict__.items():
            if callable(attr) and hasattr(attr, '_c_aliases'):
                aliases = attr._c_aliases
                # Remove aliases so that this method won't be loaded again
                # unless it's redefined.
                delattr(attr, '_c_aliases')
                for alias in aliases:
                    assert alias not in self._commands, 'Command redefinition'
                    self._commands[alias] = attr

    def load_handler_module(self, module):
        """Loads a module containing packet handler functions. If the module
        has already been loaded, it will be reloaded.

        Currently only supports one module at a time.

        """
        print 'Loading packet handlers...'

        m = _load_module(module)

        self._handlers = {}
        self._handlers_module = module

        for attr_name, attr in m.__dict__.items():
            if callable(attr) and hasattr(attr, '_p_handler_keys'):
                keys = attr._p_handler_keys
                # Remove keys so that this method won't be loaded again unless
                # it's redefined.
                delattr(attr, '_p_handler_keys')
                for key in keys:
                    if key not in self._handlers:
                        self._handlers[key] = []
                    self._handlers[key].append(attr)

    def reload(self):
        """Reloads the command and packet handler modules.

        """
        self.load_command_module(self._commands_module)
        self.load_handler_module(self._handlers_module)

    def start(self):
        try:
            asyncore.loop()
        except KeyboardInterrupt:
            self.forwarder.handle_close()

class Player(object):
    def __init__(self, client):
        self.client = client
        self.id = -1
        self.username = 'Unknown'
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0

    def message(self, message):
        """Convenience function for sending a message to the player.

        """
        self.send(ChatMessage(message=message))

    def inject(self, packet):
        """Inject a packet into the client output. The server will receive the
        packet and believe it originated from the client.

        """
        self.client.packets.append(packet)

    def send(self, packet):
        """Sends a packet to the client. The client will believe the packet
        arrived from the server.

        """
        self.client.other.packets.append(packet)

def command(*aliases):
    """Descriptor for marking a method as a command handler. Commands are
    entered by the player as a chat message starting with "/".

    """
    def decorator(handler):
        if hasattr(handler, '_c_aliases'):
            handler._c_aliases += aliases
        else:
            handler._c_aliases = aliases
        print 'Registered command %s' % '/'.join(aliases)
        return handler
    return decorator

def packet_handler(packet_type, directions=0):
    """Descriptor for marking a method as handling a certain packet type in the
    specified direction.

    If no direction is specified, the directions supported by the packet type
    are used.

    """
    if not directions:
        if issubclass(packet_type, autoproto.packet.PacketToClient):
            directions |= autoproto.packet.TO_CLIENT
        if issubclass(packet_type, autoproto.packet.PacketToServer):
            directions |= autoproto.packet.TO_SERVER

    keys = []
    if directions & autoproto.packet.TO_CLIENT:
        keys.append((packet_type, autoproto.packet.TO_CLIENT))
    if directions & autoproto.packet.TO_SERVER:
        keys.append((packet_type, autoproto.packet.TO_SERVER))

    assert keys, 'Invalid direction'

    def decorator(handler):
        if hasattr(handler, '_p_handler_keys'):
            handler._p_handler_keys += keys
        else:
            handler._p_handler_keys = keys
        print 'Registered packet handler %s (for %s)' % (
            handler.__name__, packet_type.__name__)
        return handler
    return decorator