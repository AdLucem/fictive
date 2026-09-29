"""The Judge: closes the goal in focus when the story shows it done or impossible."""

from fictive import goals

import config


def judge_focus(runtime):
    return (yield from goals.judge(runtime, "judge", system=config.prompt_path("judge", "system")))
