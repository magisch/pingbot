import io
import logging
import json
import random
import re
import time
import ChatExchange.chatexchange as ce

from . import RoomObserver as BaseRoomObserver, RoomParticipant as BaseRoomParticipant

logger = logging.getLogger('pingbot.chat.stackexchange')

def format_message(message):
    return (u'[auto]\n{}' if u'\n' in message else u'[auto] {}').format(message)

class ChatExchangeSession(object):
    def __init__(self, email, password, host='stackexchange.com'):
        self.client = ce.client.Client(host, email, password)
        logger.debug(u'Logging in as {}'.format(email))
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.client.logout()
    def listen(self, room_id):
        return RoomListener(self, room_id)

def code_quote(s):
    return u'`{}`'.format(s.replace(u'`', u''))

class RoomObserver(BaseRoomObserver):
    def __init__(self, chatexchange_session, room_id, leave_room_on_close=True, ping_format=u'@{}', superping_format=u'@@{}'):
        self.session = chatexchange_session
        self.room_id = room_id
        self.leave_room_on_close = leave_room_on_close
        self.ping_format = unicode(ping_format)
        self.superping_format = unicode(superping_format)
        self._room = self.session.client.get_room(self.room_id)
        self._room.join()
        self._observer_active = True
        logger.info(u'Joined room {}'.format(room_id))

    def watch(self, event_callback):
        if self._observer_active:
            self._room.watch(event_callback)

    def watch_polling(self, event_callback, interval):
        if self._observer_active:
            self._room.watch_polling(event_callback, interval)

    def watch_socket(self, event_callback):
        if self._observer_active:
            self._room.watch_socket(event_callback)

    def close(self):
        # If multiple threads try to leave the same room, this guard makes it
        # unlikely that more than one of them will actually run close(). If the
        # timing works out so that does happen, it's not really a problem; the
        # SE system should just ignore the duplicate leave request.
        if not self._observer_active:
            return
        self._observer_active = False
        logger.debug(u'Closing RoomObserver')
        try:
            if self.leave_room_on_close:
                logger.info(u'Leaving room {}'.format(self.room_id))
                self._room.leave()
            else:
                logger.info(u'Not leaving room {}'.format(self.room_id))
        finally:
            self._room = None

    def __iter__(self):
        # Note that multiple independent iterators will each see a copy of each
        # of the room's events.
        return iter(self._room.new_events())

    def ping_string(self, user_id, quote=False):
        return self.get_ping_strings([user_id], quote)[0]

    def ping_strings(self, user_ids, quote=False):
        ping_format = code_quote(self.ping_format) if quote else self.ping_format
        superping_format = code_quote(self.superping_format) if quote else self.superping_format
        pingable_users = dict(zip(self._room.get_pingable_user_ids(), self._room.get_pingable_user_names()))
        return [(ping_format.format(pingable_users[i].replace(u' ', u'')) if i in pingable_users else superping_format.format(i)) for i in user_ids]

    @property
    def present_user_ids(self):
        return set(self._room.get_current_user_ids())

    @property
    def pingable_user_ids(self):
        return set(self._room.get_pingable_user_ids())

    @property
    def observer_active(self):
        return self._observer_active

class RoomParticipant(RoomObserver, BaseRoomParticipant):
    def __init__(self, chatexchange_session, room_id, leave_room_on_close=True, announce=True, ping_format=u'@{}', superping_format=u'@@{}'):
        RoomObserver.__init__(self, chatexchange_session, room_id, leave_room_on_close, ping_format, superping_format)
        self.announce = announce
        self._participant_active = True
        if self.announce:
            self._send(u'Ping bot is now active')

    def send(self, message, reply_target=None):
        if not self._participant_active:
            logger.info(u'Dropping message due to inactive status: {}'.format(repr(message)))
            return
        self._send(message, reply_target)

    def _send(self, message, reply_target=None):
        message = format_message(message)
        rmessage = repr(message)
        if reply_target:
            logger.debug(u'Replying with message: {}'.format(rmessage))
            reply_target.reply(message)
        else:
            logger.debug(u'Sending message: {}'.format(rmessage))
            self._room.send_message(message)

    def close(self):
        logger.debug(u'Closing RoomParticipant')
        self._participant_active = False
        if self.announce:
            try:
                self._send(u'Ping bot is leaving')
                # hopefully a delay helps allow the ChatExchange client to clear
                # its queue and send the last message
                time.sleep(0.5)
            except:
                logger.exception(u'Error sending goodbye message')
        super(RoomParticipant, self).close()

    @property
    def participant_active(self):
        return self._participant_active
