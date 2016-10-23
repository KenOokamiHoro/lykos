import base64
import sys

import botconfig
import src.settings as var
from src import decorators, wolfgame, hooks, channel, user, stream_handler as alog

hook = decorators.hook

def on_privmsg(cli, rawnick, chan, msg, notice=False):
    if notice and "!" not in rawnick or not rawnick: # server notice; we don't care about those
        return

    if botconfig.IGNORE_HIDDEN_COMMANDS and chan.startswith(tuple(hooks.Features["STATUSMSG"])):
        return

    if (notice and ((not user.equals(chan, user.Bot.nick) and not botconfig.ALLOW_NOTICE_COMMANDS) or
                    (user.equals(chan, user.Bot.nick) and not botconfig.ALLOW_PRIVATE_NOTICE_COMMANDS))):
        return  # not allowed in settings

    source = user.get(rawnick, raw_nick=True)

    if user.equals(chan, user.Bot.nick):
        target = source
    else:
        target = channel.add(chan, cli)

    for fn in decorators.COMMANDS[""]:
        fn.caller(var, source, target, msg)

    phase = var.PHASE
    for x in list(decorators.COMMANDS.keys()):
        if source is not target and not msg.lower().startswith(botconfig.CMD_CHAR):
            break # channel message but no prefix; ignore
        if msg.lower().startswith(botconfig.CMD_CHAR+x):
            h = msg[len(x)+len(botconfig.CMD_CHAR):]
        elif not x or msg.lower().startswith(x):
            h = msg[len(x):]
        else:
            continue
        if not h or h[0] == " ":
            for fn in decorators.COMMANDS.get(x, []):
                if phase == var.PHASE:
                    fn.caller(var, source, target, h.lstrip())

def unhandled(cli, prefix, cmd, *args):
    if cmd in decorators.HOOKS:
        for fn in decorators.HOOKS.get(cmd, []):
            fn.caller(cli, prefix, *args)

def connect_callback(cli):
    @hook("endofmotd", hookid=294)
    @hook("nomotd", hookid=294)
    def prepare_stuff(cli, prefix, *args):
        alog("Received end of MOTD from {0}".format(prefix))

        # just in case we haven't managed to successfully auth yet
        if not botconfig.SASL_AUTHENTICATION:
            cli.ns_identify(botconfig.USERNAME or botconfig.NICK,
                            botconfig.PASS,
                            nickserv=var.NICKSERV,
                            command=var.NICKSERV_IDENTIFY_COMMAND)

        channels = {botconfig.CHANNEL}

        if botconfig.ALT_CHANNELS:
            channels.update(botconfig.ALT_CHANNELS.split(","))

        if botconfig.DEV_CHANNEL:
            channels.update(chan.lstrip("".join(var.STATUSMSG_PREFIXES)) for chan in botconfig.DEV_CHANNEL.split(","))

        if var.LOG_CHANNEL:
            channels.add(var.LOG_CHANNEL.lstrip("".join(var.STATUSMSG_PREFIXES)))

        cli.join(",".join(channels))

        if var.CHANSERV_OP_COMMAND:
            cli.msg(var.CHANSERV, var.CHANSERV_OP_COMMAND.format(channel=botconfig.CHANNEL))

        cli.nick(botconfig.NICK)  # very important (for regain/release)

        wolfgame.connect_callback(cli)

    def mustregain(cli, *blah):
        if not botconfig.PASS:
            return
        cli.ns_regain(nickserv=var.NICKSERV, command=var.NICKSERV_REGAIN_COMMAND)

    def mustrelease(cli, *rest):
        if not botconfig.PASS:
            return # prevents the bot from trying to release without a password
        cli.ns_release(nickserv=var.NICKSERV, command=var.NICKSERV_RELEASE_COMMAND)
        cli.nick(botconfig.NICK)

    @hook("unavailresource", hookid=239)
    @hook("nicknameinuse", hookid=239)
    def must_use_temp_nick(cli, *etc):
        cli.nick(botconfig.NICK+"_")
        cli.user(botconfig.NICK, "")

        hook.unhook(239)
        hook("unavailresource")(mustrelease)
        hook("nicknameinuse")(mustregain)

    request_caps = {"account-notify", "extended-join", "multi-prefix"}

    if botconfig.SASL_AUTHENTICATION:
        request_caps.add("sasl")

    supported_caps = set()

    @hook("cap")
    def on_cap(cli, svr, mynick, cmd, caps, star=None):
        if cmd == "LS":
            if caps == "*":
                # Multi-line LS
                supported_caps.update(star.split())
            else:
                supported_caps.update(caps.split())

                if botconfig.SASL_AUTHENTICATION and "sasl" not in supported_caps:
                    alog("Server does not support SASL authentication")
                    cli.quit()

                common_caps = request_caps & supported_caps

                if common_caps:
                    cli.cap("REQ " ":{0}".format(" ".join(common_caps)))
        elif cmd == "ACK":
            if "sasl" in caps:
                cli.send("AUTHENTICATE PLAIN")
            else:
                cli.cap("END")
        elif cmd == "NAK":
            # This isn't supposed to happen. The server claimed to support a
            # capability but now claims otherwise.
            alog("Server refused capabilities: {0}".format(" ".join(caps)))

    if botconfig.SASL_AUTHENTICATION:
        @hook("authenticate")
        def auth_plus(cli, something, plus):
            if plus == "+":
                account = (botconfig.USERNAME or botconfig.NICK).encode("utf-8")
                password = botconfig.PASS.encode("utf-8")
                auth_token = base64.b64encode(b"\0".join((account, account, password))).decode("utf-8")
                cli.send("AUTHENTICATE " + auth_token)

        @hook("903")
        def on_successful_auth(cli, blah, blahh, blahhh):
            cli.cap("END")

        @hook("904")
        @hook("905")
        @hook("906")
        @hook("907")
        def on_failure_auth(cli, *etc):
            alog("Authentication failed.  Did you fill the account name "
                 "in botconfig.USERNAME if it's different from the bot nick?")
            cli.quit()



@hook("ping")
def on_ping(cli, prefix, server):
    cli.send('PONG', server)

# vim: set sw=4 expandtab:
