import re
import fnmatch
import itertools

from typing import Union, FrozenSet, Set, Tuple, List, TypeVar, Optional, Dict

import botconfig
import src.settings as var
from src import proxy, debuglog
from src.events import Event
from src.messages import messages

# the following import is only needed for type hints
from oyoyo.client import IRCClient

RolesIterable = Union[FrozenSet[str], Set[str], Tuple[str], List[str]]
Nickname = TypeVar("Nickname", None, str)

__all__ = ["pm", "is_fake_nick", "mass_mode", "mass_privmsg", "reply",
           "is_user_simple", "is_user_notice", "in_wolflist",
           "relay_wolfchat_command", "chk_nightdone", "chk_decision",
           "chk_win", "irc_lower", "irc_equals", "is_role", "match_hostmask",
           "is_owner", "is_admin", "plural", "singular", "list_players",
           "list_players_and_roles", "get_role", "get_reveal_role",
           "get_templates", "role_order", "break_long_message",
           "complete_match", "get_victim", "get_nick", "InvalidModeException"]

# message either privmsg or notice, depending on user settings
def pm(cli: IRCClient, target: str, message: str) -> None:
    if is_fake_nick(target) and botconfig.DEBUG_MODE:
        debuglog("Would message fake nick {0}: {1!r}".format(target, message))
        return

    if is_user_notice(target):
        cli.notice(target, message)
        return

    cli.msg(target, message)

is_fake_nick = re.compile(r"^[0-9]+$").search

def mass_mode(cli: IRCClient, md_param: List[Tuple[str, str]], md_plain: List[str]) -> None:
    """ Example: mass_mode(cli, [('+v', 'asdf'), ('-v','wobosd')], ['-m']) """
    lmd = len(md_param)  # store how many mode changes to do
    if md_param:
        for start_i in range(0, lmd, var.MODELIMIT):  # 4 mode-changes at a time
            if start_i + var.MODELIMIT > lmd:  # If this is a remainder (mode-changes < 4)
                z = list(zip(*md_param[start_i:]))  # zip this remainder
                ei = lmd % var.MODELIMIT  # len(z)
            else:
                z = list(zip(*md_param[start_i:start_i+var.MODELIMIT])) # zip four
                ei = var.MODELIMIT # len(z)
            # Now z equal something like [('+v', '-v'), ('asdf', 'wobosd')]
            arg1 = "".join(md_plain) + "".join(z[0])
            arg2 = " ".join(z[1])  # + " " + " ".join([x+"!*@*" for x in z[1]])
            cli.mode(botconfig.CHANNEL, arg1, arg2)
    elif md_plain:
        cli.mode(botconfig.CHANNEL, "".join(md_plain))

def mass_privmsg(cli: IRCClient, targets: List[str], msg: str, notice: bool=False, privmsg: bool=False) -> None:
    if not targets:
        return
    if not notice and not privmsg:
        msg_targs = []
        not_targs = []
        for target in targets:
            if is_fake_nick(target):
                debuglog("Would message fake nick {0}: {1!r}".format(target, msg))
            elif is_user_notice(target):
                not_targs.append(target)
            else:
                msg_targs.append(target)
        while msg_targs:
            if len(msg_targs) <= var.MAX_PRIVMSG_TARGETS:
                bgs = ",".join(msg_targs)
                msg_targs = None
            else:
                bgs = ",".join(msg_targs[:var.MAX_PRIVMSG_TARGETS])
                msg_targs = msg_targs[var.MAX_PRIVMSG_TARGETS:]
            cli.msg(bgs, msg)
        while not_targs:
            if len(not_targs) <= var.MAX_PRIVMSG_TARGETS:
                bgs = ",".join(not_targs)
                not_targs = None
            else:
                bgs = ",".join(not_targs[:var.MAX_PRIVMSG_TARGETS])
                not_targs = not_targs[var.MAX_PRIVMSG_TARGETS:]
            cli.notice(bgs, msg)
    else:
        while targets:
            if len(targets) <= var.MAX_PRIVMSG_TARGETS:
                bgs = ",".join(targets)
                targets = None
            else:
                bgs = ",".join(targets[:var.MAX_PRIVMSG_TARGETS])
                target = targets[var.MAX_PRIVMSG_TARGETS:]
            if notice:
                cli.notice(bgs, msg)
            else:
                cli.msg(bgs, msg)

# Decide how to reply to a user, depending on the channel / query it was called in, and whether a game is running and they are playing
def reply(cli: IRCClient, nick: str, chan: str, msg: str, private: bool=False, prefix_nick: bool=False) -> None:
    if chan == nick:
        pm(cli, nick, msg)
    elif private or (nick not in list_players() and var.PHASE in var.GAME_PHASES and chan == botconfig.CHANNEL):
        cli.notice(nick, msg)
    else:
        if prefix_nick:
            cli.msg(chan, "{0}: {1}".format(nick, msg))
        else:
            cli.msg(chan, msg)

def is_user_simple(nick: str) -> bool:
    if nick in var.USERS:
        ident = irc_lower(var.USERS[nick]["ident"])
        host = var.USERS[nick]["host"].lower()
        acc = irc_lower(var.USERS[nick]["account"])
    else:
        return False
    if acc and acc != "*" and not var.DISABLE_ACCOUNTS:
        if acc in var.SIMPLE_NOTIFY_ACCS:
            return True
        return False
    elif not var.ACCOUNTS_ONLY:
        for hostmask in var.SIMPLE_NOTIFY:
            if match_hostmask(hostmask, nick, ident, host):
                return True
    return False

def is_user_notice(nick: str) -> bool:
    if nick in var.USERS and var.USERS[nick]["account"] and var.USERS[nick]["account"] != "*" and not var.DISABLE_ACCOUNTS:
        if irc_lower(var.USERS[nick]["account"]) in var.PREFER_NOTICE_ACCS:
            return True
    if nick in var.USERS and not var.ACCOUNTS_ONLY:
        ident = irc_lower(var.USERS[nick]["ident"])
        host = var.USERS[nick]["host"].lower()
        for hostmask in var.PREFER_NOTICE:
            if match_hostmask(hostmask, nick, ident, host):
                return True
    return False

def in_wolflist(nick: str, who: str) -> bool:
    myrole = get_role(nick)
    role = get_role(who)
    wolves = var.WOLFCHAT_ROLES
    if var.RESTRICT_WOLFCHAT & var.RW_REM_NON_WOLVES:
        if var.RESTRICT_WOLFCHAT & var.RW_TRAITOR_NON_WOLF:
            wolves = var.WOLF_ROLES
        else:
            wolves = var.WOLF_ROLES | {"traitor"}
    return myrole in wolves and role in wolves

def relay_wolfchat_command(cli: IRCClient, nick: str, message: str, roles: RolesIterable, is_wolf_command: bool=False, is_kill_command: bool=False) -> None:
    if not is_wolf_command and var.RESTRICT_WOLFCHAT & var.RW_NO_INTERACTION:
        return
    if not is_kill_command and var.RESTRICT_WOLFCHAT & var.RW_ONLY_KILL_CMD:
        if var.PHASE == "night" and var.RESTRICT_WOLFCHAT & var.RW_DISABLE_NIGHT:
            return
        if var.PHASE == "day" and var.RESTRICT_WOLFCHAT & var.RW_DISABLE_DAY:
            return
    if not in_wolflist(nick, nick):
        return

    wcroles = var.WOLFCHAT_ROLES
    if var.RESTRICT_WOLFCHAT & var.RW_ONLY_SAME_CMD:
        if var.PHASE == "night" and var.RESTRICT_WOLFCHAT & var.RW_DISABLE_NIGHT:
            wcroles = roles
        if var.PHASE == "day" and var.RESTRICT_WOLFCHAT & var.RW_DISABLE_DAY:
            wcroles = roles
    elif var.RESTRICT_WOLFCHAT & var.RW_REM_NON_WOLVES:
        if var.RESTRICT_WOLFCHAT & var.RW_TRAITOR_NON_WOLF:
            wcroles = var.WOLF_ROLES
        else:
            wcroles = var.WOLF_ROLES | {"traitor"}

    wcwolves = list_players(wcroles)
    wcwolves.remove(nick)
    mass_privmsg(cli, wcwolves, message)
    mass_privmsg(cli, var.SPECTATING_WOLFCHAT, "[wolfchat] " + message)

# The following functions are going to confuse the hell out of Mypy
# We annotate them anyway, but we should fix this later

@proxy.stub
def chk_nightdone(cli: IRCClient) -> None:
    pass

@proxy.stub
def chk_decision(cli: IRCClient, force: str="") -> None:
    pass

@proxy.stub
def chk_win(cli: IRCClient, end_game: bool=True, winner: bool=None) -> bool:
    pass

def irc_lower(nick: Nickname) -> Nickname:
    if nick is None:
        return None

    mapping = {
        "[": "{",
        "]": "}",
        "\\": "|",
        "^": "~",
    }

    # var.CASEMAPPING may not be defined yet in some circumstances (like database upgrades)
    # if so, default to rfc1459
    if hasattr(var, "CASEMAPPING"):
        if var.CASEMAPPING == "strict-rfc1459":
            mapping.pop("^")
        elif var.CASEMAPPING == "ascii":
            mapping = {}

    return nick.lower().translate(str.maketrans(mapping))

def irc_equals(nick1: Nickname, nick2: Nickname) -> bool:
    return irc_lower(nick1) == irc_lower(nick2)

is_role = lambda plyr, rol: rol in var.ROLES and plyr in var.ROLES[rol]

def match_hostmask(hostmask: str, nick: str, ident: str, host: str) -> bool:
    # support n!u@h, u@h, or just h by itself
    matches = re.match('(?:(?:(.*?)!)?(.*?)@)?(.*)', hostmask)

    if ((not matches.group(1) or fnmatch.fnmatch(irc_lower(nick), irc_lower(matches.group(1)))) and
            (not matches.group(2) or fnmatch.fnmatch(irc_lower(ident), irc_lower(matches.group(2)))) and
            fnmatch.fnmatch(host.lower(), matches.group(3).lower())):
        return True

    return False

def is_owner(nick: str, ident: Optional[str]=None, host: Optional[str]=None, acc: Optional[str]=None) -> bool:
    hosts = set(botconfig.OWNERS)
    accounts = set(botconfig.OWNERS_ACCOUNTS)
    if nick in var.USERS:
        if not ident:
            ident = var.USERS[nick]["ident"]
        if not host:
            host = var.USERS[nick]["host"]
        if not acc:
            acc = var.USERS[nick]["account"]

    if not var.DISABLE_ACCOUNTS and acc and acc != "*":
        for pattern in accounts:
            if fnmatch.fnmatch(irc_lower(acc), irc_lower(pattern)):
                return True

    if host:
        for hostmask in hosts:
            if match_hostmask(hostmask, nick, ident, host):
                return True

    return False

def is_admin(nick: str, ident: Optional[str]=None, host: Optional[str]=None, acc: Optional[str]=None):
    if nick in var.USERS:
        if not ident:
            ident = var.USERS[nick]["ident"]
        if not host:
            host = var.USERS[nick]["host"]
        if not acc:
            acc = var.USERS[nick]["account"]
    acc = irc_lower(acc)
    hostmask = irc_lower(nick) + "!" + irc_lower(ident) + "@" + host.lower()
    flags = var.FLAGS[hostmask] + var.FLAGS_ACCS[acc]

    if not "F" in flags:
        try:
            hosts = set(botconfig.ADMINS)
            accounts = set(botconfig.ADMINS_ACCOUNTS)

            if not var.DISABLE_ACCOUNTS and acc and acc != "*":
                for pattern in accounts:
                    if fnmatch.fnmatch(irc_lower(acc), irc_lower(pattern)):
                        return True

            if host:
                for hostmask in hosts:
                    if match_hostmask(hostmask, nick, ident, host):
                        return True
        except AttributeError:
            pass

        return is_owner(nick, ident, host, acc)

    return True

def plural(role: str, count: int=2) -> str:
    if count == 1:
        return role
    bits = role.split()
    if bits[-1][-2:] == "'s":
        bits[-1] = plural(bits[-1][:-2], count)
        bits[-1] += "'" if bits[-1][-1] == "s" else "'s"
    else:
        bits[-1] = {"person": "people",
                    "wolf": "wolves",
                    "has": "have",
                    "succubus": "succubi",
                    "child": "children"}.get(bits[-1], bits[-1] + "s")
    return " ".join(bits)

def singular(plural: str) -> str:
    # converse of plural above (kinda)
    # this is used to map plural team names back to singular,
    # so we don't need to worry about stuff like possessives
    # Note that this is currently only ever called on team names,
    # and will require adjustment if one wishes to use it on roles.
    conv = {"wolves": "wolf",
            "succubi": "succubus"}
    if plural in conv:
        return conv[plural]
    # otherwise we just added an s on the end
    return plural[:-1]

def list_players(roles: Optional[RolesIterable]=None) -> List[str]:
    if roles is None:
        roles = var.ROLES.keys()
    pl = set()
    for x in roles:
        if x in var.TEMPLATE_RESTRICTIONS.keys():
            continue
        for p in var.ROLES.get(x, ()):
            pl.add(p)
    return [p for p in var.ALL_PLAYERS if p in pl]

def list_players_and_roles() -> Dict[str, str]:
    plr = {}
    for x in var.ROLES.keys():
        if x in var.TEMPLATE_RESTRICTIONS.keys():
            continue # only get actual roles
        for p in var.ROLES[x]:
            plr[p] = x
    return plr

def get_role(p: str) -> str:
    for role, pl in var.ROLES.items():
        if role in var.TEMPLATE_RESTRICTIONS.keys():
            continue # only get actual roles
        if p in pl:
            return role

def get_roles(*roles: str) -> List[str]:
    all_roles = []
    for role in roles:
        all_roles.append(var.ROLES[role])
    return list(itertools.chain(*all_roles))

def get_reveal_role(nick: str) -> str:
    if var.HIDDEN_TRAITOR and get_role(nick) == "traitor":
        role = var.DEFAULT_ROLE
    elif var.HIDDEN_AMNESIAC and nick in var.ORIGINAL_ROLES["amnesiac"]:
        role = "amnesiac"
    elif var.HIDDEN_CLONE and nick in var.ORIGINAL_ROLES["clone"]:
        role = "clone"
    else:
        role = get_role(nick)

    evt = Event("get_reveal_role", {"role": role})
    evt.dispatch(var, nick)
    role = evt.data["role"]

    if var.ROLE_REVEAL != "team":
        return role

    if role in var.WOLFTEAM_ROLES:
        return "wolf"
    elif role in var.TRUE_NEUTRAL_ROLES:
        return "neutral player"
    else:
        return "villager"

def get_templates(nick: str) -> List[str]:
    tpl = []
    for x in var.TEMPLATE_RESTRICTIONS.keys():
        try:
            if nick in var.ROLES[x]:
                tpl.append(x)
        except KeyError:
            pass

    return tpl

role_order = lambda: var.ROLE_GUIDE

def break_long_message(phrases: List[str], joinstr: str=" ") -> str:
    message = []
    count = 0
    for phrase in phrases:
        # IRC max is 512, but freenode splits around 380ish, make 300 to have plenty of wiggle room
        if count + len(joinstr) + len(phrase) > 300:
            message.append("\n" + phrase)
            count = len(phrase)
        else:
            if not message:
                count = len(phrase)
            else:
                count += len(joinstr) + len(phrase)
            message.append(phrase)
    return joinstr.join(message)

#completes a partial nickname or string from a list
def complete_match(string: str, matches: RolesIterable):
    num_matches = 0
    bestmatch = string
    for possible in matches:
        if string == possible:
            return string, 1
        if possible.startswith(string) or possible.lstrip("[{\\^_`|}]").startswith(string):
            bestmatch = possible
            num_matches += 1
    if num_matches != 1:
        return None, num_matches
    else:
        return bestmatch, 1

#wrapper around complete_match() used for roles
def get_victim(cli: IRCClient, nick: str, victim: str, in_chan: bool, self_in_list: bool=False, bot_in_list: bool=False) -> Optional[str]:
    chan = botconfig.CHANNEL if in_chan else nick
    if not victim:
        reply(cli, nick, chan, messages["not_enough_parameters"], private=True)
        return
    pl = [x for x in list_players() if x != nick or self_in_list]
    pll = [x.lower() for x in pl]

    if bot_in_list: # for villagergame
        pl.append(botconfig.NICK)
        pll.append(botconfig.NICK.lower())

    tempvictim, num_matches = complete_match(victim.lower(), pll)
    if not tempvictim:
        #ensure messages about not being able to act on yourself work
        if num_matches == 0 and nick.lower().startswith(victim.lower()):
            return nick
        reply(cli, nick, chan, messages["not_playing"].format(victim), private=True)
        return
    return pl[pll.index(tempvictim)] #convert back to normal casing

# wrapper around complete_match() used for any nick on the channel
def get_nick(cli: IRCClient, nick: str) -> Optional[str]:
    ul = [x for x in var.USERS]
    ull = [x.lower() for x in var.USERS]
    lnick, num_matches = complete_match(nick.lower(), ull)
    if not lnick:
        return None
    return ul[ull.index(lnick)]


class InvalidModeException(Exception): pass

# vim: set sw=4 expandtab:
