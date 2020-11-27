# This is a personal project written by a Python novice. Expose your eyeballs
# to this code at your own risk. It's undocumented and probably broken in one
# or more ways at any point in time.

from curses import wrapper
import curses
import praw
import queue
from enum import Enum
import threading
import logging

class ModQItem:
    def __init__(self, **kwargs):
        self.com_or_sub = kwargs.get('com_or_sub')
        if self.com_or_sub is not None:
            assert(self.is_sub() or self.is_com())
        self.user_subs = kwargs.get('user_subs')
        self.sub_url_dup_count = kwargs.get('sub_url_dup_count')
        self.mod_and_user_reps = kwargs.get('mod_and_user_reps')

    def is_sub(self):
        return isinstance(self.com_or_sub,
                praw.models.reddit.submission.Submission) 

    def sub(self):
        assert(self.is_sub())
        return self.com_or_sub

    def com(self):
        assert(self.is_com())
        return self.com_or_sub

    def is_com(self):
        return isinstance(self.com_or_sub,
                praw.models.reddit.comment.Comment) 

    def _count_dups(self):
        self.sub_url_dup_count = 0
        if self.user_subs is None or not self.is_sub():
            return
        for sub in self.user_subs:
            if sub.url == self.com_or_sub.url:
                self.sub_url_dup_count = self.sub_url_dup_count + 1

    # Retrieves recent submissions by the user of the com_or_sub
    def retrieve_user_subs(self, ctx):
        self.user_subs = []
        for sub in ctx.reddit.redditor(
                self.com_or_sub.author.name).submissions.new(
                limit=15):
            self.user_subs.append(sub)
        self._count_dups()

    com_or_sub = None
    user_subs = None
    sub_url_dup_count = None
    mod_and_user_reps = None

class Ctx:
    def __init__(self, **kwargs):
        self.reddit = kwargs.get('reddit')
        self.subreddit = kwargs.get('subreddit')
        self.rem_reas_cache = RemoveReasonCache(ctx = self)

CONTENT_OFFSET = 10

class RemoveReasonCache:
    def __init__(self, **kwargs):
        self.ctx = kwargs.get('ctx')

    def fetch_remove_reasons(self):
        removal_reasons = self.ctx.reddit.subreddit(
                self.ctx.subreddit).mod.removal_reasons
        self.removal_reasons = []
        for removal_reason in removal_reasons:
            self.removal_reasons.append(removal_reason)

def remove_reason_interstitial(ctx, stdscr):
    # TODO: print ctx.rem_reas_cache and have the user pick one
    # TODO: return the ctx.rem_reas_cache[...].id
    return

def refresh_items(ctx):
    # Due to API lameness, we need to use an intermediate dictionary to
    # associate reports with mod queue items
    reports = ctx.reddit.subreddit(ctx.subreddit).mod.reports()
    # key: com_or_sub.id, value: [mod_/user_report,...]
    reported_items = {} 
    for reported_item in reports:
        mod_reports = reported_item.mod_reports
        user_reports = reported_item.user_reports
        if reported_item.id not in reported_items:
            reported_items[reported_item.id] = []
        for user_report in user_reports:
            reported_items[reported_item.id].append(user_report) 
        for mod_report in mod_reports:
            reported_items[reported_item.id].append(mod_report)

    mod_q_items = []
    modqueue_items = ctx.reddit.subreddit(ctx.subreddit).mod.modqueue()
    for com_or_sub in modqueue_items:
        if com_or_sub.id in reported_items:
            mod_and_user_reps = reported_items[com_or_sub.id]
        else:
            mod_and_user_reps = []
        mod_q_item = ModQItem(com_or_sub = com_or_sub, 
                mod_and_user_reps = mod_and_user_reps)
        # For now we only care about user submissions for posts
        if mod_q_item.is_sub():
            mod_q_item.retrieve_user_subs(ctx)
        mod_q_items.append(mod_q_item)
    return mod_q_items

def render_line(stdscr, mod_q_item, pos, i):
    if mod_q_item.is_sub():
        stdscr.addstr(i, CONTENT_OFFSET, '{}'.format(
            mod_q_item.sub().title[:curses.COLS-(CONTENT_OFFSET+1)]),
            curses.A_REVERSE if i == pos else 0)
    else:
        com_str = mod_q_item.com().body
        com_str = com_str.replace('\n', ' ').replace('\r', '')
        stdscr.addstr(i, CONTENT_OFFSET, '{}'.format(
            com_str[:curses.COLS-(CONTENT_OFFSET+1)]),
            curses.A_REVERSE if i == pos else 0)
    stdscr.addstr(i, 0, 'S' if mod_q_item.is_sub() else 'C') 
    if mod_q_item.is_sub():
        stdscr.addstr(i, 2, '{:02}/{:02}'.format(mod_q_item.sub_url_dup_count,
            len(mod_q_item.user_subs)))
    else:
        stdscr.addstr(i, 2, '     ')
    if len(mod_q_item.mod_and_user_reps) > 0:
        stdscr.addstr(i, 8, 'R')

def redraw(stdscr, mod_q_items, pos):
    stdscr.clear()
    i = 0
    for mod_q_item in mod_q_items:
        render_line(stdscr, mod_q_item, pos, i)
        i = i + 1

def sanitize_pos(mod_q_items, pos):
    if pos >= len(mod_q_items):
        pos = len(mod_q_items) - 1
    if pos < 0:
        pos = 0
    return pos 

def remove_mute_ban(ctx, mod_q_item):
    ctx.reddit.submission(mod_q_item.com_or_sub.id).mod.remove()
    ban_msg = ('Due to the characteristics and behavior of this account, '
        'the mods think it runs afoul of Reddit\'s '
        '[self-promotion](https://www.reddit.com/wiki/selfpromotion) '
        'policy and are banning it from r/{}.'.format(ctx.subreddit))
    ctx.reddit.subreddit(ctx.subreddit).banned.add(
            mod_q_item.com_or_sub.author,
            ban_reason="Self-promotion/spam account", ban_message=ban_msg)
    ctx.reddit.subreddit(ctx.subreddit).muted.add(mod_q_item.com_or_sub.author) 

def display_item(stdscr, mod_q_item):
    stdscr.clear()
    if mod_q_item.is_sub():
        stdscr.addstr(0, 0, 'author: {}; title: {}'.format(
            mod_q_item.com_or_sub.author,
            mod_q_item.com_or_sub.title))
        stdscr.addstr(2, 0, 'url: {}'.format(mod_q_item.com_or_sub.url))
        stdscr.addstr(4, 0, 'selftext: {}'.format(
            mod_q_item.com_or_sub.selftext))
    else:
        stdscr.addstr(0, 0, 'author: {}; body: {}'.format(
            mod_q_item.com_or_sub.author,
            mod_q_item.com_or_sub.body))
    # TODO: Limit number of rows consumed by selftext/body above
    i = 10
    for report in mod_q_item.mod_and_user_reps:
        stdscr.addstr(i, 0, 'report: {}'.format(report[0]))
        i = i + 1
    stdscr.getkey()

class SessionCtx():
    def __init__(self, pos=0):
        self.pos = pos
        self.lock = threading.Lock()  
        self.mod_q_items = []
        self.mod_q_items_lock = threading.Lock()

    def get_pos(self):
        self.lock.acquire()
        pos_local = self.pos
        self.lock.release()
        return pos_local

    def set_pos(self, new_pos):
        self.lock.acquire()
        self.pos = new_pos
        self.lock.release()
    pos = 0
    mod_q_items = []
    mod_q_items_lock = None

def loop(ctx, stdscr):
    s_ctx = SessionCtx()
    cmd = Command(cmd=CommandEnum.REFRESH, stdscr=stdscr, ctx=ctx, s_ctx=s_ctx)
    q.put(cmd)
    q.join()
    key = ''
    while not key == 'q':
        stdscr.refresh()
        key = stdscr.getkey()
        if key == "$":
            cmd = Command(cmd=CommandEnum.REFRESH, stdscr=stdscr, ctx=ctx,
                    s_ctx=s_ctx)
            q.put(cmd)
            continue
        s_ctx.mod_q_items_lock.acquire()
        if len(s_ctx.mod_q_items) == 0:
            s_ctx.mod_q_items_lock.release()
            continue
        mod_q_item = s_ctx.mod_q_items[s_ctx.get_pos()]
        s_ctx.mod_q_items_lock.release()
        if key == 'j':
            s_ctx.mod_q_items_lock.acquire()
            if s_ctx.get_pos() + 1 >= len(s_ctx.mod_q_items):
                s_ctx.mod_q_items_lock.release()
                continue
            # TODO: fix '-1' hack
            render_line(stdscr, mod_q_item, -1, s_ctx.get_pos())
            s_ctx.set_pos(s_ctx.get_pos() + 1)
            mod_q_item = s_ctx.mod_q_items[s_ctx.get_pos()]
            s_ctx.mod_q_items_lock.release()
            render_line(stdscr, mod_q_item, s_ctx.get_pos(), s_ctx.get_pos())
        if key == 'k':
            s_ctx.mod_q_items_lock.acquire()
            if s_ctx.get_pos() - 1 < 0:
                s_ctx.mod_q_items_lock.release()
                continue
            # TODO: fix '-1' hack
            render_line(stdscr, mod_q_item, -1, s_ctx.get_pos())
            s_ctx.set_pos(s_ctx.get_pos() - 1)
            mod_q_item = s_ctx.mod_q_items[s_ctx.get_pos()]
            s_ctx.mod_q_items_lock.release()
            render_line(stdscr, mod_q_item, s_ctx.get_pos(), s_ctx.get_pos())
        if key == 'a':
            cmd = Command(cmd=CommandEnum.APPROVE, stdscr=stdscr, ctx=ctx,
                    mod_q_item=mod_q_item, s_ctx=s_ctx)
            q.put(cmd)
            s_ctx.mod_q_items_lock.acquire()
            s_ctx.mod_q_items.remove(cmd.mod_q_item)
            s_ctx.mod_q_items_lock.release()
            s_ctx.set_pos(sanitize_pos(s_ctx.mod_q_items, s_ctx.get_pos()))
            redraw(stdscr, s_ctx.mod_q_items, s_ctx.get_pos())
        if key == 'r':
            # TODO: Prompt for reason and provide it
            if mod_q_item.is_sub():
                ctx.reddit.submission(mod_q_item.com_or_sub.id).mod.remove()
            else:
                assert(mod_q_item.is_com())
                ctx.reddit.comment(mod_q_item.com_or_sub.id).mod.remove()
            s_ctx.mod_q_items_lock.acquire()
            s_ctx.mod_q_items.remove(mod_q_item)
            s_ctx.mod_q_items_lock.release()
            s_ctx.set_pos(sanitize_pos(s_ctx.mod_q_items, s_ctx.get_pos()))
            redraw(stdscr, s_ctx.mod_q_items, s_ctx.get_pos())
        if key == 'b':
            remove_mute_ban(ctx, mod_q_item)
            s_ctx.mod_q_items_lock.acquire()
            s_ctx.mod_q_items.remove(mod_q_item)
            s_ctx.mod_q_items_lock.release()
            s_ctx.set_pos(sanitize_pos(s_ctx.mod_q_items, s_ctx.get_pos()))
            redraw(stdscr, s_ctx.mod_q_items, s_ctx.get_pos())
        if key == ' ' or key == '\r':
            display_item(stdscr, mod_q_item)
            redraw(stdscr, s_ctx.mod_q_items, s_ctx.get_pos())
        if key == 'i':
            if mod_q_item.is_sub():
                ctx.reddit.submission(
                        mod_q_item.com_or_sub.id).mod.ignore_reports()
                ctx.reddit.submission(mod_q_item.com_or_sub.id).mod.approve()
            else:
                assert(mod_q_item.is_com())
                ctx.reddit.comment(
                        mod_q_item.com_or_sub.id).mod.ignore_reports()
                ctx.reddit.comment(mod_q_item.com_or_sub.id).mod.approve()
            s_ctx.mod_q_items_lock.acquire()
            s_ctx.mod_q_items.remove(mod_q_item)
            s_ctx.mod_q_items_lock.release()
            s_ctx.set_pos(sanitize_pos(s_ctx.mod_q_items, s_ctx.get_pos()))
            redraw(stdscr, s_ctx.mod_q_items, s_ctx.get_pos())

class CommandEnum(Enum):
    REFRESH = 1
    APPROVE = 2
    REMOVE = 3
    REMOVE_MUTE_BAN = 4
    IGNORE_APPROVE = 5
    FETCH_REM_REAS = 6
    EXIT = 7
    INVALID = 8

# TODO: Rename variables so they make sense
class Command:
    def __init__(self, **kwargs):
        self.cmd = kwargs.get('cmd')
        if self.cmd is None:
            self.cmd = CommandEnum.INVALID
        self.stdscr = kwargs.get('stdscr')
        self.ctx = kwargs.get('ctx')
        self.mod_q_item = kwargs.get('mod_q_item')
        self.s_ctx = kwargs.get('s_ctx')

q = queue.Queue()

def worker():
    # TODO: Implement the rest of this
    terminate_recvd = False
    while not terminate_recvd:
        cmd = q.get() 
        if cmd.cmd == CommandEnum.REFRESH:
            cmd.s_ctx.mod_q_items_lock.acquire()
            cmd.s_ctx.mod_q_items = refresh_items(cmd.ctx)
            redraw(cmd.stdscr, cmd.s_ctx.mod_q_items, 0)
            cmd.s_ctx.mod_q_items_lock.release()
            q.task_done()
        elif cmd.cmd == CommandEnum.APPROVE:
            if cmd.mod_q_item.is_sub():
                cmd.ctx.reddit.submission(
                        cmd.mod_q_item.com_or_sub.id).mod.approve()
            else:
                cmd.ctx.reddit.comment(
                        cmd.mod_q_item.com_or_sub.id).mod.approve()
            q.task_done()
            continue
        elif cmd.cmd == CommandEnum.REMOVE:
            q.task_done()
            continue
        elif cmd.cmd == CommandEnum.REMOVE_MUTE_BAN:
            q.task_done()
            continue
        elif cmd.cmd == CommandEnum.IGNORE_APPROVE:
            q.task_done()
            continue
        elif cmd.cmd == CommandEnum.FETCH_REM_REAS:
            cmd.ctx.rem_reas_cache.fetch_remove_reasons()
            q.task_done()
            continue
        elif cmd.cmd == CommandEnum.EXIT:
            q.task_done()
            terminate_recvd = True
        elif cmd.cmd == CommandEnum.INVALID:
            q.task_done()
            continue
        else:
            q.task_done()
            continue

def main(stdscr):
    logging.basicConfig(level=logging.INFO)
    logging.info('ModPy Starting')
    stdscr.clear()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_RED)
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLACK)
    # TODO: Put the creds in a separate file
    reddit = praw.Reddit(
            client_id = "PUT YOUR REDDIT SCRIPT CLIENT ID HERE",
            client_secret = "PUT YOUR REDDIT CLIENT SECRET HERE",
            password = "PRAW WANTS YOUR PASSWORD I DON'T KNOW WHY LOL SOZ",
            user_agent = "Reddit Modder",
            username = "PRAW WANTS YOUR USERNAME I DON'T KNOW WHY LOL SOZ")
    ctx = Ctx(reddit = reddit, subreddit = "PUT YOUR SUBREDDIT HERE")
    cmd = Command(cmd=CommandEnum.FETCH_REM_REAS, ctx=ctx)
    q.put(cmd)
    threading.Thread(target=worker, daemon=True).start()
    loop(ctx, stdscr)
    q.join()

wrapper(main)
