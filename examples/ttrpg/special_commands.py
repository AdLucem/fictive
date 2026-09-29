"""Slash commands: /help, /save, /load, /list, /quit, /sheet, /where, /dc."""

from fictive import CommandExit, CommandRestart

import config
import rules
import state

_COMMANDS = {}


def command(name):
    def register(handler):
        _COMMANDS[name] = handler
        return handler
    return register


def register_commands(runtime):
    for name, handler in _COMMANDS.items():
        runtime.register_command(name, handler)


@command("help")
def handle_help(runtime, args):
    """List the commands."""
    for name, handler in sorted(_COMMANDS.items()):
        print(f"  /{name:<6} {handler.__doc__}")


@command("save")
def handle_save(runtime, args):
    """Save the game."""
    print(f"Game saved: {runtime.save_session()}")


def _saved_sessions(runtime):
    """Saved session ids, newest first (ids start with a timestamp)."""
    folder = runtime.interpreter.conversations_root(runtime.main_actor)
    if not folder.exists():
        return []
    return sorted((path.stem for path in folder.glob("*.json")), reverse=True)


@command("list")
def handle_list(runtime, args):
    """List saved games."""
    sessions = _saved_sessions(runtime)
    print("\n".join(f"  {session_id}" for session_id in sessions) or "No saved games.")


@command("load")
def handle_load(runtime, args):
    """Load a saved game: /load [id or start of an id]. The newest by default."""
    prefix = args.strip()
    matches = [session_id for session_id in _saved_sessions(runtime) if session_id.startswith(prefix)]
    if not matches or (prefix and len(matches) > 1 and prefix not in matches):
        print("No saved game matches." if not matches else "Several saved games match; give more of the id.")
        return
    session_id = prefix if prefix in matches else matches[0]
    runtime.load_session(session_id=session_id)
    print(f"Loaded {session_id}")
    raise CommandRestart()


@command("quit")
def handle_quit(runtime, args):
    """End the game."""
    raise CommandExit()


@command("sheet")
def handle_sheet(runtime, args):
    """Show a character sheet: /sheet [id]. Your own by default."""
    adv, sheets = state.load_adventure(), state.characters(runtime)
    sheet = sheets.get(args.strip() or adv["player_character"])
    if sheet is None or not sheet["visible"]:
        print("You don't know.")
        return
    card = state.entry(adv, sheet)
    abilities = ", ".join(f"{name.capitalize()} {value:+d}" for name, value in card["abilities"].items())
    print(f"{card['name']}: {sheet['lp']}/{config.MAX_LP} LP, {sheet['status']}. {abilities}.")
    if sheet["conditions"]:
        print("Conditions: " + ", ".join(sheet["conditions"]))


@command("where")
def handle_where(runtime, args):
    """Show where you are, the exits, and who is here."""
    adv, sheets, game_state = state.load_adventure(), state.characters(runtime), state.game(runtime)
    location = adv["locations"][game_state["location"]]
    print(f"{location['name']}: {location['description']}")
    print("Exits: " + ", ".join(adv["locations"][exit_id]["name"] for exit_id in location["exits"]))
    print("Here: " + ", ".join(f"{state.entry(adv, sheets[i])['name']} ({i})" for i in game_state["present"]))


@command("dc")
def handle_dc(runtime, args):
    """Debug: the last check, with its hidden DC."""
    check = runtime.store_get(config.LAST_CHECK_KEY)
    if not check:
        print("No check yet.")
        return
    print(f"{rules.roll_line(check)} against DC {check['dc']} ({check['tier']}): {check['band']}")
