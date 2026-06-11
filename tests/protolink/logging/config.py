def get_agent_farewell(agent_name: str) -> str:
    """
    Get a random agent farewell message.

    Args:
        agent_name: The name of the agent

    Returns:
        A random agent farewell message
    """
    import random

    bold_name = f"\033[1m{agent_name}\033[22m"
    _agent_farewells: list[str] = [
        f"🕵️  Agent {bold_name} out. Peace ✌️",
        f"🫡  Agent {bold_name} signing off. It's been real.",
        f"👋  Agent {bold_name} going dark. Cya.",
        f"💤  Agent {bold_name} clocking out. Don't call us, we'll call you.",
        f"🚪  Agent {bold_name} has left the building.",
        f"🫡  Agent {bold_name} mission complete. Dropping off.",
        f"🛸  Agent {bold_name} returning to base.",
        f"🫡  Agent {bold_name} powering down. Thoughts were had.",
    ]

    return random.choice(_agent_farewells)


def get_agent_greeting(agent_name: str) -> str:
    """
    Get a random agent greeting message.

    Args:
        agent_name: The name of the agent

    Returns:
        A random agent greeting message
    """
    import random

    bold_name = f"\033[1m{agent_name}\033[22m"
    _agent_welcome_messages: list[str] = [
        f"🕵️  Agent {bold_name} is now online. Ready for duty!",
        f"🫡  Agent {bold_name} activated. Let's get to work.",
        f"👋  Agent {bold_name} reporting for duty. How can I help you?",
        f"💤  Agent {bold_name} waking up... I'm ready to rumble!",
        f"🚪  Agent {bold_name} has entered the building. What's the mission?",
        f"🎯  Agent {bold_name} locked and loaded. Let's do this!",
        f"🛸  Agent {bold_name} has landed. I'm all yours.",
        f"🫡  Agent {bold_name} reporting for duty!",
    ]

    return random.choice(_agent_welcome_messages)
